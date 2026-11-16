import json
from datetime import datetime, timezone

import pytest

from databucket import Change, Field, NewData, Rule, Rules, Sort


def body(rules: Rules) -> str:
    return json.dumps(rules.to_body(), separators=(",", ":"))


def test_one_rule_is_sent_as_logic_without_and() -> None:
    assert body(Rules.where(Rule.property("$.city").eq("Paris"))) == '{"logic":{"==":[{"var":"$.city"},"Paris"]}}'


def test_a_property_without_the_prefix_gets_it() -> None:
    assert body(Rules.where(Rule.property("address.city").eq("Paris"))) == (
        '{"logic":{"==":[{"var":"$.address.city"},"Paris"]}}'
    )


def test_several_rules_are_combined_with_and() -> None:
    expected = '{"logic":{"and":[{">":[{"var":"$.age"},30]},{"in":[{"var":"tagId"},[1,2]]}]}}'
    assert body(Rules.where(Rule.property("$.age").gt(30), Rule.tag_id().in_(1, 2))) == expected
    assert body(Rules.where([Rule.property("$.age").gt(30), Rule.tag_id().in_([1, 2])])) == expected


def test_groups_negation_and_null() -> None:
    rules = Rules.where(
        Rule.or_(Rule.owner().is_null(), Rule.owner().eq(Rule.CURRENT_USER)),
        Rule.not_(Rule.property("$.status").like("del%")),
    )
    assert body(rules) == (
        '{"logic":{"and":[{"or":[{"is":[{"var":"owner"},null]},{"==":[{"var":"owner"},"@currentUser"]}]},'
        '{"!":{"like":[{"var":"$.status"},"del%"]}}]}}'
    )


def test_operators_and_or_not() -> None:
    a = Rule.property("$.a").eq(1)
    b = Rule.property("$.b").eq(2)
    assert (a & b).to_logic() == Rule.and_(a, b).to_logic()
    assert (a | b).to_logic() == Rule.or_(a, b).to_logic()
    assert (~a).to_logic() == Rule.not_(a).to_logic()


def test_between_empty_and_functions() -> None:
    assert body(Rules.where(Rule.property("$.n").between(1, 5))) == '{"logic":{"<=":[1,{"var":"$.n"},5]}}'
    assert body(Rules.where(Rule.property("$.email").is_empty())) == '{"logic":{"!":{"var":"$.email"}}}'
    assert body(Rules.where(Rule.owner().is_not_empty())) == '{"logic":{"!!":{"var":"owner"}}}'
    assert body(Rules.where(Rule.property("$.orders").length().gt(2))) == (
        '{"logic":{">":[{"var":"$.orders.length()"},2]}}'
    )
    assert body(Rules.where(Rule.property("$.tmp").exists())) == '{"logic":{"==":[{"var":"$.tmp.exists()"},true]}}'


def test_a_datetime_is_sent_as_iso_text_in_utc() -> None:
    created = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert body(Rules.where(Rule.field(Field.CREATED_AT).gt(created))) == (
        '{"logic":{">":[{"var":"createdAt"},"2026-01-02T03:04:05.000Z"]}}'
    )


def test_functions_only_on_properties() -> None:
    with pytest.raises(ValueError, match="only on a property"):
        Rule.owner().exists()


def test_raw_rules_and_logic_pass_through() -> None:
    assert body(Rules.from_rules([["$.city", "==", "Paris"]])) == '{"rules":[["$.city","==","Paris"]]}'
    assert body(Rules.from_logic({"==": [{"var": "id"}, 1]})) == '{"logic":{"==":[{"var":"id"},1]}}'


def test_all_is_empty() -> None:
    assert Rules.ALL.is_empty()
    assert Rules.where().is_empty()
    assert body(Rules.ALL) == "{}"


def test_change_body() -> None:
    change = Change().tag_id(4).reserved(False).set("a.b", 1).remove("$.tmp")
    assert change.to_body() == {
        "tagId": 4,
        "reserved": False,
        "propertiesToSet": {"$.a.b": 1},
        "propertiesToRemove": ["$.tmp"],
    }


def test_new_data_body() -> None:
    assert NewData({"a": 1}).tag_id(3).reserved(True).to_body() == {
        "tagId": 3,
        "reserved": True,
        "properties": {"a": 1},
    }


def test_sort() -> None:
    assert Sort.desc(Field.ID) == "desc(id)"
    assert Sort.asc("$.name") == "asc($.name)"
