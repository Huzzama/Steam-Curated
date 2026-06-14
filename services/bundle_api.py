"""
Bundle / Package lookup via Steam Store API.

Architecture — clearly separated concerns:

  Packages (sub IDs from appdetails):
    get_package_details()           → single package by ID
    get_packages_for_app()          → all packages for a game

  Editions (for "bought individually" tab):
    get_editions_for_app()          → deduplicated, ghost-free edition list

  Store Bundles (for "bought in a bundle" tab):
    scrape_bundle_ids_from_app_page() → Source 3: HTML scrape of /app/<id>/
    search_store_bundles_for_app()    → Source 2: search category1=996
    resolve_bundle_details()          → calls ajaxresolvebundles for one bundle
    get_bundles_enriched()            → full pipeline (Sources 1+2+3), UI-ready

  Enrichment:
    enrich_bundle_with_wishlist()   → adds wishlist_matches + already_purchased

Type field in every returned dict:
  "type": "package" | "bundle"
  Packages carry "package_id"
  Bundles  carry "bundle_id"

Why three sources are needed:
  • Source 1 (appdetails.packages) catches old-style multi-app packages,
    but NOT modern Store bundles which have their own bundleid namespace.
  • Source 2 (search category1=996) catches bundles that Steam indexes for
    a game name, but the index is incomplete and varies by region/language.
  • Source 3 (HTML scrape of the app page) is the most reliable: Steam
    itself links every bundle that contains a game directly from that game's
    store page as /bundle/<id>/ hrefs.  Parsing those links and resolving
    each one via ajaxresolvebundles gives us the ground truth.
"""
import html as _html
import re
import time
from typing import Optional

import requests
import certifi

_SESSION = requests.Session()
_SESSION.headers.update({"Accept-Language": "en-US,en;q=0.9"})
_SESSION.verify = certifi.where()

_cache: dict[str, Optional[dict]] = {}

_last_fetch: float = 0.0
_FETCH_DELAY = 0.4   # seconds between Steam API requests


def _throttle():
    global _last_fetch
    elapsed = time.time() - _last_fetch
    if elapsed < _FETCH_DELAY:
        time.sleep(_FETCH_DELAY - elapsed)
    _last_fetch = time.time()


# ── Packages ──────────────────────────────────────────────────────────────────

