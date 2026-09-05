// Shared helpers for the sync routes.
//
// There are no accounts here and nothing to sign in to. A browser identifies itself with a
// device id and a device secret that it generates and keeps in localStorage, and only the
// hash of the secret is ever stored. Every database call goes through these routes with the
// service key, which never leaves the server.
//
// Files beginning with an underscore are not routed by Vercel, so this module is private to
// the functions that import it.

import { createHash, randomInt, timingSafeEqual } from 'node:crypto';

export const TABLES = {
    links: 'henrusian15_sync_links',
    tokens: 'henrusian15_sync_tokens',
    favourites: 'henrusian15_sync_favourites',
    backupCodes: 'henrusian15_sync_backup_codes',
    codeRequests: 'henrusian15_sync_code_requests',
    recoveryAttempts: 'henrusian15_sync_recovery_attempts',
};

// Crockford base32, so a handwritten code cannot be confused between I, L, O, U and 1, 0.
const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

export const TOKEN_LENGTH = 8;
export const BACKUP_CODE_LENGTH = 12;
export const BACKUP_CODE_COUNT = 10;
export const TOKEN_TTL_MINUTES = 10;
export const APPROVAL_TTL_MINUTES = 10;
export const RECOVERY_LOCKOUT_ATTEMPTS = 5;
export const RECOVERY_LOCKOUT_MINUTES = 60;
export const VALID_TABS = ['dict', 'idioms', 'names'];

export function env() {
    return {
        url: process.env.SUPABASE_URL,
        serviceKey: process.env.SUPABASE_SERVICE_KEY,
        pepper: process.env.BACKUP_CODE_PEPPER || '',
        botUsername: process.env.TELEGRAM_BOT_USERNAME || 'henrusian_bot',
    };
}

export function send(res, status, body) {
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store');
    return res.status(status).json(body);
}

export function methodNotAllowed(res, allowed) {
    res.setHeader('Allow', allowed.join(', '));
    return send(res, 405, { error: 'Method not allowed.' });
}

export function configured(res) {
    const { url, serviceKey } = env();
    if (!url || !serviceKey) {
        send(res, 500, { error: 'Syncing is not configured on this server yet.' });
        return false;
    }
    return true;
}

export async function readBody(req) {
    if (req.body && typeof req.body === 'object') return req.body;
    if (typeof req.body === 'string' && req.body) {
        try {
            return JSON.parse(req.body);
        } catch {
            return {};
        }
    }
    return {};
}

// -- PostgREST ------------------------------------------------------------

function serviceHeaders(prefer) {
    const { serviceKey } = env();
    const headers = {
        apikey: serviceKey,
        Authorization: `Bearer ${serviceKey}`,
        'Content-Type': 'application/json',
    };
    if (prefer) headers.Prefer = prefer;
    return headers;
}

export async function rest(method, table, { query = '', body, prefer } = {}) {
    const { url } = env();
    const response = await fetch(`${url}/rest/v1/${table}${query}`, {
        method,
        headers: serviceHeaders(prefer),
        body: body === undefined ? undefined : JSON.stringify(body),
    });

    const text = await response.text();
    if (!response.ok) {
        console.error('Supabase error', response.status, text.slice(0, 300));
        throw new Error('database');
    }
    if (!text) return [];
    try {
        return JSON.parse(text);
    } catch {
        return [];
    }
}

export function select(table, query) {
    return rest('GET', table, { query });
}

export async function selectOne(table, query) {
    const rows = await select(table, `${query}&limit=1`);
    return rows[0] || null;
}

export function insert(table, body, { returning = true } = {}) {
    return rest('POST', table, {
        body,
        prefer: returning ? 'return=representation' : 'return=minimal',
    });
}

// Insert, treating a duplicate as success rather than an error, so a repeated star is a
// no-op.
export function upsert(table, body) {
    return rest('POST', table, { body, prefer: 'return=minimal,resolution=merge-duplicates' });
}

export function update(table, query, body, { returning = true } = {}) {
    return rest('PATCH', table, {
        query,
        body,
        prefer: returning ? 'return=representation' : 'return=minimal',
    });
}

export function remove(table, query) {
    return rest('DELETE', table, { query, prefer: 'return=minimal' });
}

// -- device credentials ---------------------------------------------------

const DEVICE_ID = /^[A-Za-z0-9_-]{16,64}$/;
const DEVICE_SECRET = /^[A-Za-z0-9_-]{32,128}$/;

export function hashSecret(secret) {
    const { pepper } = env();
    return createHash('sha256').update(`${pepper}:device:${secret}`).digest('hex');
}

function sameHash(a, b) {
    const left = Buffer.from(String(a || ''), 'utf8');
    const right = Buffer.from(String(b || ''), 'utf8');
    if (left.length !== right.length) return false;
    return timingSafeEqual(left, right);
}

