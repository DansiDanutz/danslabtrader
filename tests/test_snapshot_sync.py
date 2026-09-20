import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("sync", Path(__file__).parents[1] / ".ops/sync_snapshots.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

class SnapshotTests(unittest.TestCase):
    def test_allowlist_excludes_secrets_and_arbitrary_files(self):
        for path in [".env", ".vercel/project.json", "data/credentials.json", "../index.html", "reports/secret.json", "scripts/publish.py"]:
            self.assertFalse(sync.allowed(path), path)
        self.assertTrue(sync.allowed("reports/daily-20260920T060000Z.json"))
        self.assertTrue(sync.allowed("data/autopilot.json"))

    def test_integrity_failure_stops_import(self):
        raw = b"published snapshot"
        digest = hashlib.sha1(raw).hexdigest()
        self.assertEqual(sync.verified_bytes(base64.b64encode(raw), digest), raw)
        with self.assertRaises(ValueError):
            sync.verified_bytes(base64.b64encode(b"changed"), digest)

    def test_missing_required_files_stops_import(self):
        with self.assertRaises(ValueError):
            sync.manifest([])

    def test_path_traversal_rejected(self):
        for name in ["..", "../index.html", "/index.html", "data\\secret"]:
            with self.assertRaises(ValueError):
                sync.manifest([{"name": name, "type": "file", "uid": "0" * 40}])

    def test_mirror_config_preserves_headers_and_disables_deployments(self):
        original = {"version": 2, "headers": [{"source": "/", "headers": []}], "git": {"other": True}}
        actual = json.loads(sync.mirror_config(json.dumps(original).encode()))
        self.assertEqual(actual["headers"], original["headers"])
        self.assertIs(actual["git"]["deploymentEnabled"], False)
        self.assertTrue(actual["git"]["other"])

    def test_real_deployment_manifest_parses(self):
        nodes = []
        for name in sync.FIXED:
            parts = name.split("/")
            file = {"name": parts[-1], "type": "file", "uid": "a" * 40}
            nodes.append(file if len(parts) == 1 else {"name": parts[0], "type": "directory", "children": [file]})
        result = sync.manifest([{"name": "src", "type": "directory", "children": nodes}])
        self.assertEqual(set(result), sync.FIXED)

if __name__ == "__main__":
    unittest.main()
