STATUS_WISHLIST  = "Wishlist"
STATUS_PURCHASED = "Purchased"
STATUS_ARCHIVED  = "Archivado"

ALL_STATUSES = {STATUS_WISHLIST, STATUS_PURCHASED, STATUS_ARCHIVED}

# Statuses that should still appear in the main Wishlist grid.
WISHLIST_VISIBLE_STATUSES = {STATUS_WISHLIST, STATUS_ARCHIVED}


def normalize_status(raw: str) -> str:
    """
    Map any legacy or translated status string to one of the canonical
    constants above. This exists because earlier versions of the app
    stored i18n.t("mark_purchased.purchased_badge") directly as the status,
    which meant the literal text varied by locale (e.g. "Comprado",
    "Purchased", "Acheté", "Gekauft", ...).

    Any value not recognized as a translated "purchased" or "archived"
    label is treated as STATUS_WISHLIST — so an unrecognized status can
    never silently vanish from the wishlist grid again, even if it doesn't
    match any of these branches exactly.
    """
    if not raw:
        return STATUS_WISHLIST

    if raw in ALL_STATUSES:
        return raw

    folded = raw.strip().casefold()

    # Every known translation of "purchased_badge" across locales/*.json,
    # plus the English/Spanish canonical forms, so games saved under an
    # older locale still resolve to STATUS_PURCHASED correctly.
    _purchased_variants = {
        "comprado", "purchased", "koupeno", "købt", "gekauft", "ostettu",
        "acheté", "achete", "खरीदा गया", "megvásárolt", "megvasarolt",
        "dibeli", "acquistato", "購入済", "구매됨", "gekocht", "kjøpt", "kjopt",
        "kupiono", "cumpărat", "cumparat", "куплено", "köpt", "kopt",
        "ซื้อแล้ว", "satın alındı", "satin alindi", "đã mua", "da mua",
        "已购买", "已購買",
    }
    if folded in _purchased_variants:
        return STATUS_PURCHASED

    _archived_variants = {"archivado", "archived"}
    if folded in _archived_variants:
        return STATUS_ARCHIVED

    # Unknown status (e.g. corrupted data, a future locale not yet listed
    # above) — default to Wishlist rather than silently excluding the game
    # from every view. Worst case it shows up where it shouldn't; it never
    # just disappears.
    return STATUS_WISHLIST