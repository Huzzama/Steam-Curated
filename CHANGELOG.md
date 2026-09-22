# Changelog

## 2.0 — redesign

### Connections
- One shared HTTP session (certifi, UA, retries) for every service; typed
  `ApiError` / `Unreachable` errors surface as readable messages in the UI.
- PimpMySteam account is the single source of credentials (`creds.json`,
  migrated automatically from the old `~/.config/pimpmysteam` file and from
  `settings.json`); Steam OpenID login removed.
- Google Drive sync authenticates through the PimpMySteam backend, never
  uploads settings or credentials, and runs entirely off the GUI thread
  (startup and quit no longer freeze for 10 s).
- Wishlist import and profile info go through the backend's `/steam/me/*`
  proxy; library stats read the public community profile — the app never
  holds a Steam Web API key (the old `/auth/steam-api-key` endpoint is gone).
- All-time-low prices come from IsThereAnyDeal when a key is set (fetched in
  two batched requests during "Refresh prices" and right after the key is
  verified); without a key the app keeps its own observed price log
  (`price_log.json`) and still gives advice from typical publisher discounts.
  The SteamDB scraper was blocked by Cloudflare and returned nothing.
- Background work returns to the GUI thread through Qt signals
  (`ui/async_bridge.run_async`). The old `QTimer.singleShot` from threads
  silently never fired: wishlist sync, cover download, price refresh and the
  detail panel refresh button all work again.
- Atomic JSON writes with `.bak` recovery; one disk write per import;
  TTL caches for store details, sale banners cached on disk.
- Bundle/edition lookup passes Steam's age gate; logging to `logs/curator.log`.

### Interface
- New design system: Inter / Space Mono / Bebas Neue bundled, Lucide SVG
  icons, tokenised dark palette, single global stylesheet — no emoji, no
  per-widget stylesheets, no hard-coded `$`.
- New shell: sidebar with active state, cross-fade view transitions,
  slide-in detail panel, toast notifications, keyboard shortcuts
  (Ctrl+1…8 views, Ctrl+N add, Ctrl+R refresh, Esc close panel).
- Every screen rebuilt: Wishlist (search, filters, sort, grouped grid built
  lazily — no more 2 400 pre-built cards), Dashboard and Recap with
  QPainter charts (matplotlib removed), Deals hero with countdown, History
  with delete + confirmation, Library with clear error states, Settings
  (account, sync with progress, Drive, preferences, keys, about), Game
  detail panel (region comparison in one request, recommendation,
  editable priority/notes/rating), Add game and Mark purchased dialogs.
- Recommendations, dates and money are localised; 26 locales updated.

### Tooling
- `tests/` pytest suite; `tools/shot.py` headless screenshots;
  `tools/merge_locales.py`; trimmed requirements (pandas, matplotlib,
  beautifulsoup4, python-jose, google-auth-oauthlib dropped) and
  `packaging/build.spec`.
