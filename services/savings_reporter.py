"""
services/savings_reporter.py — Steam Curator desktop → PimpMySteam backend.

Called by mark_purchased_dialog when a game is marked as Purchased at a discount.
Uses steamkustom_auth.report_pending_saving() which always injects the Authorization
header (the original bug: the old reporter did a bare requests.post with no headers).
"""

import threading


def report_saving(amount: float, currency: str = "USD") -> None:
    """
    Report a discount saving to the backend in a background thread.
    Fire-and-forget — never blocks the UI or raises to the caller.

    amount   — the dollar/currency amount saved (e.g. 9.99)
    currency — ISO 4217 code (e.g. "USD", "MXN", "EUR")
    """
    if amount <= 0:
        return

    def _send():
        try:
            from services.steamkustom_auth import report_pending_saving
            ok = report_pending_saving(amount=amount, currency=currency)
            if ok:
                print(f"[Savings] Reported {currency} {amount:.2f} saved")
            else:
                print(f"[Savings] Skipped — no token configured")
        except Exception as e:
            # Non-critical: never crash the app over a stats report
            print(f"[Savings] report failed: {e}")

    threading.Thread(target=_send, daemon=True).start()