# OpenProject na QNAP — plan implementacji

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gotowy do wdrożenia zestaw `deploy/qnap/`: stos Docker Compose dla QNAP TS-453D (dostęp przez Tailscale i Cloudflare Tunnel, nocne kopie), CLI `opm` i serwer MCP `opm-mcp` na API v3 oraz instrukcja po polsku.

**Architecture:** Kontenery `db`, `cache`, `seeder`, `web`, `worker`, `cloudflared`, `tailscale`, `backup` w jednej sieci Dockera; `web` bez portów na hoście. Pakiet Pythona `opm` z jednym klientem API (`OpenProjectClient`), na którym stoją CLI (argparse) i serwer MCP (FastMCP, stdio).

**Tech Stack:** Docker Compose v2, `openproject/openproject:17-slim`, `postgres:17`, `memcached:1.6`, `cloudflare/cloudflared`, `tailscale/tailscale`; Python ≥ 3.11, `httpx`, `mcp`, `pytest`, `respx`.

**Spec:** `docs/superpowers/specs/2026-10-26-openproject-qnap-nas-design.md`

## Global Constraints

- Obraz OpenProject: `openproject/openproject:17-slim` (18.x jeszcze niewydane).
- Baza: `postgres:17`. Dane: `${OP_DATA_DIR:-/share/Container/openproject}/{pgdata,assets}`; kopie: `${OP_BACKUP_DIR:-/share/Backup/openproject}`.
- `OPENPROJECT_HOST__NAME=${OP_PUBLIC_HOST}`, `OPENPROJECT_HTTPS=true`, `OPENPROJECT_ADDITIONAL__HOST__NAMES=${OP_TAILSCALE_HOST}`, `OPENPROJECT_DEFAULT__LANGUAGE=pl`, `OPENPROJECT_SEED_LOCALE=pl`, `OPENPROJECT_SELF__REGISTRATION=0`.
- Profile pamięci (4 GB domyślny / 8 GB / 16 GB docelowy): `db` 512m/1g/2g, `cache` 64/128/256 MB, `web` 1200m/2g/3g z `OPENPROJECT_WEB_WORKERS` 0/1/2, `worker` 768m/1g/1536m z `OPENPROJECT_GOOD__JOB__MAX__THREADS` 3/5/10, `cloudflared` 64m, `tailscale` 96m, `backup` 128m.
- Żaden port nie jest publikowany na interfejsie publicznym; `web` opcjonalnie na `127.0.0.1:${OP_LOCAL_PORT:-8080}` tylko w profilu `local`.
- Sekrety tylko w `deploy/qnap/.env` (w `.gitignore`); w repo wyłącznie `.env.example`.
- Kopia nocna 03:15, retencja `BACKUP_RETENTION_DAYS=14`.
- CLI nazywa się `opm` (nie `op` — kolizja z 1Password), serwer MCP `opm-mcp`. Konfiguracja: `OPM_URL`, `OPM_TOKEN` lub `~/.config/opm/config.toml`.
- Uwierzytelnianie API: Basic `apikey:<token>`.
- Dokumentacja dla użytkownika po polsku; kod, identyfikatory i komunikaty commitów po angielsku.
- Bez zmian w kodzie aplikacji OpenProject — wszystko w `deploy/qnap/` i `docs/superpowers/`.

## Review Focus

1. **Konflikt edycji (409, `lockVersion`)** — ktoś zmienił zadanie w przeglądarce w trakcie edycji przez Claude; oczekiwane: jedno automatyczne ponowienie z świeżym `lockVersion`, potem czytelny błąd. Test w Task 3.
2. **Nazwy zamiast ID** — użytkownik pisze „W realizacji”, „bug”, „Jan”; oczekiwane: dopasowanie bez rozróżniania wielkości liter, a przy braku/niejednoznaczności błąd z listą dostępnych wartości. Test w Task 3.
3. **Brak lub zły token / adres** — `OPM_TOKEN` pusty albo 401; oczekiwane: komunikat co ustawić, kod wyjścia 2 w CLI, `isError` w MCP, bez stack trace. Testy w Task 3, 4, 5.
4. **Nagłówek Host / HTTPS za proxy** — wejście przez adres Tailscale lub Cloudflare; oczekiwane: brak „Invalid host_name configuration” i brak pętli przekierowań. Pokryte testem curl z nagłówkami w Task 7.
5. **Odtworzenie kopii na pustym NAS-ie** — `restore.sh` na świeżo uruchomionym stosie; oczekiwane: dane i załączniki wracają, aplikacja startuje. Test w Task 7.

