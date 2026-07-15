from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare_runtime_config = load_module(
    "prepare_runtime_config",
    ROOT / "docker" / "prepare_runtime_config.py",
)
ops_service = load_module("ops_service", ROOT / "docker" / "ops_service.py")


class PrepareRuntimeConfigTests(unittest.TestCase):
    def write_config(self, directory: Path, payload: dict) -> Path:
        path = directory / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_adds_local_nginx_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_config(Path(temporary), {"security": {}})
            changed = prepare_runtime_config.ensure_local_nginx_proxy(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(changed)
            self.assertEqual(payload["security"]["trusted_proxies"], ["127.0.0.1/32"])

    def test_preserves_existing_network_covering_loopback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            original = {"security": {"trusted_proxies": ["127.0.0.0/8"]}}
            path = self.write_config(Path(temporary), original)
            changed = prepare_runtime_config.ensure_local_nginx_proxy(path)
            self.assertFalse(changed)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_preserves_other_proxy_and_adds_local_nginx(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_config(
                Path(temporary),
                {"security": {"trusted_proxies": ["10.0.0.0/8"]}},
            )
            changed = prepare_runtime_config.ensure_local_nginx_proxy(path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(changed)
            self.assertEqual(
                payload["security"]["trusted_proxies"],
                ["10.0.0.0/8", "127.0.0.1/32"],
            )

    def test_rejects_trust_all_proxy_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_config(
                Path(temporary),
                {"security": {"trusted_proxies": ["0.0.0.0/0"]}},
            )
            with self.assertRaises(prepare_runtime_config.ConfigError):
                prepare_runtime_config.ensure_local_nginx_proxy(path)


class OpsReadinessTests(unittest.TestCase):
    def fake_connection(self, status: int, payload: dict):
        response = mock.Mock()
        response.status = status
        response.read.return_value = json.dumps(payload).encode("utf-8")
        connection = mock.Mock()
        connection.getresponse.return_value = response
        return connection

    def test_readiness_accepts_upstream_200(self) -> None:
        connection = self.fake_connection(200, {"status": "ok", "uptime_seconds": 12.5})
        with mock.patch.object(ops_service, "HTTPConnection", return_value=connection):
            ready, detail = ops_service.qwenpaw_readiness("127.0.0.1", 8088)
        self.assertTrue(ready)
        self.assertEqual(detail["http_status"], 200)
        self.assertEqual(detail["status"], "ok")

    def test_readiness_rejects_upstream_503(self) -> None:
        connection = self.fake_connection(503, {"status": "starting"})
        with mock.patch.object(ops_service, "HTTPConnection", return_value=connection):
            ready, detail = ops_service.qwenpaw_readiness("127.0.0.1", 8088)
        self.assertFalse(ready)
        self.assertEqual(detail["http_status"], 503)

    def test_readiness_handles_http_failure(self) -> None:
        with mock.patch.object(
            ops_service,
            "HTTPConnection",
            side_effect=ops_service.HTTPException("closed"),
        ):
            ready, detail = ops_service.qwenpaw_readiness("127.0.0.1", 8088)
        self.assertFalse(ready)
        self.assertEqual(detail["error"], "HTTPException")


if __name__ == "__main__":
    unittest.main()
