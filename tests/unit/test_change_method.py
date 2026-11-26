"""Data rows are changed with PATCH; a server before 3.26.0 answers 405 and gets PUT from then on."""

import json

import pytest
import requests
import responses

from databucket import Change, Databucket, DatabucketError, Rule, Rules

URL = "http://x"


def server(patch_status: int) -> list[str]:
    """A server answering PATCH with the given status (405 = before 3.26.0) and PUT with 200; returns the calls."""
    calls: list[str] = []

    def answer(request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        calls.append(f"{request.method} {request.path_url}")
        status = patch_status if request.method == "PATCH" else 200
        message = "Modified 2 data row(s)" if status == 200 else f"Request method '{request.method}' is not supported"
        return status, {}, json.dumps({"message": message})

    for method in (responses.PATCH, responses.PUT):
        responses.add_callback(method, f"{URL}/api/bucket/orders/1,2", callback=answer)
        responses.add_callback(method, f"{URL}/api/bucket/orders/1", callback=answer)
        responses.add_callback(method, f"{URL}/api/bucket/orders", callback=answer)
    return calls


@responses.activate
def test_changes_with_patch() -> None:
    calls = server(200)
    orders = Databucket(URL, token="t").bucket("orders")

    assert orders.update(Change().set("$.status", "PAID"), 1, 2) == 2
    assert orders.update(Rules.where(Rule.id().gt(0)), Change().set("$.status", "PAID")) == 2

    assert calls == ["PATCH /api/bucket/orders/1,2", "PATCH /api/bucket/orders"]


@responses.activate
def test_falls_back_to_put_on_an_older_server_and_stays_with_it() -> None:
    calls = server(405)
    orders = Databucket(URL, token="t").bucket("orders")

    assert orders.update(Change().set("$.status", "PAID"), 1, 2) == 2
    assert orders.update(Change().set("$.status", "SHIPPED"), 1, 2) == 2

    assert calls == ["PATCH /api/bucket/orders/1,2", "PUT /api/bucket/orders/1,2", "PUT /api/bucket/orders/1,2"]


@responses.activate
def test_does_not_retry_other_errors_of_patch() -> None:
    calls = server(406)
    orders = Databucket(URL, token="t").bucket("orders")

    with pytest.raises(DatabucketError) as error:
        orders.update(Change().set("$.status", "PAID"), 1)

    assert error.value.status == 406
    assert calls == ["PATCH /api/bucket/orders/1"]
