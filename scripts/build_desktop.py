"""Build one native desktop artifact and write its verification receipts."""

from __future__ import annotations

import argparse
import importlib.util
from importlib.metadata import PackageNotFoundError, version as installed_version
import json
import os
from pathlib import Path
import plistlib
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import release_contract


BUILD_TIMEOUT_SECONDS = 20 * 60
SMOKE_TIMEOUT_SECONDS = 90
GIT_TIMEOUT_SECONDS = 20
_LAUNCHERS = {
    "macos": Path("mac_app/launcher.py"),
    "windows": Path("windows_app/launcher.py"),
}


def pyinstaller_arguments(
    platform_name: str,
    repository_root: Path,
    dist_dir: Path,
    work_dir: Path,
    spec_dir: Path,
    windows_version_file: Path | None = None,
    data_root: Path | None = None,
    revision_file: Path | None = None,
) -> list[str]:
    """Build one platform command entirely from the shared release contract."""
    if platform_name not in _LAUNCHERS:
        raise ValueError(f"unsupported desktop platform: {platform_name!r}")
    root = Path(repository_root).resolve()
    data_source_root = Path(data_root).resolve() if data_root is not None else root
    arguments = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        f"--name={release_contract.APP_NAME}",
        f"--paths={root}",
        f"--distpath={Path(dist_dir)}",
        f"--workpath={Path(work_dir)}",
        f"--specpath={Path(spec_dir)}",
    ]
    for relative in release_contract.BUNDLE_DATA_DIRECTORIES:
        source = data_source_root / relative
        arguments.append(f"--add-data={source}{os.pathsep}{relative}")
    for relative in release_contract.BUNDLE_DATA_FILES:
        source = data_source_root / relative
        arguments.append(f"--add-data={source}{os.pathsep}{Path(relative).parent.as_posix()}")
    if revision_file is not None:
        arguments.append(f"--add-data={Path(revision_file)}{os.pathsep}.")
    for package in release_contract.PYINSTALLER_COLLECT_PACKAGES:
        arguments.append(f"--collect-submodules={package}")
    for module in release_contract.PYINSTALLER_HIDDEN_IMPORTS:
        arguments.append(f"--hidden-import={module}")

    if platform_name == "macos":
        arguments.append(f"--osx-bundle-identifier={release_contract.BUNDLE_IDENTIFIER}")
    else:
        if windows_version_file is None:
            raise ValueError("Windows builds require generated version metadata")
        arguments.append(f"--version-file={Path(windows_version_file)}")
        for module in release_contract.WINDOWS_HIDDEN_IMPORTS:
            arguments.append(f"--hidden-import={module}")

    arguments.append(str(root / _LAUNCHERS[platform_name]))
    return arguments


