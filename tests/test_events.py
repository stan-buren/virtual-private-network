"""Tests for event types and payloads."""

from __future__ import annotations

from vpn.core.events import EventType, VpnEvent


class TestEventType:
    def test_has_all_expected_values(self) -> None:
        expected = {
            "BOOTSTRAP_DONE", "HEALTH_OK", "HEALTH_FAIL",
            "TUNNEL_DIED", "SINGBOX_DIED", "SHUTDOWN_REQUESTED",
            "SERVER_CHANGE_REQUESTED", "TIMEOUT", "RESTART_REQUESTED",
        }
        names = {e.name for e in EventType}
        assert expected == names


class TestVpnEvent:
    def test_construction_with_payload(self) -> None:
        event = VpnEvent(type=EventType.SERVER_CHANGE_REQUESTED, payload={"server_name": "barguzin"})
        assert event.type == EventType.SERVER_CHANGE_REQUESTED
        assert event.payload["server_name"] == "barguzin"

    def test_default_empty_payload(self) -> None:
        event = VpnEvent(type=EventType.HEALTH_OK)
        assert event.payload == {}
