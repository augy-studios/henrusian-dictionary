'use strict';

// -- Config
const API_BASE = '/api';
const PAGE_SIZE = 50;

const TAB_LABELS = {
    dict: 'Words',
    idioms: 'Idioms',
    names: 'Names'
};

// -- State
let state = {
    activeTab: 'dict',
    query: '',
    sortMode: 'alpha-asc',
    allEntries: {
        dict: [],
        idioms: [],
        names: []
    },
    loading: {
        dict: false,
        idioms: false,
        names: false
    },
    fetched: {
        dict: false,
        idioms: false,
        names: false
    },
    page: {
        dict: 0,
        idioms: 0,
        names: 0
    },
    favourites: new Set(JSON.parse(localStorage.getItem('hd_favourites') || '[]')),
    synced: false,
};

// -- DOM refs
const $ = id => document.getElementById(id);
const searchInput = $('searchInput');
const clearBtn = $('clearBtn');
const entriesGrid = $('entriesGrid');
const emptyState = $('emptyState');
const loadingState = $('loadingState');
const resultsCount = $('resultsCount');
const sortBtn = $('sortBtn');

const entryModal = $('entryModal');
const entryModalClose = $('entryModalClose');
const modalTag = $('modalTag');
const modalWord = $('modalWord');
const modalDefinition = $('modalDefinition');
const modalMeta = $('modalMeta');

const entryModalStar = $('entryModalStar');
const copyWordBtn = $('copyWordBtn');
const copyDefBtn = $('copyDefBtn');
const pagination = $('pagination');
const toast = $('toast');
const favsBtn = $('favsBtn');
const favsModal = $('favsModal');
const favsModalClose = $('favsModalClose');
const favsModalSubtitle = $('favsModalSubtitle');
const favsList = $('favsList');

let currentEntry = null;
let currentEntryTab = null;
let toastTimer = null;

function showToast(message) {
    toast.textContent = message;
    toast.classList.remove('hidden', 'toast-out');
    void toast.offsetWidth; // force reflow for re-animation
    toast.classList.add('toast-in');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.classList.replace('toast-in', 'toast-out');
        setTimeout(() => toast.classList.add('hidden'), 280);
    }, 2200);
}

function saveFavourites() {
    localStorage.setItem('hd_favourites', JSON.stringify([...state.favourites]));
    syncFavsBtn();
}

function syncFavsBtn() {
    favsBtn.classList.toggle('active', state.favourites.size > 0);
}

// When this browser is linked to Telegram, a star is also written to the shared set. The
// local copy is updated either way, so a failed write never blocks the interface, and the
// next visit reconciles it.
function pushFavourite(id, tab, saved) {
    if (!state.synced || !tab) return;
    const call = saved
        ? window.HDSync.addFavourite(tab, id)
        : window.HDSync.removeFavourite(tab, id);
    call.catch(() => showToast('Saved here, but Telegram could not be reached'));
}

function toggleFavourite(id, tab) {
    if (state.favourites.has(id)) {
        state.favourites.delete(id);
    } else {
        state.favourites.add(id);
    }
    saveFavourites();
    pushFavourite(id, tab, state.favourites.has(id));
}

// Pulls the shared set down and pushes up anything this browser had on its own, so the two
// sides agree without either losing an entry.
async function reconcileFavourites() {
    if (!window.HDSync || !window.HDSync.hasDevice() || !window.HDSync.wasLinked()) return;

    try {
        const remote = await window.HDSync.status();
        if (!remote.linked) {
            window.HDSync.rememberLinked(false);
            return;
        }

        state.synced = true;
        const shared = new Set((remote.favourites || []).map((item) => String(item.id)));
        const onlyHere = [...state.favourites].filter((id) => !shared.has(String(id)));

        shared.forEach((id) => state.favourites.add(id));
        saveFavourites();
        render();

        if (onlyHere.length) {
            const pairs = onlyHere
                .map((id) => {
                    const found = findEntryAnywhere(id);
                    return found ? { tab: found.tab, id: String(id) } : null;
                })
                .filter(Boolean);
            if (pairs.length) window.HDSync.mergeFavourites(pairs).catch(() => {});
        }
    } catch {
        // Offline, or the sync service is down. The local set is still correct.
    }
}

function findEntryAnywhere(id) {
    for (const tab of Object.keys(state.allEntries)) {
        const hit = state.allEntries[tab].find((entry) => String(entry.id) === String(id));
        if (hit) return { tab, entry: hit };
    }
    return null;
}

