// Telegram sync client.
//
// There is no account and nothing to sign in to. This browser generates a device id and a
// device secret once, keeps them in localStorage, and sends them as headers. The server only
// ever stores a hash of the secret, so the pair is what proves this is the same browser.
//
// One Telegram account can pair with several browsers, and they all share one collection.
//
// Nothing here talks to Supabase directly. Every call goes to the site's own API routes.

(function () {
    'use strict';

    const DEVICE_KEY = 'henrusian.device';
    const LINKED_KEY = 'henrusian.linked';

    function base64url(bytes) {
        let binary = '';
        bytes.forEach((b) => {
            binary += String.fromCharCode(b);
        });
        return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    }

    function randomString(byteLength) {
        const bytes = new Uint8Array(byteLength);
        crypto.getRandomValues(bytes);
        return base64url(bytes);
    }

    function readDevice() {
        try {
            const raw = localStorage.getItem(DEVICE_KEY);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            return parsed && parsed.id && parsed.secret ? parsed : null;
        } catch {
            return null;
        }
    }

    // Created on the first sync attempt, never before, so a visitor who never links is not
    // given an identifier at all.
    function ensureDevice() {
        const existing = readDevice();
        if (existing) return existing;
        const device = { id: randomString(16), secret: randomString(32) };
        try {
            localStorage.setItem(DEVICE_KEY, JSON.stringify(device));
        } catch {
            // A browser refusing storage cannot sync, and the caller reports that.
        }
        return device;
    }

    function forgetDevice() {
        try {
            localStorage.removeItem(DEVICE_KEY);
            localStorage.removeItem(LINKED_KEY);
        } catch {
            /* nothing to do */
        }
    }

    function wasLinked() {
        try {
            return localStorage.getItem(LINKED_KEY) === '1';
        } catch {
            return false;
        }
    }

    function rememberLinked(linked) {
        try {
            if (linked) localStorage.setItem(LINKED_KEY, '1');
            else localStorage.removeItem(LINKED_KEY);
        } catch {
            /* nothing to do */
        }
    }

    function deviceLabel() {
        const ua = navigator.userAgent || '';
        const browser =
            /Edg\//.test(ua) ? 'Edge'
            : /OPR\//.test(ua) ? 'Opera'
            : /Firefox\//.test(ua) ? 'Firefox'
            : /Chrome\//.test(ua) ? 'Chrome'
            : /Safari\//.test(ua) ? 'Safari'
            : 'a browser';
        const platform =
            /Android/.test(ua) ? 'Android'
            : /iPhone|iPad|iPod/.test(ua) ? 'iOS'
            : /Windows/.test(ua) ? 'Windows'
            : /Mac OS X/.test(ua) ? 'macOS'
            : /Linux/.test(ua) ? 'Linux'
            : '';
        return platform ? `${browser} on ${platform}` : browser;
    }

    async function call(path, { method = 'GET', body, device } = {}) {
        const creds = device || readDevice();
        const headers = { Accept: 'application/json' };
        if (creds) {
            headers['X-Device-Id'] = creds.id;
            headers['X-Device-Secret'] = creds.secret;
        }
        if (body !== undefined) headers['Content-Type'] = 'application/json';

        let response;
        try {
            response = await fetch(path, {
                method,
                headers,
                body: body === undefined ? undefined : JSON.stringify(body),
            });
        } catch {
            throw new Error('The server could not be reached.');
        }

        let payload = {};
        try {
            payload = await response.json();
        } catch {
            payload = {};
        }

        if (!response.ok) {
            const error = new Error(payload.error || 'That did not work.');
            error.status = response.status;
            error.payload = payload;
            throw error;
        }
        return payload;
    }

    // -- the operations the pages use --------------------------------------

    async function status() {
        if (!readDevice()) return { linked: false };
        const result = await call('/api/link');
        rememberLinked(Boolean(result.linked));
        return result;
    }

    // Starts a pairing. The favourites this browser already holds travel with the token, so
    // the bot merges both sides the moment the link is made.
    async function startLink(favourites) {
        const device = ensureDevice();
        if (!readDevice()) throw new Error('This browser is not allowing local storage.');
        return call('/api/link', {
            method: 'POST',
            device,
            body: { favourites: favourites || [], label: deviceLabel() },
        });
    }

    // Unpairs this browser by default. Pass { all: true } to unpair every browser
    // sharing the collection.
    async function unlink({ all = false } = {}) {
        const result = await call(`/api/link${all ? '?all=1' : ''}`, { method: 'DELETE' });
        rememberLinked(false);
        return result;
    }

    function addFavourite(tab, id) {
        return call('/api/favourites', { method: 'POST', body: { tab, id } });
    }

    function removeFavourite(tab, id) {
        return call(
            `/api/favourites?tab=${encodeURIComponent(tab)}&entry_id=${encodeURIComponent(id)}`,
            { method: 'DELETE' }
        );
    }

    function mergeFavourites(pairs) {
        return call('/api/favourites', { method: 'POST', body: { merge: pairs } });
    }

    function requestCodes() {
        return call('/api/codes', { method: 'POST' });
    }

    function pollCodes(requestId) {
        return call(`/api/codes?request_id=${encodeURIComponent(requestId)}`);
    }

    function recover(code) {
        return call('/api/recover', { method: 'POST', body: { code } });
    }

    window.HDSync = {
        hasDevice: () => Boolean(readDevice()),
        wasLinked,
        rememberLinked,
        forgetDevice,
        deviceLabel,
        status,
        startLink,
        unlink,
        addFavourite,
        removeFavourite,
        mergeFavourites,
        requestCodes,
        pollCodes,
        recover,
    };
})();
