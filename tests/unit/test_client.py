"""The client against a mocked HTTP server (responses)."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
import requests
import responses

from databucket import Change, Databucket, DatabucketError, Project, Rule, Rules

URL = "http://x"


def test_needs_credentials_and_a_url() -> None:
    with pytest.raises(ValueError, match="url"):
        Databucket("", token="x")
    with pytest.raises(ValueError, match="credentials"):
        Databucket(URL)
    with pytest.raises(ValueError, match="both"):
        Databucket(URL, username="a")


@responses.activate
def test_signs_in_once_for_parallel_calls_sends_api_version_2_and_renews_an_expired_token() -> None:
    sign_ins = 0

    def sign_in(request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        nonlocal sign_ins
        sign_ins += 1
        return 200, {}, json.dumps({"token": f"t{sign_ins}", "project": {"id": 7, "name": "P"}})

    def data(request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        assert request.headers["Databucket-Api-Version"] == "2"
        if request.headers["Authorization"] == "Bearer t1" and "renew" in str(request.url):
            return 401, {}, json.dumps({"message": "expired"})
        return 200, {}, json.dumps({"total": 5})

    responses.add_callback(responses.POST, f"{URL}/api/public/signin", callback=sign_in)
    responses.add_callback(responses.POST, f"{URL}/api/bucket/b/get", callback=data)

    db = Databucket(URL + "/", username="u", password="p")
    bucket = db.bucket("b")
    with ThreadPoolExecutor(max_workers=3) as pool:
        counts = list(pool.map(lambda _: bucket.count(Rules.ALL), range(3)))
    assert counts == [5, 5, 5]
    assert sign_ins == 1
    assert db.project() == Project(7, "P")
    assert responses.calls[1].request.url == f"{URL}/api/bucket/b/get?limit=0"

    # an expired token: signs in again once
    assert db._call("POST", "/api/bucket/b/get?limit=0&renew", {})["total"] == 5
    assert sign_ins == 2
    assert db.token() == "t2"


@responses.activate
def test_errors_carry_the_status_and_the_server_message() -> None:
    responses.add(responses.POST, f"{URL}/api/bucket/nope/get", json={"message": "Bucket not found"}, status=404)
    with pytest.raises(DatabucketError) as error:
        Databucket(URL, token="t").bucket("nope").count(Rules.ALL)
    assert error.value.status == 404
    assert str(error.value) == "404: Bucket not found (POST /api/bucket/nope/get)"


@responses.activate
def test_a_connection_failure_is_status_0() -> None:
    responses.add(responses.POST, f"{URL}/api/bucket/b/get", body=requests.ConnectionError("connection refused"))
    with pytest.raises(DatabucketError) as error:
        Databucket(URL, token="t").bucket("b").count(Rules.ALL)
    assert error.value.status == 0
    assert "connection refused" in str(error.value)


@responses.activate
def test_several_projects_without_a_choice_fail_with_their_names() -> None:
    responses.add(
        responses.POST, f"{URL}/api/public/signin", json={"projects": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]}
    )
    with pytest.raises(DatabucketError, match=r"several projects.*A, B"):
        Databucket(URL, username="u", password="p").token()


@responses.activate
def test_project_by_name_signs_in_to_its_id() -> None:
    bodies: list[dict[str, object]] = []

    def sign_in(request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        body = json.loads(request.body or "{}")
        bodies.append(body)
        if "projectId" not in body:
            return 200, {}, json.dumps({"projects": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]})
        return 200, {}, json.dumps({"token": "t", "project": {"id": body["projectId"], "name": "B"}})

    responses.add_callback(responses.POST, f"{URL}/api/public/signin", callback=sign_in)
    db = Databucket(URL, username="u", password="p", project="B")
    assert db.project() == Project(2, "B")
    assert bodies[1]["projectId"] == 2


def test_update_and_delete_need_rules() -> None:
    bucket = Databucket(URL, token="t").bucket("b")
    with pytest.raises(ValueError):
        bucket.update(Rules.ALL, Change().set("$.a", 1))
    with pytest.raises(ValueError):
        bucket.delete(Rules.ALL)


@responses.activate
def test_rows_are_mapped_and_dates_parsed() -> None:
    responses.add(
        responses.GET,
        f"{URL}/api/bucket/b/5",
        json={
            "id": 5,
            "tagId": 2,
            "reserved": True,
            "owner": "robot",
            "properties": {"name": "x"},
            "createdBy": "robot",
            "createdAt": "2026-11-10T14:11:14.404Z",
            "modifiedBy": "robot",
            "modifiedAt": "2026-11-10T14:11:14.4Z",
        },
    )
    row = Databucket(URL, token="t").bucket("b").get(5)
    assert row is not None
    assert (row.id, row.tag_id, row.reserved, row.owner, row.properties) == (5, 2, True, "robot", {"name": "x"})
    assert row.created_at == datetime(2026, 11, 10, 14, 11, 14, 404000, tzinfo=timezone.utc)
    assert row.modified_at == datetime(2026, 11, 10, 14, 11, 14, 400000, tzinfo=timezone.utc)


@responses.activate
def test_a_missing_row_is_none_and_counts_come_from_the_message() -> None:
    responses.add(responses.GET, f"{URL}/api/bucket/b/9", json=[])
    responses.add(responses.PUT, f"{URL}/api/bucket/b/1,2", json={"message": "Modified 2 data row(s)"})
    bucket = Databucket(URL, token="t").bucket("b")
    assert bucket.get(9) is None
    assert bucket.release(1, 2) == 2
    assert json.loads(responses.calls[1].request.body or "{}") == {"reserved": False}


@responses.activate
def test_a_datetime_in_a_change_is_sent_as_iso_text() -> None:
    responses.add(responses.PUT, f"{URL}/api/bucket/b/1", json={"message": "Modified 1 data row(s)"})
    when = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    Databucket(URL, token="t").bucket("b").update(Change().set("$.paidAt", when), 1)
    sent = json.loads(responses.calls[0].request.body or "{}")
    assert sent == {"propertiesToSet": {"$.paidAt": "2026-01-02T03:04:05.000Z"}}


@responses.activate
def test_history_search_sends_the_entry_rules_as_history_logic() -> None:
    responses.add(responses.POST, f"{URL}/api/bucket/b/history/get", json={"total": 3, "history": []})
    bucket = Databucket(URL, token="t").bucket("b")
    assert bucket.search_history(Rules.where(Rule.id().eq(1))).where(Rule.field("reserved").eq(True)).count() == 3
    request = responses.calls[0].request
    assert "limit=0" in str(request.url)
    assert json.loads(request.body or "{}") == {
        "logic": {"==": [{"var": "id"}, 1]},
        "historyLogic": {"==": [{"var": "reserved"}, True]},
    }
