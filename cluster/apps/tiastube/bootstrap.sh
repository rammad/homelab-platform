#!/usr/bin/env bash
# Run on the k3s master, from a fresh homelab-iac checkout, with sudo.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
archive=${1:?Usage: sudo bash bootstrap.sh /path/to/tiastube-migration.tar}
test -f "$archive"
# Refuse initial import into a running/existing app. This is not an upgrade tool.
if kubectl -n tools get deployment tiastube >/dev/null 2>&1; then
  echo 'TiasTube already exists. Use GitOps updates or the app restore UI.' >&2; exit 1
fi
kubectl get services -A -o json | python3 -c '
import json,sys
for service in json.load(sys.stdin)["items"]:
 for port in service["spec"].get("ports",[]):
  if port.get("nodePort")==30865:sys.exit("NodePort 30865 is already in use; choose another before rollout.")'
kubectl get namespace tools >/dev/null
# Only this temporary pod mounts the parent export to create the app directory.
kubectl create -f - <<'YAML'
apiVersion: v1
kind: Pod
metadata:
  name: tiastube-bootstrap
  namespace: tools
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  containers:
    - name: bootstrap
      image: python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb
      command: [python, -c, 'import time; time.sleep(3600)']
      volumeMounts:
        - name: nas
          mountPath: /nas
  volumes:
    - name: nas
      nfs:
        server: 192.0.2.30
        path: /mnt/application-pool/k3s-app-data
YAML
trap 'kubectl -n tools delete pod tiastube-bootstrap --wait=false >/dev/null' EXIT
kubectl -n tools wait --for=condition=Ready pod/tiastube-bootstrap --timeout=180s
# A fixed allowlist avoids arbitrary paths and never changes sibling app data.
kubectl -n tools exec -i tiastube-bootstrap -- python -c '
import sys,tarfile,pathlib,tempfile,sqlite3,os,shutil,json
root=pathlib.Path("/nas/tiastube")
if root.exists():sys.exit("NAS tiastube directory already exists; preserve it and inspect before retrying.")
stage=pathlib.Path(tempfile.mkdtemp(prefix=".tiastube-import-",dir="/nas"))
try:
 seen=set()
 with tarfile.open(fileobj=sys.stdin.buffer,mode="r|*") as tar:
  for member in tar:
   if member.name not in ("tracearr.sqlite3","private/tracearr/tracearr.json") or not member.isfile() or member.name in seen or member.size>64*1024*1024:raise ValueError("Invalid migration archive")
   seen.add(member.name);target=stage/member.name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
   with tar.extractfile(member) as source,target.open("wb") as destination:shutil.copyfileobj(source,destination)
   target.chmod(0o600)
 if "tracearr.sqlite3" not in seen:raise ValueError("Missing database")
 with sqlite3.connect(stage/"tracearr.sqlite3") as db:
  if db.execute("pragma integrity_check").fetchone()[0]!="ok":raise ValueError("Database integrity check failed")
  db.execute("pragma journal_mode=DELETE")
  print("Imported playback records:",db.execute("select count(*) from sessions").fetchone()[0])
 os.rename(stage,root)
 print("Imported existing data into dedicated NAS directory.")
except BaseException:
 shutil.rmtree(stage);raise
' < "$archive"
kubectl apply --dry-run=server -k . >/dev/null
printf '\nData imported and manifests validated. Register bootstrap/tiastube-application.yaml in Argo, then sync manually.\n'
printf 'After sync: http://192.0.2.10:30865\n'
