from __future__ import annotations

import builtins
import importlib.util
import hashlib
import json
import os
import plistlib
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_release_contract():
    path = ROOT / "scripts" / "release_contract.py"
    assert path.is_file(), "the shared release contract is not implemented"
    spec = importlib.util.spec_from_file_location("inebotten_release_contract", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseContractTests(unittest.TestCase):
    def test_frozen_smoke_refuses_missing_or_malformed_revision(self):
        from scripts import smoke_release_artifact as smoke

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(smoke, '_block_network'), \
                patch.object(smoke, '_verify_network_blocked'), \
                patch.object(smoke, 'verify_bundle_assets', return_value=()):
            root = Path(directory)
            for value in (None, 'bad', 'a' * 40):
                if value is not None:
                    (root / 'commit_hash.txt').write_text(value, encoding='ascii')
                if value == 'a' * 40:
                    self.assertEqual(smoke.build_smoke_receipt(root, frozen=True)['revision'], value)
                else:
                    with self.assertRaisesRegex(ValueError, 'revision'):
                        smoke.build_smoke_receipt(root, frozen=True)

    def test_generated_revision_reaches_frozen_data_without_dirtying_source(self):
        from scripts import build_desktop
        from utils.deployment_contract import built_revision

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            root.mkdir()
            staged = build_desktop._stage_packaged_data(
                root, Path(directory) / 'staged', set(), build_revision='a' * 40)
            self.assertEqual(built_revision(staged), 'a' * 40)
            self.assertFalse((root / 'commit_hash.txt').exists())
            command = build_desktop.pyinstaller_arguments(
                'macos', root, root / 'dist', root / 'work', root / 'spec',
                revision_file=staged / 'commit_hash.txt')
            self.assertIn(f"--add-data={staged / 'commit_hash.txt'}{os.pathsep}.", command)

    @unittest.skipUnless(sys.platform == 'darwin', 'requires native macOS codesign and ditto')
    def test_final_metadata_and_extracted_archive_keep_a_valid_app_signature(self):
        from scripts import build_desktop

        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            bundle = scratch / 'Inebotten.app'
            executable = bundle / 'Contents' / 'MacOS' / 'Inebotten'
            executable.parent.mkdir(parents=True)
            shutil.copyfile('/usr/bin/true', executable)
            executable.chmod(0o755)
            info = bundle / 'Contents' / 'Info.plist'
            info.write_bytes(plistlib.dumps({
                'CFBundleExecutable': 'Inebotten',
                'CFBundleIdentifier': 'com.inebotten.fixture',
                'CFBundlePackageType': 'APPL',
                'CFBundleVersion': '1.0.0',
            }))
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(bundle)],
                           check=True, capture_output=True, timeout=30)
            # The old builder changes a signed resource after PyInstaller exits.
            build_desktop._set_macos_metadata(bundle, '2.0.0')
            broken = subprocess.run(
                ['/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle)],
                capture_output=True, timeout=30)
            self.assertNotEqual(broken.returncode, 0, 'must reproduce the shipped failure')

            build_desktop._finalize_macos_bundle(bundle, '2.0.0')
            archive = scratch / 'Inebotten-macos.zip'
            build_desktop._archive_bundle(bundle, archive)
            build_desktop._verify_macos_archive(archive, scratch / 'round-trip')

            # A valid ZIP checksum cannot replace signature verification.
            with zipfile.ZipFile(archive, 'a') as handle:
                handle.writestr('Inebotten.app/Contents/unsealed.txt', 'tampered')
            with self.assertRaises(subprocess.CalledProcessError):
                build_desktop._verify_macos_archive(archive, scratch / 'tampered')

    def test_same_lock_survives_platform_checkout_endings_but_changed_pin_does_not(self):
        contract = _load_release_contract()
        raw = (ROOT / contract.DESKTOP_LOCK).read_bytes().replace(b'\r\n', b'\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lf = root / 'publisher'
            crlf = root / 'windows'
            for checkout, content in ((lf, raw), (crlf, raw.replace(b'\n', b'\r\n'))):
                path = checkout / contract.DESKTOP_LOCK
                path.parent.mkdir(parents=True)
                path.write_bytes(content)
            self.assertEqual(contract.desktop_lock_digest(lf), contract.desktop_lock_digest(crlf))
            path.write_bytes(raw + b'changed-package==1.0\n')
            self.assertNotEqual(contract.desktop_lock_digest(lf), contract.desktop_lock_digest(crlf))

    def test_selected_tag_determines_release_version(self):
        contract = _load_release_contract()

        self.assertEqual(
            contract.resolve_release_identity("refs/tags/v2.8.3"),
            {
                "selected_ref": "refs/tags/v2.8.3",
                "tag": "v2.8.3",
                "version": "2.8.3",
            },
        )

    def test_malformed_selected_tag_is_rejected_instead_of_using_default_version(self):
        contract = _load_release_contract()

        with self.assertRaisesRegex(ValueError, "release tag"):
            contract.resolve_release_identity("refs/tags/v-not-a-version")

    def test_branch_ref_uses_the_single_default_version(self):
        contract = _load_release_contract()

        self.assertEqual(
            contract.resolve_release_identity("refs/heads/main"),
            {
                "selected_ref": "refs/heads/main",
                "tag": None,
                "version": "2.0.0",
            },
        )

    def test_manual_version_mismatch_is_refused(self):
        contract = _load_release_contract()
        validate = getattr(contract, "validate_manual_version", None)
        self.assertTrue(callable(validate), "manual version validation is not implemented")

        with self.assertRaisesRegex(ValueError, "does not match"):
            validate("refs/tags/v2.8.3", "v2.8.4")

    def test_required_bundle_assets_are_explicit_and_fail_closed(self):
        contract = _load_release_contract()
        missing_assets = getattr(contract, "missing_bundle_assets", None)
        self.assertTrue(callable(missing_assets), "bundle asset validation is not implemented")

        expected_directories = (
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
        expected_files = (
            "scripts/run_both.py",
            "ai/system_prompt.txt",
            "ai/system_prompt_12b.txt",
            "features/data/school_calendars.json",
            "web_console/templates/base.html",
            "web_console/static/main.css",
        )
        self.assertEqual(contract.REQUIRED_BUNDLE_DIRECTORIES, expected_directories)
        self.assertEqual(contract.REQUIRED_BUNDLE_FILES, expected_files)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in expected_directories:
                (root / relative).mkdir(parents=True, exist_ok=True)
            for relative in expected_files:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")

            self.assertEqual(missing_assets(root), ())
            (root / "web_console/static/main.css").unlink()
            self.assertEqual(missing_assets(root), ("web_console/static/main.css",))

    def test_distributable_archive_itself_contains_the_required_assets(self):
        contract = _load_release_contract()
        verify_archive = getattr(contract, "verify_archive_assets", None)
        self.assertTrue(callable(verify_archive), "ZIP content verification is not implemented")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layouts = {
                "macos": (
                    "Inebotten.app/Contents/MacOS/Inebotten",
                    "Inebotten.app/Contents/Frameworks",
                ),
                "windows": ("Inebotten/Inebotten.exe", "Inebotten/_internal"),
            }
            expected_assets = (
                contract.REQUIRED_BUNDLE_DIRECTORIES + contract.REQUIRED_BUNDLE_FILES
            )
            for platform_name, (entrypoint, asset_root) in layouts.items():
                with self.subTest(platform=platform_name):
                    archive_path = root / contract.ARTIFACT_NAMES[platform_name]
                    with zipfile.ZipFile(archive_path, "w") as archive:
                        archive.writestr(entrypoint, b"entrypoint")
                        for relative in contract.REQUIRED_BUNDLE_DIRECTORIES:
                            archive.writestr(
                                f"{asset_root}/{relative}/.asset-check", b""
                            )
                        for relative in contract.REQUIRED_BUNDLE_FILES:
                            archive.writestr(
                                f"{asset_root}/{relative}", b"fixture"
                            )

                    self.assertEqual(
                        verify_archive(archive_path, platform_name), expected_assets
                    )

                    with zipfile.ZipFile(archive_path, "w") as archive:
                        archive.writestr(entrypoint, b"entrypoint")
                    with self.assertRaisesRegex(ValueError, "omits required bundle assets"):
                        verify_archive(archive_path, platform_name)

    def test_platform_target_is_derived_from_actual_os_and_architecture(self):
        contract = _load_release_contract()
        target_for = getattr(contract, "target_for_runtime", None)
        self.assertTrue(callable(target_for), "runtime target derivation is not implemented")

        self.assertEqual(target_for("Darwin", "arm64"), ("macos", "macos-arm64"))
        self.assertEqual(target_for("Windows", "AMD64"), ("windows", "windows-x86_64"))

    def test_manifest_binds_ref_sha_version_platform_lock_asset_and_smoke(self):
        contract = _load_release_contract()
        create_manifest = getattr(contract, "create_release_manifest", None)
        verify_manifest = getattr(contract, "verify_release_manifest", None)
        self.assertTrue(callable(create_manifest), "release manifest creation is not implemented")
        self.assertTrue(callable(verify_manifest), "release manifest verification is not implemented")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "Inebotten-macos.zip"
            with zipfile.ZipFile(artifact, "w") as archive:
                archive.writestr("Inebotten.app/Contents/MacOS/Inebotten", b"entrypoint")
                for relative in contract.REQUIRED_BUNDLE_DIRECTORIES:
                    archive.writestr(
                        f"Inebotten.app/Contents/Frameworks/{relative}/.asset-check", b""
                    )
                for relative in contract.REQUIRED_BUNDLE_FILES:
                    archive.writestr(
                        f"Inebotten.app/Contents/Frameworks/{relative}", b"fixture"
                    )
            receipt = {
                "revision": "a" * 40,
                "schema_version": 1,
                "passed": True,
                "frozen": True,
                "network_blocked": True,
                "ui_started": False,
                "service_started": False,
                "private_state_initialized": False,
                "verified_assets": [
                    "ai",
                    "cal_system",
                    "core",
                    "features",
                    "memory",
                    "utils",
                    "web_console",
                    "web_console/templates",
                    "web_console/static",
                    "scripts/run_both.py",
                    "ai/system_prompt.txt",
                    "ai/system_prompt_12b.txt",
                    "features/data/school_calendars.json",
                    "web_console/templates/base.html",
                    "web_console/static/main.css",
                ],
            }
            receipt_path = root / "Inebotten-smoke-macos.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            lock_digest = hashlib.sha256(b"locked profile").hexdigest()
            manifest = create_manifest(
                full_commit_sha="a" * 40,
                selected_ref="refs/tags/v2.8.3",
                platform="macos",
                target="macos-arm64",
                lock_digest=lock_digest,
                artifact_path=artifact,
                smoke_receipt_path=receipt_path,
            )

            self.assertEqual(manifest["full_commit_sha"], "a" * 40)
            self.assertEqual(manifest["tag"], "v2.8.3")
            self.assertEqual(manifest["version"], "2.8.3")
            self.assertEqual(manifest["platform"], "macos")
            self.assertEqual(manifest["target"], "macos-arm64")
            self.assertEqual(manifest["lock_digest"], lock_digest)
            self.assertEqual(
                manifest["artifact_checksum"], hashlib.sha256(artifact.read_bytes()).hexdigest()
            )
            self.assertEqual(manifest["smoke_receipt"], receipt)

            verify_manifest(
                manifest,
                artifact_dir=root,
                expected_commit="a" * 40,
                expected_ref="refs/tags/v2.8.3",
                expected_platform="macos",
                expected_lock_digest=lock_digest,
            )
            for observed in (None, 'b' * 40):
                wrong = dict(manifest)
                wrong_receipt = dict(receipt, revision=observed)
                receipt_path.write_text(json.dumps(wrong_receipt), encoding='utf-8')
                wrong['smoke_receipt'] = wrong_receipt
                wrong['smoke_receipt_checksum'] = contract.sha256_file(receipt_path)
                with self.assertRaisesRegex(ValueError, 'revision'):
                    verify_manifest(wrong, artifact_dir=root, expected_commit='a' * 40,
                                    expected_ref='refs/tags/v2.8.3', expected_platform='macos',
                                    expected_lock_digest=lock_digest)
            receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, "commit"):
                verify_manifest(
                    manifest,
                    artifact_dir=root,
                    expected_commit="b" * 40,
                    expected_ref="refs/tags/v2.8.3",
                    expected_platform="macos",
                    expected_lock_digest=lock_digest,
                )

            artifact.write_bytes(b"tampered artifact")
            with self.assertRaisesRegex(ValueError, "checksum"):
                verify_manifest(
                    manifest,
                    artifact_dir=root,
                    expected_commit="a" * 40,
                    expected_ref="refs/tags/v2.8.3",
                    expected_platform="macos",
                    expected_lock_digest=lock_digest,
                )

    def test_windows_version_resource_uses_resolved_release_version(self):
        contract = _load_release_contract()
        writer = getattr(contract, "write_windows_version_file", None)
        self.assertTrue(callable(writer), "Windows version metadata generation is not implemented")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "version.txt"
            writer(path, "2.8.3")
            resource = path.read_text(encoding="utf-8")
            self.assertIn("filevers=(2, 8, 3, 0)", resource)
            self.assertIn("prodvers=(2, 8, 3, 0)", resource)

    def test_platform_build_command_uses_the_shared_asset_definition(self):
        path = ROOT / "scripts" / "build_desktop.py"
        self.assertTrue(path.is_file(), "the shared desktop builder is not implemented")
        spec = importlib.util.spec_from_file_location("inebotten_build_desktop", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)

        with tempfile.TemporaryDirectory() as directory:
            scratch = Path(directory)
            command = builder.pyinstaller_arguments(
                "macos",
                ROOT,
                scratch / "dist",
                scratch / "work",
                scratch / "spec",
            )

        self.assertIn(f"--add-data={ROOT / 'web_console'}{os.pathsep}web_console", command)
        self.assertIn(f"--add-data={ROOT / 'scripts/run_both.py'}{os.pathsep}scripts", command)
        for package in ("core", "utils"):
            self.assertIn(f"--add-data={ROOT / package}{os.pathsep}{package}", command)
            self.assertIn(f"--collect-submodules={package}", command)
        self.assertIn("--collect-submodules=core", command)
        self.assertIn("--collect-submodules=web_console", command)
        self.assertIn(f"--paths={ROOT}", command)
        self.assertIn("--osx-bundle-identifier=com.inebotten.discordbot", command)

        version_file = ROOT / ".superpowers/receipts/windows-version-test.txt"
        windows_command = builder.pyinstaller_arguments(
            "windows",
            ROOT,
            ROOT / ".superpowers/receipts/dist",
            ROOT / ".superpowers/receipts/work",
            ROOT / ".superpowers/receipts/spec",
            windows_version_file=version_file,
        )
        self.assertIn(f"--version-file={version_file}", windows_command)
        self.assertIn("--hidden-import=win32api", windows_command)
        self.assertIn("--hidden-import=win32file", windows_command)

    def test_new_files_under_core_and_utils_are_included_as_whole_directories(self):
        path = ROOT / "scripts" / "build_desktop.py"
        spec = importlib.util.spec_from_file_location("inebotten_build_desktop_dirs", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "core").mkdir()
            (root / "utils").mkdir()
            (root / "core/resource_shutdown.py").write_text("pass\n", encoding="utf-8")
            (root / "utils/resource-map.json").write_text("{}\n", encoding="utf-8")
            scratch = root / "scratch"
            command = builder.pyinstaller_arguments(
                "macos", root, scratch / "dist", scratch / "work", scratch / "spec"
            )

        self.assertIn(f"--add-data={root / 'core'}{os.pathsep}core", command)
        self.assertIn(f"--add-data={root / 'utils'}{os.pathsep}utils", command)
        self.assertIn("--collect-submodules=core", command)
        self.assertIn("--collect-submodules=utils", command)

    def test_build_data_stage_copies_tracked_assets_and_excludes_ignored_cache_files(self):
        path = ROOT / "scripts" / "build_desktop.py"
        spec = importlib.util.spec_from_file_location("inebotten_build_desktop_stage", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        stage_data = getattr(builder, "_stage_packaged_data", None)
        self.assertTrue(callable(stage_data), "tracked-only package data staging is not implemented")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracked_paths = [
                "core/resource_shutdown.py",
                "utils/resource-map.json",
                "scripts/run_both.py",
                "mac_app/launcher.py",
                "windows_app/launcher.py",
            ]
            for relative in set(
                builder.release_contract.BUNDLE_DATA_DIRECTORIES
                + builder.release_contract.PYINSTALLER_COLLECT_PACKAGES
            ):
                (root / relative).mkdir(parents=True, exist_ok=True)
            for relative in tracked_paths:
                source = root / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("tracked fixture\n", encoding="utf-8")
            cache = root / "core" / "__pycache__" / "resource.cpython-312.pyc"
            cache.parent.mkdir()
            cache.write_bytes(b"generated bytecode")
            (root / "utils" / ".DS_Store").write_bytes(b"generated metadata")

            with patch.object(builder, "_git_output", return_value="\n".join(tracked_paths)):
                tracked = builder._ensure_packaged_sources_are_versioned(root)
                staged_root = builder._stage_packaged_data(root, root / "staged", tracked)

            self.assertEqual((staged_root / "core/resource_shutdown.py").read_text(), "tracked fixture\n")
            self.assertEqual((staged_root / "utils/resource-map.json").read_text(), "tracked fixture\n")
            self.assertEqual((staged_root / "scripts/run_both.py").read_text(), "tracked fixture\n")
            self.assertFalse((staged_root / "core/__pycache__").exists())
            self.assertFalse((staged_root / "utils/.DS_Store").exists())
            command = builder.pyinstaller_arguments(
                "macos",
                root,
                root / "dist",
                root / "work",
                root / "spec",
                data_root=staged_root,
            )
            self.assertIn(
                f"--add-data={staged_root / 'core'}{os.pathsep}core", command
            )
            self.assertIn(
                f"--add-data={staged_root / 'utils'}{os.pathsep}utils", command
            )

    def test_builder_refuses_to_label_a_different_checkout_as_selected_ref(self):
        path = ROOT / "scripts" / "build_desktop.py"
        spec = importlib.util.spec_from_file_location("inebotten_build_desktop_ref", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with patch.object(
            builder,
            "_git_output",
            side_effect=["a" * 40, "b" * 40],
        ):
            with self.assertRaisesRegex(RuntimeError, "does not match selected ref"):
                builder._selected_commit(ROOT, "refs/tags/v2.8.3")

    def test_builder_refuses_dirty_source_before_creating_release_proof(self):
        path = ROOT / "scripts" / "build_desktop.py"
        spec = importlib.util.spec_from_file_location("inebotten_build_desktop_dirty", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with patch.object(builder, "_git_output", return_value=" M core/config.py"):
            with self.assertRaisesRegex(RuntimeError, "dirty checkout"):
                builder._ensure_clean_checkout(ROOT)

    def test_builder_resolves_checkout_actions_pull_ref_without_trusting_head(self):
        from scripts import build_desktop as builder

        missing = subprocess.CalledProcessError(128, ["git", "rev-parse"])
        for kind in ("merge", "head"):
            selected = f"refs/pull/72/{kind}"
            remote = f"refs/remotes/pull/72/{kind}"
            with self.subTest(kind=kind), patch.object(
                builder, "_git_output", side_effect=[missing, "a" * 40, "a" * 40]
            ) as git:
                self.assertEqual(builder._selected_commit(ROOT, selected), "a" * 40)
                self.assertEqual(git.call_args_list[1].args,
                                 (ROOT, "rev-parse", "--verify", remote + "^{commit}"))
        with patch.object(builder, "_git_output", side_effect=[missing, "a" * 40, "b" * 40]):
            with self.assertRaisesRegex(RuntimeError, "does not match selected ref"):
                builder._selected_commit(ROOT, "refs/pull/72/merge")
        with patch.object(builder, "_git_output", side_effect=[missing, missing]):
            with self.assertRaises(subprocess.CalledProcessError):
                builder._selected_commit(ROOT, "refs/pull/72/merge")
        with patch.object(builder, "_git_output", side_effect=missing) as git:
            with self.assertRaises(subprocess.CalledProcessError):
                builder._selected_commit(ROOT, "refs/tags/missing")
            self.assertEqual(git.call_count, 1)

    def test_recursive_packaging_accepts_new_tracked_assets_and_rejects_ignored_private_files(self):
        path = ROOT / "scripts" / "build_desktop.py"
        spec = importlib.util.spec_from_file_location("inebotten_build_desktop_sources", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracked_paths = [
                "core/config.py",
                "core/resource_shutdown.py",
                "utils/logger.py",
                "utils/resource-map.json",
                "scripts/run_both.py",
                "scripts/release_entry.py",
                "mac_app/launcher.py",
                "windows_app/launcher.py",
            ]
            for relative in tracked_paths:
                source = root / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text("fixture\n", encoding="utf-8")
            (root / "ai").mkdir()
            (root / "cal_system").mkdir()
            (root / "features").mkdir()
            (root / "memory").mkdir()
            (root / "web_console").mkdir()
            (root / "web_console/templates").mkdir()
            (root / "web_console/static").mkdir()

            with patch.object(builder, "_git_output", return_value="\n".join(tracked_paths)):
                builder._ensure_packaged_sources_are_versioned(root)

            private = root / "utils" / ".env.runtime"
            private.write_text("private=value\n", encoding="utf-8")
            with patch.object(builder, "_git_output", return_value="\n".join(tracked_paths)):
                with self.assertRaisesRegex(RuntimeError, "private environment file") as raised:
                    builder._ensure_packaged_sources_are_versioned(root)
            self.assertNotIn(str(private), str(raised.exception))

            private.unlink()
            ignored = root / "core" / "ignored-resource.json"
            ignored.write_text("{}\n", encoding="utf-8")
            with patch.object(builder, "_git_output", return_value="\n".join(tracked_paths)):
                with self.assertRaisesRegex(RuntimeError, "untracked or ignored file") as raised:
                    builder._ensure_packaged_sources_are_versioned(root)
            self.assertNotIn(str(ignored), str(raised.exception))

    def test_builder_refuses_a_runtime_without_the_launcher_ui_toolkit(self):
        path = ROOT / "scripts" / "build_desktop.py"
        spec = importlib.util.spec_from_file_location("inebotten_build_desktop_tk", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        original_import = builtins.__import__

        def import_without_tk(name, *args, **kwargs):
            if name == "tkinter":
                raise ImportError("synthetic missing Tk")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_tk):
            with self.assertRaisesRegex(RuntimeError, "no usable Tk support"):
                builder._ensure_tk_available()

    def test_only_release_workflow_publishes_after_the_reusable_build(self):
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        desktop = (ROOT / ".github/workflows/build-desktop-apps.yml").read_text(encoding="utf-8")
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertEqual(release.count("gh release create"), 1)
        self.assertIn("uses: ./.github/workflows/ci.yml", release)
        self.assertIn("uses: ./.github/workflows/build-desktop-apps.yml", release)
        self.assertIn("needs: [ci, build_desktop]", release)
        self.assertNotIn("gh release create", desktop)
        self.assertNotIn("action-gh-release", desktop)
        self.assertNotIn("contents: write", desktop)
        self.assertIn("workflow_call:", ci)
        self.assertEqual(
            ci.count("ref: ${{ inputs.ref || github.ref }}"),
            ci.count("uses: actions/checkout@"),
        )
        self.assertNotIn("contents: write", ci)

    def test_ci_and_manual_dispatch_check_out_the_selected_ref(self):
        desktop = (ROOT / ".github/workflows/build-desktop-apps.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_call:", desktop)
        self.assertIn("workflow_dispatch:", desktop)
        self.assertIn("ref:", desktop)
        self.assertIn("version:", desktop)
        self.assertGreaterEqual(
            desktop.count("ref: ${{ inputs.ref || github.ref }}"),
            desktop.count("uses: actions/checkout@"),
        )
        self.assertIn("python tests/test_release_contract.py", desktop)
        self.assertIn("scripts/build_desktop.py", desktop)
        self.assertIn("--smoke-artifact", (ROOT / "scripts/build_desktop.py").read_text(encoding="utf-8"))

    def test_source_smoke_entry_exits_before_tk_and_private_state_startup(self):
        smoke_path = ROOT / "scripts" / "smoke_release_artifact.py"
        self.assertTrue(smoke_path.is_file(), "artifact smoke entrypoint is not implemented")

        for platform_name in ("mac_app", "windows_app"):
            with self.subTest(platform=platform_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                receipt_path = root / "smoke.json"
                isolated = {
                    "HOME": root / "home",
                    "USERPROFILE": root / "profile",
                    "HERMES_HOME": root / "hermes",
                    "XDG_CONFIG_HOME": root / "config",
                    "XDG_CACHE_HOME": root / "cache",
                    "APPDATA": root / "appdata",
                    "LOCALAPPDATA": root / "localappdata",
                }
                env = {"PATH": os.environ.get("PATH", "")}
                env.update({key: str(value) for key, value in isolated.items()})
                env["INEBOTTEN_SMOKE_RECEIPT"] = str(receipt_path)
                probe = r'''import builtins, runpy, socket, sys
launcher = sys.argv[1]
real_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == "tkinter" or name.startswith("tkinter."):
        raise AssertionError("Tk imported before artifact smoke")
    return real_import(name, *args, **kwargs)
def denied(*args, **kwargs):
    raise AssertionError("network use during artifact smoke")
builtins.__import__ = guarded_import
socket.socket = denied
socket.create_connection = denied
socket.getaddrinfo = denied
sys.argv = [launcher, "--smoke-artifact"]
runpy.run_path(launcher, run_name="__main__")
'''
                result = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-c",
                        probe,
                        str(ROOT / platform_name / "launcher.py"),
                    ],
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                self.assertTrue(receipt["passed"])
                self.assertFalse(receipt["frozen"])
                self.assertTrue(receipt["network_blocked"])
                self.assertFalse(receipt["ui_started"])
                self.assertFalse(receipt["service_started"])
                self.assertFalse(receipt["private_state_initialized"])
                self.assertTrue(receipt["verified_assets"])
                self.assertTrue(all(not path.exists() for path in isolated.values()))


if __name__ == "__main__":
    unittest.main()
