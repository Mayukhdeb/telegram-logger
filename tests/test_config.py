import json

import pytest

import tgtqdm
from tgtqdm import config
from tgtqdm.logger import TelegramLogger


def write_credentials(path, api_token="TOKEN", chat_id=123):
    path.write_text(json.dumps({"api_token": api_token, "chat_id": chat_id}))
    return path


class TestExplicitConfigure:
    def test_configure_builds_a_logger(self):
        tgtqdm.configure(api_token="T", chat_id=1)
        logger = config.get_logger()
        assert isinstance(logger, TelegramLogger)
        assert (logger.api_token, logger.chat_id) == ("T", 1)

    def test_logger_is_cached(self):
        tgtqdm.configure(api_token="T", chat_id=1)
        assert config.get_logger() is config.get_logger()

    def test_reconfigure_replaces_the_logger(self):
        tgtqdm.configure(api_token="T", chat_id=1)
        first = config.get_logger()
        tgtqdm.configure(api_token="T", chat_id=2)
        assert config.get_logger() is not first
        assert config.get_logger().chat_id == 2

    def test_forwards_logger_kwargs(self):
        tgtqdm.configure(api_token="T", chat_id=1, min_interval=7.0, timeout=2.0)
        logger = config.get_logger()
        assert (logger.min_interval, logger.timeout) == (7.0, 2.0)

    def test_configure_from_json(self, tmp_path):
        path = write_credentials(tmp_path / "creds.json")
        tgtqdm.configure(json_filename=str(path))
        assert config.get_logger().chat_id == 123

    def test_configure_with_a_ready_made_logger(self):
        logger = TelegramLogger(api_token="T", chat_id=1)
        tgtqdm.configure(logger=logger)
        assert config.get_logger() is logger

    def test_enabled_false_disables_telegram(self):
        tgtqdm.configure(api_token="T", chat_id=1, enabled=False)
        assert config.get_logger() is None

    def test_half_configured_raises(self):
        tgtqdm.configure(api_token="T")
        with pytest.raises(ValueError, match="chat_id"):
            config.get_logger()

    def test_reset_forgets_everything(self):
        tgtqdm.configure(api_token="T", chat_id=1)
        tgtqdm.reset_config()
        assert config.get_logger(warn=False) is None


class TestDiscovery:
    def test_from_env_vars(self, monkeypatch):
        monkeypatch.setenv(config.ENV_API_TOKEN, "ENVTOKEN")
        monkeypatch.setenv(config.ENV_CHAT_ID, "-1001234")
        logger = config.get_logger()
        assert (logger.api_token, logger.chat_id) == ("ENVTOKEN", -1001234)

    def test_non_numeric_chat_id_from_env_stays_a_string(self, monkeypatch):
        monkeypatch.setenv(config.ENV_API_TOKEN, "ENVTOKEN")
        monkeypatch.setenv(config.ENV_CHAT_ID, "@mychannel")
        assert config.get_logger().chat_id == "@mychannel"

    def test_env_config_path(self, monkeypatch, tmp_path):
        path = write_credentials(tmp_path / "elsewhere.json", chat_id=9)
        monkeypatch.setenv(config.ENV_CONFIG, str(path))
        assert config.get_logger().chat_id == 9

    def test_missing_env_config_path_is_not_fatal(self, monkeypatch, tmp_path):
        monkeypatch.setenv(config.ENV_CONFIG, str(tmp_path / "nope.json"))
        assert config.get_logger(warn=False) is None

    def test_finds_telegram_info_json_in_cwd(self, tmp_path):
        import os

        write_credentials(tmp_path / "cwd" / "telegram_info.json", chat_id=5)
        assert os.path.isfile("telegram_info.json")
        assert config.get_logger().chat_id == 5

    def test_finds_dotfile_in_home(self):
        import os

        write_credentials(
            __import__("pathlib").Path(os.path.expanduser("~")) / ".tgtqdm.json",
            chat_id=6,
        )
        assert config.get_logger().chat_id == 6

    def test_cwd_wins_over_home(self, tmp_path):
        import os
        import pathlib

        write_credentials(tmp_path / "cwd" / "telegram_info.json", chat_id=1)
        write_credentials(
            pathlib.Path(os.path.expanduser("~")) / ".tgtqdm.json", chat_id=2
        )
        assert config.get_logger().chat_id == 1

    def test_explicit_configure_beats_discovery(self, monkeypatch, tmp_path):
        monkeypatch.setenv(config.ENV_API_TOKEN, "ENVTOKEN")
        monkeypatch.setenv(config.ENV_CHAT_ID, "1")
        tgtqdm.configure(api_token="EXPLICIT", chat_id=2)
        assert config.get_logger().api_token == "EXPLICIT"

    def test_broken_config_file_is_reported_not_raised(self, tmp_path, capsys):
        (tmp_path / "cwd" / "telegram_info.json").write_text("{not json")
        assert config.get_logger(warn=False) is None
        assert "could not read credentials" in capsys.readouterr().out


class TestNotConfigured:
    def test_warns_once(self, capsys):
        config.get_logger()
        first = capsys.readouterr().out
        config.get_logger()
        second = capsys.readouterr().out
        assert "no Telegram credentials found" in first
        assert second == ""

    def test_is_configured_does_not_warn(self, capsys):
        assert config.is_configured() is False
        assert capsys.readouterr().out == ""

    def test_env_disable_silences_the_warning(self, monkeypatch, capsys):
        monkeypatch.setenv(config.ENV_DISABLE, "1")
        assert config.get_logger() is None
        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_env_disable_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv(config.ENV_API_TOKEN, "T")
        monkeypatch.setenv(config.ENV_CHAT_ID, "1")
        monkeypatch.setenv(config.ENV_DISABLE, value)
        assert config.get_logger() is None

    @pytest.mark.parametrize("value", ["0", "false", "no", ""])
    def test_env_disable_falsy_values(self, monkeypatch, value):
        monkeypatch.setenv(config.ENV_API_TOKEN, "T")
        monkeypatch.setenv(config.ENV_CHAT_ID, "1")
        monkeypatch.setenv(config.ENV_DISABLE, value)
        assert config.get_logger() is not None


def test_looks_like_credentials(tmp_path):
    good = write_credentials(tmp_path / "good.json")
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    assert config.looks_like_credentials(str(good)) is True
    assert config.looks_like_credentials(str(bad)) is False
    assert config.looks_like_credentials(str(tmp_path / "missing.json")) is False
