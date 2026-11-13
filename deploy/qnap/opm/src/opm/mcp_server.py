import json
import logging
import sys
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from opm.client import OpenProjectClient, OpenProjectError
from opm.config import ConfigError, load_config

NAMES_HINT = "Status, type, user and project accept names (case-insensitive) or numeric ids."


class _LazyClient:
    def __init__(self, factory: Callable[[], OpenProjectClient]):
        self._factory = factory
        self._client: OpenProjectClient | None = None

    def call(self, method: str, *args: Any, **kwargs: Any) -> str:
        try:
            if self._client is None:
                self._client = self._factory()
            result = getattr(self._client, method)(*args, **kwargs)
        except (OpenProjectError, ConfigError) as exc:
            raise ToolError(getattr(exc, "message", None) or str(exc)) from exc
        return json.dumps(result, ensure_ascii=False)


def build_server(client_factory: Callable[[], OpenProjectClient]) -> MCPServer:
    server = MCPServer("opm")
    lazy = _LazyClient(client_factory)

    @server.tool(description="Show the OpenProject user the API token belongs to (id, name, login, email).")
    def whoami() -> str:
        return lazy.call("whoami")

    @server.tool(description="List all visible projects with id, identifier and name.")
    def list_projects() -> str:
        return lazy.call("list_projects")

    @server.tool(description="List work package statuses (id, name, isClosed). Use these exact names (the instance is seeded in Polish) for status filters and updates.")
    def list_statuses() -> str:
        return lazy.call("list_statuses")

    @server.tool(description="List work package types (id, name). Use these exact names (the instance is seeded in Polish) when creating work packages.")
    def list_types() -> str:
        return lazy.call("list_types")

    @server.tool(description="List users (id, name, login, email). Use a name or login as assignee; assignee 'me' means the token owner.")
    def list_users() -> str:
        return lazy.call("list_users")

    @server.tool(
        description=(
            "Search work packages, most recently updated first. All filters are optional and combined with AND. "
            f"{NAMES_HINT} project: identifier, name or id. status: exact status name. "
            "assignee_me: only items assigned to the token owner. open_only: exclude closed statuses. "
            "query: full-text search in subject and description. limit: max results (default 50). "
            "Returns summaries including id, subject, status, assignee, dates and url."
        )
    )
    def search_work_packages(
        project: str | None = None,
        assignee_me: bool = False,
        status: str | None = None,
        open_only: bool = False,
        query: str | None = None,
        limit: int = 50,
    ) -> str:
        return lazy.call(
            "search_work_packages",
            project=project,
            assignee_me=assignee_me,
            status=status,
            open_only=open_only,
            query=query,
            limit=limit,
        )

    @server.tool(description="Get one work package by numeric id, including its description, dates, assignee and url.")
    def get_work_package(wp_id: int) -> str:
        return lazy.call("get_work_package", wp_id)

    @server.tool(
        description=(
            "Create a work package in a project. "
            f"{NAMES_HINT} type: a type name as returned by list_types. "
            "assignee: user name or login, or 'me' for the token owner. description: Markdown. "
            "Dates are YYYY-MM-DD. Returns the created work package including its url."
        )
    )
    def create_work_package(
        project: str,
        subject: str,
        type: str | None = None,
        assignee: str | None = None,
        description: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
    ) -> str:
        return lazy.call(
            "create_work_package",
            project,
            subject,
            type=type,
            assignee=assignee,
            description=description,
            start_date=start_date,
            due_date=due_date,
        )

    @server.tool(
        description=(
            "Update fields of a work package; only the fields you pass are changed, at least one is required. "
            "status: a status name as returned by list_statuses. "
            "assignee: user name or login, or 'me' for the token owner. description: Markdown, replaces the old one. "
            "Dates are YYYY-MM-DD. percent_done: integer 0-100. "
            "An edit conflict is retried once automatically."
        )
    )
    def update_work_package(
        wp_id: int,
        subject: str | None = None,
        description: str | None = None,
        status: str | None = None,
        assignee: str | None = None,
        start_date: str | None = None,
        due_date: str | None = None,
        percent_done: int | None = None,
    ) -> str:
        candidates = {
            "subject": subject,
            "description": description,
            "status": status,
            "assignee": assignee,
            "start_date": start_date,
            "due_date": due_date,
            "percent_done": percent_done,
        }
        changes = {key: value for key, value in candidates.items() if value is not None}
        if not changes:
            raise ToolError(f"Pass at least one field to change: {', '.join(candidates)}.")
        return lazy.call("update_work_package", wp_id, **changes)

    @server.tool(description="Add a comment (Markdown) to a work package.")
    def add_comment(wp_id: int, text: str) -> str:
        return lazy.call("add_comment", wp_id, text)

    @server.tool(description="List the comments of a work package with author and timestamp.")
    def list_comments(wp_id: int) -> str:
        return lazy.call("list_comments", wp_id)

    @server.tool(
        description=(
            "Log spent time on a work package. hours is decimal (1.5 = 1h30m, minimum one minute). "
            "date is YYYY-MM-DD and defaults to today. comment is optional."
        )
    )
    def log_time(wp_id: int, hours: float, date: str | None = None, comment: str | None = None) -> str:
        return lazy.call("log_time", wp_id, hours, date=date, comment=comment)

    return server


def _build_client() -> OpenProjectClient:
    config = load_config()
    return OpenProjectClient(config.url, config.token)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    build_server(_build_client).run("stdio")

