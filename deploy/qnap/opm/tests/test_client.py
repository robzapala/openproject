import base64
import datetime
import json

import httpx
import pytest
import respx

from opm.client import OpenProjectClient, OpenProjectError, summarize_work_package

BASE = "https://op.test"


@pytest.fixture
def api():
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def client(api):
    return OpenProjectClient(BASE, "tok")


def collection(*elements):
    return httpx.Response(
        200,
        json={"_embedded": {"elements": list(elements)}, "total": len(elements), "count": len(elements)},
    )


def error(status, message, identifier="urn:openproject-org:api:v3:errors:PropertyConstraintViolation"):
    return httpx.Response(
        status, json={"_type": "Error", "errorIdentifier": identifier, "message": message}
    )


def wp(wp_id=42, lock_version=3, **overrides):
    raw = {
        "id": wp_id,
        "subject": "Faktura",
        "lockVersion": lock_version,
        "startDate": "2026-10-01",
        "dueDate": None,
        "percentageDone": 10,
        "description": {"raw": "opis"},
        "_links": {
            "project": {"href": "/api/v3/projects/1", "title": "Demo"},
            "type": {"href": "/api/v3/types/1", "title": "Task"},
            "status": {"href": "/api/v3/statuses/1", "title": "New"},
            "assignee": {"href": None, "title": None},
        },
    }
    raw.update(overrides)
    return raw


STATUSES = [
    {"id": 1, "name": "Nowe", "isClosed": False},
    {"id": 7, "name": "W realizacji", "isClosed": False},
    {"id": 9, "name": "Zamknięte", "isClosed": True},
]


def test_basic_auth_uses_apikey_user(api, client):
    route = api.get("/api/v3/users/me").respond(
        json={"id": 5, "name": "Jan Kowalski", "login": "jan", "email": "jan@example.com"}
    )

    client.whoami()

    expected = "Basic " + base64.b64encode(b"apikey:tok").decode()
    assert route.calls.last.request.headers["Authorization"] == expected
    assert route.calls.last.request.headers["Accept"] == "application/hal+json"


def test_search_builds_filters(api, client):
    api.get("/api/v3/projects/demo").respond(json={"id": 12, "identifier": "demo", "name": "Demo"})
    route = api.get("/api/v3/work_packages").respond(json=collection(wp()).json())

    result = client.search_work_packages(
        project="demo", assignee_me=True, open_only=True, query="faktura", limit=20
    )

    params = route.calls.last.request.url.params
    filters = json.loads(params["filters"])
    assert {"assignee": {"operator": "=", "values": ["me"]}} in filters
    assert {"status": {"operator": "o", "values": []}} in filters
    assert {"search": {"operator": "**", "values": ["faktura"]}} in filters
    assert {"project": {"operator": "=", "values": ["12"]}} in filters
    assert params["pageSize"] == "20"
    assert result[0]["id"] == 42
    assert result[0]["url"] == "https://op.test/work_packages/42"


def test_search_without_options_sends_no_filters(api, client):
    route = api.get("/api/v3/work_packages").respond(json=collection().json())

    assert client.search_work_packages() == []

    assert json.loads(route.calls.last.request.url.params["filters"]) == []


def test_search_by_status_name(api, client):
    api.get("/api/v3/statuses").respond(json=collection(*STATUSES).json())
    route = api.get("/api/v3/work_packages").respond(json=collection().json())

    client.search_work_packages(status="ZAMKNIĘTE")

    filters = json.loads(route.calls.last.request.url.params["filters"])
    assert {"status": {"operator": "=", "values": ["9"]}} in filters


def test_project_falls_back_to_name_lookup(api, client):
    api.get(path__regex=r"/api/v3/projects/.+").respond(404, json={"message": "nope"})
    api.get("/api/v3/projects").respond(
        json=collection({"id": 12, "identifier": "demo", "name": "Demo project"}).json()
    )
    route = api.get("/api/v3/work_packages").respond(json=collection().json())

    client.search_work_packages(project="demo PROJECT")

    filters = json.loads(route.calls.last.request.url.params["filters"])
    assert {"project": {"operator": "=", "values": ["12"]}} in filters


