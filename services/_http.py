"""
One HTTP session for the whole app.

- certifi CA bundle (fixes SSL on packaged macOS builds — applied to every
  service, not just the three that had it)
- one User-Agent / Accept-Language
- a default timeout so no call can hang the app forever
"""
import logging

import certifi
import requests

log = logging.getLogger("curator.http")

DEFAULT_TIMEOUT = 12
USER_AGENT = "SteamCurator/2.0 (+https://pimpmysteam.com)"


class _Session(requests.Session):
    def request(self, method, url, **kw):
        kw.setdefault("timeout", DEFAULT_TIMEOUT)
        return super().request(method, url, **kw)


def new_session(**headers) -> requests.Session:
    s = _Session()
    s.verify = certifi.where()
    s.headers.update({"User-Agent": USER_AGENT,
                      "Accept-Language": "en-US,en;q=0.9", **headers})
    return s


SESSION = new_session()


class ApiError(Exception):
    """A backend answered, but with an error status."""
    def __init__(self, status: int, message: str = ""):
        super().__init__(message or f"HTTP {status}")
        self.status = status


class Unreachable(Exception):
    """No answer at all (DNS, timeout, TLS, connection refused)."""
