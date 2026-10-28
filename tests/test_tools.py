import json
from typing import Any

import pytest

from citywheels.tools import TOOL_SCHEMAS, Toolbox


@pytest.fixture(scope="module")
def toolbox() -> Toolbox:
    return Toolbox.from_data()


def run(toolbox: Toolbox, name: str, arguments: str) -> dict[str, Any]:
    return json.loads(toolbox.execute(name, arguments))


def test_get_booking_found(toolbox: Toolbox) -> None:
    result = toolbox.get_booking("cw 1001")
    assert result["found"] is True
    assert result["booking"]["id"] == "CW-1001"


def test_get_booking_not_found(toolbox: Toolbox) -> None:
    assert toolbox.get_booking("CW-9999") == {
        "found": False,
        "booking_id": "CW-9999",
        "message": "No booking with this number.",
    }


def test_calculate_refund_via_execute(toolbox: Toolbox) -> None:
    result = run(toolbox, "calculate_refund", '{"booking_id":"cw1002"}')
    assert result["found"] is True
    assert result["total_refund_eur"] == 340.0


def test_calculate_refund_unknown_booking(toolbox: Toolbox) -> None:
    assert toolbox.calculate_refund("nope") == toolbox.get_booking("nope")


def test_calculate_refund_with_later_cancel_at(toolbox: Toolbox) -> None:
    result = toolbox.calculate_refund("CW-1002", "2026-06-11T09:00:00+02:00")
    assert result["total_refund_eur"] < 340.0


def test_search_policies_returns_sources(toolbox: Toolbox) -> None:
    results = toolbox.search_policies("cancellation refund")["results"]
    assert results
    assert set(results[0]) == {"source", "text", "score"}
    assert ".md#" in results[0]["source"]


def test_search_policies_no_match(toolbox: Toolbox) -> None:
    assert toolbox.search_policies("zzzqqq") == {
        "results": [],
        "message": "No matching policy sections.",
    }


def test_execute_invalid_json(toolbox: Toolbox) -> None:
    assert "error" in run(toolbox, "get_booking", "{not json")


def test_execute_arguments_not_an_object(toolbox: Toolbox) -> None:
    assert "error" in run(toolbox, "get_booking", "[]")


def test_execute_missing_argument(toolbox: Toolbox) -> None:
    assert "error" in run(toolbox, "get_booking", "{}")


def test_execute_empty_arguments_treated_as_empty_object(toolbox: Toolbox) -> None:
    assert "error" in run(toolbox, "get_booking", "")


def test_execute_unexpected_argument(toolbox: Toolbox) -> None:
    assert "error" in run(toolbox, "get_booking", '{"booking_id": "CW-1001", "x": 1}')


def test_execute_unknown_tool(toolbox: Toolbox) -> None:
    assert "error" in run(toolbox, "delete_everything", "{}")


def test_execute_cancel_at_in_past_returns_error(toolbox: Toolbox) -> None:
    arguments = '{"booking_id": "CW-1001", "cancel_at": "2026-06-09T09:00:00+02:00"}'
    assert "error" in run(toolbox, "calculate_refund", arguments)


def test_execute_invalid_cancel_at_returns_error(toolbox: Toolbox) -> None:
    arguments = '{"booking_id": "CW-1001", "cancel_at": "tomorrow"}'
    assert "error" in run(toolbox, "calculate_refund", arguments)


def test_execute_keeps_non_ascii_readable(toolbox: Toolbox) -> None:
    assert "zażółć" in toolbox.execute("get_booking", json.dumps({"booking_id": "zażółć"}))


def test_schemas_match_toolbox_methods(toolbox: Toolbox) -> None:
    names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
    assert names == set(toolbox._handlers)
    for name in names:
        assert callable(getattr(Toolbox, name))


def test_execute_non_string_argument(toolbox: Toolbox) -> None:
    result = run(toolbox, "get_booking", '{"booking_id": 1002}')
    assert result == {"error": "Argument 'booking_id' must be a string."}


def test_execute_null_cancel_at_means_now(toolbox: Toolbox) -> None:
    result = run(toolbox, "calculate_refund", '{"booking_id":"CW-1002","cancel_at":null}')
    assert result["total_refund_eur"] == 340.0


def test_handler_type_error_is_not_swallowed(
    toolbox: Toolbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    def buggy(booking_id: str) -> dict[str, Any]:
        raise TypeError("bug inside handler")

    monkeypatch.setitem(toolbox._handlers, "get_booking", buggy)
    with pytest.raises(TypeError):
        toolbox.execute("get_booking", '{"booking_id": "CW-1001"}')