// -- Fetch entries
async function fetchTab(tab) {
    if (state.loading[tab]) return;
    if (state.fetched[tab]) { render(); return; }
    state.loading[tab] = true;
    showLoading(true);

    try {
        const res = await fetch(`${API_BASE}/entries?tab=${tab}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const entries = data.entries || [];
        state.allEntries[tab] = tab === 'dict'
            ? entries.filter(e => !['Zz resume right here'].includes((e.word || '').trim()))
            : entries;
        state.fetched[tab] = true;
    } catch (err) {
        console.error('Fetch error:', err);
        state.allEntries[tab] = [];
    }

    state.loading[tab] = false;
    render();
}

// -- Render
function render() {
    const tab = state.activeTab;
    const isLoading = state.loading[tab];

    showLoading(isLoading);
    if (isLoading) return;

    const allFiltered = filterAndSort(state.allEntries[tab], state.query, state.sortMode);
    const totalPages = Math.max(1, Math.ceil(allFiltered.length / PAGE_SIZE));
    if (state.page[tab] >= totalPages) state.page[tab] = totalPages - 1;

    const start = state.page[tab] * PAGE_SIZE;
    const entries = allFiltered.slice(start, start + PAGE_SIZE);

    emptyState.classList.toggle('hidden', allFiltered.length > 0);
    resultsCount.textContent = allFiltered.length === 1 ?
        `1 ${TAB_LABELS[tab].slice(0, -1).toLowerCase()}` :
        `${allFiltered.length} ${TAB_LABELS[tab].toLowerCase()}`;

    entriesGrid.innerHTML = '';
    entries.forEach((entry, i) => {
        const card = document.createElement('div');
        card.className = 'entry-card';
        card.dataset.entryId = entry.id;
        card.style.animationDelay = `${Math.min(i * 30, 300)}ms`;
        card.setAttribute('tabindex', '0');
        card.setAttribute('role', 'button');
        card.setAttribute('aria-label', entry.word);
        const isFav = state.favourites.has(entry.id);
        card.innerHTML = `
      <button class="btn-star${isFav ? ' active' : ''}" type="button" aria-label="${isFav ? 'Remove from favourites' : 'Add to favourites'}"><span data-icon="star"></span></button>
      <span class="entry-tag">${TAB_LABELS[tab].slice(0, -1)}</span>
      <div class="entry-word">${escHtml(entry.word || '-')}</div>
      <div class="entry-preview">${escHtml(entry.definition || 'No definition available.')}</div>
    `;
        const starBtn = card.querySelector('.btn-star');
        starBtn.addEventListener('click', e => {
            e.stopPropagation();
            toggleFavourite(entry.id, tab);
            const nowFav = state.favourites.has(entry.id);
            starBtn.classList.toggle('active', nowFav);
            starBtn.setAttribute('aria-label', nowFav ? 'Remove from favourites' : 'Add to favourites');
            showToast(nowFav ? 'Added to favourites' : 'Removed from favourites');
            if (currentEntry && currentEntry.id === entry.id) {
                entryModalStar.classList.toggle('active', nowFav);
                entryModalStar.setAttribute('aria-label', nowFav ? 'Remove from favourites' : 'Add to favourites');
            }
        });
        card.addEventListener('click', () => openEntry(entry, tab));
        card.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') openEntry(entry, tab);
        });
        entriesGrid.appendChild(card);
    });

    hydrateIcons(entriesGrid);
    renderPagination(totalPages, state.page[tab], tab);
}

function renderPagination(totalPages, currentPage, tab) {
    if (totalPages <= 1) {
        pagination.classList.add('hidden');
        return;
    }
    pagination.classList.remove('hidden');
    pagination.innerHTML = `
        <button class="btn-page" id="firstPage" type="button" ${currentPage === 0 ? 'disabled' : ''}><span data-icon="chevrons-left"></span> First</button>
        <button class="btn-page" id="prevPage" type="button" ${currentPage === 0 ? 'disabled' : ''}><span data-icon="chevron-left"></span> Prev</button>
        <span class="page-info">Page ${currentPage + 1} of ${totalPages}</span>
        <button class="btn-page" id="nextPage" type="button" ${currentPage >= totalPages - 1 ? 'disabled' : ''}>Next <span data-icon="chevron-right"></span></button>
        <button class="btn-page" id="lastPage" type="button" ${currentPage >= totalPages - 1 ? 'disabled' : ''}>Last <span data-icon="chevrons-right"></span></button>
    `;
    hydrateIcons(pagination);
    pagination.querySelector('#firstPage').addEventListener('click', () => {
        state.page[tab] = 0;
        render();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    pagination.querySelector('#prevPage').addEventListener('click', () => {
        state.page[tab]--;
        render();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    pagination.querySelector('#nextPage').addEventListener('click', () => {
        state.page[tab]++;
        render();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
    pagination.querySelector('#lastPage').addEventListener('click', () => {
        state.page[tab] = totalPages - 1;
        render();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    });
}

function filterAndSort(entries, query, sortMode) {
    let out = entries;
    if (query.trim()) {
        const q = query.toLowerCase().trim();
        out = out.filter(e =>
            (e.word || '').toLowerCase().includes(q) ||
            (e.definition || '').toLowerCase().includes(q)
        );
    }
    return [...out].sort((a, b) => {
        if (sortMode === 'date-asc' || sortMode === 'date-desc') {
            const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
            const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
            return sortMode === 'date-asc' ? ta - tb : tb - ta;
        }
        const cmp = (a.word || '').localeCompare(b.word || '');
        return sortMode === 'alpha-asc' ? cmp : -cmp;
    });
}

function showLoading(visible) {
    loadingState.classList.toggle('hidden', !visible);
    if (visible) {
        emptyState.classList.add('hidden');
        entriesGrid.innerHTML = '';
    }
}

// -- Entry modal
function openEntry(entry, tab) {
    currentEntry = entry;
    currentEntryTab = tab;
    const isFav = state.favourites.has(entry.id);
    modalTag.textContent = TAB_LABELS[tab].slice(0, -1);
    modalWord.textContent = entry.word || '-';
    modalDefinition.textContent = entry.definition || 'No definition available.';
    modalMeta.textContent = entry.created_at ?
        `Added: ${new Date(entry.created_at).toLocaleDateString('en-SG', { year: 'numeric', month: 'short', day: 'numeric' })}` :
        '';
    entryModalStar.classList.toggle('active', isFav);
    entryModalStar.setAttribute('aria-label', isFav ? 'Remove from favourites' : 'Add to favourites');
    copyWordBtn.onclick = () => {
        navigator.clipboard.writeText(entry.word || '');
        showToast('Word copied to clipboard');
    };
    copyDefBtn.onclick = () => {
        navigator.clipboard.writeText(entry.definition || '');
        showToast('Definition copied to clipboard');
    };
    openModal('entryModal');
}

// -- Favourites modal
function openFavourites() {
    const allEntries = Object.entries(state.allEntries).flatMap(([tab, entries]) =>
        entries.filter(e => state.favourites.has(e.id)).map(e => ({ ...e, tab }))
    );

    favsModalSubtitle.textContent = allEntries.length === 0
        ? 'No favourites yet, star an entry to save it here.'
        : `${allEntries.length} saved ${allEntries.length === 1 ? 'entry' : 'entries'}`;

    favsList.innerHTML = '';
    allEntries.forEach(entry => {
        const row = document.createElement('div');
        row.className = 'favs-row';
        row.innerHTML = `
            <div class="favs-row-info">
                <span class="entry-tag">${TAB_LABELS[entry.tab].slice(0, -1)}</span>
                <span class="favs-word">${escHtml(entry.word || '-')}</span>
                <span class="favs-preview">${escHtml(entry.definition || '')}</span>
            </div>
            <button class="btn-trash favs-unstar" type="button" aria-label="Remove from favourites">
                <span data-icon="trash"></span>
            </button>
        `;
        row.querySelector('.favs-row-info').addEventListener('click', () => {
            closeModal('favsModal');
            openEntry(entry, entry.tab);
        });
        const unstarBtn = row.querySelector('.favs-unstar');
        unstarBtn.addEventListener('click', () => {
            toggleFavourite(entry.id, entry.tab);
            row.remove();
            showToast('Removed from favourites');
            const remaining = favsList.querySelectorAll('.favs-row').length;
            favsModalSubtitle.textContent = remaining === 0
                ? 'No favourites yet, star an entry to save it here.'
                : `${remaining} saved ${remaining === 1 ? 'entry' : 'entries'}`;
            // Sync card star in grid
            const card = entriesGrid.querySelector(`[data-entry-id="${entry.id}"]`);
            if (card) {
                const starBtn = card.querySelector('.btn-star');
                if (starBtn) {
                    starBtn.classList.remove('active');
                    starBtn.setAttribute('aria-label', 'Add to favourites');
                }
            }
        });
        favsList.appendChild(row);
    });

    hydrateIcons(favsList);
    openModal('favsModal');
}

// -- Utils
function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// -- Event listeners
searchInput.addEventListener('input', () => {
    state.query = searchInput.value;
    state.page[state.activeTab] = 0;
    clearBtn.classList.toggle('hidden', !state.query);
    render();
});

clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    state.query = '';
    state.page[state.activeTab] = 0;
    clearBtn.classList.add('hidden');
    searchInput.focus();
    render();
});

const SORT_CYCLE = ['alpha-asc', 'alpha-desc', 'date-desc', 'date-asc'];
const ARROW = '<span data-icon="arrow-right"></span>';
const SORT_LABELS = {
    'alpha-asc':  `A ${ARROW} Z`,
    'alpha-desc': `Z ${ARROW} A`,
    'date-desc':  'Newest',
    'date-asc':   'Oldest',
};

function setSortLabel(mode) {
    sortBtn.innerHTML = SORT_LABELS[mode];
    hydrateIcons(sortBtn);
}

sortBtn.addEventListener('click', () => {
    const next = SORT_CYCLE[(SORT_CYCLE.indexOf(state.sortMode) + 1) % SORT_CYCLE.length];
    state.sortMode = next;
    state.page[state.activeTab] = 0;
    setSortLabel(next);
    render();
});

document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-btn').forEach(b => {
            b.classList.remove('active');
            b.setAttribute('aria-selected', 'false');
        });
        btn.classList.add('active');
        btn.setAttribute('aria-selected', 'true');
        state.activeTab = btn.dataset.tab;
        state.query = '';
        state.page[state.activeTab] = 0;
        searchInput.value = '';
        clearBtn.classList.add('hidden');
        fetchTab(state.activeTab);
    });
});

entryModalClose.addEventListener('click', () => closeModal('entryModal'));
favsBtn.addEventListener('click', () => openFavourites());
favsModalClose.addEventListener('click', () => closeModal('favsModal'));

entryModalStar.addEventListener('click', () => {
    if (!currentEntry) return;
    toggleFavourite(currentEntry.id, currentEntryTab);
    const nowFav = state.favourites.has(currentEntry.id);
    entryModalStar.classList.toggle('active', nowFav);
    entryModalStar.setAttribute('aria-label', nowFav ? 'Remove from favourites' : 'Add to favourites');
    showToast(nowFav ? 'Added to favourites' : 'Removed from favourites');
    const card = entriesGrid.querySelector(`[data-entry-id="${currentEntry.id}"]`);
    if (card) {
        const starBtn = card.querySelector('.btn-star');
        if (starBtn) {
            starBtn.classList.toggle('active', nowFav);
            starBtn.setAttribute('aria-label', nowFav ? 'Remove from favourites' : 'Add to favourites');
        }
    }
});

// Backdrop clicks are wired in js/theme.js for every .modal-backdrop.

// Close modals on Escape; arrow keys for pagination
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        closeModal('entryModal');
        closeModal('themeModal');
        closeModal('favsModal');
    }

    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const anyModalOpen = !!document.querySelector('.modal-backdrop:not(.hidden)');
        if (anyModalOpen || document.activeElement === searchInput) return;

        const tab = state.activeTab;
        const allFiltered = filterAndSort(state.allEntries[tab], state.query, state.sortMode);
        const totalPages = Math.max(1, Math.ceil(allFiltered.length / PAGE_SIZE));

        if (e.key === 'ArrowLeft' && state.page[tab] > 0) {
            state.page[tab]--;
            render();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        } else if (e.key === 'ArrowRight' && state.page[tab] < totalPages - 1) {
            state.page[tab]++;
            render();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    }
});

// -- Deep links
// The bot links to /?tab=dict&entry=123, so a shared entry opens where it was meant to.
function pendingDeepLink() {
    const params = new URLSearchParams(window.location.search);
    const entry = params.get('entry');
    if (!entry) return null;
    const tab = params.get('tab');
    return { entry, tab: TAB_LABELS[tab] ? tab : 'dict' };
}

function activateTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        const on = btn.dataset.tab === tab;
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    state.activeTab = tab;
}

async function openDeepLink(target) {
    activateTab(target.tab);
    await fetchTab(target.tab);
    const entry = state.allEntries[target.tab].find(e => String(e.id) === String(target.entry));
    if (entry) {
        openEntry(entry, target.tab);
    } else {
        showToast('That entry could not be found');
    }
    // Leave the address bar clean, so a refresh does not reopen the modal.
    window.history.replaceState({}, '', window.location.pathname);
}

// -- Init
function init() {
    bootTheme();
    syncFavsBtn();
    setSortLabel(state.sortMode);

    const target = pendingDeepLink();
    if (target) {
        openDeepLink(target).then(reconcileFavourites);
    } else {
        fetchTab('dict').then(reconcileFavourites);
    }

    // Register service worker
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    }
}

init();