def test_unknown_project_lists_options(api, client):
    api.get("/api/v3/projects/nope").respond(404, json={"message": "nope"})
    api.get("/api/v3/projects").respond(
        json=collection(
            {"id": 1, "identifier": "demo", "name": "Demo"},
            {"id": 2, "identifier": "ops", "name": "Operacje"},
        ).json()
    )

    with pytest.raises(OpenProjectError) as exc:
        client.search_work_packages(project="nope")

    assert "demo" in exc.value.message and "ops" in exc.value.message


def test_update_resolves_status_name_case_insensitive(api, client):
    api.get("/api/v3/statuses").respond(json=collection(*STATUSES).json())
    api.get("/api/v3/work_packages/42").respond(json=wp())
    patch = api.patch("/api/v3/work_packages/42").respond(json=wp(lock_version=4))

    result = client.update_work_package(42, status="w realizacji")

    body = json.loads(patch.calls.last.request.content)
    assert body["_links"]["status"]["href"] == "/api/v3/statuses/7"
    assert body["lockVersion"] == 3
    assert result["lockVersion"] == 4


def test_update_sends_plain_fields(api, client):
    api.get("/api/v3/work_packages/42").respond(json=wp())
    patch = api.patch("/api/v3/work_packages/42").respond(json=wp())

    client.update_work_package(
        42, subject="Nowy", description="tekst", start_date="2026-11-01", due_date="2026-11-05", percent_done=50
    )

    body = json.loads(patch.calls.last.request.content)
    assert body["subject"] == "Nowy"
    assert body["description"] == {"raw": "tekst"}
    assert body["startDate"] == "2026-11-01"
    assert body["dueDate"] == "2026-11-05"
    assert body["percentageDone"] == 50


def test_update_assignee_by_name_login_or_email(api, client):
    api.get("/api/v3/principals").respond(
        json=collection(
            {"id": 5, "name": "Jan Kowalski", "login": "jan", "email": "jan@example.com"},
            {"id": 6, "name": "Anna Nowak", "login": "anna", "email": "anna@example.com"},
        ).json()
    )
    api.get("/api/v3/work_packages/42").respond(json=wp())
    patch = api.patch("/api/v3/work_packages/42").respond(json=wp())

    client.update_work_package(42, assignee="ANNA@example.com")

    body = json.loads(patch.calls.last.request.content)
    assert body["_links"]["assignee"]["href"] == "/api/v3/users/6"


def test_ambiguous_assignee_lists_candidates(api, client):
    api.get("/api/v3/principals").respond(
        json=collection(
            {"id": 5, "name": "Jan Kowalski", "login": "jan1"},
            {"id": 6, "name": "jan kowalski", "login": "jan2"},
        ).json()
    )

    with pytest.raises(OpenProjectError) as exc:
        client.update_work_package(42, assignee="Jan Kowalski")

    assert "jan1" in exc.value.message and "jan2" in exc.value.message


def test_numeric_string_is_treated_as_id(api, client):
    api.get("/api/v3/work_packages/42").respond(json=wp())
    patch = api.patch("/api/v3/work_packages/42").respond(json=wp())

    client.update_work_package(42, status="7")

    body = json.loads(patch.calls.last.request.content)
    assert body["_links"]["status"]["href"] == "/api/v3/statuses/7"


def test_unknown_status_lists_options(api, client):
    api.get("/api/v3/statuses").respond(json=collection(*STATUSES).json())

    with pytest.raises(OpenProjectError) as exc:
        client.update_work_package(42, status="nieistniejący")

    for name in ("Nowe", "W realizacji", "Zamknięte"):
        assert name in exc.value.message


def test_unknown_update_key_is_rejected(client):
    with pytest.raises(OpenProjectError):
        client.update_work_package(42, colour="red")