---

### Task 1: Stos Docker Compose i profile pamięci

**Files:**
- Create: `deploy/qnap/compose.yml`
- Create: `deploy/qnap/.env.example`
- Create: `deploy/qnap/tailscale/serve.json`
- Create: `deploy/qnap/.gitignore` (zawiera `.env`)

**Interfaces:**
- Produces: nazwy usług `db`, `cache`, `seeder`, `web`, `worker`, `cloudflared`, `tailscale`, `backup`; zmienne `.env` wymienione w Global Constraints oraz `OP_DB_PASSWORD`, `OP_SECRET_KEY_BASE`, `OP_ADMIN_PASSWORD`, `CLOUDFLARE_TUNNEL_TOKEN`, `TS_AUTHKEY`, `OP_IMAGE_TAG` (domyślnie `17-slim`). Profile Compose: `public` (cloudflared), `tailnet` (tailscale), `local` (port 127.0.0.1). Usługi `db/cache/seeder/web/worker/backup` bez profilu.

- [ ] **Step 1:** Napisz `compose.yml` z kotwicą `x-op-app` (obraz, `DATABASE_URL=postgres://openproject:${OP_DB_PASSWORD}@db/openproject?pool=20`, `OPENPROJECT_RAILS__CACHE__STORE=memcache`, `OPENPROJECT_CACHE__MEMCACHE__SERVER=cache:11211`, `SECRET_KEY_BASE`, zmienne z Global Constraints, wolumen `${OP_DATA_DIR}/assets:/var/openproject/assets`). `seeder`: `command: ./docker/prod/seeder`, `restart: on-failure`, `OPENPROJECT_SEED__ADMIN__USER__PASSWORD=${OP_ADMIN_PASSWORD}`, `OPENPROJECT_SEED__ADMIN__USER__PASSWORD__RESET=false`. `web`: `./docker/prod/web`, healthcheck `curl -fs http://localhost:8080/health_checks/default`, `depends_on: seeder: condition: service_completed_successfully`. `worker`: `./docker/prod/worker`. `db`: healthcheck `pg_isready`. Każda usługa `restart: unless-stopped` (poza `seeder`) i `mem_limit: ${..._MEM}`.
- [ ] **Step 2:** `tailscale`: `TS_AUTHKEY`, `TS_HOSTNAME=openproject`, `TS_STATE_DIR=/var/lib/tailscale` (wolumen `${OP_DATA_DIR}/tailscale`), `TS_SERVE_CONFIG=/config/serve.json`, `TS_USERSPACE=true`. `serve.json`: HTTPS 443 na `${TS_CERT_DOMAIN}` → `http://web:8080`. `cloudflared`: `command: tunnel --no-autoupdate run`, `TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}`.
- [ ] **Step 3:** `.env.example` — wszystkie zmienne z komentarzem po polsku i trzema blokami profili (4 GB aktywny, 8 GB i 16 GB zakomentowane), z poleceniem `openssl rand -hex 64` do wygenerowania `OP_SECRET_KEY_BASE`.
- [ ] **Step 4: Walidacja**

Run: `cd deploy/qnap && cp .env.example .env.test && docker compose --env-file .env.test --profile public --profile tailnet --profile local config -q && rm .env.test`
Expected: brak wyjścia, kod 0. Dodatkowo `docker compose ... config | grep -c mem_limit` = 8.

- [ ] **Step 5: Commit** `git add deploy/qnap && git commit -m "Add Docker Compose stack for OpenProject on QNAP"`

### Task 2: Kopie zapasowe i odtwarzanie

**Files:**
- Create: `deploy/qnap/backup/backup.sh`, `deploy/qnap/backup/entrypoint.sh`, `deploy/qnap/restore.sh`
- Modify: `deploy/qnap/compose.yml` (usługa `backup`)

**Interfaces:**
- Consumes: usługi `db`, `web`, `worker`; zmienne `OP_DATA_DIR`, `OP_BACKUP_DIR`, `OP_DB_PASSWORD`.
- Produces: katalog `${OP_BACKUP_DIR}/YYYY-MM-DD_HHMM/` z `openproject.dump` (`pg_dump -Fc`) i `assets.tar.gz`; `restore.sh <katalog>`.

