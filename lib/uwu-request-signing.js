/* Shared client-side request signing helpers (uwu PWAs). Plain script, attaches to window. */
(function (global) {
    'use strict';

    const STORE_KEY = 'uwu_signing_key';

    function readStore(storage) {
        try {
            const raw = storage.getItem(STORE_KEY);
            if (!raw) return null;
            const data = JSON.parse(raw);
            if (data.expiresAt && Date.now() > data.expiresAt) {
                storage.removeItem(STORE_KEY);
                return null;
            }
            return data;
        } catch {
            return null;
        }
    }

    // expiresAt (ms epoch) is optional; when set, the key is treated as stale past that time.
    function storeSigningKey(signingKey, keyId, persistent = false, expiresAt = null) {
        const storage = persistent ? localStorage : sessionStorage;
        const other = persistent ? sessionStorage : localStorage;
        storage.setItem(STORE_KEY, JSON.stringify({ signingKey, keyId, expiresAt }));
        other.removeItem(STORE_KEY);
    }

    function getSigningKey() {
        const persisted = readStore(localStorage);
        if (persisted) return persisted;
        return readStore(sessionStorage);
    }

    function clearSigningKey() {
        localStorage.removeItem(STORE_KEY);
        sessionStorage.removeItem(STORE_KEY);
    }

    async function initGuestKey(appId) {
        if (getSigningKey()) return;
        const res = await fetch(`/api/auth/guest-key?app=${encodeURIComponent(appId)}`);
        if (!res.ok) throw new Error('Failed to obtain guest signing key');
        const data = await res.json();
        storeSigningKey(data.signing_key, data.key_id, false, Date.now() + 10 * 60 * 1000);
    }

    async function hmacHex(keyHex, message) {
        const enc = new TextEncoder();
        const cryptoKey = await crypto.subtle.importKey(
            'raw', enc.encode(keyHex), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
        );
        const sig = await crypto.subtle.sign('HMAC', cryptoKey, enc.encode(message));
        return [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, '0')).join('');
    }

    async function signedFetch(url, options = {}) {
        const key = getSigningKey();
        if (!key) throw new Error('signedFetch: no signing key available — call initGuestKey() or login first');

        const method = (options.method || 'GET').toUpperCase();
        const u = new URL(url, location.origin);
        const path = u.pathname + u.search;
        const ts = Date.now().toString();

        // Treat missing/empty body the same as no body, mirroring the server's '{}' handling.
        const bodyStr = options.body ? String(options.body) : '';
        const bodyHash = bodyStr && bodyStr !== '{}' ? await hmacHex(key.signingKey, bodyStr) : 'empty';

        const message = `${ts}:${method}:${path}:${bodyHash}`;
        const token = await hmacHex(key.signingKey, message);

        const headers = new Headers(options.headers || {});
        headers.set('X-Request-Token', token);
        headers.set('X-Request-TS', ts);
        headers.set('X-Key-ID', key.keyId);

        return fetch(url, { ...options, headers });
    }

    global.storeSigningKey = storeSigningKey;
    global.getSigningKey = getSigningKey;
    global.clearSigningKey = clearSigningKey;
    global.initGuestKey = initGuestKey;
    global.signedFetch = signedFetch;
})(window);