def test_update_retries_once_on_409(api, client):
    get = api.get("/api/v3/work_packages/42")
    get.side_effect = [httpx.Response(200, json=wp(lock_version=3)), httpx.Response(200, json=wp(lock_version=4))]
    patch = api.patch("/api/v3/work_packages/42")
    patch.side_effect = [
        error(409, "Conflict", "urn:openproject-org:api:v3:errors:UpdateConflict"),
        httpx.Response(200, json=wp(lock_version=5, subject="Nowy")),
    ]

    result = client.update_work_package(42, subject="Nowy")

    bodies = [json.loads(call.request.content) for call in patch.calls]
    assert [b["lockVersion"] for b in bodies] == [3, 4]
    assert result["subject"] == "Nowy"


def test_update_gives_up_after_second_409(api, client):
    get = api.get("/api/v3/work_packages/42")
    get.side_effect = [httpx.Response(200, json=wp(lock_version=3)), httpx.Response(200, json=wp(lock_version=4))]
    patch = api.patch("/api/v3/work_packages/42")
    patch.side_effect = [
        error(409, "Conflict", "urn:openproject-org:api:v3:errors:UpdateConflict"),
        error(409, "Conflict", "urn:openproject-org:api:v3:errors:UpdateConflict"),
        httpx.Response(200, json=wp()),
    ]

    with pytest.raises(OpenProjectError) as exc:
        client.update_work_package(42, subject="Nowy")

    assert exc.value.status == 409
    assert patch.call_count == 2


def test_create_work_package(api, client):
    api.get("/api/v3/projects/demo").respond(json={"id": 12, "identifier": "demo", "name": "Demo"})
    api.get("/api/v3/types").respond(json=collection({"id": 1, "name": "Task"}, {"id": 2, "name": "Bug"}).json())
    api.get("/api/v3/principals").respond(json=collection({"id": 5, "name": "Jan Kowalski", "login": "jan"}).json())
    post = api.post("/api/v3/projects/12/work_packages").respond(201, json=wp(wp_id=99))

    result = client.create_work_package(
        "demo",
        "Faktura",
        type="bug",
        assignee="Jan Kowalski",
        description="opis",
        start_date="2026-10-01",
        due_date="2026-10-05",
    )

    body = json.loads(post.calls.last.request.content)
    assert body["subject"] == "Faktura"
    assert body["description"] == {"raw": "opis"}
    assert body["startDate"] == "2026-10-01"
    assert body["dueDate"] == "2026-10-05"
    assert body["_links"]["type"]["href"] == "/api/v3/types/2"
    assert body["_links"]["assignee"]["href"] == "/api/v3/users/5"
    assert result["id"] == 99


def test_create_minimal_sends_only_subject(api, client):
    api.get("/api/v3/projects/demo").respond(json={"id": 12, "identifier": "demo", "name": "Demo"})
    post = api.post("/api/v3/projects/12/work_packages").respond(201, json=wp())

    client.create_work_package("demo", "Faktura")

    assert json.loads(post.calls.last.request.content) == {"subject": "Faktura"}


def test_get_work_package_includes_description(api, client):
    api.get("/api/v3/work_packages/42").respond(json=wp())

    result = client.get_work_package(42)

    assert result["description"] == "opis"
    assert result["project"] == "Demo"
    assert result["assignee"] is None


def test_add_comment(api, client):
    post = api.post("/api/v3/work_packages/42/activities").respond(
        201,
        json={
            "id": 77,
            "comment": {"raw": "Gotowe"},
            "createdAt": "2026-10-26T10:00:00Z",
            "_links": {"user": {"title": "Jan Kowalski"}},
        },
    )

    result = client.add_comment(42, "Gotowe")

    assert json.loads(post.calls.last.request.content) == {"comment": {"raw": "Gotowe"}}
    assert result == {
        "id": 77,
        "comment": "Gotowe",
        "user": "Jan Kowalski",
        "createdAt": "2026-10-26T10:00:00Z",
    }


def test_list_comments_skips_activities_without_comment(api, client):
    api.get("/api/v3/work_packages/42/activities").respond(
        json=collection(
            {"id": 1, "comment": {"raw": ""}, "createdAt": "t1", "_links": {"user": {"title": "A"}}},
            {"id": 2, "comment": {"raw": "Hej"}, "createdAt": "t2", "_links": {"user": {"title": "B"}}},
        ).json()
    )

    assert client.list_comments(42) == [{"id": 2, "comment": "Hej", "user": "B", "createdAt": "t2"}]


