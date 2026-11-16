from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class DataRow(Generic[T]):
    """A data row. ``T`` is the type of the properties."""

    id: int
    tag_id: int | None
    reserved: bool
    #: The user who reserved the row.
    owner: str | None
    properties: T
    created_by: str | None
    created_at: datetime | None
    modified_by: str | None
    modified_at: datetime | None


@dataclass(frozen=True)
class Page(Generic[T]):
    """A page of rows found by :meth:`Query.fetch`."""

    rows: list[DataRow[T]]
    #: Page number, starting from 1.
    page: int
    limit: int
    #: Number of all matching rows.
    total: int
    total_pages: int


@dataclass(frozen=True)
class Reservation(Generic[T]):
    """The result of :meth:`Reserve.fetch`."""

    #: The reserved rows (fewer than the limit when not enough free rows match).
    rows: list[DataRow[T]]
    #: Number of free rows matching the rules left after this reservation.
    available: int


@dataclass(frozen=True)
class HistoryEntry(Generic[T]):
    """One change of a data row."""

    #: Id of the history entry.
    id: int
    #: Id of the data row.
    data_id: int
    #: The new tag, when it changed.
    tag_id: int | None
    #: The new reserved state, when it changed.
    reserved: bool | None
    properties_changed: bool
    #: The properties of this version (only with :meth:`HistorySearch.with_properties`, when they changed).
    properties: T | None
    modified_at: datetime | None
    modified_by: str | None


@dataclass(frozen=True)
class HistoryPage(Generic[T]):
    """A page of history entries found by :meth:`HistorySearch.fetch`."""

    entries: list[HistoryEntry[T]]
    page: int
    limit: int
    total: int
    total_pages: int


@dataclass(frozen=True)
class Project:
    """The project the client is signed in to."""

    id: int
    name: str


class DatabucketError(Exception):
    """An error returned by Databucket (HTTP status 4xx/5xx) or a failure to reach it."""

    def __init__(self, status: int, message: str, body: str | None = None) -> None:
        super().__init__(f"{status}: {message}" if status > 0 else message)
        #: HTTP status code, or 0 when there was no response (connection error, timeout) or the sign-in gave no token.
        self.status = status
        #: Raw response body, if any.
        self.body = body