- [ ] **Step 1:** `backup.sh` (POSIX sh, `set -eu`): `pg_dump -Fc -h db -U openproject openproject` → plik tymczasowy, potem `mv` (kopia nigdy nie jest „w połowie”); `tar czf` z `/assets` (montowane read-only); usuwa katalogi starsze niż `BACKUP_RETENTION_DAYS` przez `find -mindepth 1 -maxdepth 1 -type d -mtime +N`. `entrypoint.sh`: pętla czekająca do `BACKUP_TIME` (domyślnie `03:15`, strefa `TZ`), potem `backup.sh`; obsługa `backup.sh` uruchomionego ręcznie (`docker compose exec backup /backup/backup.sh`).
- [ ] **Step 2:** `restore.sh <katalog>`: sprawdza istnienie obu plików, `docker compose stop web worker`, `pg_restore --clean --if-exists --no-owner -d openproject` w kontenerze `db`, rozpakowanie `assets.tar.gz` do `${OP_DATA_DIR}/assets`, `docker compose up -d`. Pyta o potwierdzenie (`--yes` pomija).
- [ ] **Step 3: Walidacja statyczna**

Run: `shellcheck deploy/qnap/backup/*.sh deploy/qnap/restore.sh`
Expected: brak ostrzeżeń.
(Test działania — w Task 7.)

- [ ] **Step 4: Commit** `git commit -m "Add nightly backup and restore scripts"`

### Task 3: Pakiet `opm` — konfiguracja i klient API

**Files:**
- Create: `deploy/qnap/opm/pyproject.toml` (skrypty `opm = "opm.cli:main"`, `opm-mcp = "opm.mcp_server:main"`; zależności `httpx>=0.27`, `mcp>=1.2`; dev: `pytest`, `respx`)
- Create: `deploy/qnap/opm/src/opm/__init__.py`, `config.py`, `client.py`
- Test: `deploy/qnap/opm/tests/test_config.py`, `tests/test_client.py`

**Interfaces:**
- Produces:
  - `config.load_config() -> Config` (`Config(url: str, token: str)`); źródła w kolejności: env `OPM_URL`/`OPM_TOKEN`, potem `~/.config/opm/config.toml` (`url`, `token`). Brak → `ConfigError` z instrukcją.
  - `class OpenProjectError(Exception)` z `status: int | None`, `message: str`.
  - `class OpenProjectClient(url: str, token: str, transport: httpx.BaseTransport | None = None)`:
    - `whoami() -> dict`
    - `list_projects() -> list[dict]`
    - `search_work_packages(project: str | None = None, assignee_me: bool = False, status: str | None = None, open_only: bool = False, query: str | None = None, limit: int = 50) -> list[dict]`
    - `get_work_package(wp_id: int) -> dict`
    - `create_work_package(project: str, subject: str, type: str | None = None, assignee: str | None = None, description: str | None = None, start_date: str | None = None, due_date: str | None = None) -> dict`
    - `update_work_package(wp_id: int, **changes) -> dict` — klucze: `subject`, `description`, `status`, `assignee`, `start_date`, `due_date`, `percent_done`
    - `add_comment(wp_id: int, text: str) -> dict`, `list_comments(wp_id: int) -> list[dict]`
    - `log_time(wp_id: int, hours: float, date: str | None = None, comment: str | None = None) -> dict`
    - `list_statuses()`, `list_types()`, `list_users() -> list[dict]` (z `/api/v3/principals?filters=[{"type":{"operator":"=","values":["User"]}}]`)
  - Zwracane dicty są uproszczone (`summarize_work_package(raw) -> dict` z kluczami `id, subject, project, type, status, assignee, startDate, dueDate, percentageDone, lockVersion, url`).

