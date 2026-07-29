from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import tomllib

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


exporter = load_module(
    "export_hfs_space_bundle", ROOT / "scripts" / "export_hfs_space_bundle.py"
)
compat_exporter = load_module(
    "export_space_bundle_compat", ROOT / "scripts" / "export_space_bundle.py"
)

fake_huggingface_hub = types.ModuleType("huggingface_hub")
fake_huggingface_utils = types.ModuleType("huggingface_hub.utils")
fake_huggingface_hub.HfApi = type("HfApi", (), {})
fake_huggingface_utils.build_hf_headers = lambda **_kwargs: {}


def fake_validate_repo_id(repo_id: str) -> None:
    if not isinstance(repo_id, str) or "/" not in repo_id:
        raise ValueError("invalid repo id")


fake_huggingface_utils.validate_repo_id = fake_validate_repo_id
with mock.patch.dict(
    sys.modules,
    {
        "huggingface_hub": fake_huggingface_hub,
        "huggingface_hub.utils": fake_huggingface_utils,
    },
):
    sync = load_module("hf_space_sync", ROOT / "scripts" / "hf_space_sync.py")


class SyntheticBundleRepository:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self._write_sources()
        self._git("init", "-q")
        self._git("config", "user.name", "Bundle Test")
        self._git("config", "user.email", "bundle@example.invalid")
        self._git("add", ".")
        self._git("commit", "-qm", "synthetic bundle source")
        self.commit = self._git("rev-parse", "HEAD").strip()

    def cleanup(self) -> None:
        self.temporary.cleanup()

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def _write(self, relative: str, content: str, mode: int = 0o644) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(mode)

    def _write_sources(self) -> None:
        source_ref = "1" * 40
        checksum = "2" * 64
        self._write(".dockerignore", ".env\nlocal/\n")
        self._write(".gitattributes", "* text=auto eol=lf\n")
        self._write(
            "Dockerfile",
            "\n".join(
                [
                    f"ARG BASE_IMAGE_REF=node:22-slim@sha256:{'3' * 64}",
                    "FROM ${BASE_IMAGE_REF} AS runtime",
                    "ARG QWENPAW_SOURCE_REPO=https://github.com/agentscope-ai/QwenPaw.git",
                    f"ARG QWENPAW_SOURCE_REF={source_ref}",
                    "ARG QWENPAW_SOURCE_VERSION=2.0.1",
                    (
                        "ARG QWENPAW_CONSOLE_BUNDLE_URL="
                        "https://github.com/BlueSkyXN/QwenPaw-all-in-one-HFS/"
                        f"releases/download/test/{source_ref}.tar.gz"
                    ),
                    f"ARG QWENPAW_CONSOLE_BUNDLE_SHA256={checksum}",
                    "COPY docker/ /home/user/app/docker/",
                    "COPY hfs-dev.toml /home/user/app/hfs-dev.toml",
                    "",
                ]
            ),
        )
        self._write("LICENSE", "Synthetic test license\n")
        self._write(
            "README.md",
            "\n".join(
                [
                    f"GitHub: {exporter.WRAPPER_REPOSITORY}",
                    f"Hugging Face Space: {exporter.FORMAL_SPACE_URL}",
                    f"Live app: {exporter.FORMAL_LIVE_URL}",
                    f"HF_SPACE_ID={exporter.FORMAL_SPACE}",
                    "",
                ]
            ),
        )
        for profile in exporter.PROFILES.values():
            self._write(
                profile["manifest"],
                "\n".join(
                    [
                        'standard = "2.0"',
                        'project = "qwenpaw-all-in-one-hfs"',
                        f'space = "{profile["space"]}"',
                        'sovereignty = "port"',
                        'lane = "source"',
                        'version_source = "commit"',
                        'local_only = ["HF_TOKEN"]',
                        'secrets = ["OPS_TOKEN"]',
                        'optional_secrets = ["OPENAI_API_KEY"]',
                        'variables = ["PORT"]',
                        "",
                    ]
                ),
            )
        executable = {
            "docker/admin_service.py",
            "docker/entrypoint.sh",
            "docker/healthcheck.sh",
            "docker/ops_service.py",
        }
        for source_path in exporter.COMMON_SOURCE_TO_BUNDLE:
            if source_path in {
                ".dockerignore",
                ".gitattributes",
                "Dockerfile",
                "LICENSE",
                "README.md",
            }:
                continue
            self._write(
                source_path,
                f"# synthetic {source_path}\n",
                0o755 if source_path in executable else 0o644,
            )

    def export(self, profile: str = "candidate", name: str | None = None) -> Path:
        output = self.root / (name or f"{profile}-bundle")
        exporter.export_bundle(
            self.repo,
            self.commit,
            profile,
            output,
        )
        return output


