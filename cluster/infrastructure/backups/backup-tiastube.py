"""Read-only online SQLite export; publish under the dedicated backup identity."""
import contextlib
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile


def export(source, archive):
    database = source / "tracearr.sqlite3"
    config = source / "private/tracearr/tracearr.json"
    # Require config: silently omitting credentials would create an incomplete export.
    if not database.is_file() or not config.is_file():
        raise RuntimeError("Database or private configuration missing")
    config_bytes = config.read_bytes()
    json.loads(config_bytes)
    with tempfile.TemporaryDirectory() as tmp:
        copied = Path(tmp) / "tracearr.sqlite3"
        with contextlib.closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=30)) as src:
            with contextlib.closing(sqlite3.connect(copied)) as dst:
                src.backup(dst, pages=256, sleep=0.1)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("SQLite integrity check failed")
        if config.read_bytes() != config_bytes:
            raise RuntimeError("Configuration changed during backup; retry")
        private = Path(tmp) / "tracearr.json"
        private.write_bytes(config_bytes)
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(copied, arcname="tracearr.sqlite3")
            bundle.add(private, arcname="private/tracearr/tracearr.json")
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                with bundle.extractfile(member) as stream:
                    while stream.read(1024 * 1024):
                        pass


def main():
    os.umask(0o077)
    # Export needs the same NFS identity as the current root-owned application.
    # The source mount is read-only. No Kubernetes API credentials are provided.
    work = Path(tempfile.mkdtemp(prefix="tiastube-export-"))
    archive = work / "tiastube.tar.gz"
    try:
        export(Path("/source"), archive)
        # Transfer the file first: after transferring the mode-0700 directory,
        # capability-restricted root can no longer traverse it.
        os.chown(archive, 3900, 3001)
        os.chown(work, 3900, 3001)
        os.setgroups([])
        os.setgid(3001)
        os.setuid(3900)
        root = Path("/backups")
        if (root / ".backup-target").read_text().strip() != "homelab-cluster-backups-v1":
            raise RuntimeError("Backup destination marker mismatch")
        folder = root / "tiastube"
        folder.mkdir(exist_ok=True)
        lock = folder / ".lock"
        lock.mkdir()
        stage = None
        try:
            stage = Path(tempfile.mkdtemp(prefix=".partial.", dir=folder))
            target = stage / archive.name
            shutil.copyfile(archive, target)
            with archive.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise RuntimeError("Destination checksum mismatch")
            (stage / "SHA256SUMS").write_text(f"{digest}  {target.name}\n")
            now = datetime.datetime.now(datetime.timezone.utc)
            (stage / "completed-at.txt").write_text(now.isoformat() + "\n")
            name = now.strftime("%Y%m%dT%H%M%SZ") + "-" + stage.name.rsplit(".", 1)[-1]
            stage.rename(folder / name)
            stage = None
            subprocess.run(["sh", str(Path(__file__).with_name("retain-backups.sh")),
                            str(folder), name, archive.name], check=True)
            print(f"Backup complete: tiastube/{name} (SQLite integrity and archive checks passed; restore test still required)", flush=True)
        finally:
            if stage is not None:
                shutil.rmtree(stage)
            lock.rmdir()
    finally:
        shutil.rmtree(work)


if __name__ == "__main__":
    main()
