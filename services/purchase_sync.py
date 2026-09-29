"""
Send purchases to pimpmysteam.com, where the server checks them against the
linked Steam library (POST /purchases) — the app never decides "verified".

    send(purchase)    → Purchase with .verification / .verified_items filled
                        (blocking — call from run_async)
    sync_pending()    → {"sent", "failed", "skipped"}: every purchase never sent
    STATUS_TONE       verification → Pill tone for the UI

Verification (decided by the server): verified · partial · unverified · unknown
(unknown = library private / Steam down / nothing checkable; resend later).
A new purchase's saving is counted in the community total by the server once
it's verified. Purchases recorded by older versions already reported their
saving, so they are sent with credit_saving=false.
If the backend doesn't have /purchases yet (404), the saving falls back to the
old /stats/pending-savings report and the purchase stays unsent.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from data.models import Purchase

log = logging.getLogger("curator.purchase_sync")

STATUS_TONE = {"verified": "green", "partial": "gold", "unverified": "red", "unknown": "neutral"}
_DIGITS = re.compile(r"^\d{1,10}$")


def sendable(p: Purchase) -> bool:
    return bool(_DIGITS.match(str(p.app_id or "")))


def payload(p: Purchase) -> dict:
    items = [{"app_id": str(i.get("app_id")), "name": str(i.get("name") or "")[:200]}
             for i in (p.items or []) if _DIGITS.match(str(i.get("app_id") or ""))]
    items = [i for i in items if i["app_id"] != str(p.app_id)][:60]
    return {
        "app_id":        str(p.app_id),
        "name":          (p.name or "")[:200],
        "edition":       (p.edition or "Standard Edition")[:120],
        "kind":          p.kind if p.kind in ("game", "edition", "bundle") else "game",
        "items":         items,
        "price_paid":    round(float(p.price_paid or 0), 2),
        "base_price":    round(max(float(p.base_price or 0), float(p.price_paid or 0)), 2),
        "currency":      (p.currency or "USD").upper()[:3],
        "discount_pct":  max(0, min(100, int(p.discount_pct or 0))),
        "purchased_at":  p.purchased_at,
        "credit_saving": not p.saving_reported,
    }


def send(p: Purchase) -> Purchase:
    """POST one purchase; stores the server's verification locally. Raises
    services._http.ApiError / Unreachable (the caller decides what to show)."""
    from data import purchase_repository as repo
    from services._http import ApiError
    from services.steamkustom_auth import api, get_token, report_pending_saving
    if not get_token() or not sendable(p):
        return p
    try:
        res = api("/purchases", method="POST", json_body=payload(p), timeout=40)
    except ApiError as e:
        if e.status == 404 and not p.saving_reported:          # backend not updated yet
            if p.saved > 0:
                report_pending_saving(p.saved, p.currency)
            p.saving_reported = True
            repo.update(p)
        raise
    ver = res.get("verification") or {}
    p.verification = ver.get("status") or "unknown"
    p.verified_items = ver.get("items") or []
    p.saving_reported = True
    repo.update(p)
    return p


def sync_pending() -> dict:
    """Send every purchase that was never sent (e.g. recorded offline or by an
    older version). Stops at the first network error."""
    from data import purchase_repository as repo
    from services._http import ApiError, Unreachable
    from services.steamkustom_auth import get_token
    out = {"sent": 0, "failed": 0, "skipped": 0}
    if not get_token():
        return out
    for p in repo.get_all():
        if p.verification or not sendable(p):
            out["skipped"] += 1
            continue
        try:
            send(p)
            out["sent"] += 1
        except ApiError as e:
            out["failed"] += 1
            if e.status in (401, 404):                # bad token / old backend: stop
                break
        except Unreachable:
            out["failed"] += 1
            break
    return out


def summary(p: Optional[Purchase]) -> tuple[str, str]:
    """(i18n key suffix, pill tone) for a purchase's verification."""
    if p is None or not p.verification:
        return "not_sent", "neutral"
    return p.verification, STATUS_TONE.get(p.verification, "neutral")
