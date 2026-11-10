from __future__ import annotations


class Field:
    """Fields of a data row that can be used in rules and sorting (besides properties such as ``$.address.city``)."""

    ID = "id"
    TAG_ID = "tagId"
    OWNER = "owner"
    RESERVED = "reserved"
    CREATED_BY = "createdBy"
    CREATED_AT = "createdAt"
    MODIFIED_BY = "modifiedBy"
    MODIFIED_AT = "modifiedAt"


class HistoryField:
    """Fields of a history entry, for :meth:`HistorySearch.where` and sorting the history."""

    #: Id of the history entry.
    ID = "id"
    #: Id of the data row.
    DATA_ID = "dataId"
    TAG_ID = "tagId"
    RESERVED = "reserved"
    MODIFIED_BY = "modifiedBy"
    MODIFIED_AT = "modifiedAt"


class Sort:
    """Sort orders for ``Query.sort``, ``Reserve.sort`` and ``HistorySearch.sort``: a field or a property.

    ::

        Sort.asc("$.name"), Sort.desc(Field.ID), Sort.RANDOM
    """

    #: Random order, e.g. to reserve a random row.
    RANDOM = "random"

    @staticmethod
    def asc(field_or_property: str) -> str:
        return f"asc({field_or_property})"

    @staticmethod
    def desc(field_or_property: str) -> str:
        return f"desc({field_or_property})"
