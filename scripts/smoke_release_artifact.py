"""Run a no-network, no-UI check of the frozen desktop bundle's assets."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
import socket
import sys

from scripts.release_contract import verify_bundle_assets


def _deny_network(*args, **kwargs):
    raise RuntimeError("network access is blocked during release artifact smoke")


def _block_network() -> None:
    socket.socket = _deny_network
    socket.create_connection = _deny_network
    socket.getaddrinfo = _deny_network


def _verify_network_blocked() -> None:
    probes = (
        lambda: socket.socket(),
        lambda: socket.create_connection(("127.0.0.1", 9), timeout=0.1),
        lambda: socket.getaddrinfo("localhost", 80),
    )
    for probe in probes:
        try:
            probe()
        except RuntimeError:
            continue
        raise RuntimeError("network guard allowed a socket or name-resolution operation")


def build_smoke_receipt(bundle_root: Path, *, frozen: bool) -> dict:
    _block_network()
    _verify_network_blocked()
    assets = verify_bundle_assets(bundle_root)
    try:
        revision = (bundle_root / 'commit_hash.txt').read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        revision = None
    if frozen and (revision is None or not re.fullmatch('[0-9a-f]{40}', revision)):
        raise ValueError('frozen bundle omits a valid build revision')
    return {
        "schema_version": 1,
        "passed": True,
        "frozen": frozen,
        "revision": revision,
        "network_blocked": True,
        "ui_started": False,
        "service_started": False,
        "private_state_initialized": False,
        "verified_assets": list(assets),
    }


def main() -> int:
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    frozen = bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))
    receipt_path = os.environ.get("INEBOTTEN_SMOKE_RECEIPT")
    try:
        receipt = build_smoke_receipt(bundle_root, frozen=frozen)
    except (OSError, ValueError, RuntimeError) as exc:
        receipt = {
            "schema_version": 1,
            "passed": False,
            "frozen": frozen,
            "network_blocked": True,
            "ui_started": False,
            "service_started": False,
            "private_state_initialized": False,
            "verified_assets": [],
            "error": str(exc),
        }

    serialized = json.dumps(receipt, sort_keys=True, indent=2) + "\n"
    if receipt_path:
        Path(receipt_path).write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
