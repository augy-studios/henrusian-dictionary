// /api/link
//
//   POST                     Start pairing. Returns a token and the t.me link that finishes
//                            it. The favourites this browser already has travel with the
//                            token, so the bot can merge both sides in one go.
//   GET                      The state of this browser's pairing, the shared favourites, and
//                            the other browsers sharing them.
//   DELETE                   Unpair this browser. The others carry on.
//   DELETE ?all=1            Unpair every browser sharing this collection.
//
// Pairing has to begin here rather than in Telegram, because only the browser knows which
// device is being paired.

import {
    TABLES,
    TOKEN_TTL_MINUTES,
    cleanFavourites,
    codesRemaining,
    configured,
    currentLink,
    deepLink,
    deviceCredentials,
    hashSecret,
    insert,
    methodNotAllowed,
    minutesFromNow,
    newToken,
    nowIso,
    readBody,
    requireLink,
    select,
    send,
    siblingDevices,
    update,
} from './_lib.js';

export default async function handler(req, res) {
    if (!['GET', 'POST', 'DELETE'].includes(req.method)) {
        return methodNotAllowed(res, ['GET', 'POST', 'DELETE']);
    }
    if (!configured(res)) return undefined;

    try {
        if (req.method === 'POST') return start(req, res);
        if (req.method === 'GET') return status(req, res);
        return unlink(req, res);
    } catch (err) {
        console.error('link route failed', err);
        return send(res, 502, { error: 'Could not reach the sync service just now.' });
    }
}

// -- start ----------------------------------------------------------------

async function start(req, res) {
    const creds = deviceCredentials(req);
    if (!creds) {
        return send(res, 400, { error: 'This browser did not send a usable device identity.' });
    }

    const existing = await currentLink(req);
    if (existing) {
        return send(res, 409, {
            error: 'This browser is already paired with a Telegram account.',
            telegram_username: existing.telegram_username || null,
        });
    }

    const body = await readBody(req);
    const favourites = cleanFavourites(body.favourites);
    const label = cleanLabel(body.label);

    // Retire any earlier unused token from this device, so only one is ever live.
    await update(
        TABLES.tokens,
        `?device_id=eq.${encodeURIComponent(creds.id)}&used_at=is.null`,
        { expires_at: nowIso() },
        { returning: false }
    );

    const token = newToken();
    await insert(
        TABLES.tokens,
        {
            token,
            device_id: creds.id,
            device_secret_hash: hashSecret(creds.secret),
            device_label: label,
            favourites,
            expires_at: minutesFromNow(TOKEN_TTL_MINUTES),
        },
        { returning: false }
    );

    return send(res, 200, {
        token,
        url: deepLink(token),
        expires_at: minutesFromNow(TOKEN_TTL_MINUTES),
        ttl_minutes: TOKEN_TTL_MINUTES,
        sending: favourites.length,
    });
}

function cleanLabel(value) {
    const label = String(value || '').trim().replace(/\s+/g, ' ');
    return label ? label.slice(0, 60) : null;
}

// -- status ---------------------------------------------------------------

async function status(req, res) {
    const link = await currentLink(req);
    if (!link) return send(res, 200, { linked: false });

    const [rows, codes, requests, devices] = await Promise.all([
        select(
            TABLES.favourites,
            `?select=tab,entry_id&telegram_user_id=eq.${link.telegram_user_id}&order=created_at.asc`
        ),
        codesRemaining(link.telegram_user_id),
        select(
            TABLES.codeRequests,
            `?select=id,status,expires_at&telegram_user_id=eq.${link.telegram_user_id}` +
                '&order=requested_at.desc&limit=1'
        ),
        siblingDevices(link.telegram_user_id),
    ]);

    const latest = requests[0] || null;
    const open =
        latest &&
        ['pending', 'approved'].includes(latest.status) &&
        new Date(latest.expires_at).getTime() > Date.now()
            ? latest
            : null;

    // Keep a rough note of activity, which is what makes the device list useful.
    update(TABLES.links, `?id=eq.${link.id}`, { last_seen_at: nowIso() }, { returning: false })
        .catch(() => {});

    return send(res, 200, {
        linked: true,
        telegram_username: link.telegram_username || null,
        linked_at: link.linked_at,
        device_label: link.device_label || null,
        codes_remaining: codes,
        favourites: rows.map((row) => ({ tab: row.tab, id: String(row.entry_id) })),
        request: open ? { id: open.id, status: open.status, expires_at: open.expires_at } : null,
        devices: devices.map((device) => ({
            id: device.id,
            label: device.device_label || 'a browser',
            linked_at: device.linked_at,
            this_one: device.device_id === link.device_id,
        })),
    });
}

// -- unlink ---------------------------------------------------------------

async function unlink(req, res) {
    const link = await requireLink(req, res);
    if (!link) return undefined;

    const all = String((req.query && req.query.all) || '') === '1';

    // Revoking is all this side does. The shared rows stay until the bot has taken its own
    // copy of them, which it does on its next sweep once the last browser has gone. This
    // browser already holds everything in localStorage.
    const filter = all
        ? `?telegram_user_id=eq.${link.telegram_user_id}&revoked_at=is.null`
        : `?id=eq.${link.id}&revoked_at=is.null`;

    const revoked = await update(TABLES.links, filter, { revoked_at: nowIso() });
    const remaining = await siblingDevices(link.telegram_user_id);

    return send(res, 200, {
        ok: true,
        removed: Array.isArray(revoked) ? revoked.length : 0,
        remaining: remaining.length,
    });
}
