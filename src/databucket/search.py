from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Generic, TypeVar

from .model import DataRow, HistoryEntry, HistoryPage, Page, Reservation
from .rules import Rule, Rules

if TYPE_CHECKING:
    from .bucket import Bucket

T = TypeVar("T")


class Query(Generic[T]):
    """A search for data rows; create it with :meth:`Bucket.find`.

    ::

        page = users.find(rules).sort(Sort.desc(Field.ID)).limit(20).page(2).fetch()
        rows = users.find(rules).limit(100).list()
        row = users.find(rules).first()
        count = users.find(rules).count()
    """

    def __init__(self, bucket: Bucket[T], rules: Rules) -> None:
        self._bucket = bucket
        self._rules = rules
        self._page = 1
        self._limit = 1
        self._sort = "id"

    def page(self, page: int) -> Query[T]:
        """Page number, starting from 1 (default 1)."""
        if page < 1:
            raise ValueError("The page starts from 1")
        self._page = page
        return self

    def limit(self, limit: int) -> Query[T]:
        """Rows per page (default 1)."""
        if limit < 1:
            raise ValueError("The limit must be at least 1; use count() to only count rows")
        self._limit = limit
        return self

    def sort(self, sort: str) -> Query[T]:
        """Sort order, see :class:`Sort` (default: by id)."""
        self._sort = sort
        return self

    def fetch(self) -> Page[T]:
        return self._bucket._fetch_page(self._rules, self._page, self._limit, self._sort)

    def list(self) -> list[DataRow[T]]:
        """The rows of the page."""
        return self.fetch().rows

    def first(self) -> DataRow[T] | None:
        """The first matching row; None when none matches."""
        rows = self._bucket._fetch_page(self._rules, 1, 1, self._sort).rows
        return rows[0] if rows else None

    def count(self) -> int:
        """Number of matching rows (no rows are transferred)."""
        return self._bucket.count(self._rules)


class Reserve(Generic[T]):
    """A reservation of free data rows; create it with :meth:`Bucket.reserve`. Rows taken at the same moment by
    another client are skipped, so parallel tests never get the same row.

    ::

        user = users.reserve(rules).one()
        r = users.reserve(rules).limit(3).sort(Sort.RANDOM).fetch()
        free = users.reserve(rules).available()
    """

    def __init__(self, bucket: Bucket[T], rules: Rules) -> None:
        self._bucket = bucket
        self._rules = rules
        self._limit = 1
        self._sort = "id"
        self._for_user: str | None = None

    def limit(self, limit: int) -> Reserve[T]:
        """Number of rows to reserve (default 1)."""
        if limit < 1:
            raise ValueError("The limit must be at least 1; use available() to only count free rows")
        self._limit = limit
        return self

    def sort(self, sort: str) -> Reserve[T]:
        """Which free rows are taken first, see :class:`Sort` (default: by id)."""
        self._sort = sort
        return self

    def for_user(self, username: str) -> Reserve[T]:
        """Reserve for another user (ADMIN only; ignored for other roles)."""
        self._for_user = username
        return self

    def fetch(self) -> Reservation[T]:
        return self._bucket._reserve_rows(self._rules, self._limit, self._sort, self._for_user)

    def one(self) -> DataRow[T] | None:
        """Reserves one row; None when no free row matches."""
        rows = self._bucket._reserve_rows(self._rules, 1, self._sort, self._for_user).rows
        return rows[0] if rows else None

    def available(self) -> int:
        """Number of free rows matching the rules; nothing is reserved."""
        return self._bucket._reserve_rows(self._rules, 0, self._sort, self._for_user).available


class HistorySearch(Generic[T]):
    """A search of the history of a bucket; create it with :meth:`Bucket.search_history` (Databucket 3.14.0+).

    ::

        # changes made by the nightly robot since yesterday, on the rows that are now in GB, newest first
        page = (users.search_history(Rules.where(Rule.property("$.address.country").eq("GB")))
                .where(Rule.field(HistoryField.MODIFIED_BY).eq("nightly-robot"),
                       Rule.field(HistoryField.MODIFIED_AT).ge(datetime.now(timezone.utc) - timedelta(days=1)))
                .sort(Sort.desc(HistoryField.MODIFIED_AT))
                .limit(50)
                .fetch())
    """

    def __init__(self, bucket: Bucket[T], rows: Rules) -> None:
        self._bucket = bucket
        self._rows = rows
        self._entries: list[Rule] = []
        self._page = 1
        self._limit = 20
        self._sort = "id"
        self._properties = False

    def where(self, *rules: Rule | Iterable[Rule]) -> HistorySearch[T]:
        """Which history entries (all must match): rules on :class:`HistoryField` s, e.g.
        ``Rule.field(HistoryField.MODIFIED_BY).eq("john")``. The properties of the versions can't be searched."""
        for item in rules:
            if isinstance(item, Rule):
                self._entries.append(item)
            else:
                self._entries.extend(item)
        return self

    def page(self, page: int) -> HistorySearch[T]:
        """Page number, starting from 1 (default 1)."""
        if page < 1:
            raise ValueError("The page starts from 1")
        self._page = page
        return self

    def limit(self, limit: int) -> HistorySearch[T]:
        """Entries per page, 1..1000 (default 20)."""
        if limit < 1 or limit > 1000:
            raise ValueError("The limit is 1..1000; use count() to only count entries")
        self._limit = limit
        return self

    def sort(self, sort: str) -> HistorySearch[T]:
        """Sort order by a history field, e.g. ``Sort.desc(HistoryField.MODIFIED_AT)`` (default: by id)."""
        self._sort = sort
        return self

    def with_properties(self) -> HistorySearch[T]:
        """Also the properties of each version (when they changed)."""
        self._properties = True
        return self

    def fetch(self) -> HistoryPage[T]:
        return self._bucket._search_history_page(
            self._rows, Rules.where(self._entries), self._page, self._limit, self._sort, self._properties
        )

    def list(self) -> list[HistoryEntry[T]]:
        """The entries of the page."""
        return self.fetch().entries

    def count(self) -> int:
        """Number of matching history entries."""
        return self._bucket._search_history_page(self._rows, Rules.where(self._entries), 1, 0, self._sort, False).total
