"""Runs against a real Databucket with the DEMO dataset (docker compose of databucket-server, project "Acme Shop").
Every row it creates carries ``$.clientIt = <run id>`` and is removed at the end.

Settings (environment variables): DATABUCKET_URL (default http://databucket.localhost), DATABUCKET_PROJECT
(default "Acme Shop"), DATABUCKET_BUCKET (default dev-scheduler, a bucket with history).
Users demo-robot (ROBOT) and demo-member (MEMBER), password "test".
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from databucket import (
    Bucket,
    Change,
    Databucket,
    DatabucketError,
    Field,
    HistoryField,
    NewData,
    Rule,
    Rules,
    Sort,
)

URL = os.environ.get("DATABUCKET_URL") or "http://databucket.localhost"
PROJECT = os.environ.get("DATABUCKET_PROJECT") or "Acme Shop"
BUCKET = os.environ.get("DATABUCKET_BUCKET") or "dev-scheduler"
RUN = str(uuid.uuid4())


def client(username: str = "demo-robot", password: str = "test", project: int | str | None = PROJECT) -> Databucket:
    return Databucket(URL, username=username, password=password, project=project)


robot = client()
member = client("demo-member")


def item(name: str, status: str | None, count: int, labels: list[str] | None = None) -> dict[str, Any]:
    """Properties of a test row (None items are left out, so exists() / not_exists() can be checked)."""
    i: dict[str, Any] = {"clientIt": RUN, "name": name, "count": count, "labels": [] if labels is None else labels}
    if status is not None:
        i["status"] = status
    return i


def mine(*more: Rule) -> Rules:
    return Rules.where(Rule.property("$.clientIt").eq(RUN), *more)


def named(name: str, *more: Rule) -> Rules:
    return mine(Rule.property("$.name").eq(name), *more)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def fails(call: Callable[[], object]) -> DatabucketError:
    with pytest.raises(DatabucketError) as error:
        call()
    return error.value


def any_tag_id() -> int:
    # tags of the DEMO dataset are used by the rows of every bucket; take one from the data
    row = robot.bucket("dev-users").find(Rules.where(Rule.tag_id().is_not_null())).first()
    assert row is not None and row.tag_id is not None
    return row.tag_id


@pytest.fixture(scope="module")
def items() -> Iterator[Bucket[dict[str, Any]]]:
    bucket = robot.bucket(BUCKET)
    yield bucket
    bucket.delete(mine())


# ---------------------------------------------------------------------- sign-in


def test_signs_in_to_the_project_by_name() -> None:
    project = robot.project()
    assert project is not None and project.name == PROJECT


def test_signs_in_to_the_project_by_id() -> None:
    project = robot.project()
    assert project is not None
    by_id = client(project=project.id).project()
    assert by_id is not None and by_id.name == PROJECT


def test_several_projects_without_a_choice_fail() -> None:
    assert "several projects" in str(fails(lambda: client(project=None).token()))


def test_a_wrong_password_fails_with_401() -> None:
    assert fails(lambda: client(password="wrong").token()).status == 401


def test_an_unknown_project_fails() -> None:
    fails(lambda: client(project="No such project").token())


def test_an_invalid_token_fails_with_401() -> None:
    wrong = Databucket(URL, token="not-a-token")
    assert fails(lambda: wrong.bucket(BUCKET).count(Rules.ALL)).status == 401


def test_an_expired_token_is_renewed() -> None:
    db = client()
    db.token()
    db._current_token = "expired"
    assert db.bucket(BUCKET).count(Rules.ALL) >= 0
    assert db.token() != "expired"


def test_an_unknown_bucket_is_404() -> None:
    assert fails(lambda: robot.bucket("no-such-bucket").count(Rules.ALL)).status == 404


# ---------------------------------------------------------------------- insert and read


def test_insert_get_and_find(items: Bucket[dict[str, Any]]) -> None:
    row = items.insert(item("insert-get", "new", 1, ["a"]))
    assert row.id > 0
    assert row.properties["name"] == "insert-get"
    assert row.reserved is False
    assert row.created_by == "demo-robot"
    assert isinstance(row.created_at, datetime)

    read = items.get(row.id)
    assert read is not None
    assert read.properties["clientIt"] == RUN
    assert read.properties["labels"] == ["a"]

    assert items.get(999_999_999) is None
    assert len(items.get([row.id, 999_999_999])) == 1

    found = items.find(mine(Rule.property("$.name").eq("insert-get"))).first()
    assert found is not None and found.id == row.id


def test_insert_reserved_with_a_tag(items: Bucket[dict[str, Any]]) -> None:
    tag_id = any_tag_id()
    row = items.insert(NewData(item("reserved-insert", "new", 1)).tag_id(tag_id).reserved(True))
    assert row.reserved is True
    assert row.owner == "demo-robot"
    assert row.tag_id == tag_id


def test_insert_all_and_paging(items: Bucket[dict[str, Any]]) -> None:
    batch = unique("batch")
    items.insert_all(item(batch, "paged", i + 1) for i in range(7))

    rules = named(batch)
    assert items.count(rules) == 7
    assert items.find(rules).count() == 7

    page2 = items.find(rules).sort(Sort.desc("$.count")).limit(3).page(2).fetch()
    assert page2.total == 7
    assert page2.total_pages == 3
    assert [r.properties["count"] for r in page2.rows] == [4, 3, 2]

    assert len(items.find(rules).sort(Sort.desc("$.count")).limit(3).page(3).list()) == 1
    assert items.find(rules).limit(3).page(9).list() == []


# ---------------------------------------------------------------------- rules (API v2)


def test_rules(items: Bucket[dict[str, Any]]) -> None:
    group = unique("rules")
    items.insert(item(group, "active", 10, ["a", "b", "c"]))
    items.insert(item(group, "active", 20))
    no_labels = item(group, None, 30)
    del no_labels["labels"]
    items.insert({**no_labels, "tmp": "x"})

    def count(*more: Rule) -> int:
        return items.count(named(group, *more))

    assert count(Rule.property("$.status").eq("active")) == 2
    assert count(Rule.property("$.count").gt(15), Rule.property("$.count").lt(25)) == 1
    assert count(Rule.property("$.count").between(10, 20)) == 2
    assert count(Rule.property("$.count").in_(10, 30)) == 2
    assert count(Rule.property("$.count").not_in([10, 30])) == 1
    assert count(Rule.property("$.name").like("rules-%")) == 3
    assert count(Rule.property("$.name").matches_ignore_case("^RULES-")) == 3
    assert count(Rule.property("$.status").is_null()) == 1
    assert count(Rule.property("$.status").is_empty()) == 1
    assert count(Rule.property("$.status").is_not_empty()) == 2
    assert count(Rule.property("$.tmp").exists()) == 1
    assert count(Rule.property("$.tmp").not_exists()) == 2
    assert count(Rule.property("$.labels").length().gt(2)) == 1
    assert count(Rule.property("$.count").eq(10) | Rule.property("$.count").eq(30)) == 2
    assert count(~Rule.property("$.count").le(20)) == 1
    assert count(Rule.field(Field.CREATED_BY).eq(Rule.CURRENT_USER)) == 3
    assert count(Rule.owner().is_null()) == 3
    assert count(Rule.field(Field.CREATED_AT).gt(datetime.now(timezone.utc) - timedelta(hours=1))) == 3


def test_rules_in_the_api_format(items: Bucket[dict[str, Any]]) -> None:
    group = unique("format")
    items.insert(item(group, "active", 1))
    items.insert(item(group, "done", 2))
    rules = Rules.from_rules(
        [
            ["$.clientIt", "==", RUN],
            ["$.name", "==", group],
            {"or": [["$.status", "==", "done"], ["$.count", ">", 5]]},
        ]
    )
    assert items.count(rules) == 1


def test_sql_text_rules_are_refused_in_version_2(items: Bucket[dict[str, Any]]) -> None:
    assert fails(lambda: items.count(Rules.from_rules(["$.count > 1"]))).status == 400


def test_an_unknown_field_is_400(items: Bucket[dict[str, Any]]) -> None:
    assert fails(lambda: items.count(Rules.from_rules([["noSuchField", "==", 1]]))).status == 400


# ---------------------------------------------------------------------- reserve


def test_reserve_and_release(items: Bucket[dict[str, Any]]) -> None:
    group = unique("reserve")
    for i in range(5):
        items.insert(item(group, "free", i))
    free = named(group)

    assert items.reserve(free).available() == 5

    one = items.reserve(free).one()
    assert one is not None and one.reserved is True and one.owner == "demo-robot"

    two = items.reserve(free).limit(2).sort(Sort.RANDOM).fetch()
    assert len(two.rows) == 2
    assert two.available == 2

    rest = items.reserve(free).limit(10).fetch()
    assert len(rest.rows) == 2
    assert rest.available == 0
    assert items.reserve(free).one() is None

    assert items.release(one.id) == 1
    released = items.get(one.id)
    assert released is not None and released.reserved is False and released.owner is None
    assert items.reserve(free).available() == 1


def test_parallel_reservations_never_share_a_row(items: Bucket[dict[str, Any]]) -> None:
    group = unique("parallel")
    items.insert_all(item(group, "free", i) for i in range(20))
    free = named(group)

    # separate clients, as parallel test workers would have
    clients = [client().bucket(BUCKET) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: clients[i % 8].reserve(free).one(), range(24)))
    ids = [r.id for r in results if r is not None]
    assert len(set(ids)) == len(ids) == 20
    assert results.count(None) == 4


# ---------------------------------------------------------------------- modify and remove


def test_update_by_ids_and_rules(items: Bucket[dict[str, Any]]) -> None:
    row = items.insert(item("update", "new", 1))
    row2 = items.insert({**item("update", "new", 1), "tmp": "remove me"})

    assert items.update(Change().set("$.status", "used").remove("$.tmp"), row.id, row2.id) == 2
    changed = items.get(row2.id)
    assert changed is not None
    assert changed.properties["status"] == "used"
    assert "tmp" not in changed.properties

    tag_id = any_tag_id()
    assert items.update(named("update"), Change().tag_id(tag_id).set("$.count", 9)) == 2
    updated = items.get(row.id)
    assert updated is not None and updated.tag_id == tag_id and updated.properties["count"] == 9

    items.update(Change().properties(item("update-replaced", "x", 0)), row.id)
    replaced = items.get(row.id)
    assert replaced is not None and replaced.properties["name"] == "update-replaced"


def test_update_and_delete_need_rules(items: Bucket[dict[str, Any]]) -> None:
    with pytest.raises(ValueError):
        items.update(Rules.ALL, Change().set("$.a", 1))
    with pytest.raises(ValueError):
        items.delete(Rules.ALL)


def test_delete_by_ids_and_rules(items: Bucket[dict[str, Any]]) -> None:
    a = items.insert(item("delete", "x", 1))
    b = items.insert(item("delete", "x", 2))
    items.insert(item("delete", "x", 3))
    assert items.delete(a.id) == 1
    assert items.get(a.id) is None
    assert items.delete(a.id) == 0
    assert items.delete(named("delete")) == 2
    assert items.get(b.id) is None


# ---------------------------------------------------------------------- history


def test_history_for_a_member(items: Bucket[dict[str, Any]]) -> None:
    row = items.insert(item("history", "new", 1))
    items.update(Change().set("$.status", "used"), row.id)
    assert items.reserve(mine(Rule.id().eq(row.id))).one() is not None

    as_member = member.bucket(BUCKET)
    history = as_member.history(row.id)
    assert len(history) == 3
    assert history[0].properties_changed is True
    assert history[1].properties_changed is True
    assert history[2].reserved is True
    assert history[2].modified_by == "demo-robot"

    versions = as_member.history_properties(row.id, history[0].id, history[1].id)
    assert versions[history[0].id]["status"] == "new"
    assert versions[history[1].id]["status"] == "used"

    assert as_member.clear_history(row.id) >= 2
    assert len(as_member.history(row.id)) <= 1


def test_history_for_a_robot(items: Bucket[dict[str, Any]]) -> None:
    row = items.insert(item("history-robot", "new", 1))
    items.update(Change().set("$.status", "used"), row.id)
    history = items.history(row.id)
    assert len(history) == 2
    assert history[0].data_id == row.id
    assert isinstance(history[0].modified_at, datetime)
    assert items.clear_history(row.id) == 2
    assert items.history(row.id) == []

    assert fails(lambda: items.clear_history(999_999_999)).status == 404


def test_search_history(items: Bucket[dict[str, Any]]) -> None:
    group = unique("search")
    a = items.insert(item(group, "new", 1))
    b = items.insert(item(group, "new", 2))
    items.update(Change().set("$.status", "used"), a.id)
    assert items.reserve(mine(Rule.id().eq(b.id))).one() is not None
    rows = named(group)

    # 2 inserts + 1 change + 1 reservation
    assert items.search_history(rows).count() == 4
    assert items.search_history(rows).where(Rule.field(HistoryField.RESERVED).eq(True)).count() == 1
    # "a": the insert and the change, both by the robot
    by_robot = items.search_history(rows).where(
        Rule.field(HistoryField.DATA_ID).eq(a.id), Rule.field(HistoryField.MODIFIED_BY).eq(Rule.CURRENT_USER)
    )
    assert by_robot.count() == 2
    assert items.search_history(rows).where(Rule.field(HistoryField.MODIFIED_BY).eq("nobody")).count() == 0

    # rows by their current state: only "a" is used now
    assert items.search_history(named(group, Rule.property("$.status").eq("used"))).count() == 2

    page = items.search_history(rows).sort(Sort.desc(HistoryField.ID)).limit(3).with_properties().fetch()
    assert page.total == 4
    assert page.total_pages == 2
    assert len(page.entries) == 3
    newest = page.entries[0]
    assert newest.data_id == b.id
    assert newest.reserved is True
    changed = next(e for e in page.entries if e.data_id == a.id and e.properties_changed)
    assert changed.properties is not None

    second = items.search_history(rows).sort(Sort.desc(HistoryField.ID)).limit(3).page(2).list()
    assert len(second) == 1
    assert second[0].properties is None

    search = items.search_history(rows).where(Rule.property("$.status").eq("used"))
    assert fails(lambda: search.count()).status == 400
