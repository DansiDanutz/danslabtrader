import base64
from contextlib import redirect_stdout
import fcntl
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("workflow_sync", Path(__file__).parents[1] / ".ops/sync_snapshots.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.git("init", "--bare", str(self.remote))
        self.state = self.root / "state"
        self.state.mkdir()
        self.content = {name: (b"{}" if name == "vercel.json" else ("content: " + name).encode()) for name in sync.FIXED}
        self.content["reports/daily-20260920T060000Z.json"] = b"{}"
        self.deployment = {"projectId": sync.PROJECT, "readyState": "READY", "target": "production",
                           "alias": [sync.SITE], "id": "dpl_fixture", "url": "fixture.vercel.app", "source": "cli"}
        self.api_patch = patch.object(sync, "api", side_effect=self.api)
        self.mock_api = self.api_patch.start()
        self.addCleanup(self.api_patch.stop)
        remote_patch = patch.object(sync, "REMOTE", str(self.remote))
        remote_patch.start()
        self.addCleanup(remote_patch.stop)

    def git(self, *args, cwd=None):
        return subprocess.check_output(["git", *args], cwd=cwd, stderr=subprocess.DEVNULL)

    def head(self):
        return self.git("--git-dir=" + str(self.remote), "rev-parse", sync.BRANCH)

    def show(self, name):
        return self.git("--git-dir=" + str(self.remote), "show", sync.BRANCH + ":" + name)

    def api(self, endpoint):
        if endpoint.startswith("/v13/"):
            return self.deployment
        if endpoint.startswith("/v6/"):
            directories = {}
            files = []
            for name, data in self.content.items():
                parts = name.split("/")
                node = {"name": parts[-1], "type": "file", "uid": hashlib.sha1(data).hexdigest()}
                if len(parts) == 1:
                    files.append(node)
                else:
                    directories.setdefault(parts[0], []).append(node)
            files += [{"name": name, "type": "directory", "children": nodes} for name, nodes in directories.items()]
            return [{"name": "src", "type": "directory", "children": files}]
        digest = endpoint.rsplit("/", 1)[1]
        data = next(data for data in self.content.values() if hashlib.sha1(data).hexdigest() == digest)
        return {"data": base64.b64encode(data).decode()}

    def test_success_unchanged_and_deleted_report(self):
        self.assertEqual(sync.sync(self.state)["status"], "synced")
        first = self.head()
        self.assertEqual(self.show("index.html"), self.content["index.html"])
        provenance = json.loads(self.show(".snapshot.json"))
        self.assertEqual(provenance["source_sha1"]["index.html"], hashlib.sha1(self.content["index.html"]).hexdigest())
        self.mock_api.reset_mock()
        self.assertEqual(sync.sync(self.state)["status"], "unchanged")
        self.assertEqual(first, self.head())
        self.assertTrue(any(call.args[0].startswith("/v6/") for call in self.mock_api.call_args_list))
        del self.content["reports/daily-20260920T060000Z.json"]
        self.deployment["id"] = "dpl_next"
        self.assertEqual(sync.sync(self.state)["status"], "synced")
        names = self.git("--git-dir=" + str(self.remote), "ls-tree", "-r", "--name-only", sync.BRANCH).decode()
        self.assertNotIn("reports/daily-20260920T060000Z.json", names)

    def test_repairs_tampered_files_and_provenance_with_same_deployment(self):
        sync.sync(self.state)
        checkout = self.root / "tamper"
        self.git("clone", "-b", sync.BRANCH, str(self.remote), str(checkout))
        (checkout / "index.html").write_text("tampered")
        provenance = json.loads((checkout / ".snapshot.json").read_text())
        provenance["source_sha1"]["index.html"] = "0" * 40
        (checkout / ".snapshot.json").write_text(json.dumps(provenance))
        (checkout / "vercel.json").write_text('{"git":{"deploymentEnabled":true}}')
        self.git("add", "--all", cwd=checkout)
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "tamper", cwd=checkout)
        self.git("push", "origin", sync.BRANCH, cwd=checkout)
        self.assertEqual(sync.sync(self.state)["status"], "synced")
        self.assertEqual(self.show("index.html"), self.content["index.html"])
        self.assertFalse(json.loads(self.show("vercel.json"))["git"]["deploymentEnabled"])
        self.assertEqual(json.loads(self.show(".snapshot.json"))["source_sha1"]["index.html"], hashlib.sha1(self.content["index.html"]).hexdigest())

    def test_download_failure_preserves_remote(self):
        sync.sync(self.state)
        before = self.head()
        self.deployment["id"] = "dpl_next"
        self.content["index.html"] = b"new page"
        def failing(endpoint):
            if endpoint.startswith("/v8/"):
                raise RuntimeError("download failed")
            return self.api(endpoint)
        with patch.object(sync, "api", side_effect=failing), self.assertRaises(RuntimeError):
            sync.sync(self.state)
        self.assertEqual(before, self.head())

    def test_main_records_failure_without_exposing_diagnostics(self):
        with patch("sys.argv", ["sync", "--state", str(self.state)]), patch.object(sync, "sync", side_effect=RuntimeError("secret diagnostic")), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(sync.main(), 1)
        result = json.loads((self.state / "status.json").read_text())
        self.assertEqual(result["status"], "failed")
        self.assertIn("checked_at", result)
        self.assertNotIn("secret diagnostic", output.getvalue())

    def test_lock_skips_concurrent_run(self):
        with (self.state / "sync.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch("sys.argv", ["sync", "--state", str(self.state)]), patch.object(sync, "sync") as work, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(sync.main(), 0)
                work.assert_not_called()
                self.assertEqual(json.loads(output.getvalue())["status"], "busy")
