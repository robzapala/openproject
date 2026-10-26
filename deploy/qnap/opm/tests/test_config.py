import pytest

from opm.config import Config, ConfigError, load_config


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("OPM_URL", raising=False)
    monkeypatch.delenv("OPM_TOKEN", raising=False)
    return tmp_path


def write_config(home, body):
    path = home / ".config" / "opm" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(body)


def test_env_takes_precedence_over_file(isolated_home, monkeypatch):
    write_config(isolated_home, 'url = "https://file.example"\ntoken = "file-token"\n')
    monkeypatch.setenv("OPM_URL", "https://env.example")
    monkeypatch.setenv("OPM_TOKEN", "env-token")

    assert load_config() == Config(url="https://env.example", token="env-token")


def test_file_is_used_when_env_is_missing(isolated_home):
    write_config(isolated_home, 'url = "https://file.example"\ntoken = "file-token"\n')

    assert load_config() == Config(url="https://file.example", token="file-token")


def test_missing_everything_raises_config_error_with_instructions():
    with pytest.raises(ConfigError) as exc:
        load_config()

    assert "OPM_URL" in str(exc.value)
    assert "OPM_TOKEN" in str(exc.value)
    assert "config.toml" in str(exc.value)


def test_missing_token_only_names_the_token(monkeypatch):
    monkeypatch.setenv("OPM_URL", "https://env.example")

    with pytest.raises(ConfigError) as exc:
        load_config()

    assert "OPM_TOKEN" in str(exc.value)


def test_trailing_slash_is_removed(monkeypatch):
    monkeypatch.setenv("OPM_URL", "https://env.example/")
    monkeypatch.setenv("OPM_TOKEN", "t")

    assert load_config().url == "https://env.example"


def test_url_without_scheme_is_rejected(monkeypatch):
    monkeypatch.setenv("OPM_URL", "env.example")
    monkeypatch.setenv("OPM_TOKEN", "t")

    with pytest.raises(ConfigError):
        load_config()


def test_invalid_toml_raises_config_error(isolated_home):
    write_config(isolated_home, "url = ")

    with pytest.raises(ConfigError):
        load_config()


def test_whitespace_only_token_counts_as_missing(monkeypatch):
    monkeypatch.setenv("OPM_URL", "https://env.example")
    monkeypatch.setenv("OPM_TOKEN", "  ")

    with pytest.raises(ConfigError) as exc:
        load_config()

    assert "OPM_TOKEN" in str(exc.value)
