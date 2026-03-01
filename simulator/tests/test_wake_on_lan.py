import pytest

from helpdesk_sim.services.wake_on_lan import (
    build_magic_packet,
    format_mac_address,
    is_tcp_endpoint_reachable,
    mask_mac_address,
    normalize_mac_address,
    parse_endpoint_host_port,
)


def test_normalize_mac_address_accepts_common_formats() -> None:
    assert normalize_mac_address("AA-BB-CC-DD-EE-FF") == "aabbccddeeff"
    assert normalize_mac_address("aa:bb:cc:dd:ee:ff") == "aabbccddeeff"


def test_format_and_mask_mac_address() -> None:
    assert format_mac_address("aabbccddeeff") == "aa:bb:cc:dd:ee:ff"
    assert mask_mac_address("aabbccddeeff") == "aa:bb:**:**:ee:ff"


def test_build_magic_packet_has_expected_length_and_prefix() -> None:
    packet = build_magic_packet("aa:bb:cc:dd:ee:ff")
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6


def test_normalize_mac_address_rejects_invalid_length() -> None:
    with pytest.raises(ValueError):
        normalize_mac_address("aa:bb:cc")


def test_parse_endpoint_host_port_uses_url_host_and_port() -> None:
    assert parse_endpoint_host_port("http://100.114.151.26:11434") == ("100.114.151.26", 11434)


def test_parse_endpoint_host_port_uses_scheme_defaults() -> None:
    assert parse_endpoint_host_port("https://ollama.local") == ("ollama.local", 443)
    assert parse_endpoint_host_port("100.114.151.26:11434") == ("100.114.151.26", 11434)


def test_is_tcp_endpoint_reachable_reports_true_when_socket_connects(monkeypatch) -> None:
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    def fake_create_connection(address, timeout):
        assert address == ("100.114.151.26", 11434)
        assert timeout == 1.0
        return FakeConnection()

    monkeypatch.setattr("helpdesk_sim.services.wake_on_lan.socket.create_connection", fake_create_connection)

    reachable, host, port = is_tcp_endpoint_reachable("http://100.114.151.26:11434")

    assert reachable is True
    assert host == "100.114.151.26"
    assert port == 11434


def test_is_tcp_endpoint_reachable_reports_false_when_socket_fails(monkeypatch) -> None:
    def fake_create_connection(address, timeout):
        raise OSError("timed out")

    monkeypatch.setattr("helpdesk_sim.services.wake_on_lan.socket.create_connection", fake_create_connection)

    reachable, host, port = is_tcp_endpoint_reachable("http://100.114.151.26:11434")

    assert reachable is False
    assert host == "100.114.151.26"
    assert port == 11434
