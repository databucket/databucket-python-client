from __future__ import annotations

from typing import Any, Generic, TypeVar

from .rules import _property_path

T = TypeVar("T")


class Change:
    """Changes to apply to data rows; items left out stay unchanged.

    ::

        Change().set("$.status", "used").remove("$.tmp").tag_id(4)
        Change().reserved(False)        # release
        Change().properties(new_user)   # replace all properties
    """

    def __init__(self) -> None:
        self._tag_id: int | None = None
        self._reserved: bool | None = None
        self._properties: Any = None
        self._has_properties = False
        self._to_set: dict[str, Any] = {}
        self._to_remove: list[str] = []

    def tag_id(self, tag_id: int) -> Change:
        self._tag_id = tag_id
        return self

    def reserved(self, reserved: bool) -> Change:
        """True reserves the rows for the signed-in user (only rows that are not reserved yet are changed),
        False releases them."""
        self._reserved = reserved
        return self

    def properties(self, properties: Any) -> Change:
        """Replaces all properties."""
        self._properties = properties
        self._has_properties = True
        return self

    def set(self, path: str, value: Any) -> Change:
        """Sets one property, e.g. ``set("$.address.city", "Paris")`` (the ``$.`` prefix may be left out)."""
        self._to_set[_property_path(path)] = value
        return self

    def remove(self, path: str) -> Change:
        """Removes one property, e.g. ``remove("$.tmp")``."""
        self._to_remove.append(_property_path(path))
        return self

    def to_body(self) -> dict[str, Any]:
        """The request body."""
        body: dict[str, Any] = {}
        if self._tag_id is not None:
            body["tagId"] = self._tag_id
        if self._reserved is not None:
            body["reserved"] = self._reserved
        if self._has_properties:
            body["properties"] = self._properties
        if self._to_set:
            body["propertiesToSet"] = self._to_set
        if self._to_remove:
            body["propertiesToRemove"] = self._to_remove
        return body


class NewData(Generic[T]):
    """A new row with a tag or reserved, for :meth:`Bucket.insert` and :meth:`Bucket.insert_all`.

    ::

        NewData(user).tag_id(3).reserved(True)
    """

    def __init__(self, properties: T) -> None:
        self.properties = properties
        self._tag_id: int | None = None
        self._reserved: bool | None = None

    def tag_id(self, tag_id: int) -> NewData[T]:
        self._tag_id = tag_id
        return self

    def reserved(self, reserved: bool) -> NewData[T]:
        """True: the row is reserved for the signed-in user."""
        self._reserved = reserved
        return self

    def to_body(self) -> dict[str, Any]:
        """The request body."""
        body: dict[str, Any] = {}
        if self._tag_id is not None:
            body["tagId"] = self._tag_id
        if self._reserved is not None:
            body["reserved"] = self._reserved
        body["properties"] = self.properties
        return body
