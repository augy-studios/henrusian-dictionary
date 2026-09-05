// /api/codes
//
//   POST                    Ask for a new set of recovery codes.
//   GET ?request_id=...     Poll that request. Once Telegram has approved it, this call
//                           reveals the codes, exactly once, and never again.
//
// A code protects the whole collection, so any paired browser may ask for a set and the
// approval always goes to the one Telegram account that holds it.
//
// Codes are created here and nowhere else, but never immediately. The request lands as
// pending, the bot asks the linked Telegram account to approve it, and only then does a poll
// return the set. Nothing is revoked until the moment the new codes are shown, so a rejected
// or ignored request leaves the old ones working.

import {
    APPROVAL_TTL_MINUTES,
    BACKUP_CODE_COUNT,
    TABLES,
    configured,
    digestCode,
    insert,
    methodNotAllowed,
    minutesFromNow,
    newBackupCode,
    nowIso,
    prettyCode,
    requireLink,
    selectOne,
    send,
    update,
} from './_lib.js';

export default async function handler(req, res) {
    if (!['GET', 'POST'].includes(req.method)) return methodNotAllowed(res, ['GET', 'POST']);
    if (!configured(res)) return undefined;

    const link = await requireLink(req, res);
    if (!link) return undefined;

    try {
        if (req.method === 'POST') return raise(res, link);
        return poll(res, link, (req.query && req.query.request_id) || '');
    } catch (err) {
        console.error('codes route failed', err);
        return send(res, 502, { error: 'Could not reach the recovery codes just now.' });
    }
}

// -- ask ------------------------------------------------------------------

async function raise(res, link) {
    // Only one request may be open at a time, so an older one is stood down.
    await update(
        TABLES.codeRequests,
        `?telegram_user_id=eq.${link.telegram_user_id}&status=eq.pending`,
        { status: 'superseded', resolved_at: nowIso() },
        { returning: false }
    );

    const rows = await insert(TABLES.codeRequests, {
        telegram_user_id: link.telegram_user_id,
        device_id: link.device_id,
        device_label: link.device_label,
        expires_at: minutesFromNow(APPROVAL_TTL_MINUTES),
    });

    const request = rows[0] || null;
    return send(res, 200, {
        request_id: request ? request.id : null,
        status: 'pending',
        expires_at: request ? request.expires_at : minutesFromNow(APPROVAL_TTL_MINUTES),
        ttl_minutes: APPROVAL_TTL_MINUTES,
        telegram_username: link.telegram_username || null,
    });
}

// -- poll, and reveal once ------------------------------------------------

async function poll(res, link, requestId) {
    if (!requestId) return send(res, 400, { error: 'Say which request to check.' });

    const request = await selectOne(
        TABLES.codeRequests,
        `?select=id,status,expires_at&id=eq.${encodeURIComponent(requestId)}` +
            `&telegram_user_id=eq.${link.telegram_user_id}`
    );
    if (!request) return send(res, 404, { error: 'That request no longer exists.' });

    if (request.status === 'pending') {
        if (new Date(request.expires_at).getTime() <= Date.now()) {
            await update(
                TABLES.codeRequests,
                `?id=eq.${request.id}&status=eq.pending`,
                { status: 'expired', resolved_at: nowIso() },
                { returning: false }
            );
            return send(res, 200, { status: 'expired' });
        }
        return send(res, 200, { status: 'pending', expires_at: request.expires_at });
    }

    if (request.status !== 'approved') {
        return send(res, 200, { status: request.status });
    }

    // Claim the reveal before generating anything, so two tabs polling at once cannot both
    // be handed a set.
    const claimed = await update(TABLES.codeRequests, `?id=eq.${request.id}&status=eq.approved`, {
        status: 'consumed',
        consumed_at: nowIso(),
    });
    if (!Array.isArray(claimed) || !claimed.length) {
        return send(res, 200, { status: 'consumed' });
    }

    const codes = await issueCodes(link.telegram_user_id);
    return send(res, 200, { status: 'approved', codes });
}

async function issueCodes(telegramUserId) {
    // Old codes stop working at the moment the new ones are shown, not before.
    await update(
        TABLES.backupCodes,
        `?telegram_user_id=eq.${telegramUserId}&used_at=is.null&revoked_at=is.null`,
        { revoked_at: nowIso() },
        { returning: false }
    );

    const plain = [];
    const rows = [];
    while (plain.length < BACKUP_CODE_COUNT) {
        const raw = newBackupCode();
        const hash = digestCode(raw);
        if (rows.some((row) => row.code_hash === hash)) continue;
        plain.push(prettyCode(raw));
        rows.push({ telegram_user_id: telegramUserId, code_hash: hash });
    }

    await insert(TABLES.backupCodes, rows, { returning: false });
    return plain;
}
