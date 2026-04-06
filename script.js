'use strict';

// ── Config ──────────────────────────────────────────────────────────────
const API_BASE = '/api';

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

// ── State ────────────────────────────────────────────────────────────────
let state = {
    activeTab: 'dict',
    query: '',
    sortAsc: true,
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
};

// ── DOM refs ─────────────────────────────────────────────────────────────
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

// ── Theme ─────────────────────────────────────────────────────────────────
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

// ── Modal helpers ─────────────────────────────────────────────────────────
function openModal(el) {
    el.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
}

function closeModal(el) {
    el.classList.add('hidden');
    document.body.style.overflow = '';
}

// ── Fetch entries ─────────────────────────────────────────────────────────
async function fetchTab(tab) {
    if (state.fetched[tab] || state.loading[tab]) return;
    state.loading[tab] = true;
    showLoading(true);

    try {
        const res = await fetch(`${API_BASE}/entries?tab=${tab}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        state.allEntries[tab] = data.entries || [];
        state.fetched[tab] = true;
    } catch (err) {
        console.error('Fetch error:', err);
        state.allEntries[tab] = [];
    }

    state.loading[tab] = false;
    render();
}

// ── Render ────────────────────────────────────────────────────────────────
function render() {
    const tab = state.activeTab;
    const isLoading = state.loading[tab];

    showLoading(isLoading);
    if (isLoading) return;

    const entries = filterAndSort(state.allEntries[tab], state.query, state.sortAsc);

    emptyState.classList.toggle('hidden', entries.length > 0);
    resultsCount.textContent = entries.length === 1 ?
        `1 ${TAB_LABELS[tab].slice(0, -1).toLowerCase()}` :
        `${entries.length} ${TAB_LABELS[tab].toLowerCase()}`;

    entriesGrid.innerHTML = '';
    entries.forEach((entry, i) => {
        const card = document.createElement('div');
        card.className = 'entry-card';
        card.style.animationDelay = `${Math.min(i * 30, 300)}ms`;
        card.setAttribute('tabindex', '0');
        card.setAttribute('role', 'button');
        card.setAttribute('aria-label', entry.word);
        card.innerHTML = `
      <span class="entry-tag">${TAB_LABELS[tab].slice(0, -1)}</span>
      <div class="entry-word">${escHtml(entry.word || '—')}</div>
      <div class="entry-preview">${escHtml(entry.definition || 'No definition available.')}</div>
    `;
        card.addEventListener('click', () => openEntry(entry, tab));
        card.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') openEntry(entry, tab);
        });
        entriesGrid.appendChild(card);
    });
}

function filterAndSort(entries, query, asc) {
    let out = entries;
    if (query.trim()) {
        const q = query.toLowerCase().trim();
        out = out.filter(e =>
            (e.word || '').toLowerCase().includes(q) ||
            (e.definition || '').toLowerCase().includes(q)
        );
    }
    return [...out].sort((a, b) => {
        const cmp = (a.word || '').localeCompare(b.word || '');
        return asc ? cmp : -cmp;
    });
}

function showLoading(visible) {
    loadingState.classList.toggle('hidden', !visible);
    if (visible) {
        emptyState.classList.add('hidden');
        entriesGrid.innerHTML = '';
    }
}

// ── Entry modal ───────────────────────────────────────────────────────────
function openEntry(entry, tab) {
    modalTag.textContent = TAB_LABELS[tab].slice(0, -1);
    modalWord.textContent = entry.word || '—';
    modalDefinition.textContent = entry.definition || 'No definition available.';
    modalMeta.textContent = entry.created_at ?
        `Added: ${new Date(entry.created_at).toLocaleDateString('en-SG', { year: 'numeric', month: 'short', day: 'numeric' })}` :
        '';
    openModal(entryModal);
}

// ── Utils ─────────────────────────────────────────────────────────────────
function escHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// ── Event listeners ───────────────────────────────────────────────────────
searchInput.addEventListener('input', () => {
    state.query = searchInput.value;
    clearBtn.classList.toggle('hidden', !state.query);
    render();
});

clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    state.query = '';
    clearBtn.classList.add('hidden');
    searchInput.focus();
    render();
});

sortBtn.addEventListener('click', () => {
    state.sortAsc = !state.sortAsc;
    sortBtn.textContent = state.sortAsc ? 'A→Z' : 'Z→A';
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
        searchInput.value = '';
        clearBtn.classList.add('hidden');
        fetchTab(state.activeTab);
    });
});

themeBtn.addEventListener('click', () => openModal(themeModal));
themeModalClose.addEventListener('click', () => closeModal(themeModal));
entryModalClose.addEventListener('click', () => closeModal(entryModal));

// Close modals on overlay click
[entryModal, themeModal].forEach(overlay => {
    overlay.addEventListener('click', e => {
        if (e.target === overlay) closeModal(overlay);
    });
});

// Close modals on Escape
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        closeModal(entryModal);
        closeModal(themeModal);
    }
});

// ── Init ──────────────────────────────────────────────────────────────────
function init() {
    // Restore theme
    const savedTheme = localStorage.getItem('hd_theme') || 'classic';
    applyTheme(savedTheme);

    // Initial fetch
    fetchTab('dict');

    // Register service worker
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
    }
}

init();