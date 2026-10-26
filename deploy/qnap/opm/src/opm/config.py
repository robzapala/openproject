import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


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
    url = os.environ.get("OPM_URL") or file_values.get("url")
    token = os.environ.get("OPM_TOKEN") or file_values.get("token")

    missing = [name for name, value in (("OPM_URL", url), ("OPM_TOKEN", token)) if not value]
    if missing:
        raise ConfigError(
            f"Missing configuration: {', '.join(missing)}. Set the environment variables "
            f"OPM_URL and OPM_TOKEN, or create {config_path()} containing:\n"
            '  url = "https://openproject.example.com"\n'
            '  token = "<API token from My account > Access tokens>"'
        )

    url = str(url).strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ConfigError(f"OPM_URL must start with http:// or https://, got {url!r}.")
    return Config(url=url, token=str(token).strip())


def _read_file(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except (tomllib.TOMLDecodeError, OSError) as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
