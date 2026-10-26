# OpenProject na QNAP TS-453D — projekt wdrożenia

Data: 2026-10-26 · Status: zatwierdzony koncepcyjnie, do przeglądu

## Cel

OpenProject jako główne narzędzie do zarządzania projektami, hostowane na
własnym NAS-ie, dostępne z każdego miejsca i sterowane z CLI oraz z Claude
(Claude Code / Claude Desktop) — bez płatnej wersji Enterprise.

### Kryteria sukcesu

1. `https://pm.<domena>` działa z dowolnej sieci (Cloudflare Tunnel).
2. `https://openproject.<tailnet>.ts.net` działa z urządzeń w sieci Tailscale.
3. Claude Code na laptopie tworzy, wyszukuje, edytuje i komentuje zadania przez
   serwer MCP `opm-mcp`; to samo potrafi CLI `opm`.
4. Co noc powstaje kopia zapasowa (baza + załączniki), którą da się odtworzyć
   skryptem `restore.sh`.
5. Na routerze nie jest otwarty żaden port.

### Ograniczenia i założenia

- Sprzęt: QNAP TS-453D-4G, Intel Celeron J4125 (x86_64), 4 GB RAM. Docelowo
  16 GB (2 × GOODRAM GR2666S464L19S/8G, DDR4 SO-DIMM 2666 CL19 — powyżej
  oficjalnego maksimum 8 GB, potwierdzone przez społeczność). Konfiguracja
  musi działać już na 4 GB.
- Oprogramowanie: QTS + Container Station (Docker Compose).
- Wersja Community — wbudowany serwer MCP OpenProject (`/mcp`) wymaga tokenu
  Enterprise (`EnterpriseToken.allows_to?(:mcp_server)`), więc go nie używamy.
- Domena użytkownika jest zarządzana w Cloudflare.
- Kilku użytkowników, interfejs po polsku, SMTP opcjonalny (domyślnie wyłączony).

## Architektura

```
 Internet ──► Cloudflare (Access opcj.) ──► cloudflared ─┐
                                                         ├──► web (Puma :8080) ──► postgres:17
 Tailnet  ──► tailscale (tailscale serve, HTTPS) ────────┘         │                 ▲
                                                           memcached ◄┘   worker ─────┤
                                                                          backup ─────┘
```

Wszystkie kontenery w jednej sieci Dockera `openproject`; `web` nie publikuje
portu na hoście (opcjonalnie `127.0.0.1`/LAN do diagnostyki).

### Usługi (`deploy/qnap/compose.yml`)

| Usługa      | Obraz                              | Rola                                   | Limit RAM (4 GB / 8 GB / 16 GB) |
|-------------|------------------------------------|----------------------------------------|---------------------------------|
| `preflight` | `postgres:17` + skrypt             | jednorazowo: odmawia startu z hasłami `change-me…` | 32 MB                |
| `db`        | `postgres:17`                      | baza danych                            | 512 MB / 1 GB / 2 GB            |
| `cache`     | `memcached:1.6`                    | cache Rails                            | 64 MB / 128 MB / 256 MB         |
| `seeder`    | `openproject/openproject:17-slim`  | migracje + seed, jednorazowo przy starcie | —                            |
| `web`       | `openproject/openproject:17-slim`  | Puma (`OPENPROJECT_WEB_WORKERS` 0 / 1 / 2) | 1.2 GB / 2 GB / 3 GB        |
| `worker`    | `openproject/openproject:17-slim`  | GoodJob (zadania w tle i cykliczne)    | 1 GB / 1.25 GB / 1.5 GB         |
| `cloudflared` | `cloudflare/cloudflared`         | tunel publiczny `pm.<domena>`          | 64 MB                           |
| `tailscale` | `tailscale/tailscale`              | węzeł tailnet + `tailscale serve`      | 96 MB                           |
| `backup`    | `postgres:17` + skrypt             | nocny `pg_dump` + tar załączników      | 128 MB                          |

Kontener `cron` z oficjalnego zestawu pominięto — obsługuje tylko pobieranie
poczty IMAP; zadania cykliczne wykonuje GoodJob w `worker`.

Limity są ustawiane zmiennymi w `.env`; `.env.example` zawiera trzy gotowe
profile (4 GB — domyślny na start, 8 GB, 16 GB — docelowy).

### Konfiguracja OpenProject

- `OPENPROJECT_HOST__NAME=pm.<domena>`, `OPENPROJECT_HTTPS=true`.
- `OPENPROJECT_ADDITIONAL__HOST__NAMES=openproject.<tailnet>.ts.net`
  (mechanizm `config.hosts` w `config/environments/production.rb`).
- `OPENPROJECT_DEFAULT__LANGUAGE=pl`, `SECRET_KEY_BASE` generowany przy instalacji.
- Dane trwałe: `/share/Container/openproject/{pgdata,assets}`.
- Sekrety wyłącznie w `.env` (szablon `.env.example`), `.env` w `.gitignore`.

### Dostęp i bezpieczeństwo

- Brak przekierowań portów. Ruch publiczny tylko przez wychodzący tunel
  Cloudflare; prywatny przez Tailscale.
