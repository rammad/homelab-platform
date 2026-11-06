#!/bin/sh
set -eu
umask 077
: "${APP:?}" "${PGHOST:?}" "${PGDATABASE:?}" "${PGUSER:?}" "${PGPASSWORD:?}"
case "$APP" in immich|tracearr|nextcloud) ;; *) exit 2 ;; esac
root="${BACKUP_ROOT:-/backups}"
test -d "$root"
test "$(cat "$root/.backup-target")" = homelab-cluster-backups-v1
folder="$root/$APP"
mkdir -p "$folder"
# mkdir is also the lock for manual Jobs; CronJob Forbid covers scheduled overlap.
lock="$folder/.lock"
mkdir "$lock" || { echo "Backup lock exists; inspect active jobs before removing it" >&2; exit 1; }
stage=''
cleanup() {
    if [ -n "$stage" ] && [ -d "$stage" ]; then rm -rf -- "$stage"; fi
    rmdir "$lock"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
stage=$(mktemp -d "$folder/.partial.XXXXXX")
date -u +%FT%TZ > "$stage/started-at.txt"
pg_dump --no-password --format=custom --lock-wait-timeout=60s --file="$stage/database.dump" 2>"$stage/dump.stderr" || {
    echo "Database dump failed; check connectivity, credentials, and database logs (details suppressed)" >&2; exit 1;
}
test -s "$stage/database.dump"
pg_restore --list "$stage/database.dump" > "$stage/contents.txt" 2>"$stage/verify.stderr"
grep -q 'TABLE DATA' "$stage/contents.txt"
pg_dump --version > "$stage/client-version.txt"
psql --no-password -X -At -v ON_ERROR_STOP=1 -c 'SELECT version()' > "$stage/server-version.txt" 2>"$stage/version.stderr"
psql --no-password -X -At -v ON_ERROR_STOP=1 -c 'SELECT extname, extversion FROM pg_extension ORDER BY extname' > "$stage/extensions.txt" 2>>"$stage/version.stderr"
(cd "$stage" && sha256sum database.dump > SHA256SUMS && sha256sum -c SHA256SUMS >/dev/null)
date -u +%FT%TZ > "$stage/completed-at.txt"
name="$(date -u +%Y%m%dT%H%M%SZ)-${stage##*.}"
# Publish only after all checks succeed. Partial directories never count as backups.
mv "$stage" "$folder/$name"
stage=''
sh "$(dirname "$0")/retain-backups.sh" "$folder" "$name" database.dump
printf 'Backup complete: %s/%s (archive checks passed; restore test still required)\n' "$APP" "$name"
