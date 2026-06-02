"""
Google Drive sync — works in two modes:

MODE A — Via PimpMySteam API (preferred, zero local setup)
  User logs in at pimpmysteam.com, connects Google there.
  App calls /google/drive-token with its JWT to get an access token.
  No client_secret.json needed locally.

MODE B — Local OAuth (fallback, for dev / self-hosted)
  Requires client_secret.json in the project root.
  Opens browser for OAuth on first run.
"""
import io
import json
import threading
from pathlib import Path
from typing import Optional, Callable

from config import BASE_DIR

CLIENT_SECRET_PATH = BASE_DIR / "client_secret.json"
TOKEN_PATH         = BASE_DIR / "token.json"
SETTINGS_PATH      = BASE_DIR / "settings.json"

SCOPES            = ["https://www.googleapis.com/auth/drive.file"]
DRIVE_FOLDER_NAME = "Steam Curator"
SYNC_FILES        = ["wishlist.json", "settings.json", "purchases.json"]


# ── Auth mode detection ───────────────────────────────────────────────────────

def _get_steamkustom_token() -> Optional[str]:
    """Return JWT from settings.json if user logged in via pimpmysteam.com."""
    try:
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("steamkustom_token")
    except Exception:
        pass
    return None


def _get_api_url() -> str:
    try:
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH) as f:
                data = json.load(f)
            return data.get("api_url", "https://steamkustom-production.up.railway.app")
    except Exception:
        pass
    return "https://steamkustom-production.up.railway.app"


def _fetch_drive_token_from_api() -> Optional[str]:
    """Ask our backend for a Google Drive access token using the user's JWT."""
    import requests
    jwt    = _get_steamkustom_token()
    if not jwt:
        return None
    try:
        resp = requests.get(
            f"{_get_api_url()}/google/drive-token",
            headers={"Authorization": f"Bearer {jwt}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:
        pass
    return None


# ── Credentials ───────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """True if either mode is available."""
    return bool(_get_steamkustom_token()) or CLIENT_SECRET_PATH.exists()


def is_authenticated() -> bool:
    # Mode A: check if API token fetch works
    if _get_steamkustom_token():
        return bool(_fetch_drive_token_from_api())
    # Mode B: local token
    if TOKEN_PATH.exists():
        try:
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            return creds and (creds.valid or bool(creds.refresh_token))
        except Exception:
            pass
    return False


def authenticate(on_done: Callable[[bool, str], None] = None):
    def _run():
        try:
            creds = _load_or_refresh()
            if on_done:
                on_done(bool(creds), "Connected to Google Drive" if creds else "Auth failed")
        except Exception as e:
            if on_done:
                on_done(False, str(e))
    threading.Thread(target=_run, daemon=True).start()


def disconnect():
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()


def _load_or_refresh():
    """Get credentials — prefers API token, falls back to local OAuth."""
    # Mode A: get access token from our API
    api_token = _fetch_drive_token_from_api()
    if api_token:
        from google.oauth2.credentials import Credentials
        return Credentials(token=api_token)

    # Mode B: local OAuth
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def _service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_load_or_refresh())


# ── Drive helpers (unchanged) ─────────────────────────────────────────────────

def _get_or_create_folder(svc, name: str, parent_id: str = None) -> str:
    q = (f"name='{name}' and mimeType='application/vnd.google-apps.folder'"
         f" and trashed=false")
    if parent_id:
        q += f" and '{parent_id}' in parents"
    files = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    return svc.files().create(body=meta, fields="id").execute()["id"]


def _find_file(svc, name: str, parent_id: str) -> Optional[str]:
    q = (f"name='{name}' and '{parent_id}' in parents and trashed=false"
         f" and mimeType!='application/vnd.google-apps.folder'")
    files = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
    return files[0]["id"] if files else None


def _mime(path: Path) -> str:
    return {
        ".json": "application/json",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
    }.get(path.suffix.lower(), "application/octet-stream")


def _upload_file(svc, path: Path, parent_id: str):
    from googleapiclient.http import MediaFileUpload
    media    = MediaFileUpload(str(path), mimetype=_mime(path), resumable=False)
    existing = _find_file(svc, path.name, parent_id)
    if existing:
        svc.files().update(fileId=existing, media_body=media).execute()
    else:
        svc.files().create(
            body={"name": path.name, "parents": [parent_id]},
            media_body=media, fields="id",
        ).execute()


def _download_file(svc, file_id: str, dest: Path):
    from googleapiclient.http import MediaIoBaseDownload
    request = svc.files().get_media(fileId=file_id)
    buf     = io.BytesIO()
    dl      = MediaIoBaseDownload(buf, request)
    done    = False
    while not done:
        _, done = dl.next_chunk()
    with open(dest, "wb") as f:
        f.write(buf.getvalue())


# ── Public API ────────────────────────────────────────────────────────────────

def upload_all(on_progress: Callable[[str], None] = None) -> dict:
    uploaded, errors = 0, []
    try:
        svc       = _service()
        folder_id = _get_or_create_folder(svc, DRIVE_FOLDER_NAME)
        for filename in SYNC_FILES:
            path = BASE_DIR / filename
            if not path.exists():
                continue
            try:
                if on_progress:
                    on_progress(f"Uploading {filename}…")
                _upload_file(svc, path, folder_id)
                uploaded += 1
            except Exception as e:
                errors.append(f"{filename}: {e}")
    except Exception as e:
        errors.append(f"Error: {e}")
    return {"uploaded": uploaded, "errors": errors}


def download_all(on_progress: Callable[[str], None] = None) -> dict:
    downloaded, errors = 0, []
    try:
        svc = _service()
        q   = (f"name='{DRIVE_FOLDER_NAME}' and "
               f"mimeType='application/vnd.google-apps.folder' and trashed=false")
        folders = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
        if not folders:
            return {"downloaded": 0, "errors": ["No Drive folder found. Upload first."]}
        folder_id = folders[0]["id"]
        for filename in SYNC_FILES:
            file_id = _find_file(svc, filename, folder_id)
            if not file_id:
                continue
            try:
                if on_progress:
                    on_progress(f"Downloading {filename}…")
                _download_file(svc, file_id, BASE_DIR / filename)
                downloaded += 1
            except Exception as e:
                errors.append(f"{filename}: {e}")
    except Exception as e:
        errors.append(f"Error: {e}")
    return {"downloaded": downloaded, "errors": errors}


def get_sync_status() -> dict:
    jwt = _get_steamkustom_token()
    return {
        "configured":    is_configured(),
        "authenticated": is_authenticated(),
        "mode":          "api" if jwt else "local",
        "has_jwt":       bool(jwt),
    }