- Zalecane Cloudflare Access (darmowy plan, logowanie kodem e-mail) dla
  `pm.<domena>` — chroni ekran logowania przed botami.
- CLI i MCP łączą się przez adres Tailscale, więc Access ich nie dotyczy.
- Instrukcja obejmuje wyłączenie samorejestracji i włączenie 2FA dla admina.

### Kopie zapasowe

- `backup` uruchamia się co noc (domyślnie 03:15): `pg_dump -Fc` +
  `tar.gz` katalogu `assets` do `/share/Backup/openproject/<data>/`, retencja
  14 dni (`BACKUP_RETENTION_DAYS`).
- `restore.sh <katalog>` zatrzymuje aplikację, odtwarza bazę do świeżej bazy
  i zamienia ją z działającą (poprzednia zostaje jako `openproject_before_restore`),
  odtwarza załączniki i uruchamia ponownie.
- Instrukcja wysyłki poza dom przez QNAP Hybrid Backup Sync (np. do chmury).

### Aktualizacje

- Obraz przypięty do głównej wersji (`17-slim`); aktualizacja = `docker compose
  pull && docker compose up -d` (migracje robi `seeder`). Kopia przed
  aktualizacją opisana w instrukcji.

## CLI i serwer MCP (`deploy/qnap/opm/`)

Pakiet Pythona (≥ 3.11) instalowany na komputerze, z którego pracujesz
(np. `pipx install ./deploy/qnap/opm`). Zależności: `httpx`, `mcp` (oficjalne
SDK), standardowa biblioteka do CLI (`argparse`).

### Moduły

- `opm/config.py` — odczyt `OPM_URL` i `OPM_TOKEN` (zmienne środowiskowe lub
  `~/.config/opm/config.toml`).
- `opm/client.py` — klient API v3 (HAL+JSON, Basic auth `apikey:<token>`):
  projekty, zadania (filtry, odczyt, tworzenie, edycja z `lockVersion` i jednym
  ponowieniem przy konflikcie 409), komentarze, statusy, typy, priorytety,
  użytkownicy, wpisy czasu pracy. Rozwiązywanie nazw → ID (status, typ,
  użytkownik, projekt po identyfikatorze lub nazwie). Błędy API jako
  `OpenProjectError` z czytelnym komunikatem.
- `opm/cli.py` — polecenie `opm`:
  - `opm projects`
  - `opm wp list [-p PROJEKT] [--mine] [--status S] [--open] [-q TEKST]`
  - `opm wp show ID`
  - `opm wp create -p PROJEKT TYTUŁ [--type T] [--assignee U] [--due DATA] [--description …]`
  - `opm wp set ID [--status S] [--assignee U] [--due DATA] [--start DATA] [--done N] [--subject …]`
  - `opm comment ID TEKST`
  - `opm time ID GODZINY [--date DATA] [--comment …]`
  - `opm statuses | types | users`
  - `--json` przy każdym poleceniu.
- `opm/mcp_server.py` — `opm-mcp`, transport stdio, narzędzia:
  `list_projects`, `search_work_packages`, `get_work_package`,
  `create_work_package`, `update_work_package`, `add_comment`,
  `list_comments`, `log_time`, `list_statuses`, `list_types`, `list_users`,
  `whoami`. Wyniki zwięzłe (tekst/JSON), błędy jako wynik narzędzia z
  `isError`.

### Integracja z Claude

- Claude Code: `claude mcp add openproject --env OPM_URL=… --env OPM_TOKEN=… -- opm-mcp`.
- Claude Desktop: wpis w `claude_desktop_config.json` (przykład w instrukcji).

## Testy i weryfikacja

- `pytest` z `respx` (atrapy HTTP) dla klienta, CLI i narzędzi MCP —
  w tym konflikt `lockVersion`, rozwiązywanie nazw, błędy 401/404/422.
- `docker compose config` dla walidacji pliku compose.
- Test end-to-end w środowisku deweloperskim: uruchomienie stosu bez
  `cloudflared`/`tailscale` (profil), utworzenie tokenu API, utworzenie zadania
  przez `opm`, odczyt i zmiana statusu przez narzędzie MCP.

## Dokumentacja dla użytkownika

`deploy/qnap/README.md` (po polsku), krok po kroku:

1. Przygotowanie NAS-a (RAM, Container Station, udziały `Container` i `Backup`).
2. Tailscale: konto, klucz autoryzacyjny, włączenie HTTPS i MagicDNS.
3. Cloudflare: utworzenie tunelu, token, publiczna nazwa hosta, opcjonalnie Access.
4. Wypełnienie `.env`, uruchomienie stosu w Container Station.
5. Pierwsze logowanie (zmiana hasła admina, język, 2FA, wyłączenie samorejestracji).
6. Token API, instalacja `opm`, podłączenie Claude Code / Claude Desktop.
7. Kopie zapasowe, odtwarzanie, aktualizacje, rozwiązywanie problemów.

## Poza zakresem

- Wbudowany MCP Enterprise, SSO/LDAP, BIM.
- Zdalny (HTTP) serwer MCP dla claude.ai w przeglądarce.
- Serwer pocztowy — tylko opis konfiguracji SMTP.
