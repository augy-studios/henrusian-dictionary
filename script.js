'use strict';

// ── Config
const API_BASE = '/api';
const PAGE_SIZE = 50;

const THEMES = [{
        id: 'classic',
        label: 'Classic',
        hex: '#ccffcc',
        attr: ''
    },
    {
        id: 'pink',
        label: 'Not Green 1',
        hex: '#ffcccc',
        attr: 'pink'
    },
    {
        id: 'blue',
        label: 'Not Green 2',
        hex: '#ccccff',
        attr: 'blue'
    },
    {
        id: 'yellow',
        label: 'Not Green 3',
        hex: '#ffffcc',
        attr: 'yellow'
    },
    {
        id: 'magenta',
        label: 'Not Green 4',
        hex: '#ffccff',
        attr: 'magenta'
    },
    {
        id: 'cyan',
        label: 'Not Green 5',
        hex: '#ccffff',
        attr: 'cyan'
    },
    {
        id: 'white',
        label: 'Really Really Light Green',
        hex: '#ffffff',
        attr: 'white'
    },
];

const TAB_LABELS = {
    dict: 'Words',
    idioms: 'Idioms',
    names: 'Names'
};

// ── State
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
};

// ── DOM refs
const $ = id => document.getElementById(id);
const searchInput = $('searchInput');
const clearBtn = $('clearBtn');
const entriesGrid = $('entriesGrid');
const emptyState = $('emptyState');
const loadingState = $('loadingState');
const resultsCount = $('resultsCount');
const sortBtn = $('sortBtn');
const themeBtn = $('themeBtn');

const entryModal = $('entryModal');
const entryModalClose = $('entryModalClose');
const modalTag = $('modalTag');
const modalWord = $('modalWord');
const modalDefinition = $('modalDefinition');
const modalMeta = $('modalMeta');

const themeModal = $('themeModal');
const themeModalClose = $('themeModalClose');
const themeGrid = $('themeGrid');
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
    const hasFavs = state.favourites.size > 0;
    favsBtn.classList.toggle('active', hasFavs);
    favsBtn.querySelector('polygon').style.fill = hasFavs ? 'currentColor' : 'none';
}

function toggleFavourite(id) {
    if (state.favourites.has(id)) {
        state.favourites.delete(id);
    } else {
        state.favourites.add(id);
    }
    saveFavourites();
}

// ── Theme
function applyTheme(id) {
    const theme = THEMES.find(t => t.id === id) || THEMES[0];
    document.documentElement.dataset.theme = theme.attr;
    document.querySelector('meta[name="theme-color"]').content = theme.hex;
    localStorage.setItem('hd_theme', id);
    renderThemeGrid(id);
}

function renderThemeGrid(activeId) {
    themeGrid.innerHTML = '';
    THEMES.forEach(theme => {
        const btn = document.createElement('button');
        btn.className = 'theme-option' + (theme.id === activeId ? ' selected' : '');
        btn.setAttribute('aria-pressed', theme.id === activeId);
        btn.innerHTML = `
      <span class="theme-swatch" style="background:${theme.hex}"></span>
      <span class="theme-label">
        ${theme.label}
        <small>${theme.hex}</small>
      </span>
    `;
        btn.addEventListener('click', () => {
            applyTheme(theme.id);
            closeModal(themeModal);
        });
        themeGrid.appendChild(btn);
    });
}

// ── Modal helpers
function openModal(el) {
    el.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeModal(el) {
    el.classList.add('hidden');
    document.body.style.overflow = '';
}

// ── Fetch entries
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
            ? entries.filter(e => (e.word || '').trim() !== 'Zz resume here')
            : entries;
        state.fetched[tab] = true;
    } catch (err) {
        console.error('Fetch error:', err);
        state.allEntries[tab] = [];
    }

    state.loading[tab] = false;
    render();
}

