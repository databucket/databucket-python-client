from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Generic, TypeVar, overload
from urllib.parse import quote

from .change import Change, NewData
from .model import DatabucketError, DataRow, HistoryEntry, HistoryPage, Page, Reservation
from .rules import Rules
from .search import HistorySearch, Query, Reserve

if TYPE_CHECKING:
    from .client import Databucket

T = TypeVar("T")


class Bucket(Generic[T]):
    """The data of one bucket. Get it with :meth:`Databucket.bucket`. ``T`` is the type of the properties."""

    def __init__(self, databucket: Databucket, name: str) -> None:
        if not name or not name.strip():
            raise ValueError("The bucket name is empty")
        self._databucket = databucket
        self.name = name
        self._path = f"/api/bucket/{quote(name, safe='')}"

    # ------------------------------------------------------------------ insert

    def insert(self, data: T | NewData[T]) -> DataRow[T]:
        """Inserts a row (properties, or :class:`NewData` with a tag or reserved) and returns it with its id."""
        return self._row(self._databucket._call("POST", self._path, _new_data(data).to_body()))

    def insert_all(self, data: Iterable[T | NewData[T]]) -> None:
        """Inserts many rows in one call (the rows are not returned; find them by rules)."""
        bodies = [_new_data(d).to_body() for d in data]
        if bodies:
            self._databucket._call("POST", f"{self._path}/multi", bodies)

    # ------------------------------------------------------------------ read

    @overload
    def get(self, id: int) -> DataRow[T] | None: ...

    @overload
    def get(self, id: Iterable[int]) -> list[DataRow[T]]: ...

    def get(self, id: int | Iterable[int]) -> DataRow[T] | None | list[DataRow[T]]:
        """The row with the given id (None when it doesn't exist or is not visible to the user), or the rows with
        the given ids (missing ids are skipped)."""
        if isinstance(id, int):
            rows = self.get([id])
            return rows[0] if rows else None
        ids = list(id)
        if not ids:
            return []
        # one existing row comes as an object, otherwise a list
        result = self._databucket._call("GET", f"{self._path}/{_ids(ids)}")
        if isinstance(result, list):
            return self._rows(result)
        return [self._row(result)] if isinstance(result, dict) else []

    def find(self, rules: Rules) -> Query[T]:
        """A search for rows matching the rules; see :class:`Query`."""
        return Query(self, rules)

    def count(self, rules: Rules) -> int:
        """Number of rows matching the rules."""
        result = self._databucket._call("POST", f"{self._path}/get?limit=0", rules.to_body())
        return int((result or {}).get("total", 0))

    def _fetch_page(self, rules: Rules, page: int, limit: int, sort: str) -> Page[T]:
        result = (
            self._databucket._call(
                "POST", f"{self._path}/get?page={page}&limit={limit}&sort={quote(sort, safe='')}", rules.to_body()
            )
            or {}
        )
        return Page(
            rows=self._rows(result.get("data")),
            page=result.get("page", page),
            limit=result.get("limit", limit),
            total=int(result.get("total", 0)),
            total_pages=result.get("totalPages", 0),
        )

    # ------------------------------------------------------------------ reserve

    def reserve(self, rules: Rules) -> Reserve[T]:
        """A reservation of free rows matching the rules; see :class:`Reserve`."""
        return Reserve(self, rules)

    def _reserve_rows(self, rules: Rules, limit: int, sort: str, for_user: str | None) -> Reservation[T]:
        body = dict(rules.to_body())
        if for_user is not None:
            body["targetOwnerUsername"] = for_user
        result = (
            self._databucket._call("POST", f"{self._path}/reserve?limit={limit}&sort={quote(sort, safe='')}", body)
            or {}
        )
        return Reservation(rows=self._rows(result.get("data")), available=int(result.get("available", 0)))

    def release(self, *ids: int) -> int:
        """Releases the rows (reserved = False); returns the number of changed rows."""
        return self.update(Change().reserved(False), *ids)

    # ------------------------------------------------------------------ modify and remove

    @overload
    def update(self, change: Change, /, *ids: int) -> int: ...

    @overload
    def update(self, rules: Rules, change: Change, /) -> int: ...

    def update(self, first: Change | Rules, *rest: Any) -> int:
        """``update(change, *ids)``: applies the change to the rows with the given ids;
        ``update(rules, change)``: to all rows matching the rules (at least one rule).
        Returns the number of changed rows."""
        if isinstance(first, Rules):
            self._require_rules(first, "modify")
            if len(rest) != 1 or not isinstance(rest[0], Change):
                raise TypeError("update(rules, change): the change is missing")
            body = {**rest[0].to_body(), **first.to_body()}
            return _count(self._databucket._call("PUT", self._path, body))
        if not rest:
            return 0
        return _count(self._databucket._call("PUT", f"{self._path}/{_ids(rest)}", first.to_body()))

    @overload
    def delete(self, *ids: int) -> int: ...

    @overload
    def delete(self, rules: Rules, /) -> int: ...

    def delete(self, *args: Any) -> int:
        """``delete(*ids)``: removes the rows with the given ids together with their history;
        ``delete(rules)``: all rows matching the rules (at least one rule). Returns the number of removed rows."""
        if args and isinstance(args[0], Rules):
            self._require_rules(args[0], "remove")
            return _count(self._databucket._call("DELETE", self._path, args[0].to_body()))
        if not args:
            return 0
        return _count(self._databucket._call("DELETE", f"{self._path}/{_ids(args)}"))

    # ------------------------------------------------------------------ history (buckets with history enabled)

    def history(self, id: int) -> list[HistoryEntry[T]]:
        """The changes of a row, oldest first."""
        result = self._databucket._call("GET", f"{self._path}/{id}/history")
        return [
            HistoryEntry(
                id=int(e["id"]),
                data_id=id,
                tag_id=_int_or_none(e.get("tag_id")),
                reserved=e.get("reserved"),
                properties_changed=e.get("properties") is True,
                properties=None,
                modified_at=_date(e.get("modified_at")),
                modified_by=e.get("modified_by"),
            )
            for e in (result if isinstance(result, list) else [])
        ]

    def search_history(self, rows: Rules) -> HistorySearch[T]:
        """A search of the history of the rows matching the rules (by their current state; ``Rules.ALL`` for all
        rows); see :class:`HistorySearch`. Databucket 3.14.0+."""
        return HistorySearch(self, rows)

    def _search_history_page(
        self, rows: Rules, entries: Rules, page: int, limit: int, sort: str, with_properties: bool
    ) -> HistoryPage[T]:
        body = dict(rows.to_body())
        entry_body = entries.to_body()
        if "logic" in entry_body:
            body["historyLogic"] = entry_body["logic"]
        if "rules" in entry_body:
            body["historyRules"] = entry_body["rules"]
        path = f"{self._path}/history/get?page={page}&limit={limit}&sort={quote(sort, safe='')}"
        if with_properties:
            path += "&properties=true"
        result = self._databucket._call("POST", path, body) or {}
        history = result.get("history")
        return HistoryPage(
            entries=[
                HistoryEntry(
                    id=int(h["id"]),
                    data_id=int(h["dataId"]),
                    tag_id=_int_or_none(h.get("tagId")),
                    reserved=h.get("reserved"),
                    properties_changed=h.get("propertiesChanged") is True,
                    properties=self._properties(h.get("properties")),
                    modified_at=_date(h.get("modifiedAt")),
                    modified_by=h.get("modifiedBy"),
                )
                for h in (history if isinstance(history, list) else [])
            ],
            page=result.get("page", page),
            limit=result.get("limit", limit),
            total=int(result.get("total", 0)),
            total_pages=result.get("totalPages", 0),
        )

    def history_properties(self, id: int, *history_ids: int) -> dict[int, T]:
        """The properties of a row as they were in the given history entries (by history entry id)."""
        if not history_ids:
            return {}
        result = self._databucket._call("GET", f"{self._path}/{id}/history/{_ids(history_ids)}")
        return {
            int(e["id"]): self._properties(e.get("properties"))  # type: ignore[misc]
            for e in (result if isinstance(result, list) else [])
        }

    @overload
    def clear_history(self, id: int, /) -> int: ...

    @overload
    def clear_history(self, rules: Rules, /) -> int: ...

    def clear_history(self, id_or_rules: int | Rules) -> int:
        """``clear_history(id)``: removes the history of a row (the row itself stays), returns the number of removed
        history entries; ``clear_history(rules)``: of all rows matching the rules (at least one rule), returns the
        number of rows."""
        if isinstance(id_or_rules, Rules):
            self._require_rules(id_or_rules, "clear the history of")
            return _count(self._databucket._call("DELETE", f"{self._path}/history/clear", id_or_rules.to_body()))
        return _count(self._databucket._call("DELETE", f"{self._path}/{id_or_rules}/history/clear"))

    # ------------------------------------------------------------------ mapping

    def _rows(self, items: Any) -> list[DataRow[T]]:
        return [self._row(item) for item in items] if isinstance(items, list) else []

    def _row(self, item: dict[str, Any]) -> DataRow[T]:
        return DataRow(
            id=int(item["id"]),
            tag_id=_int_or_none(item.get("tagId")),
            reserved=item.get("reserved") is True,
            owner=item.get("owner"),
            properties=self._properties(item.get("properties")),  # type: ignore[arg-type]
            created_by=item.get("createdBy"),
            created_at=_date(item.get("createdAt")),
            modified_by=item.get("modifiedBy"),
            modified_at=_date(item.get("modifiedAt")),
        )

    def _properties(self, value: Any) -> T | None:
        if value is None:
            return None
        if isinstance(value, str):
            # stored as text by some endpoints
            try:
                return json.loads(value)  # type: ignore[no-any-return]
            except ValueError as e:
                raise DatabucketError(0, f"Can not read the properties: {e}", value) from e
        return value  # type: ignore[no-any-return]

    def _require_rules(self, rules: Rules, action: str) -> None:
        if rules is None or rules.is_empty():
            raise ValueError(f"Can not {action} data without rules (bucket {self.name})")

    def __repr__(self) -> str:
        return f"Bucket({self.name!r})"


def _new_data(data: Any) -> NewData[Any]:
    return data if isinstance(data, NewData) else NewData(data)


def _ids(ids: Iterable[Any]) -> str:
    return ",".join(str(int(i)) for i in ids)


def _int_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


def _date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000).astimezone()
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Python 3.10 reads only 3 or 6 digits of a fraction of a second
    text = re.sub(r"\.(\d{1,6})\d*", lambda m: "." + m.group(1).ljust(6, "0"), text, count=1)
    return datetime.fromisoformat(text)


def _count(result: Any) -> int:
    """The number in a message such as "Modified 3 data row(s)"."""
    match = re.search(r"\d+", str((result or {}).get("message", "")) if isinstance(result, dict) else "")
    return int(match.group(0)) if match else 0
