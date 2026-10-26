#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Użycie: $0 [--yes] <katalog-kopii>" >&2
  echo "Przykład: $0 /share/Backup/openproject/2026-10-26_0315" >&2
  exit 2
}

assume_yes=false
backup_dir=""
for arg in "$@"; do
  case "$arg" in
    --yes) assume_yes=true ;;
    -*) usage ;;
    *) [ -z "$backup_dir" ] || usage; backup_dir="$arg" ;;
  esac
done
[ -n "$backup_dir" ] || usage

cd "$(dirname "$0")"

[ -f .env ] || { echo "Brak pliku .env w $(pwd). Skopiuj .env.example do .env." >&2; exit 1; }
[ -d "$backup_dir" ] || { echo "Nie znaleziono katalogu kopii: $backup_dir" >&2; exit 1; }
backup_dir=$(cd "$backup_dir" && pwd)
for file in openproject.dump assets.tar.gz; do
  [ -f "$backup_dir/$file" ] || { echo "Brak pliku $file w $backup_dir" >&2; exit 1; }
done

data_dir=$(grep -E '^OP_DATA_DIR=' .env | tail -n1 | cut -d= -f2- | tr -d "\"'\r" || true)
assets_dir="${data_dir:-/share/Container/openproject}/assets"

if [ "$assume_yes" != true ]; then
  echo "UWAGA: odtworzenie zastąpi CAŁĄ bazę danych i wszystkie załączniki danymi z:"
  echo "  $backup_dir"
  echo "Aktualne dane zostaną bezpowrotnie utracone. Aplikacja będzie chwilowo niedostępna."
  read -r -p "Kontynuować? [t/N] " answer || answer=""
  case "$answer" in
    t | T | tak | TAK | y | Y | yes) ;;
    *) echo "Przerwano."; exit 1 ;;
  esac
fi

echo "Zatrzymuję aplikację..."
docker compose stop web worker

echo "Uruchamiam bazę danych..."
docker compose up -d --wait db

echo "Odtwarzam bazę danych..."
docker compose exec -T db pg_restore --clean --if-exists --no-owner --single-transaction \
  -U openproject -d openproject < "$backup_dir/openproject.dump"

echo "Odtwarzam załączniki do $assets_dir ..."
docker compose run --rm --no-deps -T --entrypoint sh \
  -v "$backup_dir:/restore:ro" -v "$assets_dir:/restore-assets" backup \
  -c 'find /restore-assets -mindepth 1 -delete && tar xzf /restore/assets.tar.gz --numeric-owner -C /restore-assets'

echo "Uruchamiam aplikację..."
docker compose up -d

echo "Gotowe. Aplikacja startuje, poczekaj kilka minut i sprawdź: docker compose ps"
