from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timezone
from typing import Any

#: A JsonLogic expression, e.g. ``{"==": [{"var": "$.city"}, "Paris"]}``.
JsonLogic = dict[str, Any]


class Rule:
    """A condition on data rows, built in code and sent to Databucket as JsonLogic (API version 2).

    ::

        Rule.property("$.address.city").eq("Paris")
        Rule.tag_id().in_(1, 2)
        Rule.or_(Rule.owner().is_null(), Rule.owner().eq(Rule.CURRENT_USER))
        Rule.property("$.orders").length().gt(2)

    Rules can also be combined with ``&``, ``|`` and ``~`` (and, or, not).
    """

    #: As a value: the signed-in user, e.g. ``Rule.owner().eq(Rule.CURRENT_USER)``.
    CURRENT_USER = "@currentUser"

    def __init__(self, logic: Any) -> None:
        self._logic = logic

    def to_logic(self) -> Any:
        """The JsonLogic expression of this rule."""
        return self._logic

    @staticmethod
    def property(path: str) -> Operand:
        """A property of the data, e.g. ``$.address.city`` (the ``$.`` prefix may be left out)."""
        return Operand(_property_path(path), is_property=True)

    @staticmethod
    def field(field: str) -> Operand:
        """A field of a data row (:class:`Field`) or of a history entry (:class:`HistoryField`)."""
        return Operand(field, is_property=False)

    @staticmethod
    def id() -> Operand:
        return Rule.field("id")

    @staticmethod
    def tag_id() -> Operand:
        return Rule.field("tagId")

    @staticmethod
    def owner() -> Operand:
        return Rule.field("owner")

    @staticmethod
    def reserved() -> Operand:
        return Rule.field("reserved")

    @staticmethod
    def and_(*rules: Rule | Iterable[Rule]) -> Rule:
        return Rule({"and": [r._logic for r in _flat(rules)]})

    @staticmethod
    def or_(*rules: Rule | Iterable[Rule]) -> Rule:
        return Rule({"or": [r._logic for r in _flat(rules)]})

    @staticmethod
    def not_(rule: Rule) -> Rule:
        return Rule({"!": rule._logic})

    @staticmethod
    def logic(json_logic: JsonLogic) -> Rule:
        """Any JsonLogic expression, e.g. copied from the rich filter."""
        return Rule(json_logic)

    def __and__(self, other: Rule) -> Rule:
        return Rule.and_(self, other)

    def __or__(self, other: Rule) -> Rule:
        return Rule.or_(self, other)

    def __invert__(self) -> Rule:
        return Rule.not_(self)

    def __repr__(self) -> str:
        return f"Rule({json.dumps(self._logic)})"


class Operand:
    """The left side of a rule: a field, a property or a property function."""

    def __init__(self, name: str, is_property: bool) -> None:
        self._name = name
        self._is_property = is_property

    def _variable(self) -> dict[str, str]:
        return {"var": self._name}

    def _op(self, operator: str, *args: Any) -> Rule:
        return Rule({operator: [self._variable(), *(_value(a) for a in args)]})

    def eq(self, value: Any) -> Rule:
        return self._op("==", value)

    def ne(self, value: Any) -> Rule:
        return self._op("!=", value)

    def gt(self, value: Any) -> Rule:
        return self._op(">", value)

    def ge(self, value: Any) -> Rule:
        return self._op(">=", value)

    def lt(self, value: Any) -> Rule:
        return self._op("<", value)

    def le(self, value: Any) -> Rule:
        return self._op("<=", value)

    def between(self, start: Any, end: Any) -> Rule:
        """start <= value <= end"""
        return Rule({"<=": [_value(start), self._variable(), _value(end)]})

    def in_(self, *values: Any) -> Rule:
        """One of the values: ``in_(1, 2)`` or ``in_([1, 2])``."""
        return self._op("in", _flat_values(values))

    def not_in(self, *values: Any) -> Rule:
        return self._op("!in", _flat_values(values))

    def like(self, pattern: str) -> Rule:
        """SQL LIKE pattern: ``%`` any text, ``_`` one character."""
        return self._op("like", pattern)

    def not_like(self, pattern: str) -> Rule:
        return self._op("!like", pattern)

    def matches(self, regex: str) -> Rule:
        """POSIX regular expression, case sensitive."""
        return self._op("~", regex)

    def matches_ignore_case(self, regex: str) -> Rule:
        """POSIX regular expression, case insensitive."""
        return self._op("~*", regex)

    def not_matches(self, regex: str) -> Rule:
        return self._op("!~", regex)

    def is_null(self) -> Rule:
        return self._op("is", None)

    def is_not_null(self) -> Rule:
        return self._op("is not", None)

    def is_empty(self) -> Rule:
        """No value: null, missing or (for a property) an empty text."""
        return Rule({"!": self._variable()})

    def is_not_empty(self) -> Rule:
        return Rule({"!!": self._variable()})

    def exists(self) -> Rule:
        """The property is present in the data (also when its value is null)."""
        return self._fn("exists()").eq(True)

    def not_exists(self) -> Rule:
        return self._fn("notExists()").eq(True)

    def length(self) -> Operand:
        """Number of items of an array property (0 when it is not an array)."""
        return self._fn("length()")

    def _fn(self, fn: str) -> Operand:
        if not self._is_property:
            raise ValueError(f"{fn} works only on a property, not on the field {self._name}")
        return Operand(f"{self._name}.{fn}", is_property=False)


