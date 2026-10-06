"""Shared release identity and artifact contract for desktop builds."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform as platform_module
import re
from pathlib import Path, PurePosixPath
import sys
import zipfile


APP_NAME = "Inebotten"
DEFAULT_VERSION = "2.0.0"
BUNDLE_IDENTIFIER = "com.inebotten.discordbot"
DESKTOP_LOCK = Path("requirements/desktop.lock")

REQUIRED_BUNDLE_DIRECTORIES = (
    "ai",
    "cal_system",
    "core",
    "features",
    "memory",
    "utils",
    "web_console",
    "web_console/templates",
    "web_console/static",
)
REQUIRED_BUNDLE_FILES = (
    "scripts/run_both.py",
    "ai/system_prompt.txt",
    "ai/system_prompt_12b.txt",
    "features/data/school_calendars.json",
    "web_console/templates/base.html",
    "web_console/static/main.css",
)
BUNDLE_DATA_DIRECTORIES = (
    "ai",
    "cal_system",
    "core",
    "features",
    "memory",
    "utils",
    "web_console",
)
BUNDLE_DATA_FILES = ("scripts/run_both.py",)
PYINSTALLER_COLLECT_PACKAGES = (
    "ai",
    "cal_system",
    "core",
    "features",
    "memory",
    "utils",
    "web_console",
    "scripts",
)
PYINSTALLER_HIDDEN_IMPORTS = (
    "discord",
    "aiohttp",
    "dateutil",
    "simpleeval",
    "dotenv",
    "keyring",
    "cryptography",
    "zoneinfo",
)
WINDOWS_HIDDEN_IMPORTS = ("win32api", "win32con", "win32gui", "win32file")
ARTIFACT_NAMES = {"macos": "Inebotten-macos.zip", "windows": "Inebotten-windows.zip"}
MANIFEST_NAMES = {
    "macos": "Inebotten-release-macos.json",
    "windows": "Inebotten-release-windows.json",
}
SMOKE_RECEIPT_NAMES = {
    "macos": "Inebotten-smoke-macos.json",
    "windows": "Inebotten-smoke-windows.json",
}

_TAG_PATTERN = re.compile(r"^v(?P<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$")
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_SHA40_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA64_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def resolve_release_identity(selected_ref: str) -> dict[str, str | None]:
    """Resolve a selected Git ref into the exact tag and app version, if any."""
    ref = selected_ref.strip()
    if not ref:
        raise ValueError("selected ref must not be empty")

    short_ref = ref.removeprefix("refs/tags/")
    match = _TAG_PATTERN.fullmatch(short_ref)
    tag = short_ref if match else None
    is_tag_ref = ref.startswith("refs/tags/") or (ref.startswith("v") and "/" not in ref)
    if is_tag_ref and tag is None:
        raise ValueError(f"release tag {ref!r} must use vMAJOR.MINOR.PATCH version syntax")
    version = match.group("version") if match else DEFAULT_VERSION
    return {"selected_ref": ref, "tag": tag, "version": version}


def validate_manual_version(selected_ref: str, requested_version: str | None) -> str:
    """Refuse a manual version that does not describe the selected ref."""
    expected = resolve_release_identity(selected_ref)["version"]
    requested = (requested_version or "").strip()
    if not requested:
        return str(expected)
    normalized = requested.removeprefix("v")
    if not _VERSION_PATTERN.fullmatch(normalized):
        raise ValueError(f"manual version {requested!r} is not a supported version")
    if normalized != expected:
        raise ValueError(
            f"manual version {requested!r} does not match selected ref version {expected!r}"
        )
    return normalized


def missing_bundle_assets(bundle_root: Path) -> tuple[str, ...]:
    """Return required packaged paths that are absent or have the wrong kind."""
    root = Path(bundle_root)
    missing = [
        relative
        for relative in REQUIRED_BUNDLE_DIRECTORIES
        if not (root / relative).is_dir()
    ]
    missing.extend(
        relative for relative in REQUIRED_BUNDLE_FILES if not (root / relative).is_file()
    )
    return tuple(missing)


def verify_bundle_assets(bundle_root: Path) -> tuple[str, ...]:
    missing = missing_bundle_assets(bundle_root)
    if missing:
        raise ValueError("required bundle assets are missing: " + ", ".join(missing))
    return REQUIRED_BUNDLE_DIRECTORIES + REQUIRED_BUNDLE_FILES


def verify_archive_assets(artifact_path: Path, platform_name: str) -> tuple[str, ...]:
    """Fail unless the distributable archive itself contains every required asset."""
    try:
        with zipfile.ZipFile(artifact_path) as archive:
            members = tuple(PurePosixPath(name).parts for name in archive.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"desktop artifact is not a readable ZIP archive: {artifact_path}") from exc

    if platform_name == "macos":
        entrypoint = (APP_NAME + ".app", "Contents", "MacOS", APP_NAME)
    elif platform_name == "windows":
        entrypoint = (APP_NAME, APP_NAME + ".exe")
    else:
        raise ValueError(f"unsupported release platform: {platform_name!r}")
    if entrypoint not in members:
        raise ValueError(f"desktop archive omits its {platform_name} launcher entrypoint")

    missing = []
    for relative in REQUIRED_BUNDLE_DIRECTORIES:
        expected = PurePosixPath(relative).parts
        if not any(
            any(
                parts[index : index + len(expected)] == expected
                for index in range(len(parts) - len(expected))
            )
            for parts in members
        ):
            missing.append(relative)
    for relative in REQUIRED_BUNDLE_FILES:
        expected = PurePosixPath(relative).parts
        if not any(
            len(parts) >= len(expected) and parts[-len(expected) :] == expected
            for parts in members
        ):
            missing.append(relative)
    if missing:
        raise ValueError("desktop archive omits required bundle assets: " + ", ".join(missing))
    return REQUIRED_BUNDLE_DIRECTORIES + REQUIRED_BUNDLE_FILES


def target_for_runtime(system: str | None = None, machine: str | None = None) -> tuple[str, str]:
    """Return stable platform and architecture labels from the build host."""
    system_name = (system or platform_module.system()).casefold()
    if system_name in {"darwin", "macos"}:
        platform_name = "macos"
    elif system_name in {"windows", "win32"}:
        platform_name = "windows"
    else:
        raise ValueError(f"desktop artifacts are unsupported on {system_name!r}")

    architecture = (machine or platform_module.machine()).casefold()
    if architecture in {"arm64", "aarch64"}:
        architecture = "arm64"
    elif architecture in {"amd64", "x86_64", "x64"}:
        architecture = "x86_64"
    else:
        raise ValueError(f"desktop artifacts are unsupported for {architecture!r}")
    return platform_name, f"{platform_name}-{architecture}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_smoke_receipt(receipt: dict, *, require_frozen: bool) -> None:
    if not isinstance(receipt, dict):
        raise ValueError("smoke receipt must be a JSON object")
    expected_true = ("passed", "network_blocked")
    if any(receipt.get(key) is not True for key in expected_true):
        raise ValueError("smoke receipt does not prove a passing no-network smoke")
    expected_false = ("ui_started", "service_started", "private_state_initialized")
    if any(receipt.get(key) is not False for key in expected_false):
        raise ValueError("smoke receipt shows UI, service, or private state startup")
    if require_frozen and receipt.get("frozen") is not True:
        raise ValueError("release smoke receipt is not from a frozen executable")
    verified_assets_value = receipt.get("verified_assets")
    if not isinstance(verified_assets_value, list) or not all(
        isinstance(asset, str) for asset in verified_assets_value
    ):
        raise ValueError("smoke receipt verified_assets must be a list of paths")
    verified_assets = set(verified_assets_value)
    required_assets = set(REQUIRED_BUNDLE_DIRECTORIES + REQUIRED_BUNDLE_FILES)
    if not required_assets.issubset(verified_assets):
        absent = sorted(required_assets - verified_assets)
        raise ValueError("smoke receipt omits required bundle assets: " + ", ".join(absent))


def create_release_manifest(
    *,
    full_commit_sha: str,
    selected_ref: str,
    platform: str,
    target: str,
    lock_digest: str,
    artifact_path: Path,
    smoke_receipt_path: Path,
) -> dict:
    """Create the release manifest after the frozen artifact smoke passes."""
    if not _SHA40_PATTERN.fullmatch(full_commit_sha):
        raise ValueError("full_commit_sha must be a full 40-character Git SHA")
    if platform not in ARTIFACT_NAMES:
        raise ValueError(f"unsupported release platform: {platform!r}")
    if not _SHA64_PATTERN.fullmatch(lock_digest):
        raise ValueError("lock_digest must be a lowercase SHA-256 digest")
    if target not in {f"{platform}-arm64", f"{platform}-x86_64"}:
        raise ValueError(f"target {target!r} does not match platform {platform!r}")

    identity = resolve_release_identity(selected_ref)
    artifact = Path(artifact_path)
    receipt_path = Path(smoke_receipt_path)
    if artifact.name != ARTIFACT_NAMES[platform]:
        raise ValueError(f"unexpected {platform} artifact name: {artifact.name!r}")
    if receipt_path.name != SMOKE_RECEIPT_NAMES[platform]:
        raise ValueError(f"unexpected {platform} smoke receipt name: {receipt_path.name!r}")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read smoke receipt {receipt_path.name!r}") from exc
    if not isinstance(receipt, dict):
        raise ValueError("smoke receipt must be a JSON object")
    _validate_smoke_receipt(receipt, require_frozen=True)

    return {
        "schema_version": 1,
        "full_commit_sha": full_commit_sha.lower(),
        "selected_ref": identity["selected_ref"],
        "tag": identity["tag"],
        "version": identity["version"],
        "target": target,
        "platform": platform,
        "lock_digest": lock_digest,
        "artifact_name": artifact.name,
        "artifact_checksum": sha256_file(artifact),
        "smoke_receipt_file": receipt_path.name,
        "smoke_receipt_checksum": sha256_file(receipt_path),
        "smoke_receipt": receipt,
    }


def verify_release_manifest(
    manifest: dict,
    *,
    artifact_dir: Path,
    expected_commit: str,
    expected_ref: str,
    expected_platform: str,
    expected_lock_digest: str,
) -> None:
    """Fail closed unless a platform artifact proves the exact selected build."""
    if not isinstance(manifest, dict):
        raise ValueError("release manifest must be a JSON object")
    if manifest.get("schema_version") != 1:
        raise ValueError("release manifest schema version is unsupported")
    if not _SHA40_PATTERN.fullmatch(expected_commit):
        raise ValueError("expected commit must be a full 40-character Git SHA")
    identity = resolve_release_identity(expected_ref)
    expected = {
        "full_commit_sha": expected_commit.lower(),
        "selected_ref": identity["selected_ref"],
        "tag": identity["tag"],
        "version": identity["version"],
        "platform": expected_platform,
        "lock_digest": expected_lock_digest,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"release manifest {key} does not match the selected build")
    target = manifest.get("target")
    if not isinstance(target, str) or target not in {
        f"{expected_platform}-arm64",
        f"{expected_platform}-x86_64",
    }:
        raise ValueError("release manifest target does not match its platform")

    artifact_name = manifest.get("artifact_name")
    receipt_name = manifest.get("smoke_receipt_file")
    if artifact_name != ARTIFACT_NAMES.get(expected_platform):
        raise ValueError("release manifest names an unexpected artifact")
    if receipt_name != SMOKE_RECEIPT_NAMES.get(expected_platform):
        raise ValueError("release manifest names an unexpected smoke receipt")
    root = Path(artifact_dir)
    artifact_path = root / artifact_name
    receipt_path = root / receipt_name
    if not artifact_path.is_file() or sha256_file(artifact_path) != manifest.get("artifact_checksum"):
        raise ValueError("release artifact checksum does not match its manifest")
    verify_archive_assets(artifact_path, expected_platform)
    if not receipt_path.is_file() or sha256_file(receipt_path) != manifest.get("smoke_receipt_checksum"):
        raise ValueError("smoke receipt checksum does not match its manifest")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("smoke receipt is not readable JSON") from exc
    if not isinstance(receipt, dict):
        raise ValueError("smoke receipt is not a JSON object")
    if receipt != manifest.get("smoke_receipt"):
        raise ValueError("smoke receipt sidecar differs from the manifest")
    _validate_smoke_receipt(receipt, require_frozen=True)


def write_windows_version_file(path: Path, version: str) -> None:
    """Write PyInstaller's Windows version resource from the release version."""
    if not _VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"unsupported Windows file version: {version!r}")
    numeric = version.split("-", 1)[0].split(".")
    file_version = tuple(int(part) for part in numeric) + (0,)
    version_text = version.replace("'", "\\'")
    source = f'''VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={file_version}, prodvers={file_version},
    mask=0x3f, flags=0x0, OS=0x4, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'Inebotten'),
        StringStruct('FileDescription', 'Inebotten desktop launcher'),
        StringStruct('FileVersion', '{version_text}'),
        StringStruct('InternalName', 'Inebotten'),
        StringStruct('OriginalFilename', 'Inebotten.exe'),
        StringStruct('ProductName', 'Inebotten'),
        StringStruct('ProductVersion', '{version_text}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''
    Path(path).write_text(source, encoding="utf-8")


def desktop_lock_digest(repository_root: Path) -> str:
    # Git's Windows checkout may convert text to CRLF. The publisher and both
    # builders bind the same lock content, independent of checkout line endings.
    raw = (Path(repository_root) / DESKTOP_LOCK).read_bytes()
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-ref")
    validate.add_argument("--ref", required=True)
    validate.add_argument("--version", default="")

    verify = commands.add_parser("verify-artifacts")
    verify.add_argument("--ref", required=True)
    verify.add_argument("--commit", required=True)
    verify.add_argument("--macos-dir", required=True, type=Path)
    verify.add_argument("--windows-dir", required=True, type=Path)
    verify.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "validate-ref":
            version = validate_manual_version(args.ref, args.version)
            print(json.dumps({**resolve_release_identity(args.ref), "version": version}))
            return 0

        repository_root = Path(__file__).resolve().parents[1]
        lock_digest = desktop_lock_digest(repository_root)
        verified = []
        for platform_name, directory in (
            ("macos", args.macos_dir),
            ("windows", args.windows_dir),
        ):
            manifest_path = directory / MANIFEST_NAMES[platform_name]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            verify_release_manifest(
                manifest,
                artifact_dir=directory,
                expected_commit=args.commit,
                expected_ref=args.ref,
                expected_platform=platform_name,
                expected_lock_digest=lock_digest,
            )
            verified.append(manifest)

        args.output_dir.mkdir(parents=True, exist_ok=True)
        checksum_file = args.output_dir / "SHA256SUMS"
        paths = [
            args.macos_dir / ARTIFACT_NAMES["macos"],
            args.macos_dir / MANIFEST_NAMES["macos"],
            args.macos_dir / SMOKE_RECEIPT_NAMES["macos"],
            args.windows_dir / ARTIFACT_NAMES["windows"],
            args.windows_dir / MANIFEST_NAMES["windows"],
            args.windows_dir / SMOKE_RECEIPT_NAMES["windows"],
        ]
        checksum_file.write_text(
            "".join(f"{sha256_file(path)}  {path.name}\n" for path in paths),
            encoding="utf-8",
        )
        print(json.dumps({"verified_platforms": [item["platform"] for item in verified]}))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"release contract failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli())
