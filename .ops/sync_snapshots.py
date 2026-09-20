"""Mirror completed public Vercel deployments to an isolated Git branch."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time

PROJECT = "prj_x7AZnstTOQGAbD7z8LToVMG978v9"
SCOPE = "irises-projects-ce549f63"
SITE = "danslabtrader.vercel.app"
REMOTE = "https://github.com/DansiDanutz/danslabtrader.git"
BRANCH = "live-snapshots"
FIXED = {"index.html", "paper/index.html", "radar/index.html", "control/index.html",
         "vercel.json", "data/system-map.md"}
DATA = {"analytics", "audits", "autopilot", "health", "radar", "report", "team"}
MAX_FILE = 10 * 1024 * 1024


def run(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, timeout=180)
    if result.returncode:
        # CLI diagnostics can contain authentication details. Do not log them.
        raise RuntimeError("command failed: " + args[0])
    return result.stdout


def api(endpoint):
    return json.loads(run(["vercel", "api", endpoint, "--scope", SCOPE, "--raw"]))


def allowed(name):
    if name in FIXED:
        return True
    if name in {"data/" + key + ".json" for key in DATA}:
        return True
    return bool(re.fullmatch(r"reports/(?:audit48h|daily|weekly)-[0-9]{8}T[0-9]{6}Z\.(?:html|json|md)", name))


def manifest(nodes):
    # The deployment API wraps uploaded source paths in a virtual src directory.
    if len(nodes) == 1 and nodes[0].get("name") == "src" and nodes[0].get("type") == "directory":
        nodes = nodes[0]["children"]
    result = {}
    def walk(entries, parent=""):
        for entry in entries:
            leaf = entry["name"]
            if not leaf or leaf in {".", ".."} or "/" in leaf or "\\" in leaf:
                raise ValueError("unsafe deployment path")
            name = str(PurePosixPath(parent) / leaf)
            if entry["type"] == "directory":
                if name not in {"data", "reports", "paper", "radar", "control"}:
                    # Source-only directories (.git, .ops, tests) are never mirrored.
                    continue
                walk(entry.get("children", []), name)
            elif entry["type"] == "file" and allowed(name):
                uid = entry["uid"]
                if name in result or not re.fullmatch("[0-9a-f]{40}", uid):
                    raise ValueError("invalid deployment manifest")
                result[name] = uid
    walk(nodes)
    if not FIXED.issubset(result):
        raise ValueError("deployment is missing required site files")
    if len(result) > 2000:
        raise ValueError("deployment exceeds mirror limit")
    return result


def verified_bytes(encoded, uid):
    value = base64.b64decode(encoded, validate=True)
    if len(value) > MAX_FILE or hashlib.sha1(value).hexdigest() != uid:
        raise ValueError("deployment file integrity mismatch")
    return value


def mirror_config(raw):
    config = json.loads(raw)
    config["git"] = {**config.get("git", {}), "deploymentEnabled": False}
    return (json.dumps(config, indent=2) + "\n").encode()


def sync(state):
    deployment = api("/v13/deployments/" + SITE)
    if (deployment.get("projectId") != PROJECT or deployment.get("readyState") != "READY"
            or deployment.get("target") != "production" or SITE not in deployment.get("alias", [])):
        raise ValueError("live deployment identity or readiness mismatch")
    uid = deployment["id"]
    if not re.fullmatch("dpl_[A-Za-z0-9]+", uid):
        raise ValueError("invalid deployment identity")
    with tempfile.TemporaryDirectory(prefix="snapshot-", dir=state) as temporary:
        root = Path(temporary)
        run(["git", "init", "-b", BRANCH], root)
        run(["git", "remote", "add", "origin", REMOTE], root)
        exists = run(["git", "ls-remote", "--heads", "origin", BRANCH], root).strip()
        if exists:
            run(["git", "fetch", "--depth=1", "origin", BRANCH], root)
            run(["git", "checkout", "-B", BRANCH, "FETCH_HEAD"], root)
            metadata = root / ".snapshot.json"
            if metadata.is_file() and json.loads(metadata.read_text()).get("deployment_id") == uid:
                return {"status": "unchanged", "deployment_id": uid}
        files = manifest(api("/v6/deployments/" + uid + "/files"))
        cache = state / "cache"
        cache.mkdir(exist_ok=True)
        def fetch(item):
            name, digest = item
            cached = cache / digest
            value = cached.read_bytes() if cached.exists() else None
            if value is None or hashlib.sha1(value).hexdigest() != digest:
                payload = api("/v8/deployments/" + uid + "/files/" + digest)
                value = verified_bytes(payload["data"], digest)
                cached.write_bytes(value)
            return name, value
        with ThreadPoolExecutor(max_workers=4) as pool:
            content = dict(pool.map(fetch, files.items()))
        # Work only in the new temporary checkout. Remove old tracked site files
        # so deleted reports are reflected without touching any user's checkout.
        tracked = run(["git", "ls-files", "-z"], root).split(b"\0")
        for path in tracked:
            if path:
                (root / os.fsdecode(path)).unlink()
        for name, value in content.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(mirror_config(value) if name == "vercel.json" else value)
        provenance = {"deployment_id": uid, "deployment_url": deployment["url"],
                      "public_url": "https://" + SITE, "source_sha1": files,
                      "configuration_difference": "git.deploymentEnabled=false prevents mirror deployments"}
        (root / ".snapshot.json").write_text(json.dumps(provenance, indent=2) + "\n")
        run(["git", "add", "--all"], root)
        run(["git", "-c", "user.name=DansLab Snapshot Sync", "-c",
             "user.email=76887748+DansiDanutz@users.noreply.github.com", "commit", "-m",
             "chore: mirror published snapshot " + uid, "-m",
             "Tested: all public source files verified against Vercel SHA-1 hashes."], root)
        # A concurrent writer causes a normal non-fast-forward rejection, never a force push.
        run(["git", "push", "origin", "HEAD:refs/heads/" + BRANCH], root)
        commit = run(["git", "rev-parse", "HEAD"], root).decode().strip()
        for cached in cache.iterdir():
            if cached.name not in set(files.values()):
                cached.unlink()
        return {"status": "synced", "deployment_id": uid, "commit": commit, "files": len(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    args.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.state / "sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "busy"}))
            return 0
        try:
            result = sync(args.state)
        except Exception as error:
            result = {"status": "failed", "error_type": type(error).__name__}
        result["checked_at"] = time.time()
        target = args.state / "status.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.replace(target)
        print(json.dumps(result))
        return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
