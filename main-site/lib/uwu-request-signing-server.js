// Shared server-side request signing helpers (uwu PWAs).
import crypto from 'node:crypto';

const TS_SKEW_MS = 30 * 1000;

function hmacHex(keyHex, message) {
    return crypto.createHmac('sha256', keyHex).update(message).digest('hex');
}

function timingSafeEqualHex(a, b) {
    const bufA = Buffer.from(a, 'hex');
    const bufB = Buffer.from(b, 'hex');
    if (bufA.length !== bufB.length) return false;
    return crypto.timingSafeEqual(bufA, bufB);
}

// Vercel parses an absent JSON body as {} — treat that the same as "no body".
function isEmptyBody(body) {
    if (body === undefined || body === null || body === '') return true;
    if (typeof body === 'object' && JSON.stringify(body) === '{}') return true;
    return false;
}

// `supabase` is { url, key } REST credentials (this codebase has no supabase-js dependency),
// matching the raw-fetch pattern already used in api/entries.js.
export async function verifySignedRequest(req, supabase) {
    const token = req.headers['x-request-token'];
    const ts = req.headers['x-request-ts'];
    const keyId = req.headers['x-key-id'];

    if (!token || !ts || !keyId) {
        return { valid: false, reason: 'Missing signing headers' };
    }

    const tsNum = Number(ts);
    if (!Number.isFinite(tsNum) || Math.abs(Date.now() - tsNum) > TS_SKEW_MS) {
        return { valid: false, reason: 'Timestamp out of range' };
    }

    const restHeaders = {
        apikey: supabase.key,
        Authorization: `Bearer ${supabase.key}`,
        'Content-Type': 'application/json',
    };

    const keyRes = await fetch(
        `${supabase.url}/rest/v1/uwu_signing_keys?select=signing_key,session_token,expires_at&session_token=eq.${encodeURIComponent(keyId)}`,
        { headers: restHeaders }
    );
    if (!keyRes.ok) return { valid: false, reason: 'Signing key lookup failed' };
    const keyRows = await keyRes.json();
    const keyRow = keyRows[0];

    if (!keyRow) {
        return { valid: false, reason: 'Unknown signing key' };
    }

    if (keyRow.expires_at && new Date(keyRow.expires_at).getTime() < Date.now()) {
        return { valid: false, reason: 'Signing key expired' };
    }

    const method = req.method.toUpperCase();
    const path = req.url;
    const bodyHash = isEmptyBody(req.body) ? 'empty' : hmacHex(keyRow.signing_key, JSON.stringify(req.body));

    const message = `${ts}:${method}:${path}:${bodyHash}`;
    const expected = hmacHex(keyRow.signing_key, message);

    if (!timingSafeEqualHex(expected, token)) {
        return { valid: false, reason: 'Signature mismatch' };
    }

    const usedRes = await fetch(
        `${supabase.url}/rest/v1/uwu_used_request_tokens?select=token&token=eq.${encodeURIComponent(token)}`,
        { headers: restHeaders }
    );
    const usedRows = usedRes.ok ? await usedRes.json() : [];
    if (usedRows.length > 0) {
        return { valid: false, reason: 'Replayed request token' };
    }

    await fetch(`${supabase.url}/rest/v1/uwu_used_request_tokens`, {
        method: 'POST',
        headers: restHeaders,
        body: JSON.stringify({ token, session_token: keyRow.session_token, used_at: new Date().toISOString() }),
    });

    return { valid: true, reason: 'OK' };
}
