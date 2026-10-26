import datetime
import json
from urllib.parse import quote

import httpx

UPDATE_KEYS = {"subject", "description", "status", "assignee", "start_date", "due_date", "percent_done"}


class OpenProjectError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status


def summarize_work_package(raw: dict, base_url: str = "") -> dict:
    links = raw.get("_links", {})
    return {
        "id": raw["id"],
        "subject": raw.get("subject"),
        "project": _title(links, "project"),
        "type": _title(links, "type"),
        "status": _title(links, "status"),
        "assignee": _title(links, "assignee"),
        "startDate": raw.get("startDate"),
        "dueDate": raw.get("dueDate"),
        "percentageDone": raw.get("percentageDone"),
        "lockVersion": raw.get("lockVersion"),
        "url": f"{base_url}/work_packages/{raw['id']}",
    }


def _title(links: dict, name: str) -> str | None:
    return (links.get(name) or {}).get("title")


def _iso_duration(hours: float) -> str:
    minutes = round(hours * 60)
    if minutes <= 0:
        raise OpenProjectError("Hours must be greater than zero (resolution is one minute).")
    whole_hours, rest = divmod(minutes, 60)
    return "PT" + (f"{whole_hours}H" if whole_hours else "") + (f"{rest}M" if rest else "")


def _activity_user(links: dict) -> str | None:
    user = links.get("user") or {}
    if user.get("title"):
        return user["title"]
    user_id = (user.get("href") or "").rstrip("/").rsplit("/", 1)[-1]
    return f"user #{user_id}" if user_id.isdigit() else None


def _simplify_activity(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "comment": (raw.get("comment") or {}).get("raw", ""),
        "user": _activity_user(raw.get("_links", {})),
        "createdAt": raw.get("createdAt"),
    }


