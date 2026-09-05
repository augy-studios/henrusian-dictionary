// POST /api/recover  { device_id, device_secret, code }
//
// The path for somebody whose Telegram account is out of reach. Spending one recovery code
// releases every browser paired with that Telegram account, and hands back the collection so
// nothing is lost. A new Telegram account can then be paired normally.
//
// This route cannot use the usual device check, because the caller may be a browser that was
// never paired, for instance after reinstalling. The code itself is the proof: it names the
// collection, and only that collection's own codes are accepted.

import {
    RECOVERY_LOCKOUT_MINUTES,
    TABLES,
    collectionLockedOut,
    configured,
    digestCode,
    methodNotAllowed,
    normaliseCode,
    nowIso,
    readBody,
    recordRecoveryAttempt,
    select,
    selectOne,
    send,
    update,
} from './_lib.js';

export default async function handler(req, res) {
    if (req.method !== 'POST') return methodNotAllowed(res, ['POST']);
    if (!configured(res)) return undefined;

    const body = await readBody(req);
    const code = normaliseCode(body.code);
    if (code.length !== 12) {
        return send(res, 400, {
            error: 'A recovery code is twelve characters, usually written in three groups of four.',
        });
    }

    try {
        const row = await selectOne(
            TABLES.backupCodes,
            `?select=id,telegram_user_id,used_at,revoked_at&code_hash=eq.${digestCode(code)}`
        );

        if (!row) {
            // Nothing to attribute this to, so nothing is recorded against a link.
            return send(res, 400, { error: 'That code did not work. Check it and try again.' });
        }

        if (row.used_at || row.revoked_at) {
            await recordRecoveryAttempt(row.telegram_user_id, null, false);
            return send(res, 400, {
                error: 'That code has been used already, or replaced by a newer set.',
            });
        }

        const locked = await collectionLockedOut(row.telegram_user_id);
        if (locked) {
            await recordRecoveryAttempt(row.telegram_user_id, null, false);
            return send(res, 429, {
                error: `Too many codes have failed here. Please try again in ${Math.max(
                    1,
                    Math.round(locked / 60)
                )} minutes.`,
                retry_after: locked,
            });
        }

        const claimed = await update(TABLES.backupCodes, `?id=eq.${row.id}&used_at=is.null`, {
            used_at: nowIso(),
        });
        if (!Array.isArray(claimed) || !claimed.length) {
            await recordRecoveryAttempt(row.telegram_user_id, null, false);
            return send(res, 400, { error: 'That code has already been used.' });
        }

        // Hand the collection back before anything is released, so the browser keeps
        // whatever only existed on the shared side.
        const favourites = await select(
            TABLES.favourites,
            `?select=tab,entry_id&telegram_user_id=eq.${row.telegram_user_id}`
        );

        // Release every browser paired with that Telegram account. The bot notices on its
        // next sweep, keeps its own copy, and clears the shared rows.
        const released = await update(
            TABLES.links,
            `?telegram_user_id=eq.${row.telegram_user_id}&revoked_at=is.null`,
            { revoked_at: nowIso() }
        );

        await recordRecoveryAttempt(row.telegram_user_id, null, true);
        const left = await select(
            TABLES.backupCodes,
            `?select=id&telegram_user_id=eq.${row.telegram_user_id}` +
                '&used_at=is.null&revoked_at=is.null'
        );

        return send(res, 200, {
            ok: true,
            released: Array.isArray(released) ? released.length : 0,
            favourites: favourites.map((item) => ({ tab: item.tab, id: String(item.entry_id) })),
            codes_remaining: left.length,
            lockout_minutes: RECOVERY_LOCKOUT_MINUTES,
        });
    } catch (err) {
        console.error('recover failed', err);
        return send(res, 502, { error: 'Could not check that code just now.' });
    }
}
