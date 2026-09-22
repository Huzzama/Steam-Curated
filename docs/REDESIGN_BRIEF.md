# Steam Curator — UI rebuild brief (read fully before touching a view)

Goal: every view/dialog is rebuilt on the new design system so the app feels
fluid and premium (Apple-like restraint) with PimpMySteam's personality:
near-black surfaces, one blue accent, mono numerals, uppercase eyebrows,
Lucide line icons, **zero emoji or unicode glyph icons anywhere**.

## Hard rules

1. **No emoji, no glyph icons** (`★ ✓ ✦ ▦ ◷ ⚙ → ↗ ⚠ …`). Icons come from
   `ui.icons` only (`icons.pixmap(name, color, size)` for a QLabel,
   `icons.icon(name, color, size)` for a button, `icons.sale_icon(event_key)`
   for sale events). Check `icons.has(name)` / `ui/icons.py` for the list.
2. **No hex colours, no inline QSS, no `setStyleSheet` in views** except the
   `label(color=…)` argument. Colours: `ui.theme.C[...]`, `PRIORITY[p]`,
   `PRIORITY_DIM[p]`. Spacing: `SP`. Radii: `R`. Never `config.COLORS`.
3. **No `QFont(...)` / `setFont` in views.** Text: `components.label(text, role, …)`
   with roles `title · h2 · body · dim · muted · eyebrow · mono · value`.
4. **No raw `QPushButton`.** Use `Button(text, variant, icon, on_click)` with
   variants `default · primary · success · danger · ghost · link`, or
   `IconButton(icon, tooltip)`, `Segmented`, `ChipGroup`.
5. **Never block the GUI thread.** Any network/disk-heavy call goes through
   `ui.async_bridge.run_async(self, work, on_done=…, on_progress=…)`.
   `on_done(result)` receives the return value **or an Exception** — always
   `if isinstance(result, Exception): …`. Never `QTimer.singleShot` or
   `threading.Thread` directly in a view. Never touch widgets from `work`.
6. **No `$` or currency hard-coded.** Use `ui.format.money(amount, currency)`,
   `pct`, `discount`, `day`, `compact`.
7. **Every user-visible string** goes through `i18n.t("section.key")`.
   Reuse existing keys from `locales/en.json` when one fits. **Do not edit
   `locales/*.json` directly** (other people are working in parallel): put
   new/changed keys in `locales/overlay/<your-area>.en.json` and
   `locales/overlay/<your-area>.es.json` (same nested shape, e.g.
   `{"wishlist": {"empty_title": "…"}}`). They are merged automatically at
   runtime and folded into the real files later.
   Same for icons: use what `ui/icons.py` has; if something is missing use the
   closest icon and list the missing Lucide names in your final report.
8. **`get_settings()`** is cheap (mtime cached) but still call it once per
   refresh, not per card.
9. Confirm before destructive actions (`delete`): use a `QMessageBox`
   styled by the theme (`QMessageBox.question(self, title, text)` is fine)
   — never delete on a single click.
10. Every list/grid must handle **0 items** with `EmptyState(icon, title,
    subtitle, action)` and **loading** with `Spinner`/`Skeleton` or
    `Button.set_loading(True)`.
11. Files are LF in the repo; keep them LF. Type hints + short docstrings.
    `python3 -m compileall -q <file>` must pass.

## Shell contract (`ui/app_window.py`)

```python
View(parent, **deps)          # deps are keyword callables the shell passes
view.refresh(force=False)     # (re)load data; force=True bypasses caches
view.retranslate()            # OPTIONAL: update visible strings in place
```
Deps the shell passes (accept the ones you need, `**_` for the rest):
`open_detail(game)`, `close_detail()`, `open_add_dialog()`,
`notify(message, tone)` (tone: info|success|warning|error → toast),
`on_data_changed()` (call after you add/update/delete games or purchases —
the shell refreshes the other views), `on_locale_change()` (Settings only).

Constructor signatures the shell uses today (keep them):
```python
WishlistView(parent, on_add_game=, on_game_click=)
LibraryView(parent)
DashboardView(parent)
DealsView(parent, on_game_click=)
NonSteamFestivalsView(parent)
HistoryView(parent, on_game_click=)
RecapView(parent)
SettingsView(parent, on_locale_change=, on_data_changed=)
GameDetailPanel(parent, on_close=, on_refresh=)    # on_refresh == on_data_changed
AddGameDialog(parent_window, on_success=)
MarkPurchasedDialog(parent_window, game, on_success=)   # check current file
```
The window is also reachable as `self.window()` (an `AppWindow`) with
`.notify(msg, tone)`, `.open_detail(game)`, `.on_data_changed()` — use it for
things the constructor does not pass.

## Page anatomy (all views)