- [ ] **Step 1: Testy (respx)** — w `test_client.py`:
  - `test_basic_auth_uses_apikey_user` — nagłówek `Authorization` = `Basic base64("apikey:tok")`.
  - `test_search_builds_filters` — `search_work_packages(project="demo", assignee_me=True, open_only=True, query="faktura")` wysyła `filters` zawierające `{"assignee":{"operator":"=","values":["me"]}}`, `{"status":{"operator":"o","values":[]}}`, `{"search":{"operator":"**","values":["faktura"]}}` i projekt po ID z `/api/v3/projects/demo`.
  - `test_update_resolves_status_name_case_insensitive` — `status="w realizacji"` → PATCH z `_links.status.href == "/api/v3/statuses/7"` dla statusu „W realizacji”.
  - `test_unknown_status_lists_options` — `OpenProjectError` z tekstem zawierającym wszystkie nazwy statusów.
  - `test_update_retries_once_on_409` — pierwszy PATCH 409, GET zwraca `lockVersion` 4, drugi PATCH z `lockVersion: 4` → sukces; trzeci 409 nie jest próbowany (drugi 409 → `OpenProjectError(status=409)`).
  - `test_log_time_uses_iso_duration_and_entity_link` — `hours=1.5` → `"hours": "PT1H30M"`, `_links.entity.href == "/api/v3/work_packages/42"`.
  - `test_401_message` — 401 → `OpenProjectError` z tekstem o tokenie API.
  - `test_422_shows_api_message` — treść `message` z odpowiedzi błędu HAL trafia do wyjątku.
  - W `test_config.py`: env ma pierwszeństwo przed plikiem; brak obu → `ConfigError`; końcowy `/` w URL usuwany.
- [ ] **Step 2:** Run `cd deploy/qnap/opm && python -m pytest -q` → FAIL (brak modułów).
- [ ] **Step 3:** Zaimplementuj `config.py` i `client.py`. Nazwy → ID przez listy z cache w instancji (statusy, typy, użytkownicy po `name`/`login`/`email`, projekty po `identifier` lub ID). Godziny → ISO 8601 przez zaokrąglenie do minut.
- [ ] **Step 4:** Run `python -m pytest -q` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Add opm API v3 client"`

### Task 4: CLI `opm`

**Files:**
- Create: `deploy/qnap/opm/src/opm/cli.py`
- Test: `deploy/qnap/opm/tests/test_cli.py`

**Interfaces:**
- Consumes: `load_config`, `OpenProjectClient`, `OpenProjectError`, `ConfigError` (Task 3).
- Produces: `main(argv: list[str] | None = None, client: OpenProjectClient | None = None) -> int`; polecenia zgodnie ze spec: `projects`, `wp list|show|create|set`, `comment`, `time`, `statuses`, `types`, `users`, `whoami`; globalna flaga `--json`.

- [ ] **Step 1: Testy** (z fałszywym klientem):
  - `test_wp_list_table_output` — kolumny `ID  STATUS  TYTUŁ  PRZYPISANY  TERMIN`.
  - `test_wp_set_passes_changes` — `opm wp set 12 --status "Zamknięte" --done 100` → `update_work_package(12, status="Zamknięte", percent_done=100)`.
  - `test_time_parses_units` — `1.5h`, `90m`, `1h30m` → `1.5`.
  - `test_json_flag_prints_json`.
  - `test_api_error_exit_code_1` i `test_config_error_exit_code_2` — komunikat na stderr, bez traceback.
- [ ] **Step 2:** `pytest tests/test_cli.py -q` → FAIL.
- [ ] **Step 3:** Zaimplementuj `cli.py` (argparse, podpolecenia).
- [ ] **Step 4:** `pytest -q` → PASS.
- [ ] **Step 5: Commit** `git commit -m "Add opm command line interface"`

### Task 5: Serwer MCP `opm-mcp`

