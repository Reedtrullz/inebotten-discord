"""Contracts for dependency profiles and optional runtime capabilities."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai.hermes_connector import HermesConnector
    from ai.openrouter_connector import OpenRouterConnector
    from ai.result_schema import AIProvider
    from core.outbound_sender import OutboundSender, OutboundSenderProtocol
    from utils.storage_contract import VersionedJsonStore, VersionedJsonStoreProtocol

    def _adapters_satisfy_contracts(
        hermes: HermesConnector,
        openrouter: OpenRouterConnector,
        sender: OutboundSender,
        store: VersionedJsonStore,
    ) -> tuple[AIProvider, AIProvider, OutboundSenderProtocol, VersionedJsonStoreProtocol]:
        return hermes, openrouter, sender, store


ROOT = Path(__file__).resolve().parents[1]
PROFILE_INPUTS = {
    "prod": ("requirements.txt",),
    "dev": ("requirements-dev.txt",),
    "desktop": ("requirements/desktop.in",),
    "optional-google": ("requirements/optional-google.in",),
    "optional-search": ("requirements/optional-search.in",),
    "optional-browser": ("requirements/optional-browser.in",),
}
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")


def _input_requirements(path: Path, seen: set[Path] | None = None) -> dict[str, list[Requirement]]:
    seen = seen or set()
    path = path.resolve()
    if path in seen:
        return {}
    seen.add(path)
    requirements: dict[str, list[Requirement]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            included = line.split(maxsplit=1)[1]
            for name, entries in _input_requirements(path.parent / included, seen).items():
                requirements.setdefault(name, []).extend(entries)
        elif line.startswith("-"):
            continue
        else:
            requirement = Requirement(line)
            requirements.setdefault(canonicalize_name(requirement.name), []).append(requirement)
    return requirements


def _lock_sections(path: Path) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        match = PIN.match(line)
        if match:
            current = canonicalize_name(match.group(1))
            sections[current] = [line]
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines) for name, lines in sections.items()}


def _locked_version(section: str) -> str:
    pin = PIN.match(section.splitlines()[0])
    assert pin is not None
    return pin.group(2)


def test_each_profile_lock_covers_its_reviewable_inputs_with_hashes() -> None:
    for profile, inputs in PROFILE_INPUTS.items():
        lock = ROOT / "requirements" / f"{profile}.lock"
        assert lock.is_file(), f"missing generated lock for {profile}"
        sections = _lock_sections(lock)
        expected: dict[str, list[Requirement]] = {}
        for source in inputs:
            for name, entries in _input_requirements(ROOT / source).items():
                expected.setdefault(name, []).extend(entries)
        assert expected.keys() <= sections.keys(), f"{profile} lock omitted {expected.keys() - sections.keys()}"
        assert sections, f"{profile} lock has no pinned distributions"
        assert all("--hash=sha256:" in section for section in sections.values())
        for name, requirements in expected.items():
            pin = PIN.match(sections[name].splitlines()[0])
            assert pin is not None, f"{profile} lock does not pin {name}"
            version = Version(pin.group(2))
            assert all(not req.specifier or version in req.specifier for req in requirements), (
                f"{profile} selected {name}=={version}, outside input constraints"
            )


def test_optional_profiles_stay_out_of_production_and_are_composable() -> None:
    prod = _lock_sections(ROOT / "requirements/prod.lock")
    google = _lock_sections(ROOT / "requirements/optional-google.lock")
    search = _lock_sections(ROOT / "requirements/optional-search.lock")
    browser = _lock_sections(ROOT / "requirements/optional-browser.lock")
    desktop = _lock_sections(ROOT / "requirements/desktop.lock")

    optional_names = {
        "google-api-python-client", "google-auth", "google-auth-httplib2",
        "google-auth-oauthlib", "browserbase", "tavily-python",
        "googlesearch-python", "ddgs",
    }
    assert optional_names.isdisjoint(prod)
    assert {"google-api-python-client", "google-auth-oauthlib"} <= google.keys()
    assert {"tavily-python", "googlesearch-python", "ddgs"} <= search.keys()
    assert "duckduckgo-search" not in search
    assert "browserbase" in browser
    assert optional_names <= desktop.keys()
    assert "pyinstaller" in desktop
    prod_versions = {name: _locked_version(section) for name, section in prod.items()}
    for optional in (google, search, browser):
        optional_versions = {
            name: _locked_version(section) for name, section in optional.items()
        }
        mismatches = {
            name: (prod_versions[name], optional_versions[name])
            for name in prod_versions.keys() & optional_versions.keys()
            if prod_versions[name] != optional_versions[name]
        }
        assert not mismatches, f"optional overlay conflicts with production pins: {mismatches}"


def test_install_consumers_use_their_profile_lock() -> None:
    consumers = {
        "Dockerfile": "prod",
        ".github/workflows/ci.yml": "dev",
        "setup.py": "prod",
        "utils/setup.py": "prod",
        "mac_app/build.py": "desktop",
        "mac_app/build.sh": "desktop",
        "mac_app/setup.sh": "desktop",
        "windows_app/build.py": "desktop",
        "windows_app/setup.bat": "desktop",
    }
    for filename, profile in consumers.items():
        source = (ROOT / filename).read_text(encoding="utf-8")
        assert f"{profile}.lock" in source, filename

    docs = (ROOT / "docs/DEPENDENCIES.md").read_text(encoding="utf-8")
    assert all(f"requirements/{profile}.lock" in docs for profile in PROFILE_INPUTS)


def test_optional_integrations_load_without_their_packages_and_explain_search_gap() -> None:
    script = r'''
import asyncio
import builtins
import os
import sys

blocked = {"tavily", "googlesearch", "ddgs", "duckduckgo_search", "browserbase", "googleapiclient", "google_auth_oauthlib", "google.auth", "google.oauth2"}
original_import = builtins.__import__
def import_without_optional(name, *args, **kwargs):
    if any(name == prefix or name.startswith(prefix + ".") for prefix in blocked):
        raise ModuleNotFoundError(f"optional dependency missing: {name}", name=name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = import_without_optional
sys.path.insert(0, os.path.join(os.getcwd(), "tests", "support"))
import inebotten_offline
inebotten_offline.bootstrap()

from cal_system.google_calendar_manager import GoogleCalendarManager
from features.browser_manager import BrowserManager
from features.search_manager import SearchManager

async def main():
    google = GoogleCalendarManager()
    assert not google.is_configured()
    search = SearchManager()
    search.tavily_api_key = "synthetic-key"
    assert await search.search("synthetic query") == []
    browser = BrowserManager()
    browser.api_key = "synthetic-key"
    browser.project_id = "synthetic-project"
    assert await browser.fetch_page_content("https://example.invalid") is None

asyncio.run(main())
'''
    env = os.environ.copy()
    env.pop("TAVILY_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "optional-search.lock" in result.stdout
    assert "tavily-python" in result.stdout
    assert "ddgs" in result.stdout


if __name__ == "__main__":
    raise SystemExit("run these contracts with pytest")
