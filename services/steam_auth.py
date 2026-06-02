"""
Steam OpenID authentication for desktop apps.

Flow:
1. Open browser to Steam login page
2. Steam redirects to localhost callback with signed OpenID params
3. We verify the signature with Steam's servers
4. Extract SteamID64 from the verified response
"""
import re
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode
from typing import Callable, Optional

import requests

STEAM_OPENID_URL = "https://steamcommunity.com/openid/login"
CALLBACK_PORT    = 14579
CALLBACK_URL     = f"http://localhost:{CALLBACK_PORT}/callback"
STEAM_ID_RE      = re.compile(r"https://steamcommunity\.com/openid/id/(\d+)")

SUCCESS_HTML = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<style>body{background:#1B2838;color:#C7D5E0;font-family:sans-serif;"
    "display:flex;align-items:center;justify-content:center;height:100vh;margin:0}"
    ".box{text-align:center}.icon{font-size:64px}.title{font-size:24px;"
    "font-weight:bold;color:#66C0F4;margin:16px 0}.sub{color:#8F98A0}"
    "</style></head><body><div class='box'>"
    "<div class='icon'>&#10003;</div>"
    "<div class='title'>Steam connected</div>"
    "<div class='sub'>You can close this window and return to Steam Curator.</div>"
    "</div></body></html>"
)

ERROR_HTML = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<style>body{background:#1B2838;color:#C7D5E0;font-family:sans-serif;"
    "display:flex;align-items:center;justify-content:center;height:100vh;margin:0}"
    ".box{text-align:center}.icon{font-size:64px}.title{font-size:24px;"
    "font-weight:bold;color:#C94444;margin:16px 0}"
    "</style></head><body><div class='box'>"
    "<div class='icon'>&#10007;</div>"
    "<div class='title'>Verification failed</div>"
    "</div></body></html>"
)


def build_auth_url() -> str:
    params = {
        "openid.ns":         "http://specs.openid.net/auth/2.0",
        "openid.mode":       "checkid_setup",
        "openid.return_to":  CALLBACK_URL,
        "openid.realm":      f"http://localhost:{CALLBACK_PORT}",
        "openid.identity":   "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    return f"{STEAM_OPENID_URL}?{urlencode(params)}"


def verify_openid(params: dict) -> Optional[str]:
    """Verify Steam's OpenID response. Returns SteamID64 or None."""
    check_params = dict(params)
    check_params["openid.mode"] = "check_authentication"
    try:
        resp = requests.post(STEAM_OPENID_URL, data=check_params, timeout=10)
        if "is_valid:true" not in resp.text:
            return None
        match = STEAM_ID_RE.search(params.get("openid.claimed_id", ""))
        return match.group(1) if match else None
    except Exception:
        return None


def login(on_done: Callable[[Optional[str], str], None]):
    """
    Launch Steam login in background thread.
    Calls on_done(steam_id64 | None, message).
    """
    def _run():
        result    = [None]
        done_evt  = threading.Event()

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if "/callback" in self.path:
                    parsed   = urlparse(self.path)
                    params   = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                    steam_id = verify_openid(params)
                    result[0] = steam_id

                    html  = SUCCESS_HTML if steam_id else ERROR_HTML
                    body  = html.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    done_evt.set()

            def log_message(self, *args):
                pass

        try:
            server = HTTPServer(("localhost", CALLBACK_PORT), _Handler)
            server.timeout = 0.5
            webbrowser.open(build_auth_url())

            elapsed = 0
            while not done_evt.is_set() and elapsed < 180:
                server.handle_request()
                elapsed += 0.5
            server.server_close()

            if result[0]:
                on_done(result[0], "connected")
            elif elapsed >= 180:
                on_done(None, "timeout")
            else:
                on_done(None, "failed")

        except OSError as e:
            on_done(None, f"port_error:{e}")

    threading.Thread(target=_run, daemon=True).start()