export function deviceCredentials(req) {
    const id = String(req.headers['x-device-id'] || '').trim();
    const secret = String(req.headers['x-device-secret'] || '').trim();
    if (!DEVICE_ID.test(id) || !DEVICE_SECRET.test(secret)) return null;
    return { id, secret };
}

// Resolves the live link for the calling device, or null. This is the only authentication
// in the project: possession of the device secret that was present when the link was made.
export async function currentLink(req) {
    const creds = deviceCredentials(req);
    if (!creds) return null;

    const row = await selectOne(
        TABLES.links,
        `?select=id,device_id,device_secret_hash,device_label,telegram_user_id,telegram_username,linked_at` +
            `&device_id=eq.${encodeURIComponent(creds.id)}&revoked_at=is.null`
    );
    if (!row) return null;
    if (!sameHash(row.device_secret_hash, hashSecret(creds.secret))) return null;
    return row;
}

export async function requireLink(req, res) {
    const link = await currentLink(req);
    if (!link) {
        send(res, 401, { error: 'This browser is not linked to a Telegram account.' });
        return null;
    }
    return link;
}

// -- codes ----------------------------------------------------------------

function randomCode(length) {
    let out = '';
    for (let i = 0; i < length; i += 1) out += ALPHABET[randomInt(ALPHABET.length)];
    return out;
}

export function newToken() {
    return randomCode(TOKEN_LENGTH);
}

export function newBackupCode() {
    return randomCode(BACKUP_CODE_LENGTH);
}

export function prettyCode(raw) {
    return raw.replace(/(.{4})(?=.)/g, '$1-');
}

// Must stay byte for byte identical to services/backup_codes.py in the bot.
export function normaliseCode(value) {
    return String(value || '')
        .toUpperCase()
        .replace(/[^A-Z0-9]/g, '')
        .replace(/[IL]/g, '1')
        .replace(/O/g, '0')
        .replace(/U/g, '1');
}

export function digestCode(value) {
    const { pepper } = env();
    return createHash('sha256').update(`${pepper}:${normaliseCode(value)}`).digest('hex');
}

export function deepLink(token) {
    return `https://t.me/${env().botUsername}?start=${token}`;
}

// -- misc -----------------------------------------------------------------

export function minutesFromNow(minutes) {
    return new Date(Date.now() + minutes * 60_000).toISOString();
}

export function nowIso() {
    return new Date().toISOString();
}

// Filters whatever the browser sent down to well formed favourites.
export function cleanFavourites(list, limit = 1000) {
    const out = [];
    const seen = new Set();
    for (const item of Array.isArray(list) ? list.slice(0, limit) : []) {
        const tab = String((item && item.tab) || '');
        const id = String((item && (item.id ?? item.entry_id)) || '');
        const key = `${tab}:${id}`;
        if (!VALID_TABS.includes(tab) || !id || id.length > 64 || seen.has(key)) continue;
        seen.add(key);
        out.push({ tab, id });
    }
    return out;
}

// Favourites, codes and requests all hang off the Telegram account rather than off one
// pairing, which is what lets several browsers share a single collection.
export async function codesRemaining(telegramUserId) {
    const rows = await select(
        TABLES.backupCodes,
        `?select=id&telegram_user_id=eq.${telegramUserId}&used_at=is.null&revoked_at=is.null`
    );
    return rows.length;
}

export async function recordRecoveryAttempt(telegramUserId, deviceId, succeeded) {
    try {
        await insert(
            TABLES.recoveryAttempts,
            { telegram_user_id: telegramUserId, device_id: deviceId, source: 'web', succeeded },
            { returning: false }
        );
    } catch {
        // The lockout is a safety net, so failing to record must not break recovery.
    }
}

export async function collectionLockedOut(telegramUserId) {
    const since = new Date(Date.now() - RECOVERY_LOCKOUT_MINUTES * 60_000).toISOString();
    const rows = await select(
        TABLES.recoveryAttempts,
        `?select=created_at&telegram_user_id=eq.${telegramUserId}&succeeded=eq.false` +
            `&created_at=gte.${since}&order=created_at.asc`
    );
    if (rows.length < RECOVERY_LOCKOUT_ATTEMPTS) return 0;

    const unlockAt =
        new Date(rows[0].created_at).getTime() + RECOVERY_LOCKOUT_MINUTES * 60_000;
    return Math.max(0, Math.round((unlockAt - Date.now()) / 1000));
}

// Every browser sharing a collection, so the page can list them.
export async function siblingDevices(telegramUserId) {
    return select(
        TABLES.links,
        `?select=id,device_id,device_label,linked_at&telegram_user_id=eq.${telegramUserId}` +
            '&revoked_at=is.null&order=linked_at.desc'
    );
}
