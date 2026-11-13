"""Explicit, restartable synchronization of local documents to StepFun retrieval."""

import argparse
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import quote, urlencode

from dotenv import load_dotenv
import requests

from audio import state_directory

AGENT_DIRECTORY = Path(__file__).resolve().parent.parent / "agent"
EXTENSIONS = {".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
              ".ppt", ".pptx", ".csv", ".html", ".htm", ".xml"}


def load_secret():
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    config = Path(os.environ.get("GUIDEBOT_CONFIG_FILE", base / "guidebot/conversation.env"))
    load_dotenv(config, override=False, interpolate=False)
    secret = os.environ.get("STEP_SECRET") or os.environ.get("STEP_API_KEY")
    if not secret:
        raise ValueError(f"Set STEP_SECRET in {config}")
    return secret


def read_soul(agent_directory=AGENT_DIRECTORY):
    path = Path(agent_directory) / "soul.md"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Instructions file is empty: {path}")
    return text


class KnowledgeAPIError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class KnowledgeAPI:
    def __init__(self, secret):
        self.secret = secret

    def request(self, method, path, payload=None, *, data=None, files=None):
        try:
            with requests.request(method, "https://api.stepfun.com/v1" + path,
                                  headers={"Authorization": f"Bearer {self.secret}"},
                                  json=payload, data=data, files=files, timeout=(10, 30)) as response:
                if not response.ok:
                    detail = response.text[:4096].replace(self.secret, "[redacted]")
                    raise KnowledgeAPIError(response.status_code,
                        f"StepFun {method} {path}: HTTP {response.status_code}: {detail}")
                return response.json() if response.content else {}
        except requests.RequestException as error:
            detail = str(error).replace(self.secret, "[redacted]")
            raise RuntimeError(f"StepFun {method} {path}: {detail}") from None

    def upload(self, path, content):
        return self.request("POST", "/files", data={"purpose": "retrieval-text"},
                            files={"file": (path.name, content, "application/octet-stream")})["id"]

    def wait_file(self, file_id, timeout=180):
        deadline = time.monotonic() + timeout
        while True:
            status = self.request("GET", "/files/" + quote(file_id, safe="")).get("status")
            if status == "success":
                return
            if status != "processed":
                raise RuntimeError(f"File {file_id} has unexpected parsing status: {status}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"File parsing timed out: {file_id}; run sync again to resume")
            time.sleep(1)

    def associations(self, store_id):
        result, cursor = set(), None
        while True:
            params = {"limit": 100}
            if cursor:
                params["after"] = cursor
            page = self.request("GET", f"/vector_stores/{quote(store_id, safe='')}/files?" + urlencode(params))
            # The API returns data=null for an empty knowledge store.
            items = page.get("data")
            if items is None:
                items = []
            if not isinstance(items, list):
                raise RuntimeError("Unexpected knowledge file list response: data must be a list or null")
            result.update(item["id"] for item in items)
            if not page.get("has_more"):
                return result
            next_cursor = page.get("last_id")
            if not next_cursor or next_cursor == cursor:
                raise RuntimeError("Knowledge file pagination did not advance")
            cursor = next_cursor

    def attach(self, store_id, file_id):
        self.request("POST", f"/vector_stores/{quote(store_id, safe='')}/files",
                     {"files": [{"file_id": file_id,
                                 "description": "珠海香洲创港中心 GuideBot 导览咨询知识资料"}]})

    def remove(self, store_id, file_id):
        path = f"/vector_stores/{quote(store_id, safe='')}/files/{quote(file_id, safe='')}"
        try:
            self.request("DELETE", path)
        except KnowledgeAPIError as error:
            if error.status != 404:
                raise


def _scan(directory):
    if not directory.is_dir():
        raise ValueError(f"Knowledge directory does not exist: {directory}")
    files = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Knowledge symlinks are not supported: {relative}")
        if path.is_dir():
            continue
        if path.suffix.lower() not in EXTENSIONS:
            raise ValueError(f"Unsupported knowledge file: {relative}")
        if not 0 < path.stat().st_size <= 64 * 1024 * 1024:
            raise ValueError(f"Knowledge files must be nonempty and <=64 MiB: {relative}")
        with path.open("rb") as source:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(chunk)
            digest = hasher.hexdigest()
        files[relative.as_posix()] = digest
    return files


def _manifest_path(directory, state_dir):
    key = hashlib.sha256(str(directory).encode("utf-8")).hexdigest()[:16]
    return Path(state_dir or state_directory()) / "knowledge" / key / "manifest.json"


def _read_manifest(path, directory):
    if not path.exists():
        return {"schema": 1, "directory": str(directory), "vector_store_id": None,
                "files": {}, "pending": {}, "retired": [], "ready": False}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema") != 1 or state.get("directory") != str(directory):
        raise ValueError(f"Unexpected knowledge synchronization state: {path}")
    return state


def _save(path, state):
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".manifest-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(state, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass(frozen=True)
class SyncResult:
    vector_store_id: str | None
    added: tuple
    modified: tuple
    deleted: tuple
    repaired: tuple = ()
    dry_run: bool = False


def load_knowledge(directory=AGENT_DIRECTORY / "knowledge", *, state_dir=None):
    directory = Path(directory).resolve()
    state = _read_manifest(_manifest_path(directory, state_dir), directory)
    if not state.get("ready") or not state.get("vector_store_id") or not state.get("files"):
        raise RuntimeError("No successfully synchronized knowledge base. Add documents and run "
                           "knowledge.py, or start conversation.py with --sync-knowledge.")
    return state["vector_store_id"]


def sync_knowledge(directory=AGENT_DIRECTORY / "knowledge", *, dry_run=False,
                   secret=None, state_dir=None):
    """Synchronize this component's documents; no-change runs never upload again."""
    directory = Path(directory).resolve()
    snapshot = _scan(directory)
    path = _manifest_path(directory, state_dir)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (path.parent / "sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Knowledge synchronization is already running") from None
        state = _read_manifest(path, directory)
        previous = state["files"]
        added = tuple(name for name in snapshot if name not in previous)
        modified = tuple(name for name in snapshot if name in previous and snapshot[name] != previous[name]["sha256"])
        deleted = tuple(name for name in previous if name not in snapshot)
        if dry_run:
            return SyncResult(state["vector_store_id"], added, modified, deleted, dry_run=True)
        if not snapshot:
            raise ValueError("Knowledge directory is empty; add documents before synchronization")
        api = KnowledgeAPI(secret or load_secret())
        state["ready"] = False
        _save(path, state)
        if not state["vector_store_id"]:
            state["vector_store_id"] = api.request("POST", "/vector_stores",
                {"name": "GuideBot_" + path.parent.name, "type": "text"})["id"]
            _save(path, state)
        store_id = state["vector_store_id"]
        remote = api.associations(store_id)
        owned = {entry["file_id"] for entry in previous.values()}
        owned.update(entry["file_id"] for entry in state["pending"].values())
        owned.update(state["retired"])
        if remote - owned:
            raise RuntimeError("Cloud knowledge contains unmanaged file associations; "
                               "resolve them before synchronization. No unknown files were removed.")
        repaired = []
        for name, staged in list(state["pending"].items()):
            current = previous.get(name)
            already_current = (current and current["sha256"] == snapshot.get(name)
                               and current["file_id"] in remote)
            if staged["sha256"] != snapshot.get(name) or already_current:
                if not current or current["file_id"] != staged["file_id"]:
                    state["retired"].append(staged["file_id"])
                del state["pending"][name]
                _save(path, state)
        # Journal uploaded IDs before waiting/attaching, so ordinary failures resume.
        for name, digest in snapshot.items():
            current = previous.get(name)
            if current and current["sha256"] == digest and current["file_id"] in remote:
                continue
            staged = state["pending"].get(name)
            if staged and staged["sha256"] != digest:
                state["retired"].append(staged["file_id"])
                del state["pending"][name]
                staged = None
                _save(path, state)
            if not staged and current and current["sha256"] == digest:
                try:
                    api.wait_file(current["file_id"])
                    staged = dict(current)
                    repaired.append(name)
                except KnowledgeAPIError as error:
                    if error.status != 404:
                        raise
            if not staged:
                content = (directory / name).read_bytes()
                if hashlib.sha256(content).hexdigest() != digest:
                    raise RuntimeError(f"Knowledge file changed during synchronization: {name}")
                staged = {"sha256": digest, "file_id": api.upload(directory / name, content)}
            state["pending"][name] = staged
            _save(path, state)
            api.wait_file(staged["file_id"])
            if staged["file_id"] not in remote:
                api.attach(store_id, staged["file_id"])
                remote.add(staged["file_id"])
            if current and current["file_id"] != staged["file_id"]:
                state["retired"].append(current["file_id"])
            previous[name] = staged
            del state["pending"][name]
            _save(path, state)
        for name in deleted:
            state["retired"].append(previous.pop(name)["file_id"])
            _save(path, state)
        for name in list(state["pending"]):
            if name not in snapshot:
                state["retired"].append(state["pending"].pop(name)["file_id"])
                _save(path, state)
        for file_id in list(state["retired"]):
            api.remove(store_id, file_id)
            state["retired"].remove(file_id)
            _save(path, state)
        if _scan(directory) != snapshot:
            raise RuntimeError("Knowledge changed during synchronization; run sync again")
        remote = api.associations(store_id)
        if not {entry["file_id"] for entry in previous.values()} <= remote:
            raise RuntimeError("Cloud knowledge associations are not ready; run sync again")
        state["ready"] = True
        state["synced_at"] = time.time()
        _save(path, state)
        return SyncResult(store_id, added, modified, deleted, tuple(repaired))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=AGENT_DIRECTORY / "knowledge")
    parser.add_argument("--dry-run", action="store_true", help="List local changes without cloud requests")
    args = parser.parse_args()
    result = sync_knowledge(args.directory, dry_run=args.dry_run)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(str(error)) from None
