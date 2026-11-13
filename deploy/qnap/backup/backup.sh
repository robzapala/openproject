#!/bin/sh
set -eu
umask 027

BACKUP_ROOT=/backups
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

case "$RETENTION_DAYS" in
  '' | *[!0-9]*)
    echo "BACKUP_RETENTION_DAYS musi być liczbą dni, a jest: '$RETENTION_DAYS'" >&2
    exit 1
    ;;
esac

stamp=$(date +%Y-%m-%d_%H%M)
target="$BACKUP_ROOT/$stamp"

if [ -e "$target" ]; then
  echo "Kopia $target już istnieje, pomijam." >&2
  exit 1
fi

find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -name '.partial-*' -mmin +120 -exec rm -rf {} +

partial=""
trap 'rm -rf "$partial"' EXIT
trap 'exit 1' INT TERM

partial=$(mktemp -d "$BACKUP_ROOT/.partial-XXXXXX")
chmod 750 "$partial"

echo "Zrzut bazy danych..."
pg_dump -Fc -h db -U openproject -f "$partial/openproject.dump" openproject

echo "Pakowanie załączników..."
tar_status=0
tar czf "$partial/assets.tar.gz" --warning=no-file-changed --numeric-owner -C /assets . || tar_status=$?
[ "$tar_status" -le 1 ] || exit "$tar_status"

mv "$partial" "$target"
echo "Kopia gotowa: $target"

find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d \
  -name '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9][0-9][0-9]' \
  -mtime +"$RETENTION_DAYS" -exec sh -c 'rm -rf "$1" && echo "Usunięto starą kopię: $1"' _ {} \;
