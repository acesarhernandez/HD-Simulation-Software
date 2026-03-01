from __future__ import annotations

import re
import socket
from urllib.parse import urlparse


def normalize_mac_address(mac_address: str) -> str:
    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac_address or "")
    if len(cleaned) != 12:
        raise ValueError("MAC address must contain exactly 12 hexadecimal characters")
    return cleaned.lower()


def format_mac_address(mac_address: str) -> str:
    normalized = normalize_mac_address(mac_address)
    return ":".join(normalized[index : index + 2] for index in range(0, 12, 2))


def mask_mac_address(mac_address: str) -> str:
    normalized = format_mac_address(mac_address)
    parts = normalized.split(":")
    return ":".join(parts[:2] + ["**", "**"] + parts[-2:])


def build_magic_packet(mac_address: str) -> bytes:
    normalized = normalize_mac_address(mac_address)
    payload = "ff" * 6 + normalized * 16
    return bytes.fromhex(payload)


def send_magic_packet(
    mac_address: str,
    broadcast_ip: str = "255.255.255.255",
    port: int = 9,
) -> int:
    packet = build_magic_packet(mac_address)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast_ip, int(port)))
    return len(packet)


def parse_endpoint_host_port(endpoint_url: str) -> tuple[str, int]:
    raw = (endpoint_url or "").strip()
    if not raw:
        raise ValueError("endpoint URL is empty")

    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("endpoint URL does not include a valid host")

    if parsed.port is not None:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80

    return host, int(port)


def is_tcp_endpoint_reachable(
    endpoint_url: str,
    timeout_seconds: float = 1.0,
) -> tuple[bool, str | None, int | None]:
    try:
        host, port = parse_endpoint_host_port(endpoint_url)
    except ValueError:
        return False, None, None

    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True, host, port
    except OSError:
        return False, host, port
