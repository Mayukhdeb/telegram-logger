import json

import pytest

from tgtqdm import TelegramError, TelegramLogger
from tgtqdm.logger import MAX_MESSAGE_LENGTH

from .conftest import FakeResponse


class TestConstruction:
    def test_rejects_non_string_token(self):
        with pytest.raises(TypeError):
            TelegramLogger(api_token=123, chat_id=1)  # type: ignore[arg-type]

    def test_rejects_empty_token(self):
        with pytest.raises(ValueError):
            TelegramLogger(api_token="", chat_id=1)

    def test_accepts_string_chat_id(self):
        ## channel usernames are valid chat ids
        assert TelegramLogger(api_token="T", chat_id="@mychannel").chat_id == "@mychannel"

    def test_rejects_bool_chat_id(self):
        with pytest.raises(TypeError):
            TelegramLogger(api_token="T", chat_id=True)

    def test_rejects_none_chat_id(self):
        with pytest.raises(TypeError):
            TelegramLogger(api_token="T", chat_id=None)  # type: ignore[arg-type]

    @pytest.mark.parametrize("kwargs", [{"min_interval": -1}, {"timeout": 0}])
    def test_rejects_bad_tuning(self, kwargs):
        with pytest.raises(ValueError):
            TelegramLogger(api_token="T", chat_id=1, **kwargs)


class TestFromJson:
    def test_reads_credentials(self, credentials_file):
        logger = TelegramLogger.from_json(str(credentials_file))
        assert logger.api_token == "TOKEN"
        assert logger.chat_id == 123

    def test_forwards_kwargs(self, credentials_file):
        logger = TelegramLogger.from_json(str(credentials_file), min_interval=5.0)
        assert logger.min_interval == 5.0

    def test_missing_key(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"api_token": "T"}))
        with pytest.raises(KeyError):
            TelegramLogger.from_json(str(path))

    def test_not_an_object(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps([1, 2, 3]))
        with pytest.raises(TypeError):
            TelegramLogger.from_json(str(path))

    def test_does_not_leak_the_file_handle(self, credentials_file):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            TelegramLogger.from_json(str(credentials_file))


class TestLog:
    def test_first_log_sends_then_edits(self, make_logger, poster):
        logger = make_logger()
        logger.log("one")
        logger.log("two")
        assert poster.methods == ["sendMessage", "editMessageText"]
        assert logger.message_id == 42
        assert poster.calls[1]["json"]["message_id"] == 42

    def test_passes_a_timeout(self, make_logger, poster):
        make_logger(timeout=3.5).log("hi")
        assert poster.calls[0]["timeout"] == 3.5

    def test_timestamp_prefix(self, make_logger, poster):
        make_logger().log("hi", timestamp=True)
        text = poster.texts[0]
        assert text.endswith("\nhi") and text.startswith("[")

    def test_identical_text_is_not_re_sent(self, make_logger, poster):
        ## telegram errors out on a no-op edit
        logger = make_logger()
        logger.log("same")
        logger.log("same")
        assert poster.methods == ["sendMessage"]

    def test_long_messages_are_truncated(self, make_logger, poster):
        make_logger().log("x" * (MAX_MESSAGE_LENGTH + 500))
        text = poster.texts[0]
        assert len(text) == MAX_MESSAGE_LENGTH
        assert text.endswith("[truncated]")

    def test_non_string_message_is_coerced(self, make_logger, poster):
        make_logger().log(1234)  # type: ignore[arg-type]
        assert poster.texts[0] == "1234"

    def test_reset_starts_a_new_message(self, make_logger, poster):
        logger = make_logger()
        logger.log("one")
        logger.reset()
        logger.log("one")
        assert poster.methods == ["sendMessage", "sendMessage"]


class TestFailureHandling:
    def test_api_error_does_not_raise(self, make_logger, poster, capsys):
        poster.queue(FakeResponse({"ok": False, "description": "chat not found"}))
        logger = make_logger()
        logger.log("hi")
        assert logger.message_id is None
        assert "chat not found" in capsys.readouterr().out

    def test_failed_send_is_retried_on_next_log(self, make_logger, poster):
        poster.queue(FakeResponse({"ok": False, "description": "nope"}))
        logger = make_logger()
        logger.log("hi")
        logger.log("hi")
        ## the second call must send rather than edit a message that never existed
        assert poster.methods == ["sendMessage", "sendMessage"]
        assert logger.message_id == 42

    def test_credentials_advice_is_shown_for_auth_errors(
        self, make_logger, poster, capsys
    ):
        poster.queue(FakeResponse({"ok": False, "description": "Unauthorized"}))
        make_logger().log("hi")
        assert "botfather" in capsys.readouterr().out

    def test_credentials_advice_is_hidden_for_unrelated_errors(
        self, make_logger, poster, capsys
    ):
        logger = make_logger()
        logger.log("one")
        poster.queue(
            FakeResponse(
                {"ok": False, "description": "Bad Request: message is not modified"}
            )
        )
        logger.log("two")
        out = capsys.readouterr().out
        assert "message is not modified" in out
        assert "botfather" not in out

    def test_non_json_response(self, make_logger, poster, capsys):
        poster.queue(FakeResponse(None, status_code=502, raw="<html>"))
        make_logger().log("hi")
        assert "non-JSON" in capsys.readouterr().out

    def test_network_error_does_not_raise(self, make_logger, monkeypatch, capsys):
        import requests

        from tgtqdm import logger as logger_module

        def boom(*args, **kwargs):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(logger_module.requests, "post", boom)
        make_logger().log("hi")
        assert "down" in capsys.readouterr().out

    def test_update_before_send_raises_internally_but_is_caught(self, make_logger):
        logger = make_logger()
        assert logger.update_message("hi") is None

    def test_failed_edit_allows_a_later_retry_of_same_text(self, make_logger, poster):
        logger = make_logger()
        logger.log("one")
        poster.queue(FakeResponse({"ok": False, "description": "flood"}))
        logger.log("two")
        logger.log("two")
        assert poster.methods == ["sendMessage", "editMessageText", "editMessageText"]


class TestThrottling:
    def test_rapid_updates_are_dropped(self, make_logger, poster):
        logger = make_logger(min_interval=60.0)
        logger.log("one")
        logger.log("two")
        assert poster.methods == ["sendMessage"]

    def test_force_bypasses_the_throttle(self, make_logger, poster):
        logger = make_logger(min_interval=60.0)
        logger.log("one")
        logger.log("two", force=True)
        assert poster.methods == ["sendMessage", "editMessageText"]

    def test_throttle_expires(self, make_logger, poster, monkeypatch):
        from tgtqdm import logger as logger_module

        clock = [1000.0]
        monkeypatch.setattr(logger_module.time, "monotonic", lambda: clock[0])
        logger = make_logger(min_interval=1.0)
        logger.log("one")
        logger.log("two")
        assert poster.methods == ["sendMessage"]
        clock[0] += 5
        logger.log("three")
        assert poster.methods == ["sendMessage", "editMessageText"]

    def test_first_message_is_never_throttled(self, make_logger, poster):
        make_logger(min_interval=1e6).log("one")
        assert poster.methods == ["sendMessage"]


def test_truncate_leaves_short_text_alone():
    assert TelegramLogger.truncate("hi") == "hi"


def test_url_contains_the_token(make_logger):
    assert make_logger()._url("sendMessage").endswith("/botTOKEN/sendMessage")


def test_get_timestamp_is_a_string(make_logger):
    assert isinstance(make_logger().get_timestamp(), str)


def test_telegram_error_is_a_runtime_error():
    assert issubclass(TelegramError, RuntimeError)
