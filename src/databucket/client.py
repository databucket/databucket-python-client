from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

import requests

from .bucket import Bucket
from .model import DatabucketError, Project
from .rules import _value

#: The header selecting the version of the data API.
API_VERSION_HEADER = "Databucket-Api-Version"
_API_VERSION = "2"
_USER_AGENT = "databucket-python-client/2"

T = TypeVar("T")

log = logging.getLogger("databucket")


class Databucket:
    """Client for one Databucket project, signed in as one user (typically a ROBOT account).

    ::

        databucket = Databucket(
            "https://databucket.example.com",
            username="tests-robot",
            password=os.environ["DATABUCKET_PASSWORD"],
            project="Acme Shop",
        )
        users = databucket.bucket("dev-users")
        user = users.reserve(Rules.where(Rule.property("$.status").eq("active"))).one()

    The client signs in on the first call and again when the token expires. One client can be shared by threads.
    All data calls use API version 2 (header ``Databucket-Api-Version: 2``). Each request is logged at DEBUG level
    by the logger ``databucket``.

    :param url: the address of Databucket, e.g. ``https://databucket.example.com`` or ``http://localhost:8080``
    :param username: sign in with a username and password (``POST /api/public/signin``), together with ``password``
    :param password: the password of ``username``
    :param sso_token: sign in with an access token of the identity provider (OAuth2 client credentials of a ROBOT
        account), exchanged for a Databucket token (``POST /api/public/sso/token-exchange``); called on every
        sign-in, so it can fetch a fresh token
    :param token: a Databucket token you already have (no sign-in; it is not renewed)
    :param project: the project by id or by name (needed only when the user has several projects)
    :param timeout: timeout of each request in seconds (default 30)
    :param session: your own ``requests.Session``, e.g. with a proxy or certificates
    """

    def __init__(
        self,
        url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        sso_token: Callable[[], str] | None = None,
        token: str | None = None,
        project: int | str | None = None,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        if not url or not url.strip():
            raise ValueError("The Databucket url is empty")
        self._base_url = url.rstrip("/")
        self._timeout = timeout
        self._session = session or requests.Session()
        self._project_id = project if isinstance(project, int) else None
        self._project_name = project if isinstance(project, str) else None
        self._current_token = token
        self._current_project: Project | None = None
        self._lock = threading.Lock()

        self._sign_in_fn: Callable[[int | None], Any] | None = None
        if username is not None or password is not None:
            if not username or password is None:
                raise ValueError("Sign-in with a password needs both username and password")
            self._sign_in_fn = lambda project_id: self._sign_in_call(
                "/api/public/signin",
                {"username": username, "password": password, **_project(project_id)},
            )
        elif sso_token is not None:
            self._sign_in_fn = lambda project_id: self._sign_in_call(
                "/api/public/sso/token-exchange", {"token": sso_token(), **_project(project_id)}
            )
        if self._sign_in_fn is None and not self._current_token:
            raise ValueError("No credentials: give username and password, sso_token or token")

    def bucket(self, name: str) -> Bucket[Any]:
        """A bucket. For typed properties: ``users: Bucket[User] = databucket.bucket("dev-users")``."""
        return Bucket(self, name)

    def project(self) -> Project | None:
        """The project the client works in (signs in if not done yet); None when only a token was given."""
        self.token()
        return self._current_project

    def token(self) -> str:
        """The current access token (signs in if needed)."""
        token = self._current_token
        if token:
            return token
        with self._lock:
            # another thread may have signed in meanwhile
            if self._current_token:
                return self._current_token
            return self._sign_in()

    # ------------------------------------------------------------------ sign-in

    def _sign_in(self) -> str:
        if self._sign_in_fn is None:
            raise DatabucketError(0, "No credentials: give username and password, sso_token or token")

        project_id = self._project_id
        response = self._sign_in_fn(project_id) or {}
        if project_id is None and not response.get("token") and isinstance(response.get("projects"), list):
            # the user has several projects: pick one by name
            project_id = self._pick_project(response["projects"])
            response = self._sign_in_fn(project_id) or {}
        signed_in = response.get("project")
        if (
            self._project_name is not None
            and project_id is None
            and signed_in
            and signed_in.get("name") != self._project_name
        ):
            raise DatabucketError(0, f"The user is not assigned to the project '{self._project_name}'")

        if not response.get("token") or response.get("changePassword"):
            reason = ": the user has to change the password first" if response.get("changePassword") else ""
            raise DatabucketError(0, f"Sign-in gave no token for a project{reason}", json.dumps(response))

        self._current_project = Project(int(signed_in["id"]), signed_in["name"]) if signed_in else None
        self._current_token = str(response["token"])
        project = self._current_project
        log.debug("Signed in to project %s (%s)", project.name if project else None, project.id if project else None)
        return self._current_token

    def _pick_project(self, projects: list[dict[str, Any]]) -> int:
        for p in projects:
            if p.get("name") == self._project_name:
                return int(p["id"])
        names = ", ".join(str(p.get("name")) for p in projects)
        if self._project_name is None:
            raise DatabucketError(0, f"The user has several projects, choose one with the 'project' option: [{names}]")
        raise DatabucketError(0, f"The user is not assigned to the project '{self._project_name}'; projects: [{names}]")

    def _sign_in_call(self, path: str, body: dict[str, Any]) -> Any:
        status, text = self._send("POST", path, {"Content-Type": "application/json"}, json.dumps(body))
        return self._handle("POST", path, status, text)

    # ------------------------------------------------------------------ HTTP

    def _call(self, method: str, path: str, body: Any = None, retry: bool = True) -> Any:
        """A call of the data API (version 2) with the token; signs in again once on 401."""
        token = self.token()
        headers = {"Authorization": f"Bearer {token}", API_VERSION_HEADER: _API_VERSION}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, default=_json_default)
        status, text = self._send(method, path, headers, data)

        if status == 401 and retry and self._sign_in_fn is not None:
            # the token expired: sign in again once
            with self._lock:
                if self._current_token == token:
                    self._current_token = None
            return self._call(method, path, body, retry=False)
        return self._handle(method, path, status, text)

    def _send(self, method: str, path: str, headers: dict[str, str], data: str | None) -> tuple[int, str]:
        url = self._base_url + path
        start = time.monotonic()
        try:
            response = self._session.request(
                method,
                url,
                headers={"Accept": "application/json", "User-Agent": _USER_AGENT, **headers},
                data=data.encode("utf-8") if data is not None else None,
                timeout=self._timeout,
            )
        except requests.Timeout as e:
            raise DatabucketError(0, f"{method} {url} failed: timeout after {self._timeout} s") from e
        except requests.RequestException as e:
            raise DatabucketError(0, f"{method} {url} failed: {e}") from e
        log.debug("%s %s -> %s (%d ms)", method, url, response.status_code, (time.monotonic() - start) * 1000)
        response.encoding = response.encoding or "utf-8"
        return response.status_code, response.text

    def _handle(self, method: str, path: str, status: int, text: str) -> Any:
        parsed = _parse(text)
        if status >= 400:
            message = None
            if isinstance(parsed, dict):
                message = parsed.get("message") or parsed.get("error")
            if not message:
                message = text if text.strip() else "no response body"
            raise DatabucketError(status, f"{message} ({method} {path.split('?')[0]})", text)
        return parsed


def _project(project_id: int | None) -> dict[str, int]:
    return {} if project_id is None else {"projectId": project_id}


def _parse(text: str) -> Any:
    if not text or not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _json_default(value: Any) -> Any:
    if isinstance(value, date):
        return _value(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
