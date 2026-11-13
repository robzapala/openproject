import json

import pytest

from opm.cli import main
from opm.client import OpenProjectError
from opm.config import ConfigError


WP = {
    "id": 12,
    "subject": "Naprawić drukarkę",
    "project": "Biuro",
    "type": "Zadanie",
    "status": "W realizacji",
    "assignee": "Jan Kowalski",
    "startDate": "2026-10-01",
    "dueDate": "2026-10-31",
    "percentageDone": 40,
    "lockVersion": 3,
    "url": "https://op.example/work_packages/12",
}


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
        return [{"id": 1, "name": "Nowe", "isClosed": False}, {"id": 2, "name": "Zamknięte", "isClosed": True}]

    def list_types(self):
        self._record("list_types")
        return [{"id": 1, "name": "Zadanie"}]

    def list_users(self):
        self._record("list_users")
        return [{"id": 5, "name": "Jan Kowalski", "login": "jan", "email": None}]

    def search_work_packages(self, **kwargs):
        self._record("search_work_packages", **kwargs)
        return [WP, {**WP, "id": 7, "subject": "x" * 80, "assignee": None, "dueDate": None}]

    def get_work_package(self, wp_id):
        self._record("get_work_package", wp_id)
        return {**WP, "description": "Opis zadania"}

    def create_work_package(self, project, subject, **kwargs):
        self._record("create_work_package", project, subject, **kwargs)
        return {**WP, "id": 123, "subject": subject, "url": "https://op.example/work_packages/123"}

    def update_work_package(self, wp_id, **changes):
        self._record("update_work_package", wp_id, **changes)
        return {**WP, "id": wp_id}

    def add_comment(self, wp_id, text):
        self._record("add_comment", wp_id, text)
        return {"id": 9, "comment": text, "user": "Jan Kowalski", "createdAt": "2026-10-26T10:00:00Z"}

    def log_time(self, wp_id, hours, date=None, comment=None):
        self._record("log_time", wp_id, hours, date=date, comment=comment)
        return {"id": 3, "hours": "PT1H30M", "spentOn": "2026-10-26", "comment": comment or ""}


@pytest.fixture
def client():
    return FakeClient()


def last_call(client):
    return client.calls[-1]


def test_wp_list_table_output(client, capsys):
    assert main(["wp", "list"], client=client) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["ID", "STATUS", "TYTUŁ", "PRZYPISANY", "TERMIN"]
    assert lines[1].split("  ")[0].strip() == "12"
    assert "Naprawić drukarkę" in lines[1]
    assert "2026-10-31" in lines[1]
    assert lines[2].rstrip().endswith("-")
    assert "-" in lines[2].split()
    assert "x" * 80 not in lines[2]
    assert "…" in lines[2]
    title_column = lines[0].index("TYTUŁ")
    assert lines[1].index("Naprawić") == title_column


def test_wp_list_passes_filters(client):
    main(["wp", "list", "-p", "biuro", "--mine", "--status", "Nowe", "--open", "-q", "drukarka"], client=client)

    assert last_call(client) == (
        "search_work_packages",
        (),
        {"project": "biuro", "assignee_me": True, "status": "Nowe", "open_only": True, "query": "drukarka"},
    )


def test_wp_list_defaults(client):
    main(["wp", "list"], client=client)

    assert last_call(client)[2] == {
        "project": None,
        "assignee_me": False,
        "status": None,
        "open_only": False,
        "query": None,
    }


def test_wp_show_prints_fields_description_and_url(client, capsys):
    assert main(["wp", "show", "12"], client=client) == 0

    out = capsys.readouterr().out
    assert last_call(client) == ("get_work_package", (12,), {})
    assert "#12" in out
    assert "Naprawić drukarkę" in out
    assert "W realizacji" in out
    assert "Jan Kowalski" in out
    assert "Opis zadania" in out
    assert "https://op.example/work_packages/12" in out


def test_wp_create_passes_arguments(client, capsys):
    code = main(
        [
            "wp", "create", "-p", "biuro", "Nowe zadanie",
            "--type", "Zadanie", "--assignee", "Jan", "--due", "2026-11-01",
            "--start", "2026-10-27", "--description", "Szczegóły",
        ],
        client=client,
    )

    assert code == 0
    assert last_call(client) == (
        "create_work_package",
        ("biuro", "Nowe zadanie"),
        {
            "type": "Zadanie",
            "assignee": "Jan",
            "description": "Szczegóły",
            "start_date": "2026-10-27",
            "due_date": "2026-11-01",
        },
    )
    out = capsys.readouterr().out
    assert "Utworzono #123" in out
    assert "https://op.example/work_packages/123" in out


def test_wp_set_passes_changes(client, capsys):
    code = main(["wp", "set", "12", "--status", "Zamknięte", "--done", "100"], client=client)

    assert code == 0
    assert last_call(client) == ("update_work_package", (12,), {"status": "Zamknięte", "percent_done": 100})
    assert "Zaktualizowano #12" in capsys.readouterr().out


def test_wp_set_maps_all_options(client):
    main(
        [
            "wp", "set", "12", "--assignee", "Jan", "--due", "2026-11-01", "--start", "2026-10-27",
            "--subject", "Nowy tytuł", "--description", "Nowy opis",
        ],
        client=client,
    )

    assert last_call(client)[2] == {
        "assignee": "Jan",
        "due_date": "2026-11-01",
        "start_date": "2026-10-27",
        "subject": "Nowy tytuł",
        "description": "Nowy opis",
    }


