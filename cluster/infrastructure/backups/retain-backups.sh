#!/bin/sh
# Called under the app's backup lock, only after publishing a checked archive.
set -eu
folder=$1
current=$2
archive=$3
case "$archive" in database.dump|k3s.tar.gz) ;; *) exit 2 ;; esac
test ! -L "$folder"
test "$(cat "$folder/../.backup-target")" = homelab-cluster-backups-v1
eligible() {
    test -d "$1" && test ! -L "$1" &&
    test -s "$1/$archive" && test ! -L "$1/$archive" &&
    test -s "$1/completed-at.txt" && test ! -L "$1/completed-at.txt" &&
    test -s "$1/SHA256SUMS" && test ! -L "$1/SHA256SUMS"
}
printf '%s\n' "$current" | grep -Eq '^[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9_-]+$'
eligible "$folder/$current"
# The new recovery point must still pass its checksum before any pruning.
(cd "$folder/$current" && sha256sum -c SHA256SUMS >/dev/null)
list=$(mktemp)
trap 'rm -f "$list"' EXIT
for path in "$folder"/*; do
    name=${path##*/}
    printf '%s\n' "$name" | grep -Eq '^[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9_-]+$' || continue
    [ "$name" != "$current" ] || continue
    eligible "$path" || continue
    printf '%s\n' "$name"
done | LC_ALL=C sort -r > "$list"
# Keep the newly completed backup plus the newest 13 prior completed backups.
count=0
while IFS= read -r name; do
    count=$((count + 1))
    [ "$count" -gt 13 ] || continue
    eligible "$folder/$name" || exit 1
    rm -rf -- "$folder/$name"
    printf 'Retention removed: %s\n' "$name"
done < "$list"
