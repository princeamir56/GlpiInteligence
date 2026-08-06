"""Low-level GLPI REST client: session lifecycle, retries, pagination."""
from __future__ import annotations

import logging
import time
from types import TracebackType
from typing import Any, Iterator

import requests

from .config import GLPIConfig
from .exceptions import (
    GLPIAPIError,
    GLPIAuthError,
    GLPIRateLimited,
    GLPISessionExpired,
    GLPIUnavailable,
)

logger = logging.getLogger(__name__)

JSONDict = dict[str, Any]


class GLPIClient:
    """Thin wrapper around the GLPI REST API.

    Use as a context manager so that ``initSession`` / ``killSession`` are
    always paired, even when exceptions occur:

        with GLPIClient(config) as client:
            rows = client.search("Ticket", forcedisplay=[1, 2, 12])
    """

    def __init__(self, config: GLPIConfig) -> None:
        self.config = config
        self._session_token: str | None = None
        self._http = requests.Session()
        self._http.verify = config.verify_ssl

    # ------------------------------------------------------------------ session
    def __enter__(self) -> "GLPIClient":
        self.init_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            self.kill_session()
        except Exception:
            logger.warning("killSession failed during context exit", exc_info=True)

    def init_session(self) -> str:
        url = f"{self.config.base_url}/initSession"
        headers = {
            "App-Token": self.config.app_token,
            "Authorization": f"user_token {self.config.user_token}",
            "Content-Type": "application/json",
        }
        logger.info("Opening GLPI session at %s", url)
        try:
            resp = self._http.get(url, headers=headers, timeout=self.config.request_timeout)
        except requests.RequestException as exc:
            raise GLPIUnavailable(f"Cannot reach GLPI at {url}: {exc}") from exc

        if resp.status_code == 401:
            raise GLPIAuthError("initSession refused: check App-Token and User-Token", 401, resp.text)
        if not resp.ok:
            raise GLPIAPIError(f"initSession failed ({resp.status_code})", resp.status_code, resp.text)

        token = resp.json().get("session_token")
        if not token:
            raise GLPIAuthError("initSession returned no session_token", resp.status_code, resp.text)

        self._session_token = token
        logger.info("GLPI session opened")
        return token

    def kill_session(self) -> None:
        if not self._session_token:
            return
        url = f"{self.config.base_url}/killSession"
        try:
            self._http.get(url, headers=self._auth_headers(), timeout=self.config.request_timeout)
            logger.info("GLPI session closed")
        finally:
            self._session_token = None

    # ------------------------------------------------------------------ helpers
    def _auth_headers(self) -> dict[str, str]:
        if not self._session_token:
            raise GLPISessionExpired("No active session; call init_session() first")
        return {
            "App-Token": self.config.app_token,
            "Session-Token": self._session_token,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> requests.Response:
        url = f"{self.config.base_url}{path}"
        headers = self._auth_headers()
        if extra_headers:
            headers.update(extra_headers)

        last_exc: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                resp = self._http.request(
                    method, url, headers=headers, params=params,
                    timeout=self.config.request_timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                wait = self.config.retry_backoff ** attempt
                logger.warning("Network error on %s %s (attempt %d/%d): %s — retrying in %.1fs",
                               method, path, attempt, self.config.max_retries, exc, wait)
                time.sleep(wait)
                continue

            if resp.status_code == 401:
                logger.warning("Session expired on %s — reopening (attempt %d)", path, attempt)
                self._session_token = None
                self.init_session()
                headers = self._auth_headers()
                if extra_headers:
                    headers.update(extra_headers)
                continue

            if resp.status_code == 429:
                wait = self.config.retry_backoff ** attempt
                logger.warning("Rate limited on %s — sleeping %.1fs", path, wait)
                time.sleep(wait)
                if attempt == self.config.max_retries:
                    raise GLPIRateLimited("GLPI rate limit exceeded", 429, resp.text)
                continue

            if resp.status_code >= 500:
                wait = self.config.retry_backoff ** attempt
                logger.warning("Server error %d on %s — retrying in %.1fs",
                               resp.status_code, path, wait)
                time.sleep(wait)
                last_exc = GLPIAPIError(
                    f"Server error {resp.status_code}", resp.status_code, resp.text[:500])
                continue

            if not resp.ok:
                raise GLPIAPIError(
                    f"{method} {path} failed ({resp.status_code}): {resp.text[:300]}",
                    resp.status_code, resp.text,
                )
            return resp

        if isinstance(last_exc, GLPIAPIError):
            raise last_exc
        raise GLPIUnavailable(
            f"GLPI unreachable after {self.config.max_retries} attempts: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------ API
    def get_item(self, itemtype: str, item_id: int, *, expand_dropdowns: bool = True) -> JSONDict:
        params = {"expand_dropdowns": "true" if expand_dropdowns else "false"}
        resp = self._request("GET", f"/{itemtype}/{item_id}", params=params)
        return resp.json()

    def list_items(
        self,
        itemtype: str,
        *,
        expand_dropdowns: bool = True,
        page_size: int | None = None,
    ) -> list[JSONDict]:
        """Simple paginated GET /{itemtype} — for small reference tables."""
        size = page_size or self.config.page_size
        out: list[JSONDict] = []
        start = 0
        while True:
            end = start + size - 1
            params = {
                "expand_dropdowns": "true" if expand_dropdowns else "false",
                "range": f"{start}-{end}",
            }
            resp = self._request("GET", f"/{itemtype}", params=params)
            try:
                batch = resp.json()
            except ValueError:
                break
            if not isinstance(batch, list) or not batch:
                break
            out.extend(batch)
            logger.debug("list_items(%s): fetched %d rows (total=%d)", itemtype, len(batch), len(out))
            if len(batch) < size:
                break
            start += size
        logger.info("list_items(%s) — %d rows", itemtype, len(out))
        return out

    def search(
        self,
        itemtype: str,
        *,
        forcedisplay: list[int],
        criteria: list[dict[str, Any]] | None = None,
        page_size: int | None = None,
    ) -> Iterator[JSONDict]:
        """Paginated /search/{itemtype}, yields one raw row at a time.

        The raw row uses GLPI numeric option IDs as keys; remapping to readable
        names is done in the extractors layer.
        """
        size = page_size or self.config.page_size
        start = 0
        total: int | None = None
        while True:
            end = start + size - 1
            params: dict[str, Any] = {
                "forcedisplay[]": forcedisplay,
                "range": f"{start}-{end}",
            }
            if criteria:
                for i, c in enumerate(criteria):
                    for k, v in c.items():
                        params[f"criteria[{i}][{k}]"] = v

            resp = self._request("GET", f"/search/{itemtype}", params=params)
            payload = resp.json() if resp.content else {}
            data = payload.get("data") or []
            total = payload.get("totalcount", total)
            if not data:
                break
            for row in data:
                yield row
            logger.debug("search(%s): %d-%d / total=%s", itemtype, start, end, total)
            if total is not None and start + len(data) >= total:
                break
            # Advance by the actual number of rows returned. GLPI enforces a
            # global cap (list_limit_max, often 500) that trims the last page
            # to fewer than `size` rows — trusting `size` here would cause us
            # to skip the rest of the dataset. Advancing by len(data) keeps
            # pagination correct even when the server returns partial pages.
            if len(data) == 0:
                break
            start += len(data)
        logger.info("search(%s) complete — totalcount=%s", itemtype, total)
