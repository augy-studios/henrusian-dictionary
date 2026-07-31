# Henrusian Dictionary

An open-source, installable web dictionary for the **Henrusian** constructed language — 15th Edition. Search words, idioms and names, star your favourites, and pick a theme. It works offline once loaded, and installs as a PWA on desktop and mobile.

Built and maintained by [Augy Studios](https://github.com/augy-studios) under the UwU Apps umbrella.

## Features

- **Three catalogues** — Words, Idioms and Names, each backed by its own table.
- **Instant search** across entries and definitions, with A→Z / Z→A sorting and paginated results (50 per page).
- **Favourites** — star any entry; saved in `localStorage` and browsable from a dedicated modal.
- **Entry detail view** with one-tap copy for the word or its definition.
- **Eight themes**, from Classic green through HelloTheme, remembered between visits.
- **PWA** — service worker caching, offline fallback, install prompt, standalone display.

## Project layout

```
main-site/
├── index.html          # App shell — header, search, tabs, modals
├── script.js           # All app logic: fetching, search, sort, favourites, themes
├── style.css           # Styles + theme variables
├── sw.js               # Service worker (cache-first with background refresh)
├── manifest.json       # PWA manifest
├── 404.html / 404.css  # Not-found page
└── api/
    └── entries.js      # GET /api/entries?tab=dict|idioms|names
```

The front end is plain HTML, CSS and vanilla JavaScript — no build step, no framework, no bundler. The `api/` folder holds Vercel serverless functions.

## How the API works

Data lives in Supabase, reached over the PostgREST endpoint with a service key that never leaves the server.

1. The browser calls `/api/entries?tab=dict|idioms|names`.
2. Requests are answered from Supabase, paged 1000 rows at a time, and cached at the CDN edge for 60 seconds.

### Expected tables

| Table | Purpose |
| --- | --- |
| `henrusian15_dict` | Word entries — `id`, `word`, `definition`, `created_at` |
| `henrusian15_idioms` | Idiom entries — same shape |
| `henrusian15_names` | Name entries — same shape |

### Environment variables

| Variable | Description |
| --- | --- |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Service role key — server-side only, never expose to the client |

## Running locally

The serverless functions need the Vercel dev server:

```bash
npm i -g vercel
cd main-site
vercel dev
```

Set both environment variables in a `.env` file (or via `vercel env pull`) before starting. Without them the API returns `500 Supabase credentials not configured`.

If you only want to work on the UI, any static server over `main-site/` will do — the entry list will fail to load, but layout, themes and modals are all testable.

## Deploying

The project targets Vercel with `main-site/` as the root directory; `vercel.json` enables clean URLs and pins the `sin1` region. Any host that can run Node serverless functions and serve the static folder will work.

## Contributing

Issues and pull requests are welcome. Please read the [Code of Conduct](CODE_OF_CONDUCT.md) first.

A few notes that will save you a round trip:
- Keep the front end dependency-free — no build step is a deliberate choice.
- Bump `CACHE` in [sw.js](main-site/sw.js) when you change a cached asset, otherwise returning visitors keep the stale copy.
- New themes go in the `THEMES` array in [script.js](main-site/script.js) and need matching `[data-theme]` variables in [style.css](main-site/style.css).

Dictionary content itself (words, definitions, idioms) lives in the database rather than the repo — open an issue for corrections or additions.

## Support

If this is useful to you, you can [buy Augy a coffee](https://donate.stripe.com/28o2akeAr3hv0DK6oo).

## License

[MIT](LICENSE) © 2026 Augy Studios
