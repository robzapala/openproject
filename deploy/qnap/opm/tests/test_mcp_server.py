import asyncio
import json

import pytest
from mcp.client import Client

from opm.client import OpenProjectError
from opm.config import ConfigError
from opm.mcp_server import build_server

TOOL_NAMES = {
    "whoami",
    "list_projects",
    "search_work_packages",
    "get_work_package",
    "create_work_package",
    "update_work_package",
    "add_comment",
    "list_comments",
    "log_time",
    "list_statuses",
    "list_types",
    "list_users",
}

WP = {"id": 12, "subject": "Naprawić drukarkę", "status": "W realizacji", "lockVersion": 3}


class FakeClient:
    def __init__(self):
        self.calls = []
        self.error = None

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self.error:
            raise self.error

    def whoami(self):
        self._record("whoami")
        return {"id": 5, "name": "Jan Kowalski", "login": "jan", "email": "jan@example.com"}

    def list_projects(self):
        self._record("list_projects")
        return [{"id": 1, "identifier": "biuro", "name": "Biuro"}]

    def list_statuses(self):
        self._record("list_statuses")
        return [{"id": 1, "name": "Nowe", "isClosed": False}]

    def list_types(self):
        self._record("list_types")
        return [{"id": 1, "name": "Zadanie"}]

    def list_users(self):
        self._record("list_users")
        return [{"id": 5, "name": "Jan Kowalski", "login": "jan", "email": None}]

    def search_work_packages(self, **kwargs):
        self._record("search_work_packages", **kwargs)
        return [WP]

    def get_work_package(self, wp_id):
        self._record("get_work_package", wp_id)
        return {**WP, "description": "Opis zadania"}

    def create_work_package(self, project, subject, **kwargs):
        self._record("create_work_package", project, subject, **kwargs)
        return {**WP, "id": 123, "subject": subject}

    def update_work_package(self, wp_id, **changes):
        self._record("update_work_package", wp_id, **changes)
        return {**WP, "id": wp_id}

    def add_comment(self, wp_id, text):
        self._record("add_comment", wp_id, text)
        return {"id": 9, "comment": text}

    def list_comments(self, wp_id):
        self._record("list_comments", wp_id)
        return [{"id": 9, "comment": "Zrobione", "user": "Jan Kowalski", "createdAt": "2026-10-26T10:00:00Z"}]

    def log_time(self, wp_id, hours, date=None, comment=None):
        self._record("log_time", wp_id, hours, date=date, comment=comment)
        return {"id": 3, "hours": "PT1H30M", "spentOn": "2026-10-26", "comment": comment or ""}


@pytest.fixture
def client():
    return FakeClient()


def run_with_session(server, action):
    async def runner():
        async with Client(server) as session:
            return await action(session)

    return asyncio.run(runner())


def call(server, name, arguments=None):
    return run_with_session(server, lambda session: session.call_tool(name, arguments or {}))


def text_of(result):
    return "\n".join(block.text for block in result.content)


def test_lists_all_tools(client):
    server = build_server(lambda: client)

    result = run_with_session(server, lambda session: session.list_tools())

    assert {tool.name for tool in result.tools} == TOOL_NAMES
    assert all(tool.description for tool in result.tools)


def test_read_tool_returns_json_text(client):
    result = call(build_server(lambda: client), "get_work_package", {"wp_id": 12})

    assert not result.is_error
    assert json.loads(text_of(result)) == {**WP, "description": "Opis zadania"}
    assert client.calls[-1] == ("get_work_package", (12,), {})


def test_results_keep_non_ascii_characters(client):
    result = call(build_server(lambda: client), "list_projects")

    assert "Biuro" in text_of(result)
    result = call(build_server(lambda: client), "list_comments", {"wp_id": 12})
    assert "Zrobione" in text_of(result)
    result = call(build_server(lambda: client), "search_work_packages")
    assert "Naprawić drukarkę" in text_of(result)


def test_search_tool_passes_filters(client):
    call(
        build_server(lambda: client),
        "search_work_packages",
        {"project": "biuro", "assignee_me": True, "status": "Nowe", "open_only": True, "query": "drukarka", "limit": 5},
    )

    assert client.calls[-1] == (
        "search_work_packages",
        (),
        {"project": "biuro", "assignee_me": True, "status": "Nowe", "open_only": True, "query": "drukarka", "limit": 5},
    )


def test_create_tool_passes_optional_fields(client):
    result = call(
        build_server(lambda: client),
        "create_work_package",
        {"project": "biuro", "subject": "Nowe zadanie", "type": "Zadanie", "assignee": "me", "due_date": "2026-11-01"},
    )

    assert json.loads(text_of(result))["id"] == 123
    name, args, kwargs = client.calls[-1]
    assert (name, args) == ("create_work_package", ("biuro", "Nowe zadanie"))
    assert kwargs["type"] == "Zadanie"
    assert kwargs["assignee"] == "me"
    assert kwargs["due_date"] == "2026-11-01"


def test_update_tool_calls_client(client):
    result = call(
        build_server(lambda: client),
        "update_work_package",
        {"wp_id": 12, "status": "W realizacji", "assignee": "me", "percent_done": 50},
    )

    assert not result.is_error
    assert client.calls[-1] == (
        "update_work_package",
        (12,),
        {"status": "W realizacji", "assignee": "me", "percent_done": 50},
    )


def test_update_tool_without_changes_is_error(client):
    result = call(build_server(lambda: client), "update_work_package", {"wp_id": 12})

    assert result.is_error
    assert "at least one" in text_of(result).lower()
    assert client.calls == []


def test_comment_and_time_tools(client):
    server = build_server(lambda: client)

    call(server, "add_comment", {"wp_id": 12, "text": "Gotowe"})
    call(server, "log_time", {"wp_id": 12, "hours": 1.5, "date": "2026-10-25", "comment": "Naprawa"})

    assert client.calls[0] == ("add_comment", (12, "Gotowe"), {})
    assert client.calls[1] == ("log_time", (12, 1.5), {"date": "2026-10-25", "comment": "Naprawa"})


def test_invalid_arguments_are_error(client):
    result = call(build_server(lambda: client), "get_work_package", {"wp_id": "abc"})

    assert result.is_error
    assert client.calls == []


def test_api_error_returns_is_error(client):
    client.error = OpenProjectError("Not found (404): The requested resource could not be found.", status=404)

    result = call(build_server(lambda: client), "get_work_package", {"wp_id": 999})

    assert result.is_error
    assert "Not found (404)" in text_of(result)


def test_missing_config_is_reported_per_call(client):
    attempts = []

    def factory():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConfigError("Missing configuration: OPM_URL, OPM_TOKEN. Set the environment variables.")
        return client

    server = build_server(factory)

    first = call(server, "whoami")
    second = call(server, "whoami")

    assert first.is_error
    assert "Missing configuration" in text_of(first)
    assert not second.is_error
    assert json.loads(text_of(second))["login"] == "jan"
    assert len(attempts) == 2


def test_client_is_created_lazily_and_reused(client):
    created = []

    def factory():
        created.append(1)
        return client

    server = build_server(factory)
    assert created == []

    async def two_calls(session):
        await session.call_tool("whoami", {})
        await session.call_tool("list_projects", {})

    run_with_session(server, two_calls)

    assert len(created) == 1
