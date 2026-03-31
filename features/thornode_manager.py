#!/usr/bin/env python3
"""
THORNode Withdrawal Monitor for Inebotten
Polls THORChain API to detect when bonded RUNE becomes withdrawable.
"""

import json
import time
import aiohttp
from pathlib import Path
from datetime import datetime


class THORNodeManager:
    """
    Monitors THORNode status for bond provider withdrawal eligibility.
    Polls the THORNode API and detects when a node transitions to Standby,
    signaling that bonded RUNE can be withdrawn.
    """

    def __init__(self, node_address, bond_provider_address, state_file=None):
        self.node_address = node_address
        self.bond_provider_address = bond_provider_address
        self.api_base = "https://thornode.ninerealms.com"
        self.fallback_api_base = "https://thornode.thorswap.net"
        self.session = None
        self.state_file = (
            state_file or Path.home() / ".hermes" / "discord" / "thornode_state.json"
        )
        self.state = self._load_state()
        self.last_node_data = None
        self.last_poll_time = None
        self.poll_errors = 0

    def _load_state(self):
        """Load persisted notification state from disk."""
        try:
            if self.state_file.exists():
                with open(self.state_file, "r") as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[THORNODE] Warning: Could not load state file: {e}")
        return {
            "last_notified_status": None,
            "last_notified_at": None,
            "last_bond_amount": "0",
            "cooldown_until": 0,
        }

    def _save_state(self):
        """Persist notification state to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, indent=2)
        except IOError as e:
            print(f"[THORNODE] Warning: Could not save state file: {e}")

    async def _get_session(self):
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "Accept": "application/json",
                    "User-Agent": "InebottenBot/1.0",
                }
            )
        return self.session

    async def fetch_node_status(self):
        """
        Fetch current node status from THORNode API.
        Tries primary endpoint, falls back to secondary.
        Returns node data dict or None on failure.
        """
        endpoints = [
            f"{self.api_base}/thorchain/node/{self.node_address}",
            f"{self.fallback_api_base}/thorchain/node/{self.node_address}",
        ]

        for url in endpoints:
            try:
                session = await self._get_session()
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.last_node_data = data
                        self.last_poll_time = datetime.now()
                        self.poll_errors = 0
                        return data
                    else:
                        print(f"[THORNODE] API returned {resp.status} from {url}")
            except aiohttp.ClientError as e:
                print(f"[THORNODE] Connection error to {url}: {e}")
            except Exception as e:
                print(f"[THORNODE] Error fetching node status: {e}")

        self.poll_errors += 1
        return None

    def check_withdrawal_eligibility(self, node_data):
        """
        Check if the bond provider can withdraw their RUNE.

        Returns dict with:
          - eligible: bool
          - reason: str explaining why/why not
          - bond_amount: str (in tor, 1e8 decimals)
          - bond_rune: float (human readable)
          - node_status: str
          - details: dict with additional context
        """
        if not node_data:
            return {
                "eligible": False,
                "reason": "Could not fetch node data",
                "bond_amount": "0",
                "bond_rune": 0.0,
                "node_status": "unknown",
                "details": {},
            }

        status = node_data.get("status", "Unknown")
        signer_membership = node_data.get("signer_membership")
        jail = node_data.get("jail", {})
        slash_points = node_data.get("slash_points", 0)

        # Find bond provider's bond amount
        bond_amount = "0"
        providers = node_data.get("bond_providers", {}).get("providers", [])
        for provider in providers:
            if provider.get("bond_address") == self.bond_provider_address:
                bond_amount = provider.get("bond", "0")
                break

        bond_rune = int(bond_amount) / 1e8

        # Check eligibility conditions
        if status != "Standby":
            return {
                "eligible": False,
                "reason": f"Node is '{status}' (must be 'Standby' to unbond)",
                "bond_amount": bond_amount,
                "bond_rune": bond_rune,
                "node_status": status,
                "details": {
                    "slash_points": slash_points,
                    "jail": bool(jail),
                    "in_vault": bool(signer_membership),
                },
            }

        if jail:
            return {
                "eligible": False,
                "reason": "Node is jailed",
                "bond_amount": bond_amount,
                "bond_rune": bond_rune,
                "node_status": status,
                "details": {"jail_info": jail},
            }

        if signer_membership:
            return {
                "eligible": False,
                "reason": "Node is part of vault migration (signer membership active)",
                "bond_amount": bond_amount,
                "bond_rune": bond_rune,
                "node_status": status,
                "details": {"vault_members": len(signer_membership)},
            }

        if int(bond_amount) <= 0:
            return {
                "eligible": False,
                "reason": "No bond remaining",
                "bond_amount": bond_amount,
                "bond_rune": bond_rune,
                "node_status": status,
                "details": {},
            }

        return {
            "eligible": True,
            "reason": "Node is Standby, not jailed, not in vault migration",
            "bond_amount": bond_amount,
            "bond_rune": bond_rune,
            "node_status": status,
            "details": {
                "slash_points": slash_points,
                "requested_to_leave": node_data.get("requested_to_leave", False),
                "forced_to_leave": node_data.get("forced_to_leave", False),
            },
        }

    def should_notify(self, eligibility):
        """
        Determine whether to send a notification.
        Prevents spam via cooldown and state tracking.
        """
        if not eligibility["eligible"]:
            self.state["last_notified_status"] = "not_eligible"
            self._save_state()
            return False

        now = time.time()
        cooldown_until = self.state.get("cooldown_until", 0)

        # If we already notified and still in cooldown, skip
        if self.state["last_notified_status"] == "eligible" and now < cooldown_until:
            return False

        # Check if bond amount changed significantly (partial unbond happened)
        last_bond = int(self.state.get("last_bond_amount", "0"))
        current_bond = int(eligibility["bond_amount"])
        bond_changed = abs(current_bond - last_bond) > 0

        # Notify if: first time eligible, bond changed, or cooldown expired
        should = (
            self.state["last_notified_status"] != "eligible"
            or bond_changed
            or now >= cooldown_until
        )

        if should:
            self.state["last_notified_status"] = "eligible"
            self.state["last_notified_at"] = datetime.now().isoformat()
            self.state["last_bond_amount"] = eligibility["bond_amount"]
            # 6 hour cooldown between notifications
            self.state["cooldown_until"] = now + 6 * 3600
            self._save_state()

        return should

    def format_alert_message(self, eligibility):
        """Format a Discord-ready alert message."""
        bond_rune = eligibility["bond_rune"]
        bond_formatted = f"{bond_rune:,.0f}" if bond_rune >= 1 else f"{bond_rune:.4f}"

        node_short = (
            self.node_address[:12] + "..." + self.node_address[-8:]
            if len(self.node_address) > 20
            else self.node_address
        )

        unbond_memo = f"UNBOND:{self.node_address}:{eligibility['bond_amount']}"

        lines = [
            "🟢 **THORNode Withdrawal Alert**",
            "",
            f"**Node:** `{node_short}`",
            f"**Status:** Standby",
            f"**Your Bond:** {bond_formatted} RUNE",
            "",
            "✅ You can now withdraw your bonded RUNE!",
            "",
            "**To withdraw, send this memo:**",
            f"```{unbond_memo}```",
            "",
            f"📊 [View on Runescan](https://runescan.io/node/{self.node_address})",
        ]

        details = eligibility.get("details", {})
        if details.get("requested_to_leave"):
            lines.append("⚠️ Node has requested to leave!")
        if details.get("slash_points", 0) > 0:
            lines.append(f"⚡ Slash points: {details['slash_points']}")

        return "\n".join(lines)

    def format_status_message(self, eligibility):
        """Format a Discord-ready status message for manual queries."""
        node_short = (
            self.node_address[:12] + "..." + self.node_address[-8:]
            if len(self.node_address) > 20
            else self.node_address
        )

        bond_rune = eligibility["bond_rune"]
        bond_formatted = f"{bond_rune:,.0f}" if bond_rune >= 1 else f"{bond_rune:.4f}"

        if eligibility["eligible"]:
            status_emoji = "🟢"
            status_text = "Can withdraw!"
        else:
            status_emoji = "🔴"
            status_text = eligibility["reason"]

        lines = [
            f"{status_emoji} **THORNode Status**",
            "",
            f"**Node:** `{node_short}`",
            f"**Status:** {eligibility['node_status']}",
            f"**Your Bond:** {bond_formatted} RUNE",
            f"**Withdrawal:** {status_text}",
        ]

        details = eligibility.get("details", {})
        if details:
            lines.append("")
            if "slash_points" in details:
                lines.append(f"⚡ Slash points: {details['slash_points']}")
            if "jail" in details and details["jail"]:
                lines.append("🔒 Jailed: Yes")
            if "in_vault" in details and details["in_vault"]:
                lines.append("🏦 In vault migration: Yes")

        if self.last_poll_time:
            lines.append("")
            lines.append(f"_Last checked: {self.last_poll_time.strftime('%H:%M:%S')}_")

        return "\n".join(lines)

    async def close(self):
        """Close the aiohttp session."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