class Rules:
    """Which data rows a call works on.

    ::

        Rules.where(Rule.property("$.status").eq("active"), Rule.reserved().eq(False))  # all must match
        Rules.ALL                                                                         # every row
        Rules.from_rules([["$.status", "==", "active"]])                                  # the API "rules" format
        Rules.from_logic(json_logic)                                                      # JsonLogic
    """

    #: No conditions: every row (not accepted when modifying or removing data).
    ALL: Rules

    def __init__(self, logic: Any = None, rules: list[Any] | None = None) -> None:
        self._logic = logic
        self._rules = rules

    @staticmethod
    def where(*rules: Rule | Iterable[Rule]) -> Rules:
        """Rows matching all the rules: ``where(r1, r2)`` or ``where([r1, r2])``."""
        flat = _flat(rules)
        if not flat:
            return Rules.ALL
        if len(flat) == 1:
            return Rules(flat[0].to_logic())
        return Rules(Rule.and_(flat).to_logic())

    @staticmethod
    def from_rules(rules: Sequence[Any]) -> Rules:
        """Rules in the API "rules" format, e.g. copied from the "API request" tab of the rich filter:
        ``[["$.city", "==", "Paris"], {"or": [["tagId", "in", [1, 2]], ["$.age", ">", 30]]}]``.

        Note: in this format a value that starts with ``$`` or equals a field name (e.g. "owner") is read as
        a property or field, not as text. :meth:`Rules.where` has no such ambiguity.
        """
        return Rules(rules=list(rules))

    @staticmethod
    def from_logic(logic: JsonLogic) -> Rules:
        """A JsonLogic expression, e.g. ``{"==": [{"var": "$.city"}, "Paris"]}``."""
        return Rules(logic)

    def is_empty(self) -> bool:
        """True when there are no conditions (every row)."""
        return self._logic is None and not self._rules

    def to_body(self) -> dict[str, Any]:
        """The request body items: ``logic`` or ``rules``."""
        if self._logic is not None:
            return {"logic": self._logic}
        if self._rules is not None:
            return {"rules": self._rules}
        return {}

    def __repr__(self) -> str:
        return "Rules.ALL" if self.is_empty() else f"Rules({json.dumps(self.to_body())})"


Rules.ALL = Rules()


def _flat(rules: Iterable[Rule | Iterable[Rule]]) -> list[Rule]:
    result: list[Rule] = []
    for item in rules:
        if isinstance(item, Rule):
            result.append(item)
        else:
            result.extend(item)
    return result


def _flat_values(values: tuple[Any, ...]) -> list[Any]:
    if len(values) == 1 and isinstance(values[0], (list, tuple, set, frozenset)):
        return [_value(v) for v in values[0]]
    return [_value(v) for v in values]


def _value(value: Any) -> Any:
    """Dates are sent as ISO text (UTC); a datetime without a time zone is local time."""
    if isinstance(value, datetime):
        utc = value.astimezone(timezone.utc)
        return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"
    if isinstance(value, date):
        return value.isoformat()
    return value


def _property_path(path: str) -> str:
    if not path or not path.strip():
        raise ValueError("The property path is empty")
    return path if path.startswith("$") else f"$.{path}"