def _git_output(repository_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    return result.stdout.strip()


def _default_ref(repository_root: Path) -> str:
    try:
        tag = _git_output(repository_root, "describe", "--exact-match", "--tags", "HEAD")
    except subprocess.CalledProcessError:
        tag = ""
    if tag:
        return f"refs/tags/{tag}"
    try:
        branch = _git_output(repository_root, "symbolic-ref", "--quiet", "--short", "HEAD")
    except subprocess.CalledProcessError:
        branch = ""
    return f"refs/heads/{branch}" if branch else _git_output(repository_root, "rev-parse", "HEAD")


def _selected_commit(repository_root: Path, selected_ref: str) -> str:
    try:
        selected = _git_output(repository_root, "rev-parse", "--verify", f"{selected_ref}^{{commit}}")
    except subprocess.CalledProcessError:
        # actions/checkout stores PR refs under refs/remotes/pull. Resolve only
        # that exact alias; an absent ref must never silently become HEAD.
        if not re.fullmatch(r"refs/pull/[1-9][0-9]*/(?:head|merge)", selected_ref):
            raise
        checkout_ref = selected_ref.replace("refs/pull/", "refs/remotes/pull/", 1)
        selected = _git_output(repository_root, "rev-parse", "--verify", f"{checkout_ref}^{{commit}}")
    head = _git_output(repository_root, "rev-parse", "HEAD")
    if len(selected) != 40 or len(head) != 40:
        raise RuntimeError("selected ref and checkout must resolve to full Git commit SHAs")
    if selected.lower() != head.lower():
        raise RuntimeError(
            f"checkout HEAD {head} does not match selected ref {selected_ref!r} ({selected})"
        )
    return head


def _ensure_clean_checkout(repository_root: Path) -> None:
    status = _git_output(repository_root, "status", "--porcelain", "--untracked-files=normal")
    if status:
        raise RuntimeError(
            "refusing to build release artifacts from a dirty checkout; commit or remove "
            "the listed source changes first"
        )


def _ensure_packaged_sources_are_versioned(repository_root: Path) -> set[str]:
    """Refuse recursive packaging of ignored, untracked, or private env files."""
    root = Path(repository_root).resolve()
    packaged_roots = tuple(
        dict.fromkeys(
            (
                *release_contract.BUNDLE_DATA_DIRECTORIES,
                *release_contract.PYINSTALLER_COLLECT_PACKAGES,
                *release_contract.BUNDLE_DATA_FILES,
                *_LAUNCHERS.values(),
            )
        )
    )
    tracked = set(
        _git_output(
            root,
            "ls-files",
            "--full-name",
            "--",
            *(Path(path).as_posix() for path in packaged_roots),
        ).splitlines()
    )

    def require_versioned(path: Path) -> None:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise RuntimeError("refusing to package a symbolic link from the source tree")
        if path.name == ".DS_Store" or path.suffix.lower() in {".pyc", ".pyo"}:
            return
        if path.name == ".env" or path.name.startswith(".env."):
            raise RuntimeError("refusing to package a private environment file")
        if relative not in tracked:
            raise RuntimeError(
                "refusing to package an untracked or ignored file from a packaged source tree"
            )

    for relative in packaged_roots:
        path = root / relative
        if relative in release_contract.BUNDLE_DATA_FILES or relative in _LAUNCHERS.values():
            if not path.is_file():
                raise RuntimeError("a required packaged source file is missing")
            require_versioned(path)
            continue
        if not path.is_dir() or path.is_symlink():
            raise RuntimeError("a required packaged source directory is missing or unsafe")
        for current, directories, files in os.walk(path, followlinks=False):
            current_path = Path(current)
            for name in tuple(directories):
                child = current_path / name
                if name == "__pycache__":
                    directories.remove(name)
                    continue
                if child.is_symlink():
                    raise RuntimeError("refusing to package a symbolic link from the source tree")
            for name in files:
                require_versioned(current_path / name)
    return tracked


def _stage_packaged_data(
    repository_root: Path, destination: Path, tracked_sources: set[str],
    *, build_revision: str | None = None,
) -> Path:
    """Copy only versioned data inputs into the bounded PyInstaller build tree."""
    root = Path(repository_root).resolve()
    staged = Path(destination).resolve()
    staged.mkdir(parents=True, exist_ok=True)
    for relative in release_contract.BUNDLE_DATA_DIRECTORIES:
        (staged / relative).mkdir(parents=True, exist_ok=True)
    for relative in release_contract.BUNDLE_DATA_FILES:
        (staged / relative).parent.mkdir(parents=True, exist_ok=True)

    data_directories = tuple(f"{relative}/" for relative in release_contract.BUNDLE_DATA_DIRECTORIES)
    for relative in sorted(tracked_sources):
        if relative not in release_contract.BUNDLE_DATA_FILES and not relative.startswith(
            data_directories
        ):
            continue
        source = root / relative
        if source.name == ".DS_Store" or source.suffix.lower() in {".pyc", ".pyo"}:
            continue
        target = staged / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    if build_revision is not None:
        if not re.fullmatch('[0-9a-f]{40}', build_revision):
            raise ValueError('invalid build revision')
        (staged / 'commit_hash.txt').write_text(build_revision + '\n', encoding='ascii')
    return staged


def _set_macos_metadata(app_bundle: Path, version: str) -> None:
    info_path = app_bundle / "Contents" / "Info.plist"
    with info_path.open("rb") as handle:
        info = plistlib.load(handle)
    numeric_version = version.split("-", 1)[0]
    info.update(
        {
            "CFBundleName": release_contract.APP_NAME,
            "CFBundleDisplayName": release_contract.APP_NAME,
            "CFBundleIdentifier": release_contract.BUNDLE_IDENTIFIER,
            "CFBundleShortVersionString": numeric_version,
            "CFBundleVersion": numeric_version,
        }
    )
    with info_path.open("wb") as handle:
        plistlib.dump(info, handle, sort_keys=True)


def _verify_macos_bundle(app_bundle: Path) -> None:
    subprocess.run(
        ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app_bundle)],
        check=True, capture_output=True, text=True, timeout=120,
    )


