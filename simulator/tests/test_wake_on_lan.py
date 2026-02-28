import pytest

from helpdesk_sim.services.wake_on_lan import (
    build_magic_packet,
    format_mac_address,
    mask_mac_address,
    normalize_mac_address,
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
