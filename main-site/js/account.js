// The sync page.
//
// Four states, one at a time: not paired, waiting for the tap in Telegram, paired, and the
// recovery code panel. Everything is driven by /api/link and /api/codes through HDSync.
//
// A Telegram account may pair with several browsers, so the paired state lists them all
// and offers to unpair either this one or the lot.

(function () {
    'use strict';

    const FAVS_KEY = 'hd_favourites';
    const POLL_MS = 3000;
    const POLL_LIMIT = 120; // roughly six minutes, comfortably longer than a token lives

    const $ = (id) => document.getElementById(id);
    const cards = {
        loading: $('loadingCard'),
        start: $('startCard'),
        pending: $('pendingCard'),
        linked: $('linkedCard'),
        codes: $('codesCard'),
        recover: $('recoverCard'),
    };

    let pollTimer = null;
    let pollCount = 0;
    let toastTimer = null;

    function show(...names) {
        Object.entries(cards).forEach(([name, el]) => {
            if (el) el.hidden = !names.includes(name);
        });
        window.hydrateIcons();
    }

    function toast(message) {
        const el = $('toast');
        el.textContent = message;
        el.classList.remove('hidden', 'toast-out');
        void el.offsetWidth;
        el.classList.add('toast-in');
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            el.classList.replace('toast-in', 'toast-out');
            setTimeout(() => el.classList.add('hidden'), 280);
        }, 2200);
    }

    function note(el, message, kind) {
        el.textContent = message;
        el.className = `sync-note${kind ? ' ' + kind : ''}`;
        el.hidden = !message;
    }

    function stopPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = null;
        pollCount = 0;
    }

    function localFavouriteIds() {
        try {
            return JSON.parse(localStorage.getItem(FAVS_KEY) || '[]');
        } catch {
            return [];
        }
    }

    function writeLocalFavourites(ids) {
        try {
            localStorage.setItem(FAVS_KEY, JSON.stringify([...new Set(ids.map(String))]));
        } catch {
            /* nothing to do */
        }
    }

    // The server needs a tab for each entry, and localStorage only keeps ids. Linking is a
    // deliberate action, so it is a fine moment to fetch all three catalogues once and work
    // out which is which.
    async function resolveLocalFavourites() {
        const ids = new Set(localFavouriteIds().map(String));
        if (!ids.size) return [];

        const tabs = ['dict', 'idioms', 'names'];
        const pairs = [];
        for (const tab of tabs) {
            if (!ids.size) break;
            try {
                const response = await fetch(`/api/entries?tab=${tab}`);
                if (!response.ok) continue;
                const data = await response.json();
                (data.entries || []).forEach((entry) => {
                    const id = String(entry.id);
                    if (ids.has(id)) {
                        pairs.push({ tab, id });
                        ids.delete(id);
                    }
                });
            } catch {
                // An unreachable catalogue only means fewer favourites travel with the token.
            }
        }
        return pairs;
    }

    function formatDate(value) {
        if (!value) return 'unknown';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return 'unknown';
        return date.toLocaleDateString('en-SG', { year: 'numeric', month: 'short', day: 'numeric' });
    }

    // -- states -----------------------------------------------------------

    function showStart(favouriteCount) {
        stopPolling();
        show('start', 'recover');
        $('startCount').textContent = favouriteCount
            ? `${favouriteCount} saved ${favouriteCount === 1 ? 'entry' : 'entries'} in this browser will be merged in.`
            : 'Nothing is saved in this browser yet, so there is nothing to merge.';
        $('recoverOpen').hidden = false;
    }

    function showPending(token, url) {
        show('pending');
        $('pendingCode').textContent = token;
        $('openTelegram').href = url;
        note($('startError'), '');
    }

    function showLinked(state) {
        stopPolling();
        show('linked');
        $('linkedWho').textContent = state.telegram_username
            ? `@${state.telegram_username}`
            : 'linked account';
        $('linkedSince').textContent = formatDate(state.linked_at);
        $('linkedCount').textContent = String((state.favourites || []).length);
        $('linkedCodes').textContent = String(state.codes_remaining || 0);
        $('noCodesWarning').hidden = Boolean(state.codes_remaining);
        $('recoverOpen').hidden = true;
        note($('linkedNote'), '');
        renderDevices(state.devices || []);
    }

    function renderDevices(devices) {
        const list = $('deviceList');
        const section = $('deviceSection');
        list.innerHTML = '';

        if (!devices.length) {
            section.hidden = true;
            return;
        }

        devices.forEach((device) => {
            const row = document.createElement('div');
            row.className = 'sync-row';
            const name = document.createElement('dt');
            name.textContent = device.this_one
                ? `${device.label} (this one)`
                : device.label;
            const when = document.createElement('dd');
            when.textContent = formatDate(device.linked_at);
            row.append(name, when);
            list.appendChild(row);
        });

        section.hidden = false;
        $('unlinkAllBtn').hidden = devices.length < 2;
        $('deviceCount').textContent =
            devices.length === 1
                ? 'One browser is sharing this collection.'
                : `${devices.length} browsers are sharing this collection.`;
    }

    // -- linking ----------------------------------------------------------

    async function refresh({ mergeDown = true } = {}) {
        try {
            const state = await window.HDSync.status();
            if (!state.linked) {
                showStart(localFavouriteIds().length);
                return state;
            }
            if (mergeDown) {
                // Take the shared set down into this browser, keeping anything only held here.
                const ids = localFavouriteIds().concat((state.favourites || []).map((f) => f.id));
                writeLocalFavourites(ids);
            }
            showLinked(state);
            if (state.request && state.request.status === 'pending') {
                watchCodes(state.request.id, { resumed: true });
            }
            return state;
        } catch (err) {
            show('start', 'recover');
            note($('startError'), err.message, 'error');
            return { linked: false };
        }
    }

    async function startLink() {
        const button = $('startBtn');
        button.disabled = true;
        note($('startError'), 'Preparing the link...', 'busy');

        try {
            const favourites = await resolveLocalFavourites();
            const result = await window.HDSync.startLink(favourites);
            showPending(result.token, result.url);
            // Opening in a new tab keeps this page alive to notice the result.
            window.open(result.url, '_blank', 'noopener');
            watchForLink();
        } catch (err) {
            note($('startError'), err.message, 'error');
            if (err.status === 409) await refresh();
        } finally {
            button.disabled = false;
        }
    }

    function watchForLink() {
        stopPolling();
        pollTimer = setInterval(async () => {
            pollCount += 1;
            if (pollCount > POLL_LIMIT) {
                stopPolling();
                $('pendingStatus').textContent = 'That took too long. Start over when you are ready.';
                return;
            }
            try {
                const state = await window.HDSync.status();
                if (state.linked) {
                    stopPolling();
                    const ids = localFavouriteIds().concat((state.favourites || []).map((f) => f.id));
                    writeLocalFavourites(ids);
                    showLinked(state);
                    toast('Linked with Telegram');
                }
            } catch {
                // Keep waiting. A single failed poll is not worth reporting.
            }
        }, POLL_MS);
    }

    async function unlink({ all = false } = {}) {
        const button = all ? $('unlinkAllBtn') : $('unlinkBtn');
        button.disabled = true;
        note($('linkedNote'), 'Removing...', 'busy');
        try {
            const result = await window.HDSync.unlink({ all });
            toast(all ? 'All browsers unpaired' : 'This browser unpaired');
            showStart(localFavouriteIds().length);

            // The others may still be sharing, which is worth saying out loud.
            if (!all && result.remaining) {
                note(
                    $('startError'),
                    `This browser no longer shares favourites. ${result.remaining} ` +
                        `${result.remaining === 1 ? 'browser is' : 'browsers are'} still ` +
                        'paired with that Telegram account.',
                    'ok'
                );
            }
        } catch (err) {
            note($('linkedNote'), err.message, 'error');
        } finally {
            button.disabled = false;
        }
    }

    // -- recovery codes ---------------------------------------------------

    async function requestCodes() {
        show('codes');
        $('codesGrid').hidden = true;
        $('codesOnce').hidden = true;
        $('codesActions').hidden = true;
        note($('codesError'), '');
        $('codesWaiting').hidden = false;
        $('codesStatus').textContent = 'Asking Telegram to approve this...';

        try {
            const request = await window.HDSync.requestCodes();
            watchCodes(request.request_id);
        } catch (err) {
            $('codesWaiting').hidden = true;
            note($('codesError'), err.message, 'error');
        }
    }

    function watchCodes(requestId, { resumed = false } = {}) {
        if (!requestId) return;
        show('codes');
        $('codesWaiting').hidden = false;
        $('codesStatus').textContent = resumed
            ? 'A request is already waiting for approval in Telegram...'
            : 'Waiting for you to approve this in Telegram...';

        stopPolling();
        pollTimer = setInterval(async () => {
            pollCount += 1;
            if (pollCount > POLL_LIMIT) {
                stopPolling();
                $('codesWaiting').hidden = true;
                note($('codesError'), 'Nothing was approved in time. Ask again when you are ready.', 'warn');
                return;
            }
            try {
                const result = await window.HDSync.pollCodes(requestId);
                if (result.status === 'pending') return;
                stopPolling();
                $('codesWaiting').hidden = true;

                if (result.status === 'approved' && Array.isArray(result.codes)) {
                    revealCodes(result.codes);
                    return;
                }
                if (result.status === 'rejected') {
                    note($('codesError'), 'That request was rejected in Telegram, so nothing changed.', 'warn');
                    return;
                }
                if (result.status === 'expired') {
                    note($('codesError'), 'That request expired, so nothing changed.', 'warn');
                    return;
                }
                note($('codesError'), 'That request has already been dealt with.', 'warn');
            } catch (err) {
                stopPolling();
                $('codesWaiting').hidden = true;
                note($('codesError'), err.message, 'error');
            }
        }, POLL_MS);
    }

    function revealCodes(codes) {
        const grid = $('codesGrid');
        grid.innerHTML = '';
        codes.forEach((code) => {
            const span = document.createElement('span');
            span.textContent = code;
            grid.appendChild(span);
        });
        grid.hidden = false;
        $('codesOnce').hidden = false;
        $('codesActions').hidden = false;
        grid.dataset.codes = codes.join('\n');
    }

    async function copyCodes() {
        const codes = $('codesGrid').dataset.codes || '';
        try {
            await navigator.clipboard.writeText(codes);
            toast('Codes copied to clipboard');
        } catch {
            toast('Copying was blocked, so select them by hand');
        }
    }

    async function redeem() {
        const input = $('recoverInput');
        const button = $('recoverBtn');
        const code = input.value.trim();
        if (!code) {
            note($('recoverNote'), 'Enter one of your recovery codes.', 'warn');
            return;
        }

        button.disabled = true;
        note($('recoverNote'), 'Checking that code...', 'busy');
        try {
            const result = await window.HDSync.recover(code);
            // Keep anything that only existed on the shared side.
            const ids = localFavouriteIds().concat((result.favourites || []).map((f) => f.id));
            writeLocalFavourites(ids);
            window.HDSync.rememberLinked(false);

            const released = result.released || 0;
            note(
                $('recoverNote'),
                `${released} ${released === 1 ? 'browser was' : 'browsers were'} released, ` +
                    `and ${result.codes_remaining} ` +
                    `${result.codes_remaining === 1 ? 'code' : 'codes'} remain. Your ` +
                    'favourites are still here, and you can pair a new Telegram account ' +
                    'whenever you like.',
                'ok'
            );
            input.value = '';
            setTimeout(() => refresh({ mergeDown: false }), 1500);
        } catch (err) {
            note($('recoverNote'), err.message, 'error');
        } finally {
            button.disabled = false;
        }
    }

    // -- wiring -----------------------------------------------------------

    function wire() {
        $('startBtn').addEventListener('click', startLink);
        $('cancelPending').addEventListener('click', () => {
            stopPolling();
            showStart(localFavouriteIds().length);
        });
        $('unlinkBtn').addEventListener('click', () => unlink({ all: false }));
        $('unlinkAllBtn').addEventListener('click', () => unlink({ all: true }));
        $('codesBtn').addEventListener('click', requestCodes);
        $('codesDoneBtn').addEventListener('click', () => {
            $('codesGrid').dataset.codes = '';
            refresh({ mergeDown: false });
        });
        $('copyCodesBtn').addEventListener('click', copyCodes);
        $('recoverOpenBtn').addEventListener('click', () => {
            cards.recover.hidden = false;
            $('recoverInput').focus();
        });
        $('recoverCancel').addEventListener('click', () => {
            cards.recover.hidden = true;
            note($('recoverNote'), '');
        });
        $('recoverBtn').addEventListener('click', redeem);
        $('recoverInput').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') redeem();
        });

        // Coming back to the tab is the moment to check whether the tap in Telegram landed.
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && !cards.pending.hidden) {
                window.HDSync.status()
                    .then((state) => {
                        if (state.linked) {
                            stopPolling();
                            const ids = localFavouriteIds().concat(
                                (state.favourites || []).map((f) => f.id)
                            );
                            writeLocalFavourites(ids);
                            showLinked(state);
                            toast('Linked with Telegram');
                        }
                    })
                    .catch(() => {});
            }
        });
    }

    function init() {
        window.bootTheme();
        wire();

        if (!window.HDSync.hasDevice()) {
            showStart(localFavouriteIds().length);
            return;
        }
        show('loading');
        refresh();
    }

    init();
})();