@pytest.mark.parametrize(
    ("hours", "expected"),
    [(1.5, "PT1H30M"), (2, "PT2H"), (0.25, "PT15M"), (0.99999, "PT1H")],
)
def test_log_time_uses_iso_duration_and_entity_link(api, client, hours, expected):
    post = api.post("/api/v3/time_entries").respond(
        201, json={"id": 3, "hours": expected, "spentOn": "2026-10-26", "comment": {"raw": "praca"}}
    )

    result = client.log_time(42, hours, date="2026-10-26", comment="praca")

    body = json.loads(post.calls.last.request.content)
    assert body["hours"] == expected
    assert body["spentOn"] == "2026-10-26"
    assert body["comment"] == {"raw": "praca"}
    assert body["_links"]["entity"]["href"] == "/api/v3/work_packages/42"
    assert result["id"] == 3


def test_log_time_defaults_to_today(api, client):
    post = api.post("/api/v3/time_entries").respond(201, json={"id": 3, "hours": "PT1H", "spentOn": "x"})

    client.log_time(42, 1)

    assert json.loads(post.calls.last.request.content)["spentOn"] == datetime.date.today().isoformat()


def test_log_time_rejects_non_positive_hours(client):
    with pytest.raises(OpenProjectError):
        client.log_time(42, 0)


def test_lists(api, client):
    api.get("/api/v3/statuses").respond(json=collection(*STATUSES).json())
    api.get("/api/v3/types").respond(json=collection({"id": 1, "name": "Task"}).json())
    api.get("/api/v3/projects").respond(
        json=collection({"id": 1, "identifier": "demo", "name": "Demo", "extra": "x"}).json()
    )
    users = api.get("/api/v3/principals").respond(
        json=collection({"id": 5, "name": "Jan", "login": "jan", "email": "j@x"}, {"id": 6, "name": "Ola"}).json()
    )

    assert client.list_statuses()[1] == {"id": 7, "name": "W realizacji", "isClosed": False}
    assert client.list_types() == [{"id": 1, "name": "Task"}]
    assert client.list_projects() == [{"id": 1, "identifier": "demo", "name": "Demo"}]
    assert client.list_users()[1] == {"id": 6, "name": "Ola", "login": None, "email": None}
    assert json.loads(users.calls.last.request.url.params["filters"]) == [
        {"type": {"operator": "=", "values": ["User"]}}
    ]


def test_lists_follow_pagination(api, client):
    route = api.get("/api/v3/types")
    route.side_effect = [
        httpx.Response(
            200,
            json={"_embedded": {"elements": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}, "total": 3},
        ),
        httpx.Response(200, json={"_embedded": {"elements": [{"id": 3, "name": "C"}]}, "total": 3}),
    ]
    paged = OpenProjectClient(BASE, "tok", page_size=2)

    assert [t["name"] for t in paged.list_types()] == ["A", "B", "C"]
    assert route.calls[1].request.url.params["offset"] == "2"


def test_name_lists_are_cached_per_instance(api, client):
    route = api.get("/api/v3/statuses").respond(json=collection(*STATUSES).json())
    api.get("/api/v3/work_packages/42").respond(json=wp())
    api.patch("/api/v3/work_packages/42").respond(json=wp())

    client.update_work_package(42, status="Nowe")
    client.update_work_package(42, status="Zamknięte")

    assert route.call_count == 1


def test_401_message(api, client):
    api.get("/api/v3/users/me").respond(401, json={"message": "You need to be authenticated"})

    with pytest.raises(OpenProjectError) as exc:
        client.whoami()

    assert exc.value.status == 401
    assert "OPM_TOKEN" in exc.value.message
    assert "API tokens" in exc.value.message


def test_403_and_404_messages(api, client):
    api.get("/api/v3/work_packages/1").respond(403, json={"message": "no access"})
    api.get("/api/v3/work_packages/2").respond(404, json={"message": "not found"})

    with pytest.raises(OpenProjectError) as forbidden:
        client.get_work_package(1)
    with pytest.raises(OpenProjectError) as missing:
        client.get_work_package(2)

    assert forbidden.value.status == 403
    assert missing.value.status == 404
    assert "not found" in missing.value.message