class OpenProjectClient:
    def __init__(
        self,
        url: str,
        token: str,
        transport: httpx.BaseTransport | None = None,
        page_size: int = 100,
    ):
        self.base_url = url.rstrip("/")
        self._page_size = page_size
        self._http = httpx.Client(
            base_url=self.base_url,
            auth=("apikey", token),
            headers={"Accept": "application/hal+json"},
            timeout=30.0,
            transport=transport,
        )
        self._cache: dict[str, list[dict]] = {}

    def whoami(self) -> dict:
        raw = self._request("GET", "/api/v3/users/me", expect=("id",))
        return {key: raw.get(key) for key in ("id", "name", "login", "email")}

    def list_projects(self) -> list[dict]:
        return [
            {"id": p["id"], "identifier": p.get("identifier"), "name": p.get("name")}
            for p in self._collect("/api/v3/projects")
        ]

    def list_statuses(self) -> list[dict]:
        return [
            {"id": s["id"], "name": s["name"], "isClosed": s.get("isClosed")}
            for s in self._collect("/api/v3/statuses")
        ]

    def list_types(self) -> list[dict]:
        return [{"id": t["id"], "name": t["name"]} for t in self._collect("/api/v3/types")]

    def list_users(self) -> list[dict]:
        filters = json.dumps([{"type": {"operator": "=", "values": ["User"]}}])
        return [
            {"id": u["id"], "name": u.get("name"), "login": u.get("login"), "email": u.get("email")}
            for u in self._collect("/api/v3/principals", {"filters": filters})
        ]

    def search_work_packages(
        self,
        project: str | None = None,
        assignee_me: bool = False,
        status: str | None = None,
        open_only: bool = False,
        query: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        filters = []
        if project:
            filters.append({"project": {"operator": "=", "values": [str(self._project_id(project))]}})
        if assignee_me:
            filters.append({"assignee": {"operator": "=", "values": ["me"]}})
        if status:
            filters.append({"status": {"operator": "=", "values": [str(self._status_id(status))]}})
        if open_only:
            filters.append({"status": {"operator": "o", "values": []}})
        if query:
            filters.append({"search": {"operator": "**", "values": [query]}})
        raw = self._request(
            "GET",
            "/api/v3/work_packages",
            params={
                "filters": json.dumps(filters),
                "pageSize": limit,
                "sortBy": json.dumps([["updatedAt", "desc"]]),
            },
        )
        return [summarize_work_package(wp, self.base_url) for wp in self._elements(raw)]

    def get_work_package(self, wp_id: int) -> dict:
        return self._detailed(self._request("GET", f"/api/v3/work_packages/{wp_id}", expect=("id",)))

    def create_work_package(
        self,
        project: str,
        subject: str,
        type: str | None = None,
        assignee: str | None = None,
        description: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
    ) -> dict:
        project_id = self._project_id(project)
        body: dict = {"subject": subject}
        links: dict = {}
        if description is not None:
            body["description"] = {"raw": description}
        if start_date:
            body["startDate"] = start_date
        if due_date:
            body["dueDate"] = due_date
        if type:
            links["type"] = {"href": f"/api/v3/types/{self._type_id(type)}"}
        if assignee:
            links["assignee"] = {"href": f"/api/v3/users/{self._user_id(assignee)}"}
        if links:
            body["_links"] = links
        raw = self._request("POST", f"/api/v3/projects/{project_id}/work_packages", json=body, expect=("id",))
        return summarize_work_package(raw, self.base_url)

    def update_work_package(self, wp_id: int, **changes) -> dict:
        unknown = set(changes) - UPDATE_KEYS
        if unknown:
            raise OpenProjectError(
                f"Unknown fields: {', '.join(sorted(unknown))}. Allowed: {', '.join(sorted(UPDATE_KEYS))}."
            )
        body = self._update_body(changes)
        path = f"/api/v3/work_packages/{wp_id}"
        lock_version = self._request("GET", path, expect=("lockVersion",))["lockVersion"]
        try:
            raw = self._request("PATCH", path, json={**body, "lockVersion": lock_version}, expect=("id",))
        except OpenProjectError as exc:
            if exc.status != 409:
                raise
            lock_version = self._request("GET", path, expect=("lockVersion",))["lockVersion"]
            try:
                raw = self._request("PATCH", path, json={**body, "lockVersion": lock_version}, expect=("id",))
            except OpenProjectError as retry_exc:
                if retry_exc.status != 409:
                    raise
                raise OpenProjectError(
                    f"Work package #{wp_id} keeps being modified by someone else. "
                    "Re-read it and try again.",
                    status=409,
                ) from retry_exc
        return summarize_work_package(raw, self.base_url)

    def add_comment(self, wp_id: int, text: str) -> dict:
        raw = self._request(
            "POST", f"/api/v3/work_packages/{wp_id}/activities", json={"comment": {"raw": text}}
        )
        return _simplify_activity(raw)

    def list_comments(self, wp_id: int) -> list[dict]:
        activities = self._collect(f"/api/v3/work_packages/{wp_id}/activities")
        comments = [_simplify_activity(activity) for activity in activities]
        return [comment for comment in comments if comment["comment"]]

    def log_time(
        self, wp_id: int, hours: float, date: str | None = None, comment: str | None = None
    ) -> dict:
        body: dict = {
            "hours": _iso_duration(hours),
            "spentOn": date or datetime.date.today().isoformat(),
            "_links": {"entity": {"href": f"/api/v3/work_packages/{wp_id}"}},
        }
        if comment:
            body["comment"] = {"raw": comment}
        raw = self._request("POST", "/api/v3/time_entries", json=body)
        return {
            "id": raw.get("id"),
            "hours": raw.get("hours"),
            "spentOn": raw.get("spentOn"),
            "comment": (raw.get("comment") or {}).get("raw", ""),
        }

    def _detailed(self, raw: dict) -> dict:
        summary = summarize_work_package(raw, self.base_url)
        summary["description"] = (raw.get("description") or {}).get("raw", "")
        return summary

    def _update_body(self, changes: dict) -> dict:
        body: dict = {}
        links: dict = {}
        for key, value in changes.items():
            if key == "subject":
                body["subject"] = value
            elif key == "description":
                body["description"] = {"raw": value}
            elif key == "start_date":
                body["startDate"] = value
            elif key == "due_date":
                body["dueDate"] = value
            elif key == "percent_done":
                body["percentageDone"] = value
            elif key == "status":
                links["status"] = {"href": f"/api/v3/statuses/{self._status_id(value)}"}
            elif key == "assignee":
                links["assignee"] = {"href": f"/api/v3/users/{self._user_id(value)}"}
        if links:
            body["_links"] = links
        return body

    def _status_id(self, value: str) -> int:
        return self._resolve("status", value, self.list_statuses, ("name",))

    def _type_id(self, value: str) -> int:
        return self._resolve("type", value, self.list_types, ("name",))

    def _user_id(self, value: str) -> int:
        if value.strip().lower() == "me":
            return self.whoami()["id"]
        return self._resolve("user", value, self.list_users, ("name", "login", "email"))

    def _project_id(self, value: str) -> int:
        value = str(value).strip()
        if value.isdigit():
            return int(value)
        try:
            return self._request("GET", f"/api/v3/projects/{quote(value, safe='')}", expect=("id",))["id"]
        except OpenProjectError as exc:
            if exc.status != 404:
                raise
        return self._resolve("project", value, self.list_projects, ("identifier", "name"))

    def _resolve(self, kind: str, value: str, load_items, fields: tuple[str, ...]) -> int:
        value = str(value).strip()
        if value.isdigit():
            return int(value)
        wanted = value.casefold()

        def find(items: list[dict]) -> list[dict]:
            return [
                item for item in items
                if any(str(item.get(field) or "").casefold() == wanted for field in fields)
            ]

        items = self._cache.get(kind)
        matches = find(items) if items is not None else []
        if not matches:
            items = self._cache[kind] = load_items()
            matches = find(items)
        if len(matches) == 1:
            return matches[0]["id"]

        def label(item: dict) -> str:
            return " / ".join(str(item[f]) for f in fields if item.get(f))

        if matches:
            raise OpenProjectError(
                f"Ambiguous {kind} {value!r}; candidates: {', '.join(label(m) for m in matches)}."
            )
        raise OpenProjectError(
            f"Unknown {kind} {value!r}. Available: {', '.join(label(i) for i in items) or 'none'}."
        )

    def _collect(self, path: str, params: dict | None = None) -> list[dict]:
        elements: list[dict] = []
        while True:
            page = self._request(
                "GET",
                path,
                params={**(params or {}), "pageSize": self._page_size, "offset": len(elements) // self._page_size + 1},
            )
            batch = self._elements(page)
            elements.extend(batch)
            if len(batch) < self._page_size or len(elements) >= page.get("total", len(elements)):
                return elements

    @staticmethod
    def _elements(payload: dict) -> list[dict]:
        elements = (payload.get("_embedded") or {}).get("elements")
        if not isinstance(elements, list):
            raise OpenProjectError("Unexpected response from OpenProject: collection has no elements. Check OPM_URL.")
        return elements

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: dict | None = None,
        expect: tuple[str, ...] = (),
    ) -> dict:
        try:
            response = self._http.request(method, path, params=params, json=json)
        except httpx.HTTPError as exc:
            raise OpenProjectError(
                f"Cannot reach OpenProject at {self.base_url}: {exc}. Check OPM_URL and your network/VPN."
            ) from exc
        if response.status_code >= 400:
            raise self._error_for(response)
        if response.is_redirect:
            location = response.headers.get("Location", "an unknown address")
            raise OpenProjectError(
                f"OpenProject redirected the request to {location} (HTTP {response.status_code}). "
                f"Set OPM_URL to that address (typically the https:// one) instead of {self.base_url}.",
                status=response.status_code,
            )
        payload = self._parse_json(response)
        missing = [key for key in expect if key not in payload]
        if missing:
            raise OpenProjectError(
                f"Unexpected response from {self.base_url}: missing {', '.join(missing)}. Check OPM_URL."
            )
        return payload

    def _parse_json(self, response: httpx.Response) -> dict:
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            raise OpenProjectError(
                f"Unexpected non-JSON response from {self.base_url} (HTTP {response.status_code}); "
                "check OPM_URL points at OpenProject itself, not a login or proxy page."
            )
        return payload

    def _error_for(self, response: httpx.Response) -> OpenProjectError:
        status = response.status_code
        detail = self._api_message(response)
        if status == 401:
            message = (
                "Authentication failed (401). Check the API token (OPM_TOKEN) and make sure API tokens "
                "are enabled in OpenProject administration (Administration > API and webhooks)."
            )
        elif status == 403:
            message = f"Permission denied (403): {detail}"
        elif status == 404:
            message = f"Not found (404): {detail}"
        elif status == 409:
            message = f"Update conflict (409): {detail}"
        else:
            message = f"OpenProject error {status}: {detail}"
        return OpenProjectError(message, status=status)

    @staticmethod
    def _api_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip() or response.reason_phrase
        nested = [e.get("message") for e in payload.get("_embedded", {}).get("errors", []) if e.get("message")]
        return " ".join(nested) or payload.get("message") or response.reason_phrase