// ── Render
const STAR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="1em" height="1em" aria-hidden="true"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>`;

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
      <button class="btn-star${isFav ? ' active' : ''}" aria-label="${isFav ? 'Remove from favourites' : 'Add to favourites'}">${STAR_SVG}</button>
      <span class="entry-tag">${TAB_LABELS[tab].slice(0, -1)}</span>
      <div class="entry-word">${escHtml(entry.word || '—')}</div>
      <div class="entry-preview">${escHtml(entry.definition || 'No definition available.')}</div>
    `;
        const starBtn = card.querySelector('.btn-star');
        starBtn.addEventListener('click', e => {
            e.stopPropagation();
            toggleFavourite(entry.id);
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

    renderPagination(totalPages, state.page[tab], tab);
}

const SVG_CHEVRONS_LEFT  = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="1em" height="1em" aria-hidden="true"><polyline points="11 17 6 12 11 7"/><polyline points="18 17 13 12 18 7"/></svg>`;
const SVG_CHEVRON_LEFT   = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="1em" height="1em" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>`;
const SVG_CHEVRON_RIGHT  = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="1em" height="1em" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>`;
const SVG_CHEVRONS_RIGHT = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="1em" height="1em" aria-hidden="true"><polyline points="13 17 18 12 13 7"/><polyline points="6 17 11 12 6 7"/></svg>`;

function renderPagination(totalPages, currentPage, tab) {
    if (totalPages <= 1) {
        pagination.classList.add('hidden');
        return;
    }
    pagination.classList.remove('hidden');
    pagination.innerHTML = `
        <button class="btn-page" id="firstPage" ${currentPage === 0 ? 'disabled' : ''}>${SVG_CHEVRONS_LEFT} First</button>
        <button class="btn-page" id="prevPage" ${currentPage === 0 ? 'disabled' : ''}>${SVG_CHEVRON_LEFT} Prev</button>
        <span class="page-info">Page ${currentPage + 1} of ${totalPages}</span>
        <button class="btn-page" id="nextPage" ${currentPage >= totalPages - 1 ? 'disabled' : ''}>Next ${SVG_CHEVRON_RIGHT}</button>
        <button class="btn-page" id="lastPage" ${currentPage >= totalPages - 1 ? 'disabled' : ''}>Last ${SVG_CHEVRONS_RIGHT}</button>
    `;
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

// ── Entry modal
function openEntry(entry, tab) {
    currentEntry = entry;
    const isFav = state.favourites.has(entry.id);
    modalTag.textContent = TAB_LABELS[tab].slice(0, -1);
    modalWord.textContent = entry.word || '—';
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
    openModal(entryModal);
}

// ── Favourites modal
function openFavourites() {
    const allEntries = Object.entries(state.allEntries).flatMap(([tab, entries]) =>
        entries.filter(e => state.favourites.has(e.id)).map(e => ({ ...e, tab }))
    );

    favsModalSubtitle.textContent = allEntries.length === 0
        ? 'No favourites yet — star an entry to save it here.'
        : `${allEntries.length} saved ${allEntries.length === 1 ? 'entry' : 'entries'}`;

    favsList.innerHTML = '';
    allEntries.forEach(entry => {
        const row = document.createElement('div');
        row.className = 'favs-row';
        row.innerHTML = `
            <div class="favs-row-info">
                <span class="entry-tag">${TAB_LABELS[entry.tab].slice(0, -1)}</span>
                <span class="favs-word">${escHtml(entry.word || '—')}</span>
                <span class="favs-preview">${escHtml(entry.definition || '')}</span>
            </div>
            <button class="btn-trash favs-unstar" aria-label="Remove from favourites">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="1em" height="1em" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            </button>
        `;
        row.querySelector('.favs-row-info').addEventListener('click', () => {
            closeModal(favsModal);
            openEntry(entry, entry.tab);
        });
        const unstarBtn = row.querySelector('.favs-unstar');
        unstarBtn.addEventListener('click', () => {
            toggleFavourite(entry.id);
            row.remove();
            showToast('Removed from favourites');
            const remaining = favsList.querySelectorAll('.favs-row').length;
            favsModalSubtitle.textContent = remaining === 0
                ? 'No favourites yet — star an entry to save it here.'
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

    openModal(favsModal);
}

// ── Utils
function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ── Event listeners
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
const SORT_LABELS = { 'alpha-asc': 'A→Z', 'alpha-desc': 'Z→A', 'date-desc': 'Newest', 'date-asc': 'Oldest' };

sortBtn.addEventListener('click', () => {
    const next = SORT_CYCLE[(SORT_CYCLE.indexOf(state.sortMode) + 1) % SORT_CYCLE.length];
    state.sortMode = next;
    state.page[state.activeTab] = 0;
    sortBtn.textContent = SORT_LABELS[next];
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

themeBtn.addEventListener('click', () => openModal(themeModal));
themeModalClose.addEventListener('click', () => closeModal(themeModal));
entryModalClose.addEventListener('click', () => closeModal(entryModal));
favsBtn.addEventListener('click', () => openFavourites());
favsModalClose.addEventListener('click', () => closeModal(favsModal));

entryModalStar.addEventListener('click', () => {
    if (!currentEntry) return;
    toggleFavourite(currentEntry.id);
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

// Close modals on overlay click
[entryModal, themeModal, favsModal].forEach(overlay => {
    overlay.addEventListener('click', e => {
        if (e.target === overlay) closeModal(overlay);
    });
});

// Close modals on Escape; arrow keys for pagination
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        closeModal(entryModal);
        closeModal(themeModal);
        closeModal(favsModal);
    }

    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        const anyModalOpen = !entryModal.classList.contains('hidden') ||
            !themeModal.classList.contains('hidden') ||
            !favsModal.classList.contains('hidden');
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

// ── Init
function init() {
    // Restore theme
    const savedTheme = localStorage.getItem('hd_theme') || 'classic';
    applyTheme(savedTheme);
    syncFavsBtn();

    // Initial fetch
    fetchTab('dict');

    // Register service worker
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    }
}

init();