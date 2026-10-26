#!/bin/sh
set -eu

BACKUP_TIME="${BACKUP_TIME:-03:15}"

case "$BACKUP_TIME" in
  [0-2][0-9]:[0-5][0-9]) ;;
  *)
    echo "BACKUP_TIME musi mieć format GG:MM, a jest: '$BACKUP_TIME'" >&2
    exit 1
    ;;
esac

trap 'exit 0' INT TERM

while :; do
  now=$(date +%s)
  next=$(date -d "$BACKUP_TIME" +%s)
  if [ "$next" -le "$now" ]; then
    next=$(date -d "tomorrow $BACKUP_TIME" +%s)
  fi
  echo "Następna kopia: $(date -d "@$next" '+%Y-%m-%d %H:%M %Z')"
  sleep $((next - now)) &
  wait $!
  /backup/backup.sh || echo "Kopia zapasowa nie powiodła się." >&2
done
