import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    url: str
    token: str


def config_path() -> Path:
    return Path.home() / ".config" / "opm" / "config.toml"


def load_config() -> Config:
    file_values = _read_file(config_path())
    url = str(os.environ.get("OPM_URL") or file_values.get("url") or "").strip()
    token = str(os.environ.get("OPM_TOKEN") or file_values.get("token") or "").strip()

    missing = [name for name, value in (("OPM_URL", url), ("OPM_TOKEN", token)) if not value]
    if missing:
        raise ConfigError(
            f"Missing configuration: {', '.join(missing)}. Set the environment variables "
            f"OPM_URL and OPM_TOKEN, or create {config_path()} containing:\n"
            '  url = "https://openproject.example.com"\n'
            '  token = "<API token from My account > Access tokens>"'
        )

    url = url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ConfigError(f"OPM_URL must start with http:// or https://, got {url!r}.")
    parsed = urlparse(url)
    if parsed.scheme == "http" and not _is_plain_http_host(parsed.hostname or ""):
        raise ConfigError(
            f"OPM_URL {url!r} uses plain http://, which would send the API token unencrypted. "
            "Use https://. Plain http:// is only accepted for localhost, 127.0.0.1 and *.ts.net hosts."
        )
    return Config(url=url, token=token)


def _is_plain_http_host(host: str) -> bool:
    return host in ("localhost", "127.0.0.1") or host.endswith(".ts.net")


def _read_file(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