def get_package_details(pkg_id: str, country: str = "mx") -> Optional[dict]:
    """
    Fetch a single Steam package (sub) by ID.

    Returns:
        {type, package_id, name, apps, app_count, price, currency, discount}
    """
    cache_key = f"pkg:{pkg_id}:{country}"
    if cache_key in _cache:
        return _cache[cache_key]

    _throttle()
    try:
        r = _SESSION.get(
            "https://store.steampowered.com/api/packagedetails",
            params={"packageids": pkg_id, "cc": country, "l": "english"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get(str(pkg_id), {})
        if not data.get("success") or not data.get("data"):
            _cache[cache_key] = None
            return None

        d     = data["data"]
        apps  = [{"id": str(a["id"]), "name": a.get("name", f"App {a['id']}")}
                 for a in d.get("apps", [])]
        price = d.get("price", {})

        result = {
            "type":              "package",
            "package_id":        pkg_id,
            "bundle_id":         None,
            "name":              d.get("name", f"Package {pkg_id}"),
            "apps":              apps,
            "app_count":         len(apps),
            "price":             price.get("final", 0) / 100 if price else 0,
            "currency":          price.get("currency", "USD") if price else "USD",
            "discount":          price.get("discount_percent", 0) if price else 0,
            "price_unavailable": False,
        }
        _cache[cache_key] = result
        return result

    except Exception as e:
        print(f"[BundleAPI] package {pkg_id} error: {e}")
        _cache[cache_key] = None
        return None


def get_packages_for_app(app_id: str, country: str = "mx") -> list[dict]:
    """Return all raw packages (subs) listed in appdetails for this game."""
    from services.steam_api import get_app_details
    data = get_app_details(str(app_id), country=country)
    if not data:
        return []
    results = []
    for pkg_id in [str(p) for p in data.get("packages", [])]:
        pkg = get_package_details(pkg_id, country=country)
        if pkg:
            results.append(pkg)
    return results


# ── Editions (for "I bought this individually" tab) ───────────────────────────

def get_editions_for_app(app_id: str, country: str = "mx") -> list[dict]:
    """
    Return clean, deduplicated editions for the "bought individually" tab.

    Sources:
      1. appdetails → price_overview       → Standard Edition
      2. appdetails → package_groups.subs  → Gold / Deluxe / Complete / etc.

    Each edition dict: {name, current, base, discount, currency}

    Filters applied (ghost-row protection):
      • Empty name → skip
      • Single character → skip
      • Digits/symbols only → skip
      • Currency code only → skip
      • Normalised-key duplicate → skip
    """
    from services.steam_api import get_app_details
    data = get_app_details(str(app_id), country=country)
    if not data:
        return []

    editions  = []
    seen_keys = set()
    currency  = (data.get("price_overview") or {}).get("currency", "USD")

    # Source 1 — price_overview
    po = data.get("price_overview") or {}
    if po:
        editions.append({
            "name":     "Standard Edition",
            "current":  po.get("final", 0) / 100,
            "base":     po.get("initial", 0) / 100,
            "discount": po.get("discount_percent", 0),
            "currency": po.get("currency", "USD"),
        })
        seen_keys.add(_normalize_name("Standard Edition"))

    # Source 2 — package_groups.subs
    for pkg_group in data.get("package_groups", []):
        for sub in pkg_group.get("subs", []):
            raw_text = sub.get("option_text", "").strip()
            print(f"[Editions] raw option_text: {raw_text!r}")

            if not raw_text or raw_text.lower() in ("standard", "base game"):
                print(f"[Editions] skipped ghost row (trivial text): {raw_text!r}")
                continue

            try:
                cur = int(sub.get("price_in_cents_with_discount", 0)) / 100
            except (ValueError, TypeError):
                print(f"[Editions] skipped (bad price): {raw_text!r}")
                continue

            try:
                disc_raw = (sub.get("percent_savings_text", "") or "").strip()
                disc_raw = disc_raw.replace("-", "").replace("%", "").strip()
                disc = int(disc_raw) if disc_raw else 0
            except ValueError:
                disc = 0

            base_p = round(cur / (1 - disc / 100), 2) if disc > 0 else cur
            name   = _clean_edition_name(raw_text, data.get("name", ""))
            print(f"[Editions] cleaned name: {name!r}")

            if not _is_valid_edition_name(name):
                print(f"[Editions] skipped ghost row (invalid name): {name!r}")
                continue

            key = _normalize_name(name)
            if not key or key in seen_keys:
                print(f"[Editions] skipped duplicate: {name!r} (key={key!r})")
                continue
            seen_keys.add(key)

            editions.append({
                "name":     name,
                "current":  cur,
                "base":     base_p,
                "discount": disc,
                "currency": currency,
            })

    if not editions:
        return [{
            "name":     "Standard Edition",
            "current":  0.0,
            "base":     0.0,
            "discount": 0,
            "currency": "USD",
        }]

    return editions


def _clean_edition_name(option_text: str, game_name: str) -> str:
    """
    Strip price tokens and leading game-name prefix from option_text.

    Examples:
      "Metro Exodus - Mex$ 517.00 Mex$ 77.55"                        → ""
      "Metro Exodus - Gold Edition - Mex$ 689.00 …"                  → "Gold Edition"
      "Metro Exodus Gold Edition"                                      → "Gold Edition"
      "Complete Pack - $14.99"                                         → "Complete Pack"
      "Game - <span class=...>Mex$ 178.99</span> Mex$ 35.79"        → "" (base game)

    Steam sometimes embeds HTML tags inside option_text (e.g. a <span> wrapping
    the original price for on-sale items). The price regex strips the price
    content inside the tag but leaves the tag shell, producing ghost strings like
    '<span class="discount_original_price"></span>'.
    Fix: unescape HTML entities then strip all tags BEFORE applying price regex.
    """
    # ── Step 0: sanitise HTML ────────────────────────────────────────────────
    # Unescape entities (&amp; → &, &quot; → ", etc.) then remove all tags.
    name = _html.unescape(option_text).strip()
    name = re.sub(r"<[^>]+>", "", name).strip()

    price_re = re.compile(
        r"(?<!\w)"
        r"(?:"
        r"[A-Z]{1,4}\$\s*[\d]+(?:[.,]\d+)?"
        r"|[£€¥₽₩₪฿]\s*[\d]+(?:[.,]\d+)?"
        r"|\$\s*[\d]+(?:[.,]\d+)?"
        r"|[\d]+[.,]\d{2}\s+(?:USD|MXN|EUR|GBP|BRL|ARS|JPY|CAD|AUD|CLP|COP)"
        r"|(?:USD|MXN|EUR|GBP|BRL|ARS|JPY|CAD|AUD|CLP|COP)\s*[\d]+(?:[.,]\d+)?"
        r")"
        r"(?!\w)",
        re.IGNORECASE,
    )
    prev = None
    while prev != name:
        prev = name
        name = price_re.sub("", name)

    if game_name:
        name = re.sub(
            r"^" + re.escape(game_name) + r"\s*[-–—:]\s*",
            "", name, flags=re.IGNORECASE,
        )
        name = re.sub(
            r"^" + re.escape(game_name) + r"\s+",
            "", name, flags=re.IGNORECASE,
        )

    name = re.sub(r"\s*[-–—]\s*", " ", name)
    name = re.sub(
        r"\b(USD|MXN|EUR|GBP|BRL|ARS|JPY|CAD|AUD|CLP|COP)\b",
        "", name, flags=re.IGNORECASE,
    )
    return re.sub(r"\s{2,}", " ", name).strip(" -–—:·")


def _is_valid_edition_name(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    if re.fullmatch(r"[\W\d]+", name):
        return False
    if re.fullmatch(r"(USD|MXN|EUR|GBP|BRL|ARS|JPY|CAD|AUD|CLP|COP)", name, re.IGNORECASE):
        return False
    return True


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())


# ── Store Bundles — Source 3: HTML scrape ────────────────────────────────────

def scrape_bundle_ids_from_app_page(app_id: str, country: str = "mx") -> set[str]:
    """
    Extract real Steam Store bundle IDs from the public app page HTML.

    This is the most reliable source because Steam links every bundle that
    contains a game directly from that game's store page as /bundle/<id>/ hrefs.
    Neither appdetails.packages nor the search endpoint is guaranteed to list
    all of these — but the HTML page always does.

    Why the other two sources are insufficient:
      • appdetails.packages returns SUB/PACKAGE IDs, not BUNDLE IDs.
        A bundle like "Metro Saga Bundle" (bundleid=7533) will NOT appear there.
      • search/results?category1=996 returns bundles that Steam has indexed for
        the search term, but indexing is incomplete and region-sensitive.
        "Metro Saga Bundle" often does NOT appear when searching "Metro Exodus"
        because the bundle name doesn't contain those exact words.

    What this function does:
      • GET https://store.steampowered.com/app/<appid>/
      • Scan the HTML for any href/url containing /bundle/<digits>/
      • Return the set of unique bundle IDs found.

    Returns:
        set[str]: unique bundle IDs found in the app page HTML.
    """
    bundle_ids: set[str] = set()

    try:
        _throttle()
        r = _SESSION.get(
            f"https://store.steampowered.com/app/{app_id}/",
            params={"cc": country, "l": "english"},
            timeout=12,
        )
        r.raise_for_status()
        html = r.text or ""

        # Match /bundle/<id>/ anywhere in the page HTML.
        # This covers both relative hrefs (/bundle/7533/) and absolute URLs
        # (https://store.steampowered.com/bundle/7533/...).
        # Some IDs scraped here will be retired/removed bundles that return 400
        # from ajaxresolvebundles — those are silently discarded by resolve_bundle_details().
        for match in re.finditer(r"/bundle/(\d+)(?:/|\b)", html):
            bundle_ids.add(match.group(1))

        print(f"[Bundles] scraped from app page (app_id={app_id}): {bundle_ids}")

    except Exception as e:
        print(f"[Bundles] app page scrape failed for app_id={app_id}: {e}")

    return bundle_ids


# ── Store Bundles — Source 2: Search API ─────────────────────────────────────

def search_store_bundles_for_app(
    app_id: str,
    game_name: str,
    country: str = "mx",
    exclude_bundle_ids: set | None = None,
) -> list[dict]:
    """
    Search Steam Store for bundles containing this app (category1=996).

    Three search passes:
      Pass 1: full game name  → "Metro Exodus"
      Pass 2: first word      → "Metro"   (catches franchise bundles)
      Pass 3: first 3 words   → middle ground

    For each result: reads item["id"] (direct bundle id from Steam JSON),
    falls back to parsing the CDN logo URL as /bundles/<id>/ (plural).
    Verifies inclusion via resolve_bundle_details().
    """
    if not game_name:
        return []

    exclude_bundle_ids = exclude_bundle_ids or set()
    words     = game_name.split()
    terms_raw = [game_name, words[0], " ".join(words[:3])]

    seen_terms: set[str] = set()
    search_terms = []
    for t in terms_raw:
        tl = t.lower().strip()
        if tl not in seen_terms:
            seen_terms.add(tl)
            search_terms.append(t)

    seen_bundle_ids: set[str] = set(exclude_bundle_ids)
    results: list[dict] = []

    for term in search_terms:
        print(f"[Bundles] search term: {term!r}")
        try:
            _throttle()
            r = _SESSION.get(
                "https://store.steampowered.com/search/results",
                params={
                    "term":      term,
                    "category1": "996",
                    "cc":        country,
                    "json":      "1",
                    "count":     "15",
                },
                timeout=12,
            )
            r.raise_for_status()
            items = r.json().get("items", [])
        except Exception as e:
            print(f"[Bundles] search error for {term!r}: {e}")
            continue

        for item in items:
            print(f"[Bundles] search item: {item.get('name')!r}  id={item.get('id')!r}")

            bundle_id = str(item.get("id", "")).strip()
            if not bundle_id:
                logo = item.get("logo", "") or item.get("streamingURL", "")
                m = re.search(r"/bundles/(\d+)/", logo)
                if m:
                    bundle_id = m.group(1)

            if not bundle_id or bundle_id in seen_bundle_ids:
                continue
            seen_bundle_ids.add(bundle_id)

            bundle = resolve_bundle_details(bundle_id, app_id, country)
            if bundle:
                print(f"[Bundles] accepted: {bundle['name']!r}  ({bundle['app_count']} apps)")
                results.append(bundle)
            else:
                print(f"[Bundles] rejected (app not in bundle or resolve failed): bundle_id={bundle_id}")

    return results


# ── Store Bundles — Resolver ──────────────────────────────────────────────────

def resolve_bundle_details(
    bundle_id: str,
    target_app_id: str,
    country: str = "mx",
) -> Optional[dict]:
    """
    Resolve a Steam bundle — tries two sources in order:

    1. /actions/ajaxresolvebundles  (fast JSON, no price)
       Works for most current Store bundles.

    2. /bundle/<bundle_id>/ HTML page  (fallback)
       Used when ajaxresolvebundles returns 400, empty, or doesn't include
       the bundle.  Some bundles (e.g. older Enter the Gungeon bundles) exist
       as real store pages but are not indexed by ajaxresolvebundles.

    Both paths produce the same dict shape.  The HTML source additionally
    tries to extract a price, so it may return price_unavailable=False when
    ajaxresolvebundles would not.

    Caches the result after whichever source succeeds (or None if both fail).
    """
    cache_key = f"bundle:{bundle_id}"
    if cache_key in _cache:
        cached = _cache[cache_key]
        if cached is not None:
            if str(target_app_id) not in {a["id"] for a in cached.get("apps", [])}:
                return None
        return cached

    # ── Source A: ajaxresolvebundles ──────────────────────────────────────────
    ajax_failed = False
    _throttle()
    try:
        r = _SESSION.get(
            "https://store.steampowered.com/actions/ajaxresolvebundles",
            params={"bundleids": bundle_id},
            timeout=10,
        )
        r.raise_for_status()
        bundle_list = r.json()

        if bundle_list and isinstance(bundle_list, list):
            d = next(
                (b for b in bundle_list if str(b.get("bundleid", "")) == str(bundle_id)),
                None,
            )
            if d:
                app_ids_raw = d.get("appids", []) or d.get("apps", [])
                apps = []
                for entry in app_ids_raw:
                    if isinstance(entry, dict):
                        apps.append({
                            "id":   str(entry.get("appid", entry.get("id", ""))),
                            "name": entry.get("name", f"App {entry.get('appid', '')}"),
                        })
                    else:
                        apps.append({"id": str(entry), "name": f"App {entry}"})

                if len(apps) > 1 and str(target_app_id) in {a["id"] for a in apps}:
                    result = {
                        "type":              "bundle",
                        "bundle_id":         bundle_id,
                        "package_id":        None,
                        "name":              d.get("name", f"Bundle {bundle_id}"),
                        "apps":              apps,
                        "app_count":         len(apps),
                        "price":             None,
                        "currency":          "USD",
                        "discount":          0,
                        "price_unavailable": True,
                        "source":            "ajaxresolvebundles",
                    }
                    _cache[cache_key] = result
                    return result

        # ajaxresolvebundles returned something but didn't contain this bundle
        ajax_failed = True

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        print(f"[Bundles] ajaxresolvebundles {status} for bundle_id={bundle_id} — trying HTML fallback")
        ajax_failed = True
    except Exception as e:
        print(f"[BundleAPI] ajaxresolvebundles error for bundle_id={bundle_id}: {e} — trying HTML fallback")
        ajax_failed = True

    # ── Source B: HTML bundle page fallback ───────────────────────────────────
    result = resolve_bundle_details_from_html(bundle_id, target_app_id, country)
    _cache[cache_key] = result  # cache result OR None
    return result


def resolve_bundle_details_from_html(
    bundle_id: str,
    target_app_id: str,
    country: str = "mx",
) -> Optional[dict]:
    """
    Resolve a Steam bundle by scraping its store page HTML.

    Used as a fallback when /actions/ajaxresolvebundles does not return the
    bundle (400, empty list, or target app not included).  Some bundles — such
    as older Enter the Gungeon bundles — exist as real /bundle/<id>/ pages but
    are not indexed by ajaxresolvebundles.

    Extraction:
      Name  — og:title → <title> → .pageheader → h2
      Apps  — data-ds-appid / data-ds-appids → "appid": N (JSON) → /app/<N>/ links
      Price — .discount_final_price → .game_purchase_price →
              bundle_final_package_price → visible currency text

    Returns the same dict shape as resolve_bundle_details(), with
    "source": "bundle_html" and price_unavailable=True when no price found.

    Returns None if:
      • HTTP request fails
      • target_app_id is not found in the bundle's app list
      • fewer than 2 apps found (not a real multi-game bundle)
    """
    url = f"https://store.steampowered.com/bundle/{bundle_id}/"
    print(f"[BundlesHTML] fetching bundle page: {url}")

    try:
        _throttle()
        r = _SESSION.get(
            url,
            params={"cc": country, "l": "english"},
            timeout=12,
        )
        r.raise_for_status()
        html_text = r.text or ""
    except Exception as e:
        print(f"[BundlesHTML] fetch failed for bundle_id={bundle_id}: {e}")
        return None

    # ── Extract name ──────────────────────────────────────────────────────────
    bundle_name = _extract_bundle_name_from_html(html_text, bundle_id)
    print(f"[BundlesHTML] extracted name: {bundle_name!r}")

    # ── Extract app IDs ───────────────────────────────────────────────────────
    raw_app_ids = _extract_appids_from_bundle_html(html_text)
    print(f"[BundlesHTML] extracted appids: {sorted(raw_app_ids)}")

    if not raw_app_ids or str(target_app_id) not in raw_app_ids:
        print(f"[BundlesHTML] rejected bundle_id={bundle_id}: "
              f"target_app_id={target_app_id} not in appids={sorted(raw_app_ids)}")
        return None

    if len(raw_app_ids) < 2:
        print(f"[BundlesHTML] rejected bundle_id={bundle_id}: only {len(raw_app_ids)} app(s) found")
        return None

    apps = [{"id": aid, "name": f"App {aid}"} for aid in sorted(raw_app_ids)]

    # ── Extract price ─────────────────────────────────────────────────────────
    price, base_price, currency, discount = _extract_price_from_bundle_html(html_text)

    result = {
        "type":              "bundle",
        "bundle_id":         bundle_id,
        "package_id":        None,
        "name":              bundle_name,
        "apps":              apps,
        "app_count":         len(apps),
        "price":             price,
        "base_price":        base_price,   # original pre-discount price or None
        "currency":          currency,
        "discount":          discount,
        "price_unavailable": price is None,
        "source":            "bundle_html",
    }
    print(f"[BundlesHTML] accepted: {bundle_name!r}  "
          f"app_count={len(apps)}  price={price}  base_price={base_price}  {currency}")
    return result


def _extract_bundle_name_from_html(html_text: str, bundle_id: str) -> str:
    """
    Try multiple extraction strategies, return the first non-trivial hit.
    Priority: og:title > <title> > .pageheader > <h2>
    """
    # 1. og:title  (most reliable — Steam always sets this correctly)
    for pattern in [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\']\s[^>]*property=["\']og:title["\']',
    ]:
        m = re.search(pattern, html_text, re.IGNORECASE | re.DOTALL)
        if m:
            name = _html.unescape(m.group(1)).strip()
            if name and "steam" not in name.lower():
                return name

    # 2. <title>Bundle Name on Steam</title>
    m = re.search(r'<title>([^<]+?)\s*(?:on Steam|[–-] Steam)?\s*</title>', html_text, re.IGNORECASE)
    if m:
        name = _html.unescape(m.group(1)).strip()
        name = re.sub(
            r'\s*(on Steam|[–-] Steam|on the Steam Store)\s*$',
            "", name, flags=re.IGNORECASE,
        ).strip()
        if name:
            return name

    # 3. class="pageheader" (Steam store page title div)
    m = re.search(r'class=["\']pageheader["\'][^>]*>([^<]+)<', html_text, re.IGNORECASE)
    if m:
        name = _html.unescape(m.group(1)).strip()
        if name:
            return name

    # 4. First <h2> that looks like a bundle name
    m = re.search(r'<h2[^>]*>([^<]{5,80})</h2>', html_text, re.IGNORECASE)
    if m:
        name = _html.unescape(m.group(1)).strip()
        if name:
            return name

    return f"Bundle {bundle_id}"


def _extract_appids_from_bundle_html(html_text: str) -> set[str]:
    """
    Extract Steam app IDs from a bundle page HTML.

    Priority order:
    1. data-ds-appid="N"          — on bundle item cards (most reliable)
    2. data-ds-appids="[N,N,...]" — on bundle item cards (array form)
    3. "appid": N                 — in JSON blobs embedded in the page
    4. /app/N/ href links         — fallback only if 1-3 found nothing
       (avoided by default to prevent picking up Steam nav/footer app links)
    """
    ids: set[str] = set()

    # 1+2: data attributes on bundle item card elements
    for m in re.finditer(r'data-ds-appid=["\'](\d+)["\']', html_text):
        ids.add(m.group(1))
    for m in re.finditer(r'data-ds-appids=(?:"([^"]*)"|\'([^\']*)\')', html_text):
        val = m.group(1) if m.group(1) is not None else (m.group(2) or '')
        for n in re.findall(r'\d+', val):
            ids.add(n)

    # 3: "appid": N  in embedded JS/JSON objects
    for m in re.finditer(r'"appid"\s*:\s*(\d+)', html_text):
        ids.add(m.group(1))

    # 4: /app/N/ links — only if nothing found above (avoids nav noise)
    if not ids:
        for m in re.finditer(r'/app/(\d+)/', html_text):
            ids.add(m.group(1))

    return ids


def _extract_price_from_bundle_html(html_text: str) -> tuple:
    """
    Extract price information from a Steam bundle page.

    Returns:
        (final_price, base_price, currency, discount)

        final_price — what the user pays now (float or None)
        base_price  — original price before discount (float or None)
                      Extracted from .discount_original_price when available.
                      The caller should calculate it from final + discount when None.
        currency    — currency code string, e.g. "MXN", "USD"
        discount    — integer percentage 0-99

    Steam's discount HTML structure:
        <div class="discount_block">
          <div class="discount_pct">-87%</div>
          <div class="discount_prices">
            <div class="discount_original_price">Mex$ 996.38</div>  ← strikethrough
            <div class="discount_final_price">Mex$ 129.53</div>      ← what user pays
          </div>
        </div>

    When a bundle is not on sale, only game_purchase_price is present.
    """
    final_price: float | None = None
    base_price:  float | None = None
    currency = "USD"
    discount = 0

    # ── On-sale path: discount block with original + final prices ─────────────
    final_m = re.search(
        r'class=["\'\']discount_final_price["\'\'][^>]*>\s*([^<]+?)\s*<',
        html_text, re.IGNORECASE,
    )
    orig_m = re.search(
        r'class=["\'\']discount_original_price["\'\'][^>]*>\s*([^<]+?)\s*<',
        html_text, re.IGNORECASE,
    )
    disc_m = re.search(
        r'class=["\'\']discount_pct["\'\'][^>]*>\s*-?(\d+)%',
        html_text, re.IGNORECASE,
    )

    if final_m:
        final_price, currency = _parse_price_text(final_m.group(1))

    if orig_m:
        base_price, _ = _parse_price_text(orig_m.group(1))

    if disc_m:
        try:
            discount = int(disc_m.group(1))
        except ValueError:
            pass

    if final_price is not None:
        return final_price, base_price, currency, discount

    # ── Regular (non-discounted) price ────────────────────────────────────────
    for pattern in [
        r'class=["\'\']game_purchase_price\s*price["\'\'][^>]*>\s*([^<]+?)\s*<',
        r'class=["\'\']game_purchase_price["\'\'][^>]*>\s*([^<]+?)\s*<',
        r'bundle_final_package_price[^>]*>\s*([^<]+?)\s*<',
    ]:
        mo = re.search(pattern, html_text, re.IGNORECASE)
        if mo:
            p, c = _parse_price_text(mo.group(1))
            if p is not None:
                return p, None, c, 0

    return None, None, "USD", 0


def _parse_price_text(text: str) -> tuple:
    """
    Parse a price string like 'Mex$ 149.99', '$14.99', '€9.99', 'R$29,90', '149.99 MXN'
    into (float, currency_code) or (None, "USD") if unparseable.

    Handles both period-as-decimal ("14.99") and comma-as-decimal ("29,90" — BRL/EUR regions).
    """
    text = _html.unescape(text).strip()
    if not text or text.lower() in ("free", "free to play", "play for free!"):
        return 0.0, "USD"

    def _normalise(s: str) -> str:
        # "29,90" or "1.299,90" → comma is decimal separator
        if re.search(r",\d{2}$", s):
            return s.replace(".", "").replace(",", ".")
        # "1,299.90" → comma is thousands separator
        return s.replace(",", "")

    CURRENCY_MAP = [
        ("CDN$", "CAD"), ("Mex$", "MXN"), ("HK$",  "HKD"), ("NZ$",  "NZD"),
        ("A$",   "AUD"), ("S$",   "SGD"), ("R$",   "BRL"),
        ("₩",    "KRW"), ("₽",   "RUB"),  ("₪",   "ILS"),  ("฿",   "THB"),
        ("€",    "EUR"), ("£",   "GBP"),  ("¥",   "JPY"),  ("$",   "USD"),
    ]
    for symbol, code in CURRENCY_MAP:
        m = re.search(re.escape(symbol) + r"\s*([\d,.]+)", text, re.IGNORECASE)
        if m:
            try:
                return float(_normalise(m.group(1))), code
            except ValueError:
                pass

    # "149.99 MXN" style
    m = re.search(
        r"([\d,.]+)\s+(USD|MXN|EUR|GBP|BRL|ARS|JPY|CAD|AUD|CLP|COP|KRW|RUB|ILS|THB|HKD|NZD|SGD)",
        text, re.IGNORECASE,
    )
    if m:
        try:
            return float(_normalise(m.group(1))), m.group(2).upper()
        except ValueError:
            pass

    return None, "USD"


# ── Enrichment ────────────────────────────────────────────────────────────────

def enrich_bundle_with_wishlist(bundle: dict) -> dict:
    """Add wishlist_matches and already_purchased lists to a bundle dict."""
    import data.repository as repo
    import data.purchase_repository as purchases

    wishlist_ids  = {g.app_id for g in repo.get_all() if g.status == "Wishlist"}
    purchased_ids = {p.app_id for p in purchases.get_all()}

    wishlist_matches  = []
    already_purchased = []

    for app in bundle.get("apps", []):
        aid = str(app["id"])
        if aid in wishlist_ids:
            wishlist_matches.append(app)
        elif aid in purchased_ids:
            already_purchased.append(app)

    return {
        **bundle,
        "wishlist_matches":  wishlist_matches,
        "already_purchased": already_purchased,
    }


# ── Full pipeline ─────────────────────────────────────────────────────────────

def get_bundles_enriched(app_id: str, country: str = "mx") -> list[dict]:
    """
    Full pipeline — returns bundles for the "bought in a bundle" tab.

    Three sources (processed in order, each deduplicates against prior results):

    Source 1 — appdetails.packages with app_count > 1
        Old-style multi-app packages. These carry real price data.
        type="package", package_id set, bundle_id=None.

    Source 2 — Steam store search (category1=996)
        Modern Store bundles found via keyword search.
        type="bundle", bundle_id set, price=None (no price from ajaxresolvebundles).
        Three search passes: full name, first word (franchise), first 3 words.

    Source 3 — HTML scrape of /app/<appid>/
        The most reliable source. Steam's own app page links every bundle that
        contains the game. Parsing those /bundle/<id>/ hrefs and resolving each
        one via ajaxresolvebundles gives us ground truth that Sources 1 and 2
        often miss (e.g. "Metro Saga Bundle" for Metro Exodus).

    Final deduplication:
        keyed on bundle_id for real bundles, package_id for packages.
        Bundles sort before packages; within type, sorted by app_count desc.
    """
    from services.steam_api import get_app_details

    data = get_app_details(str(app_id), country=country)
    if not data:
        return []

    game_name = data.get("name", "")
    bundles: list[dict] = []

    # ── Source 1: multi-app packages ─────────────────────────────────────────
    for pkg_id in [str(p) for p in data.get("packages", [])]:
        pkg = get_package_details(pkg_id, country=country)
        if not pkg or pkg.get("app_count", 0) <= 1:
            continue
        bundles.append({
            **pkg,
            "type":              "package",
            "bundle_id":         None,
            "price_unavailable": False,
        })

    # ── Source 2: Steam search ────────────────────────────────────────────────
    store_bundles = search_store_bundles_for_app(
        app_id=app_id,
        game_name=game_name,
        country=country,
    )
    bundles.extend(store_bundles)

    # ── Source 3: HTML scrape of the app page ─────────────────────────────────
    existing_bundle_ids = {
        str(b.get("bundle_id"))
        for b in bundles
        if b.get("bundle_id")
    }

    scraped_ids = scrape_bundle_ids_from_app_page(app_id, country)

    for bundle_id in scraped_ids:
        if bundle_id in existing_bundle_ids:
            continue
        bundle = resolve_bundle_details(
            bundle_id=bundle_id,
            target_app_id=app_id,
            country=country,
        )
        if bundle:
            print(f"[Bundles] accepted from app page scrape: {bundle['name']!r}")
            bundles.append(bundle)
            existing_bundle_ids.add(bundle_id)
        else:
            print(f"[Bundles] rejected scraped bundle_id={bundle_id}")

    # ── Enrich with wishlist / purchased data ─────────────────────────────────
    enriched = [enrich_bundle_with_wishlist(b) for b in bundles]

    # ── Final deduplication ───────────────────────────────────────────────────
    # Key: bundle:<bundle_id> | package:<package_id> | name:<normalised_name>
    # This catches duplicates that slipped through all three sources.
    seen_keys: set[str] = set()
    unique: list[dict] = []

    for b in enriched:
        if b.get("type") == "bundle" and b.get("bundle_id"):
            key = f"bundle:{b['bundle_id']}"
        elif b.get("type") == "package" and b.get("package_id"):
            key = f"package:{b['package_id']}"
        else:
            key = f"name:{_normalize_name(b.get('name', ''))}"

        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(b)

    # Sort: real bundles first, then packages; within each type by app_count desc
    unique.sort(
        key=lambda b: (
            0 if b.get("type") == "bundle" else 1,
            -b.get("app_count", 0),
            b.get("price") if b.get("price") is not None else 999_999,
        )
    )

    return unique