def rewrite_checksums(bundle: Path) -> None:
    lines = []
    for relative in exporter.BUNDLE_PATHS:
        if relative == "SHA256SUMS":
            continue
        digest = hashlib.sha256((bundle / relative).read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative}\n")
    (bundle / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")


class ProfileBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.synthetic = SyntheticBundleRepository()
        self.addCleanup(self.synthetic.cleanup)

    def test_exports_candidate_bundle_with_exact_allowlist_and_checksums(self) -> None:
        bundle = self.synthetic.export("candidate")
        actual = {
            path.relative_to(bundle).as_posix()
            for path in bundle.rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual, set(exporter.BUNDLE_PATHS))
        self.assertNotIn(exporter.CANDIDATE_MANIFEST, actual)

        manifest = tomllib.loads((bundle / "hfs-dev.toml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["space"], exporter.CANDIDATE_SPACE)
        readme = (bundle / "README.md").read_text(encoding="utf-8")
        self.assertIn(exporter.CANDIDATE_SPACE_URL, readme)
        self.assertIn(exporter.CANDIDATE_LIVE_URL, readme)
        self.assertIn(exporter.WRAPPER_REPOSITORY, readme)
        self.assertTrue(os.access(bundle / "docker" / "entrypoint.sh", os.X_OK))

        evidence = json.loads((bundle / "BUILD_SOURCE.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["wrapper_source_commit"], self.synthetic.commit)
        self.assertEqual(evidence["target_space"], exporter.CANDIDATE_SPACE)
        self.assertEqual(evidence["manifest_profile"], exporter.CANDIDATE_MANIFEST)
        self.assertEqual(evidence["profile"], "candidate")
        exporter.verify_bundle(bundle, "candidate")

    def test_exports_formal_bundle_with_fixed_target_and_provenance(self) -> None:
        bundle = self.synthetic.export("formal")
        actual = {
            path.relative_to(bundle).as_posix()
            for path in bundle.rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual, set(exporter.BUNDLE_PATHS))
        self.assertNotIn(exporter.CANDIDATE_MANIFEST, actual)

        manifest = tomllib.loads((bundle / "hfs-dev.toml").read_text(encoding="utf-8"))
        self.assertEqual(manifest["space"], exporter.FORMAL_SPACE)
        self.assertEqual(manifest["optional_secrets"], ["OPENAI_API_KEY"])
        readme = (bundle / "README.md").read_text(encoding="utf-8")
        self.assertIn(exporter.FORMAL_SPACE_URL, readme)
        self.assertIn(exporter.FORMAL_LIVE_URL, readme)
        self.assertIn(f"HF_SPACE_ID={exporter.FORMAL_SPACE}", readme)

        evidence = json.loads((bundle / "BUILD_SOURCE.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence["wrapper_source_commit"], self.synthetic.commit)
        self.assertEqual(evidence["wrapper_source_repository"], exporter.WRAPPER_REPOSITORY)
        self.assertEqual(evidence["target_space"], exporter.FORMAL_SPACE)
        self.assertEqual(evidence["manifest_profile"], exporter.FORMAL_MANIFEST)
        self.assertEqual(evidence["profile"], "formal")
        self.assertEqual(evidence["upstream_source_ref"], "1" * 40)
        exporter.verify_bundle(bundle, "formal")

    def test_verifier_rejects_production_space_target_leak(self) -> None:
        bundle = self.synthetic.export("candidate")
        with (bundle / "README.md").open("a", encoding="utf-8") as file:
            file.write(f"HF_SPACE_ID={exporter.FORMAL_SPACE}\n")
        rewrite_checksums(bundle)
        with self.assertRaisesRegex(exporter.BundleError, "formal Space target"):
            exporter.verify_bundle(bundle, "candidate")

    def test_verifier_rejects_profile_mismatch(self) -> None:
        bundle = self.synthetic.export("candidate")
        with self.assertRaisesRegex(exporter.BundleError, "unexpected space"):
            exporter.verify_bundle(bundle, "formal")

    def test_formal_verifier_rejects_provenance_target_tampering(self) -> None:
        bundle = self.synthetic.export("formal")
        evidence_path = bundle / "BUILD_SOURCE.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["target_space"] = exporter.CANDIDATE_SPACE
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rewrite_checksums(bundle)
        with self.assertRaisesRegex(exporter.BundleError, "unexpected Space target"):
            exporter.verify_bundle(bundle, "formal")

    def test_verifier_rejects_unexpected_file(self) -> None:
        bundle = self.synthetic.export("candidate")
        (bundle / "unexpected.txt").write_text("not allowlisted\n", encoding="utf-8")
        with self.assertRaisesRegex(exporter.BundleError, "path set mismatch"):
            exporter.verify_bundle(bundle, "candidate")

    def test_verifier_rejects_checksum_tampering(self) -> None:
        bundle = self.synthetic.export("formal")
        with (bundle / "README.md").open("a", encoding="utf-8") as file:
            file.write("tampered\n")
        with self.assertRaisesRegex(exporter.BundleError, "checksum mismatch"):
            exporter.verify_bundle(bundle, "formal")

    def test_exporter_rejects_dirty_checkout(self) -> None:
        with (self.synthetic.repo / "README.md").open("a", encoding="utf-8") as file:
            file.write("dirty\n")
        with self.assertRaisesRegex(exporter.BundleError, "dirty checkout"):
            self.synthetic.export("candidate")

    def test_exporter_rejects_source_commit_mismatch(self) -> None:
        with self.assertRaisesRegex(exporter.BundleError, "current checkout HEAD"):
            exporter.export_bundle(
                self.synthetic.repo,
                "0" * 40,
                "formal",
                self.synthetic.root / "mismatch",
            )

    def test_exporter_rejects_non_allowlisted_profile(self) -> None:
        with self.assertRaisesRegex(exporter.BundleError, "candidate, formal"):
            self.synthetic.export("BlueSkyXN/arbitrary")
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            exporter.build_parser().parse_args(
                ["paths", "--profile", "BlueSkyXN/arbitrary"]
            )

    def test_candidate_compatibility_cli_rejects_other_manifest(self) -> None:
        with (
            contextlib.redirect_stderr(io.StringIO()),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = compat_exporter.main(
                [
                    "export",
                    "--source-commit",
                    self.synthetic.commit,
                    "--manifest",
                    exporter.FORMAL_MANIFEST,
                    "--output",
                    str(self.synthetic.root / "compat-rejected"),
                ]
            )
        self.assertEqual(result, 1)


def write_sync_fixture(root: Path, *, ops_token: str, optional_token: str) -> None:
    (root / "hfs-dev.toml").write_text(
        "\n".join(
            [
                'standard = "2.0"',
                'project = "qwenpaw-all-in-one-hfs"',
                f'space = "{exporter.CANDIDATE_SPACE}"',
                'sovereignty = "port"',
                'lane = "source"',
                'version_source = "commit"',
                'local_only = ["HF_TOKEN"]',
                'secrets = ["OPS_TOKEN"]',
                'optional_secrets = ["OPENAI_API_KEY"]',
                'variables = ["PORT"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / ".env").write_text(
        "\n".join(
            [
                "HF_TOKEN=local-control-token",
                f"OPS_TOKEN={ops_token}",
                f"OPENAI_API_KEY={optional_token}",
                "PORT=7860",
                "",
            ]
        ),
        encoding="utf-8",
    )


class OptionalSecretTests(unittest.TestCase):
    def preflight(self, ops_token: str, optional_token: str):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        write_sync_fixture(root, ops_token=ops_token, optional_token=optional_token)
        return root, sync.preflight(root)

    def test_empty_optional_secret_is_accepted(self) -> None:
        _root, result = self.preflight("required-ops-value", "")
        _manifest, env, _token, required, optional, variables, _seed = result
        self.assertEqual(required, {"OPS_TOKEN"})
        self.assertEqual(optional, {"OPENAI_API_KEY"})
        self.assertEqual(variables, {"PORT"})
        self.assertEqual(
            required | sync.configured_optional_secrets(env, optional),
            {"OPS_TOKEN"},
        )

    def test_missing_required_secret_is_rejected(self) -> None:
        with self.assertRaisesRegex(sync.SyncError, "缺少已登记值"):
            self.preflight("", "")

    def test_nonempty_optional_placeholder_is_rejected(self) -> None:
        with self.assertRaisesRegex(sync.SyncError, "仍是占位符"):
            self.preflight("required-ops-value", "CHANGE_ME")

    def test_configured_optional_secret_is_pushed_and_required_on_readback(self) -> None:
        root, _result = self.preflight("required-ops-value", "configured-provider-value")
        remote_secrets: set[str] = set()
        api = FakeSpaceApi(remote_secrets)
        with (
            mock.patch.object(sync, "api_client", return_value=api),
            mock.patch.object(sync, "resolve_targets", return_value=(exporter.CANDIDATE_SPACE, "BlueSkyXN")),
            mock.patch.object(sync, "space_secret_names", side_effect=lambda *_args: set(remote_secrets)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(sync.cmd_push(root, False, False), 0)
        self.assertEqual(api.added_secrets, ["OPENAI_API_KEY", "OPS_TOKEN"])
        self.assertEqual(remote_secrets, {"OPENAI_API_KEY", "OPS_TOKEN"})

    def test_prune_retains_registered_optional_secret_when_local_value_is_empty(self) -> None:
        root, _result = self.preflight("required-ops-value", "")
        remote_secrets = {"OPENAI_API_KEY", "UNREGISTERED_SECRET"}
        api = FakeSpaceApi(remote_secrets)
        with (
            mock.patch.object(sync, "api_client", return_value=api),
            mock.patch.object(sync, "resolve_targets", return_value=(exporter.CANDIDATE_SPACE, "BlueSkyXN")),
            mock.patch.object(sync, "space_secret_names", side_effect=lambda *_args: set(remote_secrets)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(sync.cmd_push(root, True, True), 0)
        self.assertEqual(api.deleted_secrets, ["UNREGISTERED_SECRET"])
        self.assertIn("OPENAI_API_KEY", remote_secrets)


class FakeVariable:
    def __init__(self, value: str) -> None:
        self.value = value


class FakeSpaceApi:
    def __init__(self, remote_secrets: set[str]) -> None:
        self.remote_secrets = remote_secrets
        self.remote_variables: dict[str, FakeVariable] = {}
        self.added_secrets: list[str] = []
        self.deleted_secrets: list[str] = []

    def space_info(self, *_args, **_kwargs) -> None:
        return None

    def add_space_secret(self, _space: str, name: str, _value: str, **_kwargs) -> None:
        self.added_secrets.append(name)
        self.remote_secrets.add(name)

    def delete_space_secret(self, _space: str, name: str, **_kwargs) -> None:
        self.deleted_secrets.append(name)
        self.remote_secrets.remove(name)

    def add_space_variable(self, _space: str, name: str, value: str, **_kwargs) -> None:
        self.remote_variables[name] = FakeVariable(value)

    def delete_space_variable(self, _space: str, name: str, **_kwargs) -> None:
        self.remote_variables.pop(name, None)

    def get_space_variables(self, *_args, **_kwargs) -> dict[str, FakeVariable]:
        return dict(self.remote_variables)


if __name__ == "__main__":
    unittest.main()
