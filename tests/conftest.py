import json
import os
from typing import Any, Dict, List, Optional

import pytest

from tgtqdm import config as config_module
from tgtqdm import logger as logger_module
from tgtqdm import std as std_module


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """
    Keep global state out of the tests: no leftover configuration, no leftover
    bars, and no chance of picking up a real telegram_info.json from the repo or
    the developer's home directory.
    """
    for name in (
        config_module.ENV_API_TOKEN,
        config_module.ENV_CHAT_ID,
        config_module.ENV_CONFIG,
        config_module.ENV_DISABLE,
    ):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", str(home), 1))
    config_module.reset()
    std_module.registry().clear()
    yield
    config_module.reset()
    std_module.registry().clear()


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200, raw: Optional[str] = None):
        self._payload = payload
        self.status_code = status_code
        self._raw = raw

    def json(self) -> Any:
        if self._raw is not None:
            raise ValueError("not json")
        return self._payload


class FakePoster:
    """Records every requests.post call and replies with queued responses."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.responses: List[FakeResponse] = []
        self.default_message_id = 42

    def queue(self, response: FakeResponse) -> None:
        self.responses.append(response)

    def __call__(self, url: str, json: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.responses:
            return self.responses.pop(0)
        if url.endswith("/sendMessage"):
            return FakeResponse(
                {"ok": True, "result": {"message_id": self.default_message_id}}
            )
        return FakeResponse({"ok": True, "result": {}})

    @property
    def methods(self) -> List[str]:
        return [call["url"].rsplit("/", 1)[-1] for call in self.calls]

    @property
    def texts(self) -> List[str]:
        return [call["json"]["text"] for call in self.calls]


@pytest.fixture
def poster(monkeypatch: pytest.MonkeyPatch) -> FakePoster:
    fake = FakePoster()
    monkeypatch.setattr(logger_module.requests, "post", fake)
    return fake


@pytest.fixture
def make_logger(poster: FakePoster):
    def factory(**kwargs: Any) -> logger_module.TelegramLogger:
        kwargs.setdefault("api_token", "TOKEN")
        kwargs.setdefault("chat_id", 123)
        kwargs.setdefault("min_interval", 0.0)
        return logger_module.TelegramLogger(**kwargs)

    return factory


@pytest.fixture
def credentials_file(tmp_path):
    path = tmp_path / "telegram_info.json"
    path.write_text(json.dumps({"api_token": "TOKEN", "chat_id": 123}))
    return path
