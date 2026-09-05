// /api/favourites
//
//   GET                          The shared set for this browser's link.
//   POST { tab, entry_id }       Save one. Starring twice is a no-op.
//   POST { merge: [...] }        Save many at once.
//   DELETE ?tab=&entry_id=       Remove one.
//
// Only reachable while a link exists. Before then the browser keeps its favourites in
// localStorage and the bot keeps its own, and neither needs this route.
//
// The collection belongs to the Telegram account, so every browser paired with it reads and
// writes the same set.

import {
    TABLES,
    VALID_TABS,
    cleanFavourites,
    configured,
    methodNotAllowed,
    readBody,
    remove,
    requireLink,
    select,
    send,
    upsert,
} from './_lib.js';

const MAX_MERGE = 1000;

export default async function handler(req, res) {
    if (!['GET', 'POST', 'DELETE'].includes(req.method)) {
        return methodNotAllowed(res, ['GET', 'POST', 'DELETE']);
    }
    if (!configured(res)) return undefined;

    const link = await requireLink(req, res);
    if (!link) return undefined;

    try {
        if (req.method === 'GET') return list(res, link);
        if (req.method === 'POST') return save(res, link, await readBody(req));
        return drop(res, link, req.query || {});
    } catch (err) {
        console.error('favourites failed', err);
        return send(res, 502, { error: 'Could not reach your favourites just now.' });
    }
}

async function list(res, link) {
    const rows = await select(
        TABLES.favourites,
        `?select=tab,entry_id&telegram_user_id=eq.${link.telegram_user_id}&order=created_at.asc`
    );
    return send(res, 200, {
        favourites: rows.map((row) => ({ tab: row.tab, id: String(row.entry_id) })),
        count: rows.length,
    });
}

async function save(res, link, body) {
    const incoming = Array.isArray(body.merge)
        ? body.merge
        : [{ tab: body.tab, id: body.entry_id ?? body.id }];

    const clean = cleanFavourites(incoming, MAX_MERGE);
    if (!clean.length) return send(res, 400, { error: 'Nothing valid to save.' });

    await upsert(
        TABLES.favourites,
        clean.map((item) => ({
            telegram_user_id: link.telegram_user_id,
            tab: item.tab,
            entry_id: item.id,
        }))
    );
    return send(res, 200, { ok: true, saved: clean.length });
}

async function drop(res, link, query) {
    const tab = String(query.tab || '');
    const entryId = String(query.entry_id || query.id || '');
    if (!VALID_TABS.includes(tab) || !entryId) {
        return send(res, 400, { error: 'Say which entry to remove.' });
    }

    await remove(
        TABLES.favourites,
        `?telegram_user_id=eq.${link.telegram_user_id}&tab=eq.${tab}` +
            `&entry_id=eq.${encodeURIComponent(entryId)}`
    );
    return send(res, 200, { ok: true });
}
