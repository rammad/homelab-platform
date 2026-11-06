"""Online k3s SQLite recovery archive; no service stop or host writes."""
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


def export(source, archive, rancher=Path("/host-config/rancher"),
           systemd=Path("/host-config/systemd"), kubelet=Path("/host-config/kubelet")):
    database = source / "db/state.db"
    token = source / "token"
    if not database.is_file() or (source / "db/etcd").exists():
        raise RuntimeError("Expected SQLite datastore; refusing other datastore layouts")
    token_before = token.read_bytes()
    if not token_before.strip():
        raise RuntimeError("Server token missing")
    for required in (rancher / "k3s/config.yaml", rancher / "node/password", systemd / "k3s.service"):
        if not required.is_file():
            raise RuntimeError("Required node configuration missing")
    with tempfile.TemporaryDirectory() as tmp:
        copied = Path(tmp) / "state.db"
        with contextlib.closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=30)) as src:
            with contextlib.closing(sqlite3.connect(copied)) as dst:
                src.backup(dst, pages=256, sleep=0.1)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("SQLite integrity check failed")
                if not dst.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kine'").fetchone():
                    raise RuntimeError("Expected k3s kine table missing")
        private_token = Path(tmp) / "token"
        private_token.write_bytes(token_before)
        def archive_entry(info):
            # Host-absolute links may be dangling inside this container.
            # Preserve their identity without reading outside the mounted roots.
            return info if info.isfile() or info.isdir() or info.issym() or info.islnk() else None
        with tarfile.open(archive, "w:gz", dereference=False) as bundle:
            prefix = "var/lib/rancher/k3s/server/"
            bundle.add(copied, arcname=prefix + "db/state.db")
            bundle.add(private_token, arcname=prefix + "token")
            # Do not copy live SQLite/WAL/SHM files. Preserve certificates/manifests.
            for child in sorted(source.iterdir()):
                if child.name not in {"db", "token", "node-token"}:
                    bundle.add(child, arcname=prefix + child.name, filter=archive_entry)
            bundle.add(rancher, arcname="etc/rancher", filter=archive_entry)
            for name in ("k3s.service", "k3s.service.env", "k3s.service.d"):
                path = systemd / name
                if path.exists() or path.is_symlink():
                    bundle.add(path, arcname="etc/systemd/system/" + name, filter=archive_entry)
            bundle.add(kubelet, arcname="var/lib/rancher/k3s/agent/etc/kubelet.conf.d", filter=archive_entry)
        if token.read_bytes() != token_before:
            raise RuntimeError("Server token changed during backup; retry after rotation completes")
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                if member.isfile():
                    with bundle.extractfile(member) as stream:
                        while stream.read(1024 * 1024):
                            pass


def main():
    os.umask(0o077)
    # Export requires root to read control-plane credentials from read-only host mounts.
    # The source mount is read-only. No Kubernetes API credentials are provided.
    work = Path(tempfile.mkdtemp(prefix="k3s-export-"))
    archive = work / "k3s.tar.gz"
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
        folder = root / "k3s"
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
            print(f"Backup complete: k3s/{name} (SQLite integrity and archive checks passed; restore test still required)", flush=True)
        finally:
            if stage is not None:
                shutil.rmtree(stage)
            lock.rmdir()
    finally:
        shutil.rmtree(work)


if __name__ == "__main__":
    main()
