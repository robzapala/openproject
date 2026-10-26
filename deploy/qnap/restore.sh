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

restore_tmp=/restore-assets/.restore-tmp

run_in_backup_container() {
  docker compose run --rm --no-deps -T --entrypoint sh \
    -v "$backup_dir:/restore:ro" -v "$assets_dir:/restore-assets" backup -c "$1"
}

echo "Sprawdzam poprawność kopii..."
if ! docker compose run --rm --no-deps -T --entrypoint sh -v "$backup_dir:/restore:ro" backup \
  -c 'gzip -t /restore/assets.tar.gz && tar tzf /restore/assets.tar.gz >/dev/null' >/dev/null; then
  echo "Plik assets.tar.gz jest uszkodzony lub niepełny. Nic nie zostało zmienione." >&2
  exit 1
fi
if ! docker compose run --rm --no-deps -T --entrypoint sh -v "$backup_dir:/restore:ro" backup \
  -c 'pg_restore -l /restore/openproject.dump >/dev/null' >/dev/null; then
  echo "Plik openproject.dump jest uszkodzony lub niepełny. Nic nie zostało zmienione." >&2
  exit 1
fi

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

stage=""
db_state="bez zmian"
assets_state="bez zmian"

report_failure() {
  local status=$?
  [ "$status" -ne 0 ] && [ -n "$stage" ] || return 0
  {
    echo
    echo "BŁĄD na etapie: $stage."
    echo "  Baza danych: $db_state"
    echo "  Załączniki:  $assets_state"
    echo "  Aplikacja (web, worker) może być zatrzymana."
    echo "Kopia w $backup_dir nie została zmieniona; po usunięciu przyczyny uruchom restore.sh ponownie."
    echo "Aby tylko uruchomić aplikację z obecnymi danymi: docker compose up -d"
  } >&2
}
trap report_failure EXIT

stage="zatrzymywanie aplikacji"
echo "Zatrzymuję aplikację..."
docker compose stop web worker

stage="uruchamianie bazy danych"
echo "Uruchamiam bazę danych..."
docker compose up -d --wait db

stage="odtwarzanie bazy danych"
echo "Odtwarzam bazę danych..."
docker compose exec -T db pg_restore --clean --if-exists --no-owner --single-transaction \
  -U openproject -d openproject < "$backup_dir/openproject.dump"
db_state="ODTWORZONA z kopii"

stage="rozpakowywanie załączników"
echo "Rozpakowuję załączniki..."
run_in_backup_container "
  set -e
  rm -rf $restore_tmp
  mkdir $restore_tmp
  tar xzf /restore/assets.tar.gz --numeric-owner -C $restore_tmp || { rm -rf $restore_tmp; exit 1; }
"

stage="podmiana załączników"
echo "Podmieniam załączniki w $assets_dir ..."
assets_state="MOGĄ BYĆ NIEKOMPLETNE (podmiana przerwana)"
run_in_backup_container "
  set -e
  find /restore-assets -mindepth 1 -maxdepth 1 ! -name .restore-tmp -exec rm -rf {} +
  find $restore_tmp -mindepth 1 -maxdepth 1 -exec mv -t /restore-assets {} +
  rmdir $restore_tmp
"
assets_state="ODTWORZONE z kopii"

stage="uruchamianie aplikacji"
echo "Uruchamiam aplikację..."
docker compose up -d

stage=""
echo "Gotowe. Aplikacja startuje, poczekaj kilka minut i sprawdź: docker compose ps"
