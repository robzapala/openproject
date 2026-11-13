#!/bin/sh
set -eu

problems=0

for name in OP_DB_PASSWORD OP_SECRET_KEY_BASE OP_ADMIN_PASSWORD; do
  value=$(printenv "$name" || true)
  case "$value" in
    change-me*)
      echo "BŁĄD: $name w pliku .env ma wartość przykładową (change-me...)." >&2
      problems=1
      ;;
  esac
done

secret_key_base=$(printenv OP_SECRET_KEY_BASE || true)
if [ "${#secret_key_base}" -lt 64 ]; then
  echo "BŁĄD: OP_SECRET_KEY_BASE w pliku .env jest krótszy niż 64 znaki." >&2
  problems=1
fi

if [ "$problems" -ne 0 ]; then
  echo "Baza danych i aplikacja nie zostały uruchomione. Ustaw własne wartości według README," >&2
  echo "rozdział 6.1, sprawdź plik poleceniem z rozdziału 6.3 i uruchom: docker compose up -d" >&2
  exit 1
fi
