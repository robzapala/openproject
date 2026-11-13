#!/bin/sh
set -eu

BACKUP_TIME="${BACKUP_TIME:-03:15}"

case "$BACKUP_TIME" in
  [01][0-9]:[0-5][0-9] | 2[0-3]:[0-5][0-9]) ;;
  *)
    echo "BACKUP_TIME musi mieć format GG:MM, a jest: '$BACKUP_TIME'" >&2
    exit 1
    ;;
esac

trap 'exit 0' INT TERM

next_run() {
  next=$(date -d "$BACKUP_TIME" +%s) || return 1
  if [ "$next" -le "$1" ]; then
    next=$(date -d "tomorrow $BACKUP_TIME" +%s) || return 1
  fi
  echo "$next"
}

while :; do
  now=$(date +%s)
  if ! next=$(next_run "$now"); then
    echo "Nie można obliczyć terminu kopii dla BACKUP_TIME=$BACKUP_TIME, ponawiam za godzinę." >&2
    sleep 3600 &
    wait $!
    continue
  fi
  echo "Następna kopia: $(date -d "@$next" '+%Y-%m-%d %H:%M %Z')"
  sleep $((next - now)) &
  wait $!
  /backup/backup.sh || echo "Kopia zapasowa nie powiodła się." >&2
done
