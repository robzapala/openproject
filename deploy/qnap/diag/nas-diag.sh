#!/bin/sh
set -u

speedtest=0
[ "${1:-}" = "--speedtest" ] && speedtest=1

out="${NAS_DIAG_OUT:-$PWD/nas-diag-$(date +%Y%m%d-%H%M).txt}"

has() { command -v "$1" >/dev/null 2>&1; }

section() { printf '\n===== %s =====\n' "$1"; }

run() {
  printf '$ %s\n' "$*"
  "$@" 2>&1 || printf '(polecenie zakończone kodem %s)\n' "$?"
}

cpu_busy_percent() {
  a=$(awk '/^cpu /{print $2+$3+$4+$6+$7+$8, $5}' /proc/stat)
  sleep 5
  b=$(awk '/^cpu /{print $2+$3+$4+$6+$7+$8, $5}' /proc/stat)
  echo "$a $b" | awk '{busy=$3-$1; idle=$4-$2; t=busy+idle; if (t>0) printf "CPU zajęty: %.0f%% (średnio z 5 s)\n", busy*100/t; else print "CPU: brak danych"}'
}

disk_busy_percent() {
  snap() { awk '$3 ~ /^(sd[a-z]+|nvme[0-9]+n[0-9]+|md[0-9]+)$/ {print $3, $6, $10, $13}' /proc/diskstats; }
  snap > "$tmp/d1"
  sleep 5
  snap > "$tmp/d2"
  printf '%-10s %10s %10s %8s\n' urządzenie odczyt_MB/s zapis_MB/s zajęty_%
  awk 'NR==FNR {r[$1]=$2; w[$1]=$3; t[$1]=$4; next}
       ($1 in r) {printf "%-10s %10.1f %10.1f %8.0f\n", $1, ($2-r[$1])*512/5/1048576, ($3-w[$1])*512/5/1048576, ($4-t[$1])/50}' "$tmp/d1" "$tmp/d2"
}

network_links() {
  for dev in /sys/class/net/*; do
    name=$(basename "$dev")
    case "$name" in lo|docker*|veth*|br-*|lxc*|qvs*|tun*|tailscale*) continue ;; esac
    state=$(cat "$dev/operstate" 2>/dev/null)
    speed=$(cat "$dev/speed" 2>/dev/null || echo "?")
    duplex=$(cat "$dev/duplex" 2>/dev/null || echo "?")
    rx_err=$(cat "$dev/statistics/rx_errors" 2>/dev/null || echo "?")
    tx_err=$(cat "$dev/statistics/tx_errors" 2>/dev/null || echo "?")
    drops=$(cat "$dev/statistics/rx_dropped" 2>/dev/null || echo "?")
    printf '%-10s stan=%-6s prędkość=%s Mb/s dupleks=%s błędy_rx=%s błędy_tx=%s odrzucone_rx=%s\n' \
      "$name" "$state" "$speed" "$duplex" "$rx_err" "$tx_err" "$drops"
  done
}

disks() {
  for dev in /sys/block/sd* /sys/block/nvme*; do
    [ -e "$dev" ] || continue
    name=$(basename "$dev")
    model=$(cat "$dev/device/model" 2>/dev/null | tr -s ' ')
    size_gb=$(awk '{printf "%.0f", $1*512/1e9}' "$dev/size" 2>/dev/null)
    rotational=$(cat "$dev/queue/rotational" 2>/dev/null)
    kind=HDD
    [ "$rotational" = "0" ] && kind=SSD
    printf '%-8s %-30s %6s GB %s\n' "$name" "$model" "$size_gb" "$kind"
  done
}

smart_summary() {
  if ! has smartctl; then
    echo "smartctl niedostępny — sprawdź stan dysków w Menedżerze magazynu (Dyski → Stan)."
    return
  fi
  for dev in /dev/sd? /dev/nvme?n1; do
    [ -e "$dev" ] || continue
    printf '\n--- %s ---\n' "$dev"
    smartctl -H -i -A "$dev" 2>&1 | grep -iE 'model|serial|health|result|reallocated|pending|uncorrect|crc|power_on|temperature|wear|percentage' || true
  done
}

read_speed() {
  target=$(awk '$2 ~ /^\/share\/CACHEDEV1_DATA$/ {print $1}' /proc/mounts | head -n 1)
  [ -n "$target" ] || target=/dev/md1
  if [ ! -e "$target" ]; then
    echo "Nie znaleziono urządzenia woluminu do testu odczytu."
    return
  fi
  echo "Test odczytu 1 GB z $target (tylko odczyt)..."
  dd if="$target" of=/dev/null bs=1M count=1024 2>&1 | tail -n 1
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM

{
  echo "Raport diagnostyczny NAS — $(date)"
  echo "Skrypt tylko czyta dane; niczego nie zmienia."

  section "System"
  run uname -a
  has getcfg && printf 'QTS: %s (build %s)\n' "$(getcfg System Version)" "$(getcfg System 'Build Number')"
  run uptime
  grep -m1 'model name' /proc/cpuinfo
  printf 'Rdzenie: %s\n' "$(grep -c ^processor /proc/cpuinfo)"

  section "Procesor (pomiar 5 s)"
  cpu_busy_percent

  section "Pamięć"
  run free -m
  grep -E 'MemTotal|MemAvailable|SwapTotal|SwapFree|^Cached' /proc/meminfo
  run cat /proc/swaps

  section "Najbardziej obciążające procesy"
  if top -b -n 1 >/dev/null 2>&1; then
    top -b -n 1 | head -n 25
  else
    run ps
  fi

  section "Sieć"
  network_links
  has ip && run ip -4 -o addr

  section "Dyski"
  disks

  section "RAID (szukaj: resync / recovery / check)"
  run cat /proc/mdstat

  section "Obciążenie dysków (pomiar 5 s)"
  disk_busy_percent

  section "Stan SMART"
  smart_summary

  section "Woluminy"
  run df -h

  section "Ustawienia SMB"
  if [ -f /etc/config/smb.conf ]; then
    grep -iE '^[[:space:]]*(server (min|max) protocol|min protocol|max protocol|smb encrypt|server signing|oplocks|aio|strict sync|socket options)' /etc/config/smb.conf || echo "(brak nietypowych ustawień)"
  fi

  section "Docker"
  if has docker; then
    run docker ps --format '{{.Names}}\t{{.Status}}'
    run docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'
  else
    echo "Docker niedostępny w tej powłoce."
  fi

  if [ "$speedtest" = 1 ]; then
    section "Test odczytu z dysków"
    read_speed
  fi
} > "$out" 2>&1

chmod 600 "$out"
echo "Gotowe. Raport zapisany w: $out"
echo "Przejrzyj go, zanim komuś wyślesz (zawiera adresy IP i nazwy dysków)."
