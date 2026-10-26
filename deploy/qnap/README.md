# OpenProject na QNAP TS-453D — instrukcja wdrożenia

Ta instrukcja prowadzi krok po kroku przez uruchomienie OpenProject (wersja
Community) na NAS-ie QNAP TS-453D-4G, z dostępem:

- publicznym przez **Cloudflare Tunnel** (`https://pm.twoja-domena.pl`),
- prywatnym przez **Tailscale** (`https://openproject.<nazwa-tailnetu>.ts.net`),
- z linii poleceń (`opm`) i z Claude (Claude Code / Claude Desktop) przez serwer MCP `opm-mcp`.

Na routerze nie otwierasz żadnego portu. Wszystkie hasła i klucze trzymasz
wyłącznie w pliku `.env` na NAS-ie.

> Nazwy menu w QTS, panelu Tailscale i panelu Cloudflare podaję według stanu z
> 2026 roku. Producenci co jakiś czas zmieniają układ interfejsu, więc
> przyciski mogą nazywać się nieco inaczej lub leżeć w innym miejscu. W
> razie wątpliwości szukaj pozycji o podobnej nazwie.

## Spis treści

1. [Co dostajesz i czego potrzebujesz](#1-co-dostajesz-i-czego-potrzebujesz)
2. [Przygotowanie NAS-a](#2-przygotowanie-nas-a)
3. [Pobranie zestawu na NAS-a](#3-pobranie-zestawu-na-nas-a)
4. [Tailscale](#4-tailscale)
5. [Cloudflare Tunnel i Access](#5-cloudflare-tunnel-i-access)
6. [Plik `.env`](#6-plik-env)
7. [Uruchomienie stosu](#7-uruchomienie-stosu)
8. [Pierwsze logowanie](#8-pierwsze-logowanie)
9. [Token API, `opm` i Claude](#9-token-api-opm-i-claude)
10. [Kopie zapasowe i odtwarzanie](#10-kopie-zapasowe-i-odtwarzanie)
11. [Aktualizacje](#11-aktualizacje)
12. [Wymiana RAM i przełączenie profilu pamięci](#12-wymiana-ram-i-przełączenie-profilu-pamięci)
13. [Opcjonalnie: dane na SSD](#13-opcjonalnie-dane-na-ssd)
14. [Rozwiązywanie problemów](#14-rozwiązywanie-problemów)
15. [Opis zmiennych `.env`](#15-opis-zmiennych-env)

---

## 1. Co dostajesz i czego potrzebujesz

### Z czego składa się stos

Wszystko uruchamia się poleceniem `docker compose` z pliku `compose.yml`:

| Usługa        | Rola                                                                  |
|---------------|-----------------------------------------------------------------------|
| `db`          | baza PostgreSQL 17                                                    |
| `cache`       | memcached (cache aplikacji)                                           |
| `seeder`      | jednorazowe zadanie: migracje bazy i dane początkowe                  |
| `web`         | aplikacja OpenProject (serwer Puma, port 8080 tylko wewnątrz sieci Dockera) |
| `worker`      | zadania w tle (powiadomienia, zadania cykliczne)                      |
| `backup`      | nocna kopia zapasowa (baza + załączniki)                              |
| `cloudflared` | tunel Cloudflare — profil `public`                                    |
| `tailscale`   | węzeł Tailscale z HTTPS — profil `tailnet`                            |
| `local-proxy` | dostęp diagnostyczny z samego NAS-a — profil `local`                  |

Obraz aplikacji to `openproject/openproject:17-slim` (stabilna linia 17.x).
Interfejs jest po polsku, samorejestracja użytkowników jest wyłączona.

### Czego potrzebujesz

- QNAP TS-453D z QTS i zainstalowaną **Container Station**.
- Komputer z przeglądarką, terminalem i Pythonem 3.11 lub nowszym (do `opm`).
- Domenę zarządzaną w Cloudflare (bezpłatne konto wystarcza).
- Konto Tailscale (plan darmowy wystarcza).
- Około godziny na całość; pierwszy start stosu trwa kilka minut.

---

## 2. Przygotowanie NAS-a

### 2.1. Pamięć RAM

NAS ma teraz 4 GB RAM i **na tym działa** (domyślny profil pamięci w `.env.example`
jest właśnie na 4 GB). Wymianę na 16 GB możesz zrobić później, zanim zaczniesz
tego potrzebować — patrz [rozdział 12](#12-wymiana-ram-i-przełączenie-profilu-pamięci).
Zalecam jednak zainstalować nowe moduły i przetestować je **przed** wdrożeniem,
bo wtedy NAS nie ma jeszcze danych, a okno na zwrot sprzętu (zwykle 14 dni) biegnie od otrzymania towaru.

### 2.2. Container Station

1. Zaloguj się do QTS jako administrator.
2. Otwórz **App Center**, wyszukaj **Container Station** i zainstaluj.
3. Uruchom Container Station raz, aby dokończyć wstępną konfigurację. Przy tej
   okazji zostanie utworzony współdzielony folder **`Container`**
   (ścieżka `/share/Container`).

Z Container Station korzystasz tylko jako ze źródła silnika Docker. Stosu **nie**
uruchamiasz z jego zakładki „Applications” — ona nie widzi plików położonych
obok `compose.yml` (skryptów kopii, konfiguracji Tailscale), których stos
potrzebuje. Wszystko robisz poleceniami `docker compose` przez SSH (rozdział 3).
Po uruchomieniu kontenery będą natomiast widoczne w Container Station i tam
możesz podejrzeć ich stan.

### 2.3. Foldery udostępnione `Container` i `Backup`

Potrzebne są dwa foldery udostępnione:

- **`Container`** — dane aplikacji (powstaje razem z Container Station).
- **`Backup`** — nocne kopie zapasowe.

Jeżeli folderu `Backup` jeszcze nie ma, utwórz go:

1. **Panel sterowania → Uprawnienia → Foldery udostępnione → Utwórz → Folder udostępniony**.
2. Nazwa: `Backup`, wolumen: główny wolumen na dyskach HDD (najlepiej z RAID).
3. Dokończ kreator (domyślne uprawnienia wystarczą — dostęp do niego ma tylko
   kontener działający jako administrator).

Jeśli chcesz użyć innych folderów, zmienisz je później w `.env`
(`OP_DATA_DIR`, `OP_BACKUP_DIR`).

### 2.4. Włączenie SSH

1. **Panel sterowania → Sieć i usługi plików → Telnet/SSH**.
2. Zaznacz **Zezwalaj na połączenia SSH**, port `22`, zastosuj.
3. Na komputerze połącz się:

```bash
ssh admin@ADRES-IP-NAS
```

Używasz konta z grupy administratorów (zwykle `admin`). Sprawdź, że Docker
działa:

```bash
docker --version
docker compose version
```

Jeśli pojawi się `docker: command not found`, upewnij się, że Container Station
jest zainstalowana i uruchomiona, a potem zaloguj się przez SSH ponownie.
Jeśli `docker compose version` zgłasza błąd, zaktualizuj Container Station
(**App Center**) do najnowszej wersji — starsze wydania nie mają polecenia `docker compose`.

Po zakończeniu całej instalacji możesz SSH ponownie wyłączyć — będzie potrzebne
tylko przy aktualizacjach i odtwarzaniu kopii.

### 2.5. Utworzenie katalogów na dane

Przez SSH:

```bash
mkdir -p /share/Container/openproject/pgdata \
         /share/Container/openproject/assets \
         /share/Container/openproject/tailscale
mkdir -p /share/Backup/openproject
chown 1000:1000 /share/Container/openproject/assets
```

Ostatnie polecenie jest konieczne: OpenProject działa w kontenerze jako
użytkownik o numerze 1000 i bez tego nie zapisze załączników (obrazów, plików
w zadaniach) — przy próbie dodania załącznika dostaniesz błąd o braku uprawnień
do systemu plików.

Jeżeli w `.env` ustawisz inne ścieżki (`OP_DATA_DIR`, `OP_BACKUP_DIR`), utwórz
katalogi w tych miejscach (i tam wykonaj `chown`).

---

## 3. Pobranie zestawu na NAS-a

Zestaw (`deploy/qnap/`) leży w repozytorium Git. Pobierz go tak, żeby skrypty
zachowały atrybut wykonywalności — użyj w tym celu jednorazowego kontenera z
Gitem (na NAS-ie nie musisz instalować Gita). Przez SSH:

```bash
docker run --rm -v /share/Container:/git alpine/git clone --depth 1 \
  --branch claude/peaceful-mayer-mgvjbs \
  https://github.com/robzapala/openproject.git /git/openproject-src
```

To pobiera całe repozytorium OpenProject (kilkaset MB, ale tylko ostatnią wersję);
potrzebny jest z niego tylko katalog `deploy/qnap`. Dalej pracujesz **zawsze w tym katalogu**:

```bash
cd /share/Container/openproject-src/deploy/qnap
ls -l
```

Pliki `restore.sh` oraz `backup/backup.sh` i `backup/entrypoint.sh` powinny mieć
bit wykonywalności (`-rwxr-xr-x`).

> **Pobranie archiwum ZIP z GitHuba** gubi atrybut wykonywalności. Jeżeli mimo
> to tak zrobisz, wykonaj w katalogu `deploy/qnap`:
>
> ```bash
> chmod +x restore.sh backup/*.sh
> ```
>
> Bez tego kontener `backup` nie wystartuje, a `restore.sh` nie da się uruchomić.

Wszystkie kolejne polecenia `docker compose ...` wykonujesz z katalogu
`/share/Container/openproject-src/deploy/qnap`.

---

## 4. Tailscale

1. Załóż konto na <https://login.tailscale.com> (logowanie przez Google,
   Microsoft, Apple lub GitHub).
2. W konsoli administracyjnej otwórz **DNS** i sprawdź dwie rzeczy:
   - **MagicDNS** jest włączony (w nowych tailnetach jest domyślnie),
   - w sekcji **HTTPS Certificates** kliknij **Enable HTTPS** (zgódź się na
     publikację nazw maszyn w publicznym rejestrze certyfikatów).
   Bez tego kroku węzeł nie dostanie certyfikatu i adres HTTPS nie zadziała.
3. Zanotuj nazwę swojego tailnetu widoczną na stronie **DNS** (np.
   `tail1234ab.ts.net`). Węzeł z tego stosu nazywa się `openproject`, więc jego
   pełny adres to:

   ```
   openproject.tail1234ab.ts.net
   ```

   To jest wartość zmiennej **`OP_TAILSCALE_HOST`** (bez `https://`).
4. Wygeneruj klucz autoryzacyjny: **Settings → Keys → Generate auth key**.
   - Zaznacz **Reusable** (klucz wielokrotnego użytku) — tak zaleca też
     `.env.example`. Do pierwszego startu wystarczyłby klucz jednorazowy
     (węzeł rejestruje się raz, a jego stan zapisuje w
     `/share/Container/openproject/tailscale`), ale klucz wielokrotny pozwoli
     zarejestrować węzeł od nowa, gdybyś kiedyś skasował ten katalog.
   - Tagi i wstępna akceptacja (*Pre-approved*) są opcjonalne.
   - Skopiuj klucz (zaczyna się od `tskey-auth-`) — to wartość **`TS_AUTHKEY`**.
     Wyświetla się tylko raz.
5. Po pierwszym uruchomieniu stosu (rozdział 7) wejdź w **Machines**, przy
   maszynie `openproject` kliknij trzy kropki → **Disable key expiry**. Inaczej
   po około 180 dniach węzeł wygaśnie i adres przestanie działać.
6. Zainstaluj Tailscale na telefonie i laptopie (<https://tailscale.com/download>)
   i zaloguj się na to samo konto. Tylko urządzenia w Twoim tailnecie
   zobaczą adres `openproject.<tailnet>.ts.net`.

Jeżeli nie chcesz na razie używać Tailscale, i tak musisz wpisać w `.env`
jakąś niepustą wartość `TS_AUTHKEY` i `OP_TAILSCALE_HOST` (patrz rozdział 6).
Ale CLI `opm` i Claude łączą się właśnie przez Tailscale, więc zalecam go skonfigurować.

---

## 5. Cloudflare Tunnel i Access

Tunel to połączenie *wychodzące* z NAS-a do Cloudflare — nie otwierasz portów.

### 5.1. Utworzenie tunelu

1. Zaloguj się na <https://dash.cloudflare.com> i otwórz **Zero Trust** (menu
   po lewej). Przy pierwszym wejściu wybierz plan **Free** i nazwę zespołu.
2. **Networks → Tunnels** (w nowszym układzie: **Networks → Connectors →
   Cloudflare Tunnels**) → **Create a tunnel**.
3. Wybierz typ **Cloudflared**, nazwij tunel np. `qnap-openproject`, zatwierdź.
4. Na ekranie instalacji wybierz środowisko **Docker**. Zobaczysz polecenie
   `docker run cloudflare/cloudflared ... tunnel run --token eyJh...`. **Nie
   uruchamiaj go.** Skopiuj tylko długi token po `--token` — to wartość
   **`CLOUDFLARE_TUNNEL_TOKEN`**. Token jest sekretem; traktuj go jak hasło.
5. Przejdź dalej do zakładki **Public hostname** (w nowszym układzie:
   **Published application routes**) i dodaj trasę:
   - **Subdomain**: `pm`, **Domain**: Twoja domena → `pm.twoja-domena.pl`
   - **Service type**: `HTTP`
   - **URL**: `web:8080`

   Zapisz. Cloudflare sam doda wpis DNS (CNAME) dla `pm`. Nazwa `pm.twoja-domena.pl`
   to wartość **`OP_PUBLIC_HOST`**.

Kontener `cloudflared` działa w tej samej sieci Dockera co `web`, dlatego
adres `web:8080` jest poprawny. Nie wpisuj tu `localhost` ani adresu IP NAS-a.

### 5.2. Zalecane: Cloudflare Access (logowanie kodem e-mail)

Access stawia przed ekranem logowania OpenProject bramkę Cloudflare, dzięki
czemu boty i skanery nie dobierają się do aplikacji.

1. **Zero Trust → Access → Applications** (w nowszym układzie: **Access
   controls → Applications**) → **Add an application** → **Self-hosted**.
2. **Application name**: np. `OpenProject`. **Public hostname**: `pm` +
   Twoja domena.
3. Dodaj politykę: **Action: Allow**, reguła **Include → Emails** i wpisz
   adresy e-mail osób, które mają mieć dostęp (albo **Emails ending in**
   `@twoja-domena.pl`).
4. W sekcji metod logowania zostaw **One-time PIN** (kod jednorazowy wysyłany
   na e-mail; w darmowym planie działa bez dodatkowej konfiguracji).
5. Zapisz aplikację.

Od teraz wejście na `https://pm.twoja-domena.pl` najpierw prosi o e-mail i kod,
a dopiero potem pokazuje ekran logowania OpenProject.

**CLI `opm` i serwer MCP omijają Access**, bo łączą się przez adres Tailscale
(`https://openproject.<tailnet>.ts.net`), a nie przez `pm.twoja-domena.pl`.
Nie ustawiaj w nich adresu publicznego — Access zablokowałby żądania API.

---

## 6. Plik `.env`

W katalogu `deploy/qnap`:

```bash
cd /share/Container/openproject-src/deploy/qnap
cp .env.example .env
```

Wartości w `.env` ustawisz poleceniami `sed`, które możesz po prostu skopiować
i wkleić do terminala SSH — edytor `vi` z QTS jest niewygodny i nie musisz go
używać. Każde polecenie `sed -i "s|^NAZWA=.*|NAZWA=wartość|" .env` podmienia
całą linię `NAZWA=…` w pliku `.env`; znaki `|` zostają, zmieniasz tylko
wartość po drugim `|`.

> **Ostrzeżenie.** Wartości zaczynające się od `change-me` są w `.env.example`
> publicznie znanymi przykładami. **Nigdy nie uruchamiaj stosu z takimi
> wartościami** — każdy mógłby wtedy zalogować się na konto administratora lub
> podrabiać sesje. Zastąp **każdą** wartość `change-me…` własną i wykonaj
> sprawdzenie z punktu 6.3.

### 6.1. Sekrety (generowane automatycznie)

Trzy polecenia generują losowe sekrety i od razu wpisują je do `.env`:

```bash
sed -i "s|^OP_SECRET_KEY_BASE=.*|OP_SECRET_KEY_BASE=$(openssl rand -hex 64)|" .env
sed -i "s|^OP_DB_PASSWORD=.*|OP_DB_PASSWORD=$(openssl rand -hex 24)|" .env
sed -i "s|^OP_ADMIN_PASSWORD=.*|OP_ADMIN_PASSWORD=$(openssl rand -base64 24)|" .env
```

`OP_DB_PASSWORD` to same znaki hex, bo hasło trafia do adresu URL bazy.
Hasło administratora odczytasz i zapiszesz w menedżerze haseł poleceniem:

```bash
grep '^OP_ADMIN_PASSWORD=' .env
```

Hasło administratora musi spełniać wymagania OpenProject (m.in. co najmniej 10
znaków i różne rodzaje znaków). Wynik `openssl rand -base64 24` zwykle je spełnia;
gdyby logowanie się nie powiodło, wygeneruj hasło ponownie (powtórz trzecie
polecenie) i zobacz rozdział 14. Gdyby na NAS-ie nie było `openssl`, wygeneruj
wartości na laptopie i wstaw je w to samo polecenie `sed` zamiast `$(openssl …)`.

### 6.2. Adresy i klucze (wklejasz własne wartości)

Zamień wartości po prawej stronie na swoje (nie usuwaj znaków `|`):

```bash
sed -i "s|^OP_PUBLIC_HOST=.*|OP_PUBLIC_HOST=pm.twoja-domena.pl|" .env
sed -i "s|^OP_TAILSCALE_HOST=.*|OP_TAILSCALE_HOST=openproject.tail1234ab.ts.net|" .env
sed -i "s|^CLOUDFLARE_TUNNEL_TOKEN=.*|CLOUDFLARE_TUNNEL_TOKEN=WKLEJ-TUTAJ-TOKEN-CLOUDFLARE|" .env
sed -i "s|^TS_AUTHKEY=.*|TS_AUTHKEY=WKLEJ-TUTAJ-KLUCZ-TAILSCALE|" .env
```

| Zmienna | Co wpisać |
|---------|-----------|
| `OP_PUBLIC_HOST` | `pm.twoja-domena.pl` (rozdział 5) |
| `OP_TAILSCALE_HOST` | `openproject.<tailnet>.ts.net` (rozdział 4) |
| `CLOUDFLARE_TUNNEL_TOKEN` | token z kroku 5.1 |
| `TS_AUTHKEY` | klucz z kroku 4.4 |

**`CLOUDFLARE_TUNNEL_TOKEN`, `TS_AUTHKEY` i `OP_TAILSCALE_HOST` muszą być niepuste
także wtedy, gdy danej ścieżki dostępu nie używasz.** Docker Compose sprawdza
wszystkie usługi, również te, których profil nie jest włączony, i bez wartości
przerwie działanie komunikatem w rodzaju „Set TS_AUTHKEY in .env”. Gdy
np. nie korzystasz z Cloudflare, wpisz atrapę
(`sed -i "s|^CLOUDFLARE_TUNNEL_TOKEN=.*|CLOUDFLARE_TUNNEL_TOKEN=nieuzywany|" .env`)
i po prostu nie włączaj profilu `public`.

Pozostałe zmienne (ścieżki, kopie, limity pamięci) mają sensowne wartości
domyślne dla 4 GB RAM. Ich pełny opis jest w [rozdziale 15](#15-opis-zmiennych-env).

### 6.3. Obowiązkowe sprawdzenie

```bash
grep -n 'change-me' .env
grep -nE '^[A-Z_]+=.*(example\.com|tailnet-name)' .env
docker compose --profile public --profile tailnet config -q
```

**Wszystkie trzy polecenia muszą nic nie wypisać.** Jeśli pierwsze lub drugie
wypisze linię, została w niej wartość przykładowa — popraw ją odpowiednim
poleceniem `sed` z 6.1 lub 6.2. Jeśli trzecie wypisze błąd w rodzaju „Set
TS_AUTHKEY in .env”, brakuje jakiejś wartości.

Plik `.env` jest w `.gitignore` i **nie trafia do repozytorium**. Zachowaj jego
kopię w menedżerze haseł: **kopie zapasowe z rozdziału 10 nie obejmują `.env`**,
a bez `OP_SECRET_KEY_BASE` i haseł nie odtworzysz środowiska od zera.

### 6.4. Awaryjnie: edycja w `vi`

Jeśli wolisz poprawić plik ręcznie: `vi .env`, strzałkami ustaw kursor, `i`
włącza pisanie, a **Esc**, potem `:wq` i **Enter** zapisuje plik i wychodzi
(`:q!` wychodzi bez zapisu). Plik można też edytować przez SFTP (np. WinSCP,
Cyberduck), pamiętając o końcach linii w stylu Unix (LF).

---

## 7. Uruchomienie stosu

```bash
cd /share/Container/openproject-src/deploy/qnap
docker compose --profile public --profile tailnet up -d
```

Pierwszy start pobiera obrazy (kilka GB) i wykonuje migracje bazy oraz dane
początkowe — na Celeronie J4125 trwa to **kilka minut**, czasem kilkanaście.

Sprawdzaj postęp:

```bash
docker compose ps
docker compose logs -f seeder web
```

(`Ctrl+C` kończy podgląd logów, nie zatrzymuje stosu.)

Stos jest gotowy, gdy:

- `seeder` ma status `exited (0)` — to normalne, jest jednorazowy,
- `web` ma status `healthy`,
- w logach `web` widać, że Puma nasłuchuje.

> **Skrót.** Profile można włączyć na stałe, dopisując w `.env` linię
> `COMPOSE_PROFILES=public,tailnet` — wtedy nie trzeba podawać `--profile`.
> W tej instrukcji podaję pełne polecenia.

Po starcie wejdź w konsoli Tailscale w **Machines** i wykonaj krok 4.5 (wyłączenie
wygasania klucza). Sprawdź też adres `openproject` — jeśli nazwa maszyny jest
inna (np. `openproject-1`), popraw `OP_TAILSCALE_HOST` w `.env` i uruchom polecenie
`up -d` ponownie.

Jeśli używasz tylko jednej ścieżki dostępu, włącz tylko jej profil, np. samo
`--profile tailnet`. Pamiętaj, że w `.env` nadal muszą być niepuste wartości
pozostałych zmiennych (rozdział 6.2).

### Profil `local` (tylko diagnostyka)

Profil `local` uruchamia `local-proxy`, który wystawia `web` na
`127.0.0.1:${OP_LOCAL_PORT}` — **wyłącznie na pętli zwrotnej NAS-a**, nie w sieci LAN.

```bash
docker compose --profile local up -d local-proxy
PORT=$(grep '^OP_LOCAL_PORT=' .env | cut -d= -f2)
curl -sI -H "Host: pm.twoja-domena.pl" -H "X-Forwarded-Proto: https" "http://127.0.0.1:${PORT:-8081}/"
```

Służy do sprawdzenia z samego NAS-a (przez SSH), czy aplikacja odpowiada
(powyższe polecenie podszywa się pod nagłówki, które normalnie dodaje Cloudflare/Tailscale;
w `Host` wpisz swoją wartość `OP_PUBLIC_HOST`).
**Nie otworzysz tego adresu w przeglądarce na laptopie**, a nawet z NAS-a
logowanie nie zadziała: OpenProject wymusza HTTPS i sprawdza nazwę hosta, więc
przekieruje na `https://pm.…` albo odrzuci żądanie jako „Invalid host_name
configuration”. Do normalnej pracy używaj adresu Tailscale lub Cloudflare.

Domyślny port diagnostyczny to `8081` (`OP_LOCAL_PORT`), bo QTS sam używa portu
8080 do panelu administracyjnego. Jeżeli i ten port jest zajęty, ustaw w `.env`
inną wartość `OP_LOCAL_PORT` i uruchom polecenie ponownie.

---

## 8. Pierwsze logowanie

1. Otwórz `https://openproject.<tailnet>.ts.net` (z urządzenia z Tailscale) lub
   `https://pm.twoja-domena.pl`.
   Pierwsze żądanie po starcie bywa wolne (kilkanaście sekund).
2. Zaloguj się: login **`admin`**, hasło = wartość `OP_ADMIN_PASSWORD` z `.env`.
3. Zrób od razu:
   1. **Zmień hasło administratora** (awatar w prawym górnym rogu → **Moje konto
      → Zmień hasło**). Hasło z `.env` działa tylko jako startowe — zmiana w
      aplikacji go nie aktualizuje, a to w porządku.
   2. **Włącz uwierzytelnianie dwuskładnikowe (2FA)** dla konta admina:
      **Moje konto → Uwierzytelnianie dwuskładnikowe** (aplikacja
      uwierzytelniająca w telefonie). Zapisz kody zapasowe.
   3. **Sprawdź, że samorejestracja jest wyłączona**: **Administracja →
      Uwierzytelnianie → Ustawienia** (pole „Samodzielna rejestracja” /
      „Self-registration”) ma mieć wartość *Wyłączona*. Stos ustawia to
      zmienną środowiskową, ale warto to zobaczyć.
   4. **Sprawdź język**: domyślny język instalacji to polski. Własny język konta
      zmienisz w **Moje konto → Ustawienia**.
   5. **Włącz tokeny API**: **Administracja → API i webhooki → API**, zaznacz
      **Włącz tokeny API** (nazwa pola może brzmieć nieco inaczej) i zapisz.
      Bez tego `opm` dostanie błąd 401.
4. Dodaj użytkowników: **Administracja → Użytkownicy → + Użytkownik**.
   Poczta (SMTP) nie jest tu skonfigurowana, więc zaproszenia e-mail i
   „Nie pamiętam hasła” nie wyślą wiadomości. Ustaw nowemu użytkownikowi hasło
   ręcznie w formularzu i przekaż je innym kanałem.

---

## 9. Token API, `opm` i Claude

### 9.1. Osobisty token API

1. Zaloguj się do OpenProject (przez adres Tailscale lub Cloudflare).
2. **Moje konto → Tokeny dostępu** (w angielskim interfejsie: *My account →
   Access tokens*) → w sekcji **API** kliknij **+ Token API**.
3. Nadaj nazwę (np. `opm laptop`) i zatwierdź. **Token wyświetla się tylko raz** —
   skopiuj go od razu.

Uprawnienia tokenu są takie same jak Twojego konta. Każdy użytkownik tworzy
własny token. Jeśli token wycieknie, usuń go na tej samej stronie.

Jeśli sekcji API nie ma lub token nie działa — włącz tokeny API w
administracji (krok 8.3.5).

### 9.2. Instalacja `opm` na laptopie

Wymagany jest Python 3.11 lub nowszy (`python3 --version`; w Windows `py --version`)
i [pipx](https://pipx.pypa.io/). Zainstaluj pipx zależnie od systemu:

macOS (Homebrew):

```bash
brew install pipx
pipx ensurepath
```

Debian / Ubuntu:

```bash
sudo apt install pipx
pipx ensurepath
```

Windows (PowerShell; Python z <https://www.python.org/downloads/>, w kreatorze
zaznacz „Add python.exe to PATH” lub użyj launchera `py`):

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

Po `ensurepath` **zamknij i otwórz terminal ponownie**. Potem, na każdym systemie,
instalacja bezpośrednio z GitHuba:

```bash
pipx install "git+https://github.com/robzapala/openproject.git@claude/peaceful-mayer-mgvjbs#subdirectory=deploy/qnap/opm"
```

Albo z lokalnej kopii repozytorium (np. po `git clone`):

```bash
pipx install ./deploy/qnap/opm
```

(Wariant z GitHuba wymaga zainstalowanego Gita na laptopie.)

Zainstalowane zostaną dwa polecenia: `opm` (CLI) i `opm-mcp` (serwer MCP dla Claude).
Aktualizacja: ponów polecenie `pipx install` z opcją `--force`.

### 9.3. Konfiguracja

**`OPM_URL` musi być adresem `https://` z Tailscale**, bez końcowego ukośnika:
`https://openproject.<tailnet>.ts.net`. Klient nie podąża za przekierowaniami —
jeśli podasz `http://…`, dostaniesz komunikat o przekierowaniu wraz z adresem,
którego trzeba użyć. Laptop musi mieć włączony Tailscale.

Najprościej (na każdym systemie) utwórz plik konfiguracyjny. Ścieżka to
`~/.config/opm/config.toml`, czyli w Windows
`C:\Users\<użytkownik>\.config\opm\config.toml` (folder `.config\opm` utwórz
sam). Zawartość:

```toml
url = "https://openproject.tail1234ab.ts.net"
token = "wklej-token-tutaj"
```

Zmienne środowiskowe `OPM_URL` i `OPM_TOKEN` mają pierwszeństwo przed plikiem.

macOS / Linux — zmienne na czas bieżącej sesji terminala i zabezpieczenie pliku
(`chmod` istnieje tylko w systemach uniksowych):

```bash
export OPM_URL=https://openproject.tail1234ab.ts.net
export OPM_TOKEN=wklej-token-tutaj
chmod 600 ~/.config/opm/config.toml
```

Windows (PowerShell) — zmienne zapamiętane na stałe (obowiązują w *nowo*
otwartych terminalach):

```powershell
setx OPM_URL "https://openproject.tail1234ab.ts.net"
setx OPM_TOKEN "wklej-token-tutaj"
```

Sprawdzenie:

```bash
opm whoami
```

### 9.4. Polecenia

Każde polecenie przyjmuje `--json` (wynik w JSON zamiast tabeli). Statusy, typy,
projekty i użytkowników podajesz **nazwą** (wielkość liter nie ma znaczenia)
albo numerem ID. Gdy nazwa jest nieznana lub niejednoznaczna, `opm` wypisze
listę dostępnych wartości.

```bash
# Kim jestem, co jest dostępne
opm whoami
opm projects
opm statuses
opm types
opm users

# Lista zadań
opm wp list                                  # najnowsze zadania (do 50)
opm wp list -p moj-projekt                   # w projekcie (identyfikator lub nazwa)
opm wp list --mine --open                    # moje, niezamknięte
opm wp list -p moj-projekt --status "W realizacji"
opm wp list -q "faktura"                     # szukaj w tytułach i opisach
opm wp list --mine --json

# Szczegóły
opm wp show 42

# Tworzenie
opm wp create -p moj-projekt "Przygotować ofertę"
opm wp create -p moj-projekt "Naprawić formularz" --type Bug --assignee Jan \
    --due 2026-11-15 --description "Formularz nie wysyła załączników."

# Zmiana (przynajmniej jedna opcja)
opm wp set 42 --status "W realizacji"
opm wp set 42 --assignee me --due 2026-11-30 --done 50
opm wp set 42 --subject "Nowy tytuł" --description "Nowy opis"

# Komentarz
opm comment 42 "Wysłałem ofertę do klienta."

# Czas pracy
opm time 42 1.5h
opm time 42 90m --date 2026-10-25 --comment "Spotkanie z klientem"
opm time 42 1h30m
```

Nazwy statusów i typów zależą od instalacji — zobacz `opm statuses` i `opm types`.
`--assignee` przyjmuje imię i nazwisko, login, e-mail lub `me` (właściciel tokenu).
Czas: `1.5h`, `1,5h`, `90m`, `1h30m` albo sama liczba godzin.

Kody wyjścia:

| Kod | Znaczenie |
|-----|-----------|
| `0` | sukces |
| `1` | błąd API (np. 401, 403, 404, 409, 422, brak połączenia, nieznana nazwa) |
| `2` | błąd konfiguracji (brak `OPM_URL`/`OPM_TOKEN`, zły format adresu) lub błędne argumenty polecenia |

Błędy są wypisywane na stderr krótkim komunikatem, bez śladu stosu. Jeśli
ktoś zmienił zadanie w przeglądarce w trakcie Twojej edycji, `opm wp set`
sam raz ponawia zmianę z aktualnym numerem wersji; dopiero powtórny konflikt
kończy się błędem.

### 9.5. Claude Code

Dodaj serwer MCP (token wklej własny):

```bash
claude mcp add openproject \
  -e OPM_URL=https://openproject.tail1234ab.ts.net \
  -e OPM_TOKEN=wklej-token-tutaj \
  -- opm-mcp
```

Dodaj `--scope user`, jeśli ma być dostępny we wszystkich projektach, a nie
tylko w bieżącym. Sprawdź: `claude mcp list` albo `/mcp` w sesji Claude Code.
Laptop musi mieć włączony Tailscale.

### 9.6. Claude Desktop

Otwórz **Settings → Developer → Edit Config** (plik `claude_desktop_config.json`;
macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`)
i dodaj:

```json
{
  "mcpServers": {
    "openproject": {
      "command": "opm-mcp",
      "env": {
        "OPM_URL": "https://openproject.tail1234ab.ts.net",
        "OPM_TOKEN": "wklej-token-tutaj"
      }
    }
  }
}
```

Claude Desktop nie zawsze widzi `PATH` z terminala. Jeśli serwer się nie
uruchamia, podaj pełną ścieżkę — sprawdź ją poleceniem `which opm-mcp`
(macOS/Linux) lub `where opm-mcp` (Windows); pipx zwykle instaluje w
`~/.local/bin/opm-mcp`. Po zmianie konfiguracji zamknij Claude Desktop
całkowicie i uruchom ponownie.

### 9.7. Narzędzia MCP

| Narzędzie | Co robi |
|-----------|---------|
| `whoami` | pokazuje użytkownika, do którego należy token |
| `list_projects` | lista projektów (id, identyfikator, nazwa) |
| `list_statuses` | lista statusów zadań |
| `list_types` | lista typów zadań (np. Zadanie, Błąd) |
| `list_users` | lista użytkowników (imię, login, e-mail) |
| `search_work_packages` | szuka zadań wg projektu, statusu, osoby, tekstu |
| `get_work_package` | szczegóły jednego zadania z opisem |
| `create_work_package` | tworzy zadanie w projekcie |
| `update_work_package` | zmienia status, osobę, daty, postęp, tytuł, opis |
| `add_comment` | dodaje komentarz do zadania |
| `list_comments` | wypisuje komentarze zadania |
| `log_time` | zapisuje czas pracy przy zadaniu |

Błąd (zły token, nieznany status, konflikt) wraca do Claude jako wynik
narzędzia oznaczony jako błąd, z opisem co poprawić — bez zawieszania sesji.

### 9.8. Przykładowe prośby do Claude

- „Pokaż moje otwarte zadania w projekcie Strona WWW.”
- „Utwórz zadanie ‘Przygotować ofertę dla Kowalskiego’ w projekcie Sprzedaż,
  typ Zadanie, przypisz do Jana, termin 15 listopada.”
- „Przełącz zadanie 42 na status W realizacji i dodaj komentarz, że czekam na
  odpowiedź klienta.”
- „Znajdź zadania ze słowem ‘faktura’ i zapisz 1,5 godziny pracy przy
  zadaniu 57 z komentarzem ‘rozmowa telefoniczna’.”
- „Podsumuj, co się zmieniło w zadaniu 42 — wypisz komentarze.”

---

## 10. Kopie zapasowe i odtwarzanie

### 10.1. Co, kiedy i gdzie

Kontener `backup` robi kopię **co noc o 03:15** (czas `TZ`, domyślnie
`Europe/Warsaw`). Każda kopia to katalog:

```
/share/Backup/openproject/2026-10-26_0315/
├── openproject.dump     # baza danych (pg_dump -Fc)
└── assets.tar.gz        # załączniki
```

- Godzinę zmienia `BACKUP_TIME` (format `GG:MM`), strefę `TZ`.
- Kopie starsze niż `BACKUP_RETENTION_DAYS` dni (domyślnie 14) są usuwane
  automatycznie.
- Katalog docelowy to `OP_BACKUP_DIR`.
- Kopia powstaje najpierw w katalogu tymczasowym i jest przenoszona na miejsce
  dopiero po udanym wykonaniu — nieudana nie zostawia niepełnego katalogu.

Po zmianie `BACKUP_TIME`, `TZ` lub `BACKUP_RETENTION_DAYS` zastosuj:

```bash
docker compose --profile public --profile tailnet up -d
```

Kopia **nie zawiera pliku `.env`** ani stanu Tailscale — zachowaj `.env` osobno
(menedżer haseł).

Sprawdzenie, że harmonogram działa:

```bash
docker compose logs backup
ls -l /share/Backup/openproject
```

W logu zobaczysz linię „Następna kopia: …”.

### 10.2. Kopia ręczna

Zawsze wykonaj ją przed aktualizacją lub większą zmianą:

```bash
docker compose exec backup /backup/backup.sh
```

Wypisze `Kopia gotowa: /backups/<data_godzina>` (w `/share/Backup/openproject` na NAS-ie).

### 10.3. Odtwarzanie

Odtwarzanie **zastępuje całą bazę i wszystkie załączniki** danymi z kopii.
Wykonaj w `deploy/qnap`, podając **bezwzględną** ścieżkę katalogu kopii:

```bash
./restore.sh /share/Backup/openproject/2026-10-26_0315
```

Skrypt:

1. sprawdza poprawność plików kopii (jeśli są uszkodzone — nic nie zmienia),
2. prosi o potwierdzenie (wpisz `t`; opcja `--yes` pomija pytanie),
3. zatrzymuje `web` i `worker`, odtwarza bazę, podmienia załączniki,
4. uruchamia aplikację ponownie (nie rusza `cloudflared` ani `tailscale`).

Po zakończeniu poczekaj kilka minut i sprawdź `docker compose ps`.

Kopia zawiera całą bazę, więc po odtworzeniu **hasła użytkowników, w tym
administratora, są takie, jakie były w momencie robienia kopii** — nie
wartość `OP_ADMIN_PASSWORD` z `.env` (ta działa tylko przy pierwszym starcie na
pustej bazie).

Odtwarzanie na świeżym NAS-ie: wykonaj rozdziały 2–7 (z tym samym `.env`),
poczekaj na pierwszy start stosu, skopiuj katalog kopii na NAS (np. do
`/share/Backup/openproject/`) i uruchom `./restore.sh` jak wyżej.

### 10.4. Kopia poza domem (Hybrid Backup Sync 3)

Kopie na tym samym NAS-ie nie chronią przed kradzieżą, pożarem ani awarią
urządzenia. Wysyłaj je poza dom:

1. W **App Center** zainstaluj **Hybrid Backup Sync 3 (HBS3)**.
2. Otwórz HBS3 → **Sync** (lub **Backup & Restore**) → **Utwórz zadanie**.
3. Źródło: folder `/Backup/openproject` (cały).
4. Cel: wybrana chmura (np. Backblaze B2, Amazon S3, Google Drive) albo
   zewnętrzny dysk / drugi NAS. Podaj dane dostępowe.
5. Harmonogram: codziennie, **po 03:15** (np. 05:00), żeby wysyłać świeżą kopię.
6. Włącz szyfrowanie po stronie klienta, jeśli HBS3 je oferuje — w kopii jest
   cała zawartość projektów.
7. Raz sprawdź, że pliki faktycznie pojawiły się w miejscu docelowym i że umiesz
   je pobrać.

Zachowaj kopię `.env` poza NAS-em (rozdział 6).

---

## 11. Aktualizacje

W obrębie linii 17.x aktualizujesz tak:

```bash
cd /share/Container/openproject-src/deploy/qnap
docker compose exec backup /backup/backup.sh      # 1. kopia przed aktualizacją
docker run --rm -v /share/Container:/git alpine/git -C /git/openproject-src pull --ff-only   # 2. nowa wersja zestawu
docker compose --profile public --profile tailnet pull                                       # 3. nowe obrazy
docker compose --profile public --profile tailnet up -d                                      # 4. restart ze zmianami
```

- Krok 2 pobiera zmiany zestawu (`compose.yml`, skrypty, `.env.example`). Plik
  `.env` jest ignorowany przez Git i zostaje nietknięty. Po tym kroku porównaj
  `.env.example` ze swoim `.env` (`diff .env.example .env`) — jeśli w
  `.env.example` pojawiły się nowe zmienne, dopisz je do `.env`.
- Krok 3 z podaniem profili pobiera także nowe obrazy `cloudflared` i
  `tailscale` (bez profili pobrałby tylko usługi podstawowe).
- Migracje bazy wykonuje kontener `seeder` przy starcie; śledź je w
  `docker compose logs -f seeder web`.

**Zmiana wersji głównej (17 → 18)** nie dzieje się sama: obraz jest przypięty
do `OP_IMAGE_TAG=17-slim`. Gdy wyjdzie linia 18, najpierw przeczytaj uwagi
do wydania na <https://www.openproject.org/docs/release-notes/>, zrób kopię
(ręczną, a najlepiej też świeżą kopię poza domem), a dopiero potem zmień `OP_IMAGE_TAG` w `.env` na
nowy tag i wykonaj `pull` oraz `up -d`. Powrót do starej wersji po migracji
wymaga odtworzenia kopii.

---

## 12. Wymiana RAM i przełączenie profilu pamięci

### 12.1. Montaż modułów

1. Wykonaj kopię ręczną (10.2), zatrzymaj stos: `docker compose --profile public --profile tailnet down`,
   a potem wyłącz NAS (QTS → Zasilanie → Wyłącz) i odłącz zasilanie.
2. Zainstaluj moduły według instrukcji QNAP dla TS-453D (sposób dostępu do gniazd
   SO-DIMM opisuje podręcznik sprzętowy modelu).
   Wstaw **oba** moduły GOODRAM GR2666S464L19S/8G. **Oryginalny moduł 4 GB
   zachowaj** w antystatycznym opakowaniu — przyda się, jeśli nowa pamięć okaże
   się wadliwa.
3. 16 GB to więcej niż oficjalne maksimum QNAP (8 GB). Użytkownicy zgłaszają, że
   16–32 GB w tym modelu działa, ale producent NAS-a tego oficjalnie nie wspiera,
   więc test pamięci poniżej jest tym ważniejszy.

### 12.2. Test pamięci (memtest86+)

Przetestuj pamięć **zanim** zaufasz jej danym — błędy RAM potrafią po cichu
uszkodzić bazę.

1. Na laptopie pobierz **memtest86+** (<https://memtest.org>, wersja do USB) i
   zapisz na pendrivie (kreator z pobranego pakietu albo Rufus / balenaEtcher).
2. Podłącz do NAS-a monitor kablem **HDMI** i klawiaturę USB oraz pendrive.
3. Włącz NAS i przy starcie wejdź do BIOS-u (zwykle klawisz **Del** lub **F2**;
   klawisz może zależeć od wersji firmware) i wybierz pendrive jako urządzenie
   startowe jednorazowo.
4. Zostaw test na **co najmniej 2 pełne przebiegi** (dla 16 GB to kilka godzin).
   Wynik prawidłowy: **0 błędów**. Jakikolwiek błąd = wadliwy moduł → wróć do
   modułu 4 GB i reklamuj/zwróć zakup.
5. Zakup na odległość daje zwykle 14 dni na odstąpienie od umowy, liczone od
   **otrzymania towaru** (sprawdź warunki sklepu) — zmieść test w tym terminie.
6. Wyjmij pendrive, uruchom NAS normalnie. W QTS sprawdź, że widać 16 GB
   (**Panel sterowania → Stan systemu → Informacje o systemie**).

### 12.3. Przełączenie profilu 4 → 16 GB

Siedem zmiennych profilu pamięci jest w `.env` w sekcji „Profil pamieci: 4 GB
RAM (aktywny)”. Podmień ich wartości na wartości profilu 16 GB — skopiuj i wklej
w katalogu `deploy/qnap`:

```bash
cd /share/Container/openproject-src/deploy/qnap
sed -i "s|^OP_DB_MEM=.*|OP_DB_MEM=2g|" .env
sed -i "s|^OP_CACHE_MEM=.*|OP_CACHE_MEM=256m|" .env
sed -i "s|^OP_CACHE_MB=.*|OP_CACHE_MB=192|" .env
sed -i "s|^OP_WEB_MEM=.*|OP_WEB_MEM=3g|" .env
sed -i "s|^OP_WORKER_MEM=.*|OP_WORKER_MEM=1536m|" .env
sed -i "s|^OP_WEB_WORKERS=.*|OP_WEB_WORKERS=2|" .env
sed -i "s|^OP_GOOD_JOB_MAX_THREADS=.*|OP_GOOD_JOB_MAX_THREADS=10|" .env
grep -E '^OP_(DB_MEM|CACHE_MEM|CACHE_MB|WEB_MEM|WORKER_MEM|WEB_WORKERS|GOOD_JOB_MAX_THREADS)=' .env
```

Ostatnie polecenie wypisuje siedem linii z nowymi wartościami. Zakomentowane
bloki „Profil pamieci: 8 GB RAM” i „Profil pamieci: 16 GB RAM” w `.env` są tylko
ściągą i zostają bez zmian; polecenia `sed` zmieniają wyłącznie linie aktywne
(bez `#` na początku). Dla 8 GB użyj wartości z kolumny „8 GB” tabeli poniżej.
Powrót do 4 GB działa tak samo, z wartościami z kolumny „4 GB”.

Zastosuj zmiany:

```bash
docker compose --profile public --profile tailnet up -d
docker stats --no-stream
```

Docker odtworzy tylko kontenery, których ustawienia się zmieniły, a `docker stats`
pokaże nowe limity pamięci.

Wartości profili:

| Zmienna | 4 GB | 8 GB | 16 GB |
|---------|------|------|-------|
| `OP_DB_MEM` | 512m | 1g | 2g |
| `OP_CACHE_MEM` | 64m | 128m | 256m |
| `OP_CACHE_MB` | 48 | 96 | 192 |
| `OP_WEB_MEM` | 1200m | 2g | 3g |
| `OP_WORKER_MEM` | 768m | 1g | 1536m |
| `OP_WEB_WORKERS` | 0 | 1 | 2 |
| `OP_GOOD_JOB_MAX_THREADS` | 3 | 5 | 10 |

---

## 13. Opcjonalnie: dane na SSD

Szybsza baza = szybszy OpenProject. Dane (baza, załączniki, stan Tailscale)
możesz trzymać na SSD, a **kopie zapasowe zostaw na dyskach HDD w RAID**.

1. Zainstaluj SSD i utwórz na nim osobny wolumen (**Storage & Snapshots**,
   po polsku „Pamięć masowa i migawki” → **Utwórz → Nowy wolumen**).
   Szczegóły zależą od modelu dysku i slotu — kieruj się dokumentacją QNAP.
   Pamiętaj, że pojedynczy SSD bez RAID nie chroni przed awarią — dlatego kopie
   zostają na HDD.
2. Utwórz na tym wolumenie folder udostępniony, np. `SSD` (ścieżka `/share/SSD`).
3. Zatrzymaj stos i skopiuj dane z zachowaniem uprawnień:

   ```bash
   cd /share/Container/openproject-src/deploy/qnap
   docker compose --profile public --profile tailnet down
   mkdir -p /share/SSD/openproject
   cp -a /share/Container/openproject/. /share/SSD/openproject/
   ```

4. W `.env` zmień:

   ```
   OP_DATA_DIR=/share/SSD/openproject
   ```

   (`OP_BACKUP_DIR` zostaw na HDD, np. `/share/Backup/openproject`.)
5. Uruchom: `docker compose --profile public --profile tailnet up -d` i sprawdź
   `docker compose ps` oraz logowanie do aplikacji.
6. Gdy wszystko działa kilka dni, stary katalog `/share/Container/openproject`
   możesz usunąć (po sprawdzeniu, że nocna kopia zapisuje się poprawnie).

---

## 14. Rozwiązywanie problemów

Podstawowe narzędzia:

```bash
docker compose ps
docker compose logs --tail=100 web
docker compose logs --tail=100 seeder
docker stats --no-stream
```

**Komunikat „Invalid host_name configuration”.** Wchodzisz pod adresem, którego
aplikacja nie zna. Poprawne są tylko dwa: `OP_PUBLIC_HOST` i `OP_TAILSCALE_HOST`.
Sprawdź w `.env`, czy nazwy są wpisane dokładnie (bez `https://`, bez ukośnika, bez
literówek), popraw i wykonaj `docker compose --profile public --profile tailnet up -d`.
Ten komunikat dostaniesz też, wchodząc na adres IP NAS-a lub przez profil `local`.

**Cloudflare pokazuje błąd 502 lub 1033.** Tunel nie dociera do aplikacji.
- W panelu Cloudflare usługa trasy musi być **`HTTP`** → **`web:8080`**
  (rozdział 5.1), a nie `https://…` ani `localhost`.
- Zobacz logi tunelu: `docker compose --profile public logs --tail=100 cloudflared`.
  Błąd „Unauthorized” / „invalid token” oznacza zły `CLOUDFLARE_TUNNEL_TOKEN`.
- Sprawdź, czy `web` jest `healthy` (`docker compose ps`) — tuż po starcie lub
  po aktualizacji aplikacja potrzebuje kilku minut.

**Tailscale: brak certyfikatu / błąd TLS / adres się nie otwiera.**
- W konsoli Tailscale → **DNS** musi być włączone **HTTPS Certificates** (rozdział 4.2).
- Zobacz logi: `docker compose --profile tailnet logs --tail=100 tailscale`.
  Komunikat o niedostępnych certyfikatach HTTPS potwierdza powód; po włączeniu
  opcji zrestartuj: `docker compose --profile tailnet restart tailscale`.
- W **Machines** sprawdź, czy maszyna nazywa się dokładnie `openproject`. Jeśli
  jest `openproject-1`, w tailnecie została stara maszyna o tej nazwie — usuń ją
  i popraw `OP_TAILSCALE_HOST`.
- Wygasły klucz maszyny: **Machines → … → Disable key expiry** (krok 4.5).
- Urządzenie, z którego wchodzisz, musi mieć włączony Tailscale.

**Kontener ubity / aplikacja restartuje się (brak pamięci, OOM).**
- `docker stats --no-stream` pokazuje zużycie względem limitów.
- Sprawdź, który kontener został ubity:
  `docker inspect -f '{{.State.OOMKilled}}' $(docker compose ps -q web)` (analogicznie `worker`, `db`).
- Rozwiązanie: zainstaluj RAM i przełącz profil na 8/16 GB (rozdział 12) albo zwiększ
  pojedynczy limit w `.env` (`OP_WEB_MEM`, `OP_WORKER_MEM`, `OP_DB_MEM`).

**`opm` zwraca „Authentication failed (401)”.** Zły lub wygaśnięty token
(`OPM_TOKEN`), albo w administracji OpenProject nie są włączone tokeny API
(krok 8.3.5). Wygeneruj nowy token (rozdział 9.1) i sprawdź, czy token nie ma
spacji na początku lub końcu.

**`opm` zwraca komunikat o przekierowaniu („OpenProject redirected the request to …”).**
`OPM_URL` jest adresem `http://` lub niewłaściwą nazwą. Ustaw adres `https://`
z komunikatu — czyli `https://openproject.<tailnet>.ts.net`.

**`opm` zwraca „Cannot reach OpenProject …”.** Brak połączenia: włącz Tailscale
na laptopie i sprawdź adres w `OPM_URL`.

**`opm` zwraca „Missing configuration” (kod 2).** Ustaw `OPM_URL` i `OPM_TOKEN`
albo utwórz `~/.config/opm/config.toml` (rozdział 9.3).

**Stos nie startuje i pisze „Set … in .env”.** Brakuje wartości wymaganej
zmiennej — pamiętaj, że `CLOUDFLARE_TUNNEL_TOKEN`, `TS_AUTHKEY` i `OP_TAILSCALE_HOST`
muszą być niepuste także wtedy, gdy profil nie jest używany (rozdział 6.2).

**`seeder` kończy się błędem.** Zajrzyj w `docker compose logs seeder`. Możliwe
powody: zbyt słabe `OP_ADMIN_PASSWORD` (wygeneruj dłuższe i zrestartuj
`docker compose --profile public --profile tailnet up -d`), zły `OP_DB_PASSWORD`
względem istniejącej bazy (hasło bazy ustawia się tylko przy jej pierwszym
utworzeniu — po zmianie trzeba skasować `pgdata`, tracąc dane, albo zmienić hasło
w PostgreSQL), albo brak miejsca na dysku.

**Dodanie załącznika kończy się błędem „brak uprawnień do systemu plików”.**
Katalog `assets` nie należy do użytkownika 1000. Wykonaj
`chown -R 1000:1000 /share/Container/openproject/assets` (rozdział 2.5; przy
innej wartości `OP_DATA_DIR` użyj jej ścieżki) i spróbuj ponownie — restart nie jest
potrzebny.

**Kontener `backup` restartuje się z błędem uprawnień.** Skrypty utraciły bit
wykonywalności — `chmod +x restore.sh backup/*.sh` (rozdział 3).

---

## 15. Opis zmiennych `.env`

Wartości ustawiasz w pliku `deploy/qnap/.env`. Zmiany zastosujesz poleceniem
`docker compose --profile public --profile tailnet up -d`.

### Obraz i ścieżki

| Zmienna | Domyślnie | Opis |
|---------|-----------|------|
| `OP_IMAGE_TAG` | `17-slim` | Tag obrazu `openproject/openproject`. Zmiana wersji głównej wyłącznie świadomie (rozdział 11). |
| `OP_DATA_DIR` | `/share/Container/openproject` | Katalog danych z podkatalogami `pgdata`, `assets`, `tailscale`. Można przenieść na SSD (rozdział 13). |
| `OP_BACKUP_DIR` | `/share/Backup/openproject` | Katalog nocnych kopii zapasowych (rozdział 10). |

### Adresy

| Zmienna | Domyślnie | Opis |
|---------|-----------|------|
| `OP_PUBLIC_HOST` | `projekty.example.com` | Publiczna nazwa hosta z Cloudflare, np. `pm.twoja-domena.pl`. Główny adres aplikacji, używany w linkach. |
| `OP_TAILSCALE_HOST` | `openproject.tailnet-name.ts.net` | Nazwa węzła w Tailscale. Dodatkowy dozwolony adres aplikacji; nie może być pusta. |
| `OP_LOCAL_PORT` | `8081` | Port na `127.0.0.1` NAS-a dla profilu `local` (diagnostyka). Nie używaj 8080 — zajmuje go panel QTS. |

### Sekrety

| Zmienna | Opis |
|---------|------|
| `OP_DB_PASSWORD` | Hasło bazy danych (`openssl rand -hex 24`, same znaki hex). |
| `OP_SECRET_KEY_BASE` | Klucz sesji Rails (`openssl rand -hex 64`). Zmiana wylogowuje wszystkich użytkowników. |
| `OP_ADMIN_PASSWORD` | Hasło konta `admin`, używane tylko przy pierwszym starcie. |
| `CLOUDFLARE_TUNNEL_TOKEN` | Token tunelu Cloudflare (profil `public`); niepusty także gdy profil nieużywany. |
| `TS_AUTHKEY` | Klucz autoryzacyjny Tailscale (profil `tailnet`); niepusty także gdy profil nieużywany. |

### Kopie zapasowe

| Zmienna | Domyślnie | Opis |
|---------|-----------|------|
| `BACKUP_TIME` | `03:15` | Godzina nocnej kopii, format `GG:MM`. |
| `BACKUP_RETENTION_DAYS` | `14` | Ile dni przechowywać kopie. |
| `TZ` | `Europe/Warsaw` | Strefa czasowa kontenera kopii (wpływa na `BACKUP_TIME`). |

### Profil pamięci

Siedem zmiennych, które przełączasz razem (rozdział 12). Wartości dla 4 / 8 / 16 GB
są w tabeli w rozdziale 12.3.

| Zmienna | Opis |
|---------|------|
| `OP_DB_MEM` | Limit pamięci kontenera `db` (PostgreSQL). |
| `OP_CACHE_MEM` | Limit pamięci kontenera `cache` (memcached). |
| `OP_CACHE_MB` | Rozmiar pamięci cache w MB (ustawiany w memcached, mniejszy od `OP_CACHE_MEM`). |
| `OP_WEB_MEM` | Limit pamięci kontenera `web` (oraz jednorazowego `seeder`). |
| `OP_WORKER_MEM` | Limit pamięci kontenera `worker`. |
| `OP_WEB_WORKERS` | Liczba procesów Puma (`0` = tryb pojedynczy, najmniej pamięci). |
| `OP_GOOD_JOB_MAX_THREADS` | Liczba wątków zadań w tle w `worker`. |

Limity `cloudflared` (64 MB), `tailscale` (96 MB) i `backup` (128 MB) ustalają
odpowiednio opcjonalne zmienne `OP_CLOUDFLARED_MEM`, `OP_TAILSCALE_MEM`
i `OP_BACKUP_MEM`, których zwykle nie trzeba zmieniać (nie ma ich w `.env.example`).

---

Powiązane: dokumentacja `opm` i serwera MCP — [`opm/README.md`](opm/README.md).