**Files:**
- Create: `deploy/qnap/opm/src/opm/mcp_server.py`
- Test: `deploy/qnap/opm/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `OpenProjectClient` (Task 3).
- Produces: `build_server(client_factory: Callable[[], OpenProjectClient]) -> FastMCP`; `main() -> None` (stdio). Narzędzia: `whoami`, `list_projects`, `search_work_packages`, `get_work_package`, `create_work_package`, `update_work_package`, `add_comment`, `list_comments`, `log_time`, `list_statuses`, `list_types`, `list_users` — parametry jak metody klienta, opisy narzędzi po angielsku (dla modelu), wynik JSON.

- [ ] **Step 1: Testy** (klient MCP w pamięci z `mcp.shared.memory.create_connected_server_and_client_session`):
  - `test_lists_all_tools` — 12 nazw powyżej.
  - `test_update_tool_calls_client` — argumenty trafiają do `update_work_package`.
  - `test_api_error_returns_is_error` — `OpenProjectError` → `isError=True`, tekst błędu w treści.
  - `test_missing_config_is_reported_per_call` — brak konfiguracji nie zabija serwera przy starcie; wywołanie narzędzia zwraca `isError` z instrukcją.
- [ ] **Step 2:** `pytest tests/test_mcp_server.py -q` → FAIL.
- [ ] **Step 3:** Zaimplementuj `mcp_server.py` (klient tworzony leniwie przy pierwszym wywołaniu).
- [ ] **Step 4:** `pytest -q` → PASS (cały pakiet).
- [ ] **Step 5: Commit** `git commit -m "Add opm MCP server for Claude"`

### Task 6: Instrukcja wdrożenia (PL)

**Files:**
- Create: `deploy/qnap/README.md`
- Create: `deploy/qnap/opm/README.md` (krótko: instalacja `pipx install ./deploy/qnap/opm`, konfiguracja, przykłady)

- [ ] **Step 1:** Rozdziały wg spec („Dokumentacja dla użytkownika” 1–7) plus: wymiana RAM i test pamięci (memtest86+ z USB przez HDMI), przełączenie profilu 4 → 16 GB, opcjonalny SSD (zmiana `OP_DATA_DIR`), Cloudflare Access (z wyjątkiem: CLI/MCP przez Tailscale), aktualizacje, rozwiązywanie problemów (`Invalid host_name configuration`, 502 z tunelu, brak certyfikatu Tailscale, OOM — `docker stats`). Konfiguracja Claude Code: `claude mcp add openproject -e OPM_URL=https://openproject.<tailnet>.ts.net -e OPM_TOKEN=... -- opm-mcp`; Claude Desktop: przykład JSON.
- [ ] **Step 2:** Sprawdź, że każda zmienna z `.env.example` jest opisana: `grep -oE '^[A-Z_]+' deploy/qnap/.env.example | sort -u` vs wystąpienia w README.
- [ ] **Step 3: Commit** `git commit -m "Add Polish deployment guide for QNAP"`

### Task 7: Weryfikacja end-to-end

**Files:** bez nowych plików (ewentualne poprawki w plikach z Task 1–6).

- [ ] **Step 1:** Uruchom `dockerd` w sandboxie; w kopii katalogu z `.env` testowym (`OP_DATA_DIR`/`OP_BACKUP_DIR` w scratchpadzie, `OP_PUBLIC_HOST=pm.example.test`, `OP_TAILSCALE_HOST=openproject.tail-test.ts.net`) `docker compose --profile local up -d`; czekaj na `healthy` dla `web`.
- [ ] **Step 2:** `curl -s -o /dev/null -w '%{http_code}' -H 'Host: pm.example.test' -H 'X-Forwarded-Proto: https' http://127.0.0.1:8080/login` → `200`; to samo z hostem Tailscale → `200`; z `Host: evil.test` → `400`.
- [ ] **Step 3:** Przełącz test na HTTP: w `.env` testowym `OPENPROJECT_HTTPS=false` przez nadpisanie w `compose.override.yml` w scratchpadzie (nie w repo), `docker compose up -d web worker`. Utwórz token API admina: `docker compose exec web bundle exec rails runner 'puts Token::API.create!(user: User.admin.first).plain_value'`.
- [ ] **Step 4:** Ze statusem `S` = druga pozycja z `opm statuses`: `opm projects`, `opm wp create -p <identyfikator pierwszego projektu> "Test E2E"`, `opm wp set <id> --status "S"`, `opm comment <id> "ok"`, `opm time <id> 30m` — wszystkie kod 0. Przez MCP (skrypt klienta stdio w scratchpadzie): `get_work_package(<id>)` zwraca status `S`.
- [ ] **Step 5:** `docker compose exec backup /backup/backup.sh` → katalog z dwoma plikami; `docker compose down -v`, wyczyść `pgdata`, `up -d`, `./restore.sh --yes <katalog>` → `opm wp show <id>` zwraca zadanie z komentarzem.
- [ ] **Step 6:** Zatrzymaj stos, usuń dane testowe; commit ewentualnych poprawek `git commit -m "Fix issues found in end-to-end test"`.
