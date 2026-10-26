# opm — CLI i serwer MCP dla OpenProject

`opm` to polecenie do pracy z OpenProject (API v3) z terminala, a `opm-mcp` to
serwer MCP (stdio), dzięki któremu Claude Code i Claude Desktop mogą tworzyć,
szukać, zmieniać i komentować zadania. Przeznaczone dla instalacji z
[`deploy/qnap`](../README.md); pełna instrukcja wdrożenia (Tailscale, tokeny,
rozwiązywanie problemów) jest w [głównej instrukcji](../README.md#9-token-api-opm-i-claude).

Wymagania: Python 3.11+, [pipx](https://pipx.pypa.io/), włączony Tailscale na
komputerze oraz osobisty token API z OpenProject
(**Moje konto → Tokeny dostępu → + Token API**; wcześniej tokeny API muszą być
włączone w **Administracja → API i webhooki**).

## Instalacja

Z GitHuba:

```bash
pipx install "git+https://github.com/robzapala/openproject.git@claude/peaceful-mayer-mgvjbs#subdirectory=deploy/qnap/opm"
```

Instalacja pipx: macOS `brew install pipx`, Debian/Ubuntu `sudo apt install pipx`,
Windows `py -m pip install --user pipx` i `py -m pipx ensurepath` (potem otwórz
nowy terminal). Szczegóły: [instrukcja główna, 9.2](../README.md#92-instalacja-opm-na-laptopie).

Albo z lokalnej kopii repozytorium:

```bash
pipx install ./deploy/qnap/opm
```

Aktualizacja: ponów polecenie z opcją `--force`.

## Konfiguracja

`OPM_URL` to adres `https://` z Tailscale (nie adres publiczny za Cloudflare Access).
Klient nie podąża za przekierowaniami — przy `http://` poda, jakiego adresu użyć. Adres `http://` jest
odrzucany (kod 2), chyba że to `localhost`, `127.0.0.1` lub host `*.ts.net`.

```bash
export OPM_URL=https://openproject.<tailnet>.ts.net
export OPM_TOKEN=<token>
```

albo plik `~/.config/opm/config.toml` (w Windows `C:\Users\<użytkownik>\.config\opm\config.toml`;
zmienne środowiskowe mają pierwszeństwo, w PowerShell ustawisz je przez `setx`):

```toml
url = "https://openproject.<tailnet>.ts.net"
token = "<token>"
```

## Przykłady

Każde polecenie przyjmuje `--json`. Statusy, typy, użytkowników i projekty
podajesz nazwą (bez rozróżniania wielkości liter) lub ID.

```bash
opm whoami
opm projects
opm statuses
opm types
opm users

opm wp list --mine --open
opm wp list -p moj-projekt --status "W realizacji"
opm wp list -q faktura --json
opm wp show 42
opm wp create -p moj-projekt "Przygotować ofertę" --type Bug --assignee Jan --due 2026-11-15
opm wp set 42 --status "W realizacji" --assignee me --done 50
opm comment 42 "Wysłałem ofertę do klienta."
opm time 42 1h30m --date 2026-10-25 --comment "Spotkanie"
```

Kody wyjścia: `0` sukces, `1` błąd API lub połączenia, `2` błąd konfiguracji
albo argumentów.

## Claude Code

```bash
claude mcp add openproject \
  -e OPM_URL=https://openproject.<tailnet>.ts.net \
  -e OPM_TOKEN=<token> \
  -- opm-mcp
```

## Claude Desktop

W `claude_desktop_config.json` (Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "openproject": {
      "command": "opm-mcp",
      "env": {
        "OPM_URL": "https://openproject.<tailnet>.ts.net",
        "OPM_TOKEN": "<token>"
      }
    }
  }
}
```

Jeśli Claude Desktop nie znajduje `opm-mcp`, wpisz w `command` pełną ścieżkę
(`which opm-mcp`).

## Narzędzia MCP

`whoami`, `list_projects`, `list_statuses`, `list_types`, `list_users`,
`search_work_packages`, `get_work_package`, `create_work_package`,
`update_work_package`, `add_comment`, `list_comments`, `log_time`.

Opis każdego z nich i przykładowe prośby do Claude:
[główna instrukcja, rozdział 9](../README.md#97-narzędzia-mcp).

## Testy

```bash
cd deploy/qnap/opm
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```