def _finalize_macos_bundle(app_bundle: Path, version: str) -> None:
    """Seal final metadata; retain PyInstaller's nested ad hoc signatures."""
    _set_macos_metadata(app_bundle, version)
    subprocess.run(
        ['/usr/bin/codesign', '--force', '--sign', '-', str(app_bundle)],
        check=True, capture_output=True, text=True, timeout=120,
    )
    _verify_macos_bundle(app_bundle)


def _verify_macos_archive(archive_path: Path, extracted_dir: Path) -> None:
    """Check the actual distributable after native extraction, before receipts."""
    extracted_dir.mkdir()
    subprocess.run(
        ['/usr/bin/ditto', '-x', '-k', str(archive_path), str(extracted_dir)],
        check=True, capture_output=True, text=True, timeout=120,
    )
    _verify_macos_bundle(extracted_dir / f'{release_contract.APP_NAME}.app')


def _write_zip_entry_for_symlink(archive: zipfile.ZipFile, path: Path, relative: Path) -> None:
    info = zipfile.ZipInfo(relative.as_posix())
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, os.readlink(path))


def _archive_bundle(bundle: Path, archive_path: Path) -> None:
    """Archive a bundle while retaining executable modes and macOS symlinks."""
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for current, directories, files in os.walk(bundle, followlinks=False):
            current_path = Path(current)
            for name in tuple(directories):
                path = current_path / name
                if path.is_symlink():
                    relative = Path(bundle.name) / path.relative_to(bundle)
                    _write_zip_entry_for_symlink(archive, path, relative)
                    directories.remove(name)
            for name in files:
                path = current_path / name
                relative = Path(bundle.name) / path.relative_to(bundle)
                if path.is_symlink():
                    _write_zip_entry_for_symlink(archive, path, relative)
                else:
                    archive.write(path, relative.as_posix(), compress_type=zipfile.ZIP_DEFLATED)