def test_422_shows_api_message(api, client):
    api.get("/api/v3/work_packages/42").respond(json=wp())
    api.patch("/api/v3/work_packages/42").respond(422, json=error(422, "Subject can't be blank.").json())

    with pytest.raises(OpenProjectError) as exc:
        client.update_work_package(42, subject="")

    assert exc.value.status == 422
    assert "Subject can't be blank." in exc.value.message


def test_422_with_multiple_errors_lists_each(api, client):
    api.get("/api/v3/work_packages/42").respond(json=wp())
    api.patch("/api/v3/work_packages/42").respond(
        422,
        json={
            "_type": "Error",
            "message": "Multiple field constraints have been violated.",
            "_embedded": {"errors": [{"message": "Subject can't be blank."}, {"message": "Due date is invalid."}]},
        },
    )

    with pytest.raises(OpenProjectError) as exc:
        client.update_work_package(42, subject="")

    assert "Subject can't be blank." in exc.value.message
    assert "Due date is invalid." in exc.value.message


def test_network_error_becomes_opm_error(api, client):
    api.get("/api/v3/users/me").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(OpenProjectError) as exc:
        client.whoami()

    assert exc.value.status is None
    assert BASE in exc.value.message


def test_non_json_error_body_is_reported(api, client):
    api.get("/api/v3/users/me").respond(502, text="Bad gateway")

    with pytest.raises(OpenProjectError) as exc:
        client.whoami()

    assert exc.value.status == 502
    assert "Bad gateway" in exc.value.message


def test_injected_transport_is_used():
    def handler(request):
        return httpx.Response(200, json={"id": 1, "name": "Jan", "login": "jan"})

    client = OpenProjectClient(BASE, "tok", transport=httpx.MockTransport(handler))

    assert client.whoami()["id"] == 1


def test_summarize_work_package():
    summary = summarize_work_package(wp(), base_url=BASE)

    assert summary == {
        "id": 42,
        "subject": "Faktura",
        "project": "Demo",
        "type": "Task",
        "status": "New",
        "assignee": None,
        "startDate": "2026-10-01",
        "dueDate": None,
        "percentageDone": 10,
        "lockVersion": 3,
        "url": "https://op.test/work_packages/42",
    }


def test_html_200_response_is_reported(api, client):
    api.get("/api/v3/users/me").respond(200, html="<html>Login</html>")

    with pytest.raises(OpenProjectError) as exc:
        client.whoami()

    assert "non-JSON" in exc.value.message
    assert "OPM_URL" in exc.value.message


@pytest.mark.parametrize("body", [b"", b"<html>Moved</html>"])
def test_redirect_is_not_followed_and_names_location(api, client, body):
    api.post("/api/v3/time_entries").respond(
        301, headers={"Location": "https://op.test/api/v3/time_entries"}, content=body
    )

    with pytest.raises(OpenProjectError) as exc:
        client.log_time(42, 1)

    assert exc.value.status == 301
    assert "https://op.test/api/v3/time_entries" in exc.value.message
    assert "OPM_URL" in exc.value.message


def test_http_to_https_redirect_message():
    def handler(request):
        return httpx.Response(301, headers={"Location": "https://op.test/api/v3/users/me"})

    client = OpenProjectClient("http://op.test", "tok", transport=httpx.MockTransport(handler))

    with pytest.raises(OpenProjectError) as exc:
        client.whoami()

    assert "https://op.test" in exc.value.message


def test_payload_missing_expected_keys_is_reported(api, client):
    api.get("/api/v3/users/me").respond(json={"hello": "world"})
    api.get("/api/v3/work_packages").respond(json={"hello": "world"})
    api.get("/api/v3/work_packages/42").respond(json={"hello": "world"})

    for call in (client.whoami, client.search_work_packages, lambda: client.update_work_package(42, subject="x")):
        with pytest.raises(OpenProjectError) as exc:
            call()
        assert "Unexpected response" in exc.value.message
