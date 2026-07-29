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
import tomllib
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


exporter = load_module("export_space_bundle", ROOT / "scripts" / "export_space_bundle.py")

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
        self._git("config", "user.name", "Candidate Test")
        self._git("config", "user.email", "candidate@example.invalid")
        self._git("add", ".")
        self._git("commit", "-qm", "synthetic candidate")
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
                    f"Hugging Face Space: {exporter.PRIMARY_SPACE_URL}",
                    f"Live app: {exporter.PRIMARY_LIVE_URL}",
                    f"HF_SPACE_ID={exporter.PRIMARY_SPACE}",
                    "",
                ]
            ),
        )
        self._write(
            exporter.CANDIDATE_MANIFEST,
            "\n".join(
                [
                    'standard = "2.1"',
                    'project = "qwenpaw-all-in-one-hfs"',
                    f'space = "{exporter.CANDIDATE_SPACE}"',
                    'project_class = "preview"',
                    'target_role = "candidate"',
                    'sovereignty = "port"',
                    'lane = "source"',
                    'version_source = "commit"',
                    'env_file = "local/hfs-targets/candidate.env"',
                    'secret_files = []',
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
        for source_path in exporter.SOURCE_TO_BUNDLE:
            if source_path in {
                ".dockerignore",
                ".gitattributes",
                "Dockerfile",
                "LICENSE",
                "README.md",
                exporter.CANDIDATE_MANIFEST,
            }:
                continue
            self._write(
                source_path,
                f"# synthetic {source_path}\n",
                0o755 if source_path in executable else 0o644,
            )

    def export(self, name: str = "bundle") -> Path:
        output = self.root / name
        exporter.export_bundle(
            self.repo,
            self.commit,
            Path(exporter.CANDIDATE_MANIFEST),
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


class CandidateBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.synthetic = SyntheticBundleRepository()
        self.addCleanup(self.synthetic.cleanup)

    def test_exports_candidate_bundle_with_exact_allowlist_and_checksums(self) -> None:
        bundle = self.synthetic.export()
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
        exporter.verify_bundle(bundle)

    def test_verifier_rejects_primary_space_target_leak(self) -> None:
        bundle = self.synthetic.export()
        with (bundle / "README.md").open("a", encoding="utf-8") as file:
            file.write(f"HF_SPACE_ID={exporter.PRIMARY_SPACE}\n")
        rewrite_checksums(bundle)
        with self.assertRaisesRegex(exporter.BundleError, "canonical primary Space target"):
            exporter.verify_bundle(bundle)

    def test_verifier_rejects_unexpected_file(self) -> None:
        bundle = self.synthetic.export()
        (bundle / "unexpected.txt").write_text("not allowlisted\n", encoding="utf-8")
        with self.assertRaisesRegex(exporter.BundleError, "path set mismatch"):
            exporter.verify_bundle(bundle)

    def test_exporter_rejects_dirty_checkout(self) -> None:
        with (self.synthetic.repo / "README.md").open("a", encoding="utf-8") as file:
            file.write("dirty\n")
        with self.assertRaisesRegex(exporter.BundleError, "dirty checkout"):
            self.synthetic.export()

    def test_exporter_rejects_source_commit_mismatch(self) -> None:
        with self.assertRaisesRegex(exporter.BundleError, "current checkout HEAD"):
            exporter.export_bundle(
                self.synthetic.repo,
                "0" * 40,
                Path(exporter.CANDIDATE_MANIFEST),
                self.synthetic.root / "mismatch",
            )


def write_sync_fixture(root: Path, *, ops_token: str, optional_token: str) -> None:
    (root / "hfs-dev.toml").write_text(
        "\n".join(
            [
                'standard = "2.1"',
                'project = "qwenpaw-all-in-one-hfs"',
                f'space = "{exporter.CANDIDATE_SPACE}"',
                'project_class = "preview"',
                'target_role = "candidate"',
                'sovereignty = "port"',
                'lane = "source"',
                'version_source = "commit"',
                'env_file = ".env"',
                'secret_files = []',
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
        self.assertEqual(sync.configured_secret_names(required, optional, env), {"OPS_TOKEN"})

    def test_missing_required_secret_is_rejected(self) -> None:
        with self.assertRaisesRegex(sync.SyncError, "缺少已登记值"):
            self.preflight("", "")

    def test_env_file_override_must_match_manifest(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        write_sync_fixture(root, ops_token="required-ops-value", optional_token="")
        with self.assertRaisesRegex(sync.SyncError, "必须与 manifest 声明一致"):
            sync.preflight(root, env_file=Path("local/hfs-targets/candidate.env"))

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
