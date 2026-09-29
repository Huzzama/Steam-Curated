# Changelog

## [2.0.0] — 2026-09-29

First packaged release of the rebuilt app (2.0, 2.1 and 2.2 below were never
published on their own — v1.0.10 was the last release).

- Installers for every platform: Windows setup, macOS dmg, AppImage, .deb and
  .rpm, built and self-tested on GitHub Actions from one `VERSION` file.
- The app checks GitHub once a day for a newer release and says so with a
  toast; Settings › About shows the version, "Check for updates" and a
  download button.
- `steam-curator --version` / `--self-test` (headless start-up check used by
  the release pipeline).
- Discord alerts are linked on pimpmysteam.com (Settings › Alerts); the app
  opens that page and picks the link up by itself. Messages arrive in any of
  the 26 app languages, as one list per DM (links, price, was, you save,
  total), plus an announcement with the banner when a Steam sale or fest
  starts (new "Steam events" toggle).
- Proper square icon and a real `.ico`.

### Steam-only price history, roomier detail panel (2.2)

- IsThereAnyDeal removed completely (key field, test button, API calls). Its
  prices came back in USD for regions it doesn't track, and a third-party key
  is no longer needed: the deal history is built from Steam itself.
- Automatic daily price check (`services/price_watch.py`): on start-up (when
  the last check is ~a day old) and then hourly re-evaluation, every wishlist
  price is fetched from Steam and each sale is recorded in the deal history.
  A toast announces games that just went on sale. Settings › Price tracking
  shows the last check, how many sales are recorded, and a "Check now" button.
- SteamDB is deliberately not scraped: its FAQ forbids scraping/crawling and
  bans automated clients (and it sits behind Cloudflare).
- Detail panel: never wider than its column any more — the content follows
  the panel width and every one-line text elides; price row split in two
  lines; genre/developer lists shortened ("FromSoftware +2", full list in the
  tooltip); long region names elide. Default width 400 px, resizable by
  dragging its left edge (340–640 px, remembered in `detail_panel_width`).
- Deal events imported by older versions are kept and still used.
- "At all-time low" only when the game is on sale right now at (or within
  5 % of) its lowest recorded price (`Game.is_at_low`). A game only ever seen
  at full price no longer counts as "at its low"; such full-price "lows" are
  dropped on start-up.
- Price by region: every foreign price shows its value converted to your
  currency and how much cheaper (green) or more expensive (red) it is than in
  your region. Rates: ExchangeRate-API open endpoint, cached 12 h in
  `fx_rates.json`, built-in rough table when offline (`services/fx.py`).
- The detail panel opens at its maximum width (640 px) by default.
- Library tab: reads owned games from pimpmysteam.com (`/steam/me/games`,
  Steam Web API with the server's key), falling back to the community XML,
  which now tolerates odd characters in game names ("not well-formed
  (invalid token)") and explains a private profile.
- Purchases are sent to pimpmysteam.com (`POST /purchases`) and verified
  **by the server** against the Steam library: the game plus every app of an
  edition (Steam package) or bundle. DLC can't be checked (Steam doesn't list
  it among owned games). The detail panel shows Verified / Partly verified /
  Not in library / Pending with "Verify again"; purchases recorded before are
  sent once at start-up without counting their saving twice. The saving now
  counts on the website only once the purchase is verified
  (`services/purchase_sync.py`; `services/savings_reporter.py` removed).
- Discord alerts: Settings › Discord alerts links your Discord account to
  pimpmysteam.com; the server checks your wishlist prices every 3 h (even with
  the app closed) and the PimpMySteam bot DMs you when a game goes on sale or
  hits its all-time low — or once a day as a digest. The app uploads only the
  wishlist's app ids, names, priorities and known lows, region and language,
  and only while linked (`services/discord_alerts.py`).

### Own deal predictor (2.1)

- "Buy now or wait?" is computed by Steam Curator's own algorithm
  (`services/deal_predictor.py`): past sale episodes → how often, how deep and
  in which seasonal sales the game gets discounted → probability and depth of
  the next sale → buy now / good deal / wait / fair price, with confidence.
- Deal history (`services/deal_history.py`, `deal_history.json`) stores only
  dates and discount %: every price the app sees (plus, in 2.1 only, an
  IsThereAnyDeal import — removed in 2.2). Every price shown — all-time low, estimated
  sale price, past deals — is computed from the base price in *your* currency.
  (ITAD answers in USD for regions it doesn't track, e.g. Mexico.)
- Detail panel: deal-history block with sales count, record, usual discount,
  average gap, a timeline of past sales with the predicted one, and the last
  deals priced in your currency.
- Old absolute ITAD lows are re-derived on startup.

### Redesign (2.0)

#### Connections
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

#### Interface
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

#### Tooling
- `tests/` pytest suite; `tools/shot.py` headless screenshots;
  `tools/merge_locales.py`; trimmed requirements (pandas, matplotlib,
  beautifulsoup4, python-jose, google-auth-oauthlib dropped) and
  `packaging/build.spec`.
