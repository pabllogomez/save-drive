"""Google Drive API via stdlib urllib — OAuth device-code flow only."""

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    bundled = Path(__file__).with_name("cacert.pem")
    candidates = [
        str(bundled),
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/ssl/cert.pem",
        "/etc/pki/tls/certs/ca-bundle.crt",
    ]
    for cafile in candidates:
        if os.path.isfile(cafile):
            try:
                ctx.load_verify_locations(cafile=cafile)
                return ctx
            except Exception:
                pass
    return ctx

OAUTH_DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"


def _request_json(url: str, method: str = "GET", headers: dict | None = None,
                  data: bytes | None = None, timeout: int = 30) -> tuple[int, Any]:
    req = urllib.request.Request(url, method=method, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        code = resp.getcode()
        body = resp.read().decode("utf-8", errors="replace")
        if not body:
            return code, {}
        return code, json.loads(body)


def _post_form(url: str, payload: dict, timeout: int = 30) -> tuple[int, Any]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return _request_json(url, method="POST", headers=headers, data=data, timeout=timeout)


def start_device_auth(client_id: str) -> dict:
    payload = {
        "client_id": client_id,
        "scope": "https://www.googleapis.com/auth/drive.file",
    }
    code, resp = _post_form(OAUTH_DEVICE_CODE_URL, payload)
    return resp


def poll_for_token(client_id: str, client_secret: str, device_code: str,
                   interval: int, expires_in: int) -> dict:
    """Block until the user approves, denies, or the code expires."""
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        try:
            code, resp = _post_form(OAUTH_TOKEN_URL, payload)
            if "error" not in resp:
                return resp
            if resp.get("error") == "authorization_pending":
                continue
            if resp.get("error") == "slow_down":
                interval += 1
                continue
            raise OAuthError(resp.get("error_description", resp.get("error", "unknown")))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                err = json.loads(body)
            except Exception:
                err = {"error": body}
            if err.get("error") == "authorization_pending":
                continue
            raise OAuthError(err.get("error_description", err.get("error", str(e))))
    raise OAuthError("Device code expired")


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    code, resp = _post_form(OAUTH_TOKEN_URL, payload)
    return resp


def revoke_token(refresh_token: str) -> None:
    try:
        _post_form(OAUTH_REVOKE_URL, {"token": refresh_token})
    except Exception:
        pass


class OAuthError(Exception):
    pass


class GDrive:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self.access_token}"}
        if extra:
            h.update(extra)
        return h

    def get_user_email(self) -> str | None:
        url = "https://www.googleapis.com/drive/v3/about?fields=user"
        try:
            _, resp = _request_json(url, headers=self._headers())
            return resp.get("user", {}).get("emailAddress")
        except Exception:
            return None

    def find_folder(self, name: str, parent_id: str | None = None) -> str | None:
        q = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and trashed=false"
        if parent_id:
            q += f" and '{parent_id}' in parents"
        url = f"{DRIVE_FILES_URL}?q={urllib.parse.quote(q)}&spaces=drive&fields=files(id,name)"
        _, resp = _request_json(url, headers=self._headers())
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def create_folder(self, name: str, parent_id: str | None = None) -> str:
        metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            metadata["parents"] = [parent_id]
        data = json.dumps(metadata).encode("utf-8")
        headers = self._headers({"Content-Type": "application/json"})
        _, resp = _request_json(DRIVE_FILES_URL, method="POST",
                                headers=headers, data=data, timeout=30)
        return resp["id"]

    def get_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        fid = self.find_folder(name, parent_id)
        if fid:
            return fid
        return self.create_folder(name, parent_id)

    def list_files(self, parent_id: str, prefix: str | None = None) -> list[dict]:
        q = f"'{parent_id}' in parents and trashed=false"
        if prefix:
            q += f" and name contains '{prefix}'"
        url = f"{DRIVE_FILES_URL}?q={urllib.parse.quote(q)}&spaces=drive&fields=files(id,name,createdTime,size,md5Checksum)"
        _, resp = _request_json(url, headers=self._headers())
        return resp.get("files", [])

    def delete_file(self, file_id: str) -> None:
        url = f"{DRIVE_FILES_URL}/{file_id}"
        _request_json(url, method="DELETE", headers=self._headers())

    def upload_file(self, local_path: Path, name: str, parent_id: str,
                    mime_type: str = "application/zip") -> str:
        """Resumable upload; returns file id."""
        size = local_path.stat().st_size
        metadata = {"name": name, "parents": [parent_id]}
        headers = self._headers({
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": mime_type,
            "X-Upload-Content-Length": str(size),
        })
        data = json.dumps(metadata).encode("utf-8")
        req = urllib.request.Request(
            f"{DRIVE_UPLOAD_URL}?uploadType=resumable",
            method="POST", data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            upload_url = resp.headers.get("Location")
        if not upload_url:
            raise RuntimeError("No upload URL returned")

        with open(local_path, "rb") as f:
            body = f.read()
        put_headers = self._headers({
            "Content-Type": mime_type,
            "Content-Length": str(size),
        })
        put_req = urllib.request.Request(upload_url, method="PUT",
                                         data=body, headers=put_headers)
        with urllib.request.urlopen(put_req, timeout=120, context=_ssl_context()) as resp:
            _, upload_resp = resp.getcode(), json.loads(resp.read().decode("utf-8"))
        return upload_resp["id"]

    def download_file(self, file_id: str, dest: Path) -> None:
        url = f"{DRIVE_FILES_URL}/{file_id}?alt=media"
        req = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as resp, open(dest, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