def _isolated_smoke_environment(scratch: Path, receipt_path: Path) -> tuple[dict[str, str], tuple[Path, ...]]:
    temporary = scratch / "smoke-temp"
    temporary.mkdir()
    home = scratch / "smoke-home"
    paths = (
        home,
        scratch / "smoke-profile",
        scratch / "smoke-hermes",
        scratch / "smoke-config",
        scratch / "smoke-cache",
        scratch / "smoke-appdata",
        scratch / "smoke-localappdata",
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(paths[0]),
        "USERPROFILE": str(paths[1]),
        "HERMES_HOME": str(paths[2]),
        "XDG_CONFIG_HOME": str(paths[3]),
        "XDG_CACHE_HOME": str(paths[4]),
        "APPDATA": str(paths[5]),
        "LOCALAPPDATA": str(paths[6]),
        "TMPDIR": str(temporary),
        "TEMP": str(temporary),
        "TMP": str(temporary),
        "INEBOTTEN_SMOKE_RECEIPT": str(receipt_path),
    }
    for key in ("SYSTEMROOT", "WINDIR", "LANG", "LC_ALL"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env, paths


def _isolated_build_environment(scratch: Path) -> dict[str, str]:
    env = {key: os.environ[key] for key in ('PATH', 'SYSTEMROOT', 'WINDIR', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR') if key in os.environ}
    for key, name in (('HOME', 'home'), ('USERPROFILE', 'profile'), ('HERMES_HOME', 'hermes'),
                      ('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'), ('APPDATA', 'appdata'),
                      ('LOCALAPPDATA', 'localappdata'), ('TMPDIR', 'temp'), ('TEMP', 'temp'), ('TMP', 'temp'),
                      ('PYINSTALLER_CONFIG_DIR', 'pyinstaller-config')):
        path = scratch / ('build-' + name)
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        env[key] = str(path)
    env['INEBOTTEN_OFFLINE'] = '1'
    return env


def _ensure_desktop_profile(repository_root: Path, *, version_lookup=None) -> None:
    # Imports remain local: standalone workflow contract tests need only stdlib.
    from packaging.requirements import Requirement
    lookup = version_lookup or installed_version
    requirements = []
    for raw in (repository_root / release_contract.DESKTOP_LOCK).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(('#', '--hash=')):
            continue
        if not re.match(r'^[A-Za-z0-9_.-]+==', line):
            raise RuntimeError('desktop profile contains an unsupported requirement')
        requirements.append(Requirement(line.removesuffix('\\').strip()))
    if not requirements:
        raise RuntimeError('desktop profile is empty')
    for requirement in requirements:
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            version = lookup(requirement.name)
        except PackageNotFoundError as error:
            raise RuntimeError(f'desktop profile dependency is missing: {requirement.name}') from error
        if version not in requirement.specifier:
            raise RuntimeError(f'desktop profile dependency version differs: {requirement.name}')


def _run_frozen_smoke(executable: Path, scratch: Path, receipt_path: Path) -> dict:
    env, private_paths = _isolated_smoke_environment(scratch, receipt_path)
    try:
        result = subprocess.run(
            [str(executable), "--smoke-artifact"],
            cwd=scratch,
            env=env,
            capture_output=True,
            text=True,
            timeout=SMOKE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("frozen artifact smoke exceeded its 90-second deadline") from exc
    if result.returncode != 0:
        diagnostic = (result.stderr or result.stdout).strip()[-1200:]
        raise RuntimeError(f"frozen artifact smoke exited {result.returncode}: {diagnostic}")
    if any(path.exists() for path in private_paths):
        raise RuntimeError("frozen artifact smoke created a private configuration directory")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("frozen artifact smoke did not write a valid receipt") from exc
    if not isinstance(receipt, dict) or receipt.get("frozen") is not True:
        raise RuntimeError("frozen artifact smoke receipt does not identify a frozen executable")
    release_contract._validate_smoke_receipt(receipt, require_frozen=True)
    # Exercise the actual windowed executable's stdio and native Tk runtime.
    # Private homes stay synthetic; no bot, bridge or real provider is started.
    env['INEBOTTEN_OFFLINE'] = '1'
    worker = subprocess.run([str(executable),'--run-research-worker'],input=b'{}',
                            stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=scratch,env=env,timeout=15)
    if worker.returncode or json.loads(worker.stdout) != {'status':'unavailable','reason':'RuntimeError','results':[]}:
        raise RuntimeError('frozen research stdio smoke failed')
    ui_path = scratch / 'desktop-ui-smoke.json'
    env['INEBOTTEN_UI_SMOKE_RECEIPT'] = str(ui_path)
    ui = subprocess.run([str(executable),'--smoke-ui'],stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=scratch,env=env,timeout=30)
    if ui.returncode:
        raise RuntimeError('frozen native UI smoke failed: '+ui.stderr.decode('utf-8','replace')[-1200:])
    ui_receipt = json.loads(ui_path.read_text(encoding='utf-8'))
    if not (ui_receipt.get('passed') is True and ui_receipt.get('frozen') is True
            and ui_receipt.get('all_widget_calls_on_main_thread') is True
            and ui_receipt.get('private_state_initialized') is False):
        raise RuntimeError('frozen native UI receipt invalid')
    if any(path.exists() for path in private_paths):
        raise RuntimeError('frozen worker/UI smoke initialized private state')
    runtime_receipt = {'schema_version':1,'passed':True,'research_stdio_offline_smoke':True,
                       'native_ui_smoke':ui_receipt,'real_provider_started':False,
                       'human_acceptance':False}
    (scratch/'desktop-runtime-smoke.json').write_text(json.dumps(runtime_receipt,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return receipt


def _ensure_pyinstaller_available() -> None:
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError(
            "PyInstaller is unavailable; create a child-owned environment and install "
            "requirements/desktop.lock from https://pypi.org/simple"
        )


def _ensure_tk_available() -> None:
    try:
        import tkinter  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "the build interpreter has no usable Tk support; refusing to package a GUI "
            "launcher without its UI runtime"
        ) from exc


def build_desktop(
    platform_name: str,
    *,
    repository_root: Path,
    selected_ref: str,
    requested_version: str,
    output_dir: Path,
) -> dict:
    root = Path(repository_root).resolve()
    platform_name_actual, target = release_contract.target_for_runtime()
    if platform_name != platform_name_actual:
        raise RuntimeError(
            f"{platform_name} artifacts must be built on {platform_name}; "
            f"this host is {platform_name_actual}"
        )
    missing = release_contract.missing_bundle_assets(root)
    if missing:
        raise ValueError("source is missing required bundle assets: " + ", ".join(missing))

    identity = release_contract.resolve_release_identity(selected_ref)
    version = release_contract.validate_manual_version(selected_ref, requested_version)
    commit = _selected_commit(root, identity["selected_ref"])
    _ensure_clean_checkout(root)
    tracked_sources = _ensure_packaged_sources_are_versioned(root)
    lock_digest = release_contract.desktop_lock_digest(root)
    _ensure_tk_available()
    _ensure_pyinstaller_available()
    _ensure_desktop_profile(root)

    destination = Path(output_dir).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"artifact output directory must be empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    receipts = root / ".superpowers" / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="desktop-build-", dir=receipts) as temporary:
        scratch = Path(temporary)
        dist_dir = scratch / "dist"
        work_dir = scratch / "work"
        spec_dir = scratch / "spec"
        dist_dir.mkdir()
        work_dir.mkdir()
        spec_dir.mkdir()
        version_file = None
        if platform_name == "windows":
            version_file = scratch / "windows-version.txt"
            release_contract.write_windows_version_file(version_file, version)
        data_root = _stage_packaged_data(
            root, scratch / "source-data", tracked_sources, build_revision=commit)

        command = pyinstaller_arguments(
            platform_name,
            root,
            dist_dir,
            work_dir,
            spec_dir,
            windows_version_file=version_file,
            data_root=data_root,
            revision_file=data_root / 'commit_hash.txt',
        )
        build_env = _isolated_build_environment(scratch)
        try:
            subprocess.run(
                command,
                cwd=root,
                check=True,
                env=build_env,
                timeout=BUILD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("PyInstaller exceeded its 20-minute build deadline") from exc

        if platform_name == "macos":
            bundle = dist_dir / f"{release_contract.APP_NAME}.app"
            executable = bundle / "Contents" / "MacOS" / release_contract.APP_NAME
            _finalize_macos_bundle(bundle, version)
        else:
            bundle = dist_dir / release_contract.APP_NAME
            executable = bundle / f"{release_contract.APP_NAME}.exe"
        if not executable.is_file():
            raise RuntimeError(f"PyInstaller did not create the expected entrypoint for {platform_name}")

        smoke_source = scratch / release_contract.SMOKE_RECEIPT_NAMES[platform_name]
        receipt = _run_frozen_smoke(executable, scratch, smoke_source)
        shutil.copyfile(smoke_source, destination / release_contract.SMOKE_RECEIPT_NAMES[platform_name])
        runtime_smoke = scratch/'desktop-runtime-smoke.json'
        if runtime_smoke.exists():
            shutil.copyfile(runtime_smoke,destination/f'Inebotten-runtime-smoke-{platform_name}.json')

        artifact_path = destination / release_contract.ARTIFACT_NAMES[platform_name]
        _archive_bundle(bundle, artifact_path)
        if platform_name == 'macos':
            _verify_macos_archive(artifact_path, scratch / 'archive-check')

    manifest = release_contract.create_release_manifest(
        full_commit_sha=commit,
        selected_ref=identity["selected_ref"],
        platform=platform_name,
        target=target,
        lock_digest=lock_digest,
        artifact_path=artifact_path,
        smoke_receipt_path=destination / release_contract.SMOKE_RECEIPT_NAMES[platform_name],
    )
    manifest_path = destination / release_contract.MANIFEST_NAMES[platform_name]
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    release_contract.verify_release_manifest(
        manifest,
        artifact_dir=destination,
        expected_commit=commit,
        expected_ref=identity["selected_ref"],
        expected_platform=platform_name,
        expected_lock_digest=lock_digest,
    )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=tuple(_LAUNCHERS))
    parser.add_argument("--ref", default=os.environ.get("RELEASE_REF"))
    parser.add_argument("--version", default=os.environ.get("RELEASE_VERSION", ""))
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = ROOT
    receipts = root / ".superpowers" / "receipts"
    output_dir = args.output_dir or receipts / f"desktop-{args.platform}-{os.getpid()}"
    try:
        selected_ref = args.ref or _default_ref(root)
        manifest = build_desktop(
            args.platform,
            repository_root=root,
            selected_ref=selected_ref,
            requested_version=args.version,
            output_dir=output_dir,
        )
    except (
        OSError,
        RuntimeError,
        ValueError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        print(f"desktop build failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "platform": manifest["platform"],
                "target": manifest["target"],
                "full_commit_sha": manifest["full_commit_sha"],
                "tag": manifest["tag"],
                "version": manifest["version"],
                "artifact": manifest["artifact_name"],
                "artifact_checksum": manifest["artifact_checksum"],
                "output_dir": str(output_dir),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