def test_wp_set_without_changes_is_usage_error(client, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["wp", "set", "12"], client=client)

    assert exc.value.code == 2
    assert client.calls == []
    assert "--status" in capsys.readouterr().err


def test_wp_set_rejects_done_out_of_range(client):
    with pytest.raises(SystemExit) as exc:
        main(["wp", "set", "12", "--done", "150"], client=client)

    assert exc.value.code == 2
    assert client.calls == []


def test_comment_adds_comment(client, capsys):
    assert main(["comment", "12", "Gotowe"], client=client) == 0

    assert last_call(client) == ("add_comment", (12, "Gotowe"), {})
    assert "Dodano komentarz do #12" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text, hours",
    [
        ("1.5h", 1.5),
        ("1,5h", 1.5),
        ("90m", 1.5),
        ("1h30m", 1.5),
        ("1h 30m", 1.5),
        ("2", 2.0),
        ("0.25", 0.25),
        ("2h", 2.0),
    ],
)
def test_time_parses_units(client, text, hours):
    assert main(["time", "12", text], client=client) == 0

    assert last_call(client) == ("log_time", (12, hours), {"date": None, "comment": None})


def test_time_passes_date_and_comment(client, capsys):
    main(["time", "12", "1h", "--date", "2026-10-25", "--comment", "Spotkanie"], client=client)

    assert last_call(client) == ("log_time", (12, 1.0), {"date": "2026-10-25", "comment": "Spotkanie"})
    assert "Zapisano czas" in capsys.readouterr().out


@pytest.mark.parametrize("text", ["abc", "0", "0h", "-1h", "1x", "", "h"])
def test_time_rejects_invalid_duration(client, text, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["time", "12", text], client=client)

    assert exc.value.code == 2
    assert client.calls == []
    assert "GODZINY" in capsys.readouterr().err


def test_json_flag_prints_json(client, capsys):
    assert main(["--json", "wp", "show", "12"], client=client) == 0

    assert json.loads(capsys.readouterr().out) == {**WP, "description": "Opis zadania"}


def test_json_flag_after_subcommand(client, capsys):
    assert main(["wp", "list", "--json"], client=client) == 0

    assert [wp["id"] for wp in json.loads(capsys.readouterr().out)] == [12, 7]


def test_json_keeps_polish_characters_and_indent(client, capsys):
    main(["--json", "statuses"], client=client)

    out = capsys.readouterr().out
    assert "Zamknięte" in out
    assert out.startswith("[\n  {")


@pytest.mark.parametrize(
    "argv, method",
    [
        (["projects"], "list_projects"),
        (["statuses"], "list_statuses"),
        (["types"], "list_types"),
        (["users"], "list_users"),
        (["whoami"], "whoami"),
    ],
)
def test_reference_commands_print_json(client, capsys, argv, method):
    assert main(["--json", *argv], client=client) == 0

    assert last_call(client)[0] == method
    assert json.loads(capsys.readouterr().out)


def test_reference_commands_print_tables(client, capsys):
    main(["projects"], client=client)
    main(["statuses"], client=client)
    main(["whoami"], client=client)

    out = capsys.readouterr().out
    assert "biuro" in out
    assert "Zamknięte" in out
    assert "Jan Kowalski" in out


def test_create_and_set_with_json(client, capsys):
    main(["--json", "wp", "create", "-p", "biuro", "Tytuł"], client=client)
    main(["--json", "comment", "12", "x"], client=client)
    main(["--json", "time", "12", "1h"], client=client)
    main(["--json", "wp", "set", "12", "--done", "10"], client=client)

    decoder = json.JSONDecoder()
    out = capsys.readouterr().out
    index = 0
    parsed = []
    while index < len(out):
        value, index = decoder.raw_decode(out, index)
        parsed.append(value)
        while index < len(out) and out[index].isspace():
            index += 1
    assert len(parsed) == 4


def test_api_error_exit_code_1(client, capsys):
    client.error = OpenProjectError("Not found (404): nope", status=404)

    assert main(["wp", "show", "99"], client=client) == 1

    captured = capsys.readouterr()
    assert captured.err.strip() == "Błąd: Not found (404): nope"
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_config_error_exit_code_2(monkeypatch, capsys):
    def fail():
        raise ConfigError("Missing configuration: OPM_URL, OPM_TOKEN.")

    monkeypatch.setattr("opm.cli.load_config", fail)

    assert main(["whoami"]) == 2

    captured = capsys.readouterr()
    assert "Missing configuration" in captured.err
    assert "Traceback" not in captured.err


def test_without_client_builds_one_from_config(monkeypatch, client):
    built = {}

    class Config:
        url = "https://op.example"
        token = "secret"

    def factory(url, token):
        built["args"] = (url, token)
        return client

    monkeypatch.setattr("opm.cli.load_config", lambda: Config())
    monkeypatch.setattr("opm.cli.OpenProjectClient", factory)

    assert main(["whoami"]) == 0
    assert built["args"] == ("https://op.example", "secret")


def test_injected_client_skips_config(client, monkeypatch):
    def boom():
        raise AssertionError("config must not be loaded")

    monkeypatch.setattr("opm.cli.load_config", boom)

    assert main(["whoami"], client=client) == 0


def test_help_is_polish(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "OpenProject" in out
    assert "pokaż pomoc" in out
