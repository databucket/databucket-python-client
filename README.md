# databucket-python-client

[![PyPI](https://img.shields.io/pypi/v/databucket-client)](https://pypi.org/project/databucket-client/)

Python client for [Databucket](https://github.com/databucket/databucket-server): find, reserve, change and remove test
data from your automated tests (pytest, Robot Framework libraries, Behave, scripts).

- Python 3.10+, one dependency (`requests`), type hints included
- API version 2 of Databucket (3.13.0 or newer; history search and history for ROBOT accounts: 3.14.0)
- Sign-in with a password or with a token of your identity provider (SSO robot accounts, Databucket 3.10.0+);
  the token is renewed when it expires
- Parallel tests never reserve the same row; one client can be shared by threads

```
pip install databucket-client
```

The same features and version numbers as the [Java client](https://github.com/databucket/databucket-java-client) and
the [JavaScript client](https://github.com/databucket/databucket-js-client).

## Quick start

```python
import os
from databucket import Change, Databucket, Rule, Rules

databucket = Databucket(
    "https://databucket.example.com",
    username="tests-robot",
    password=os.environ["DATABUCKET_PASSWORD"],
    project="Acme Shop",  # by name or id; needed when the user has several projects
)

users = databucket.bucket("dev-users")

# reserve one free active user for this test
user = users.reserve(
    Rules.where(
        Rule.property("$.account.status").eq("active"),
        Rule.property("$.address.country").in_("GB", "PL"),
    )
).one()
assert user, "No free active user"

# ... the test ...

users.update(Change().set("$.account.status", "suspended"), user.id)
users.release(user.id)
```

Rows are `DataRow` objects: `id`, `tag_id`, `reserved`, `owner`, `properties` (a dict by default), `created_by`,
`created_at`, `modified_by`, `modified_at` (`datetime`). For typed properties, e.g. a `TypedDict`:
`users: Bucket[User] = databucket.bucket("dev-users")`.

## pytest

A fixture that gives each test its own user and releases it afterwards, also when the test fails:

```python
# conftest.py
import os
import pytest
from databucket import Databucket, Rule, Rules

databucket = Databucket(
    os.environ["DATABUCKET_URL"],
    username="tests-robot",
    password=os.environ["DATABUCKET_PASSWORD"],
    project="Acme Shop",
)
users = databucket.bucket("dev-users")


@pytest.fixture
def user():
    row = users.reserve(Rules.where(Rule.property("$.account.status").eq("active"))).one()
    if row is None:
        pytest.fail("No free active user in dev-users")
    yield row
    users.release(row.id)


# test_login.py
def test_signs_in(page, user):
    page.goto("/login")
    page.get_by_label("Email").fill(user.properties["email"])
    # ...
```

Works with `pytest-xdist` too: parallel workers never get the same row.

## Rules

Rules are written in code and sent as JsonLogic, so values are never mistaken for fields or properties.

```python
Rule.property("$.address.city").eq("Paris")         # also: ne, gt, ge, lt, le
Rule.property("$.age").between(18, 65)
Rule.tag_id().in_(1, 2)                              # or in_([1, 2]); also: not_in
Rule.property("$.email").like("%@example.com")       # also: not_like, matches, matches_ignore_case, not_matches
Rule.owner().is_null()                               # also: is_not_null
Rule.property("$.phone").is_empty()                  # None, missing or ""; also: is_not_empty
Rule.property("$.tmp").exists()                      # also: not_exists
Rule.property("$.orders").length().gt(2)             # items of an array
Rule.field(Field.CREATED_BY).eq(Rule.CURRENT_USER)   # the signed-in user
Rule.or_(rule1, rule2), Rule.and_(...), Rule.not_(rule)
rule1 | rule2, rule1 & rule2, ~rule                  # the same with operators

Rules.where(rule1, rule2)    # all must match; also Rules.where([rule1, rule2])
Rules.ALL                    # every row (not accepted for update / delete)
Rules.from_rules(list)       # the API "rules" format, e.g. copied from the "API request" tab of the rich filter
Rules.from_logic(dict)       # JsonLogic
```

Fields: `id`, `tagId`, `owner`, `reserved`, `createdBy`, `createdAt`, `modifiedBy`, `modifiedAt` (`Field`).
Dates can be given as `datetime`; they are sent as ISO text in UTC (a `datetime` without a time zone is local time).

## Operations

| Call | API |
|---|---|
| `insert(properties)`, `insert(NewData(p).tag_id(3).reserved(True))` | `POST /api/bucket/{bucket}` |
| `insert_all([p1, p2, NewData(p3).tag_id(3)])` | `POST /api/bucket/{bucket}/multi` |
| `get(id)` (`None` when missing), `get([id1, id2])` | `GET /api/bucket/{bucket}/{ids}` |
| `find(rules).sort(Sort.desc("$.name")).limit(20).page(2).fetch()` / `.list()` / `.first()` / `.count()`, `count(rules)` | `POST /api/bucket/{bucket}/get` |
| `reserve(rules).one()`, `.limit(3).sort(Sort.RANDOM).fetch()`, `.available()`, `.for_user("john")` (ADMIN) | `POST /api/bucket/{bucket}/reserve` |
| `update(change, *ids)`, `update(rules, change)`, `release(*ids)` | `PUT /api/bucket/{bucket}[/{ids}]` |
| `delete(*ids)`, `delete(rules)` | `DELETE /api/bucket/{bucket}[/{ids}]` |
| `history(id)`, `history_properties(id, *history_ids)`, `clear_history(id)`, `clear_history(rules)` | `/api/bucket/{bucket}/{id}/history...` |
| `search_history(rows).where(...).sort(...).limit(50).with_properties().fetch()` / `.list()` / `.count()` | `POST /api/bucket/{bucket}/history/get` |

`update`, `release`, `delete` and `clear_history` return the number of changed rows (or removed history entries).

`Change()` sets, removes or replaces properties, the tag and the reservation:
`Change().set("$.status", "used").remove("$.tmp").tag_id(4)`, `Change().properties(new_user)`.

## History

```python
from datetime import datetime, timedelta, timezone
from databucket import HistoryField, Rule, Rules, Sort

# changes made by the nightly robot since yesterday, on the rows that are now in GB, newest first
page = (
    users.search_history(Rules.where(Rule.property("$.address.country").eq("GB")))
    .where(
        Rule.field(HistoryField.MODIFIED_BY).eq("nightly-robot"),
        Rule.field(HistoryField.MODIFIED_AT).ge(datetime.now(timezone.utc) - timedelta(days=1)),
    )
    .sort(Sort.desc(HistoryField.MODIFIED_AT))
    .limit(50)
    .with_properties()  # the properties of each version
    .fetch()
)
```

The rows are chosen by their current state (`Rules`), the entries by the fields of the history (`HistoryField`:
`ID`, `DATA_ID`, `TAG_ID`, `RESERVED`, `MODIFIED_BY`, `MODIFIED_AT`); the properties of past versions can't be searched.

Errors are raised as `DatabucketError` with `status` (the HTTP status, 0 when there was no response) and the server's
message; `body` holds the raw response. Wrong arguments (e.g. `update(Rules.ALL, ...)`) raise `ValueError`.

## Options

```python
Databucket(
    "https://databucket.example.com",
    username="tests-robot", password=password,   # POST /api/public/signin
    # or: sso_token=fetch_token_from_idp,         # POST /api/public/sso/token-exchange (client credentials of a ROBOT)
    # or: token=databucket_token,                 # a token you already have (not renewed)
    project=15,                                   # or "Acme Shop"
    timeout=10,                                   # per request, seconds (default 30)
    session=my_session,                           # your requests.Session, e.g. with a proxy or certificates
)
```

Each request is logged at DEBUG level by the logger `databucket`
(`logging.getLogger("databucket").setLevel(logging.DEBUG)`).

## Build

```
python -m venv .venv
.venv/Scripts/activate            # Windows; Linux / macOS: source .venv/bin/activate
pip install -e . --group dev      # pip 25.1+
pytest                            # unit tests
pytest tests/it                   # integration tests
ruff check . && ruff format --check . && mypy
python -m build                   # dist/
```

The integration tests need Databucket with the DEMO dataset, e.g. the docker compose of databucket-server
(http://databucket.localhost, project "Acme Shop", users `demo-robot` and `demo-member`); the history tests need
Databucket 3.14.0+. Change it with `DATABUCKET_URL`, `DATABUCKET_PROJECT`, `DATABUCKET_BUCKET`. They work only on rows
they create and remove them at the end.

Release to PyPI: `python -m build` and `twine upload dist/*` (with an API token of pypi.org).