```
QWidget
└─ vbox(margins=(SP.xl, SP.lg, SP.xl, SP.xl), spacing=SP.lg)
   ├─ SectionHeader(title, subtitle, actions=[Button…])     ← 56 px, fixed
   ├─ (optional) toolbar row: SearchField / Segmented / ChipGroup
   └─ scroll_area(content)   with FlowLayout for card grids
```
Cards: `Card(padding, clickable)` → `.body` layout. Stats: `StatCard(title,
value, icon, tone, caption)` + `set_value(v, fmt)`. Lists: `ListRow(title,
subtitle, leading, trailing)`. Priority: `PriorityBadge("S")`. Status/
discount: `Pill(text, tone)` tones `neutral · accent · green · gold · red ·
violet · cyan · orange`. Covers: `CoverImage(w, h)` + `ui.image_cache.get(path,
size)`. Section titles inside a page: `SubHeader(title, trailing)`.

Grid of game cards: **`ui.game_card.GameCard(game, on_click)`** (168 px,
portrait cover, priority badge, price/discount, "at low" tag) inside a
**`FlowLayout`** — never a fixed 6-column grid and never a pre-built pool of
thousands of cards. Build the cards of the
current filter only; reuse widgets by clearing the layout
(`animations.clear_layout`).

## Data & services (thread-safe unless noted)

- `data.repository`: `get_all() → list[Game]`, `get_by_app_id`, `get_by_id`,
  `add`, `add_many`, `update`, `update_many`, `delete(game_id)`, `get_on_sale`,
  `get_recent`, `get_by_priority`.
- `data.purchase_repository`: `get_all() → list[Purchase]`, `get_by_app_id`,
  `add`, `delete(app_id)`, `total_spent/base/saved()`.
- `data.models`: `Game` (priority S/A/B/C, status Wishlist/Comprado/
  Archivado, `price: PriceInfo`, `price_history: PriceHistory`, `cover_path`,
  `play_status`), `Purchase`, `PriceInfo(current, base, currency,
  discount_pct, is_on_sale)`, `PriceHistory(all_time_low, all_time_low_date,
  all_time_discount, …)`.
- `services.steam_api`: `refresh_price(app_id, country, force)`,
  `bulk_refresh_prices(...)` (read its signature), `search_games(query, limit,
  cc)`, `get_game_metadata(app_id, country)`, `get_app_details`.
- `services.price_history`: `get_price_history(app_id, country, force, currency)`
  (ITAD when configured, else observed local low; never returns worse data),
  `get_price_histories(games, country)` batched, `observe(app_id, price)`,
  `merge(old, new)`; `PriceHistory.source` is "itad" | "observed".
- `services.recommendation.get_recommendation(game) → dict` (read keys).
- `services.steam_wishlist.import_wishlist(steam_id64, api_key, country,
  on_progress(i, total, app_id), skip_existing) → {"added","skipped","errors","total"}`.
- `services.steamkustom_auth`: `is_connected()`, `get_username()`,
  `get_steam_id()`, `verify_token(token) → user dict (raises ApiError /
  Unreachable)`, `save_account(token, user)`, `clear_token()`,
  `get_wishlist()`, `get_player_summary()`, `get_steam_account()` (all via `/steam/me/*`).
- `services.library_api.get_library_stats()` → dict, **raises `LibraryError`**
  with a user-facing message (show it in an EmptyState, not a crash).
- `services.sale_images`: `get_sale_events()` (fallback `config.STEAM_SALE_EVENTS`),
  `get_local_path(server_img_key) → Path|None`, `is_ready()`.
- `ui.event_time`: `event_state(event, tz) → (state, dt)`, `visible_events`,
  `hero_event(events, tz)`.
- `services.steamgriddb.download_cover(app_id, api_key, name)`,
  `download_all_missing(...)`; `services.drive_sync`: `is_configured`,
  `is_authenticated`, `upload_all`, `download_all`, `get_sync_status`.
- `services.bundle_api.get_bundles_enriched(app_id, country)` (slow — async).
- `ui.settings_loader`: `get_settings()`, `get(key, default)`,
  `save_settings(partial_dict)`; keys `locale, country, timezone,
  steamgriddb_key, itad_key, compare_regions`.
- Errors: `services._http.ApiError(status, message)`, `Unreachable`.

## Known bugs to fix while rebuilding (from the audit)

- Callbacks from threads used `QTimer.singleShot` → never fired (sync,
  cover download, price refresh, detail refresh). Use `run_async`.
- `refresh(force=True)` raised TypeError in 5 views → accept `force`.
- SettingsView swallowed `on_data_changed` → call it after a wishlist sync.
- Deals view polled sale banners every second → render from cache, re-render
  when the shell calls `refresh(force=True)`; countdown timer is fine (1 s
  QTimer on the GUI thread is OK for a clock label only).
- Delete without confirmation.
- matplotlib charts drawn on the GUI thread on every refresh → draw with
  `QPainter` (simple bars/donut) instead; no matplotlib in the UI.
- Wishlist built 2,400 cards up-front → build only what's shown.
- Region price comparator in the detail panel: fetch all regions in one
  `run_async`, show `Skeleton` rows meanwhile.

## Screenshot check (do this before you finish)

```
QT_QPA_PLATFORM=offscreen python3 tools/shot.py <view_key> /tmp/shots/<view>.png
```
`tools/shot.py` builds the app with the theme, shows the view with sample data
and saves a PNG — open it with the Read tool and fix what looks wrong
(clipped text, misaligned rows, low-contrast text, missing icons).
