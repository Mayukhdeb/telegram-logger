"""
Process-wide credential configuration.

The point of this module is that ``from tgtqdm import tqdm`` can work without
threading an api token through every call site. Credentials are resolved once,
lazily, the first time a bar actually wants to talk to Telegram.
"""

import json
import os
import threading
from typing import Any, Dict, Optional, Tuple, cast

from .logger import ChatId, TelegramLogger

ENV_API_TOKEN = "TGTQDM_API_TOKEN"
ENV_CHAT_ID = "TGTQDM_CHAT_ID"
ENV_CONFIG = "TGTQDM_CONFIG"
ENV_DISABLE = "TGTQDM_DISABLE"

## searched in order, relative to the cwd and then the home directory
DEFAULT_CONFIG_NAMES = ("telegram_info.json", ".tgtqdm.json")

_lock = threading.RLock()
_overrides: Dict[str, Any] = {}
_logger: Optional[TelegramLogger] = None
_resolved = False
_warned = False


def configure(
    api_token: Optional[str] = None,
    chat_id: Optional[ChatId] = None,
    json_filename: Optional[str] = None,
    logger: Optional[TelegramLogger] = None,
    enabled: bool = True,
    **logger_kwargs: Any,
) -> None:
    """
    Set the credentials used by every :class:`tgtqdm.tqdm` from here on.

    Call this once near the top of your script::

        import tgtqdm
        tgtqdm.configure(api_token="...", chat_id=123)

    Passing ``enabled=False`` turns Telegram off entirely, leaving plain local
    progress bars. If you never call this, credentials are looked up in the
    ``TGTQDM_API_TOKEN``/``TGTQDM_CHAT_ID`` environment variables, then in
    ``$TGTQDM_CONFIG``, then in ``telegram_info.json`` or ``.tgtqdm.json`` in
    the current directory or your home directory.
    """
    global _overrides, _resolved, _logger, _warned
    with _lock:
        _overrides = {
            "api_token": api_token,
            "chat_id": chat_id,
            "json_filename": json_filename,
            "logger": logger,
            "enabled": enabled,
            "logger_kwargs": logger_kwargs,
        }
        ## force a re-resolve on next use
        _resolved = False
        _logger = None
        _warned = False


def reset() -> None:
    """Forget any configuration, including the cached logger."""
    global _overrides, _resolved, _logger, _warned
    with _lock:
        _overrides = {}
        _resolved = False
        _logger = None
        _warned = False


def is_configured() -> bool:
    """Whether a logger is available, without emitting the not-configured warning."""
    return get_logger(warn=False) is not None


def get_logger(warn: bool = True) -> Optional[TelegramLogger]:
    """
    Return the shared :class:`TelegramLogger`, or ``None`` if Telegram is
    disabled or no credentials could be found.
    """
    global _resolved, _logger, _warned
    with _lock:
        if not _resolved:
            _logger = _build_logger()
            _resolved = True
        if _logger is None and warn and not _warned:
            _warned = True
            if not _disabled_by_env():
                print(_NOT_CONFIGURED_MESSAGE)
        return _logger


def _disabled_by_env() -> bool:
    value = os.environ.get(ENV_DISABLE, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _build_logger() -> Optional[TelegramLogger]:
    if _disabled_by_env():
        return None

    kwargs: Dict[str, Any] = dict(_overrides.get("logger_kwargs") or {})

    if _overrides:
        if not _overrides.get("enabled", True):
            return None
        explicit = _overrides.get("logger")
        if explicit is not None:
            ## any object with a compatible log() is accepted
            return cast(TelegramLogger, explicit)
        api_token = _overrides.get("api_token")
        chat_id = _overrides.get("chat_id")
        if api_token is not None and chat_id is not None:
            return TelegramLogger(api_token=api_token, chat_id=chat_id, **kwargs)
        if _overrides.get("json_filename") is not None:
            return TelegramLogger.from_json(_overrides["json_filename"], **kwargs)
        if api_token is not None or chat_id is not None:
            missing = "chat_id" if api_token is not None else "api_token"
            raise ValueError(f"configure() is missing {missing}")

    from_env = _credentials_from_env()
    if from_env is not None:
        return TelegramLogger(
            api_token=from_env[0], chat_id=from_env[1], **kwargs
        )

    path = _find_config_file()
    if path is not None:
        try:
            return TelegramLogger.from_json(path, **kwargs)
        except Exception as e:  ## noqa: BLE001 - a broken config must not crash a loop
            print(f"[tgtqdm] could not read credentials from {path}: {e}")
            return None
    return None


def _parse_chat_id(raw: str) -> ChatId:
    text = raw.strip()
    try:
        return int(text)
    except ValueError:
        return text


def _credentials_from_env() -> Optional[Tuple[str, ChatId]]:
    api_token = os.environ.get(ENV_API_TOKEN)
    chat_id = os.environ.get(ENV_CHAT_ID)
    if api_token and chat_id:
        return api_token.strip(), _parse_chat_id(chat_id)
    return None


def _find_config_file() -> Optional[str]:
    explicit = os.environ.get(ENV_CONFIG)
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for directory in (os.getcwd(), os.path.expanduser("~")):
        for name in DEFAULT_CONFIG_NAMES:
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def looks_like_credentials(path: str) -> bool:
    """Whether ``path`` is a JSON object holding both required keys."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception:  ## noqa: BLE001
        return False
    return isinstance(data, dict) and "api_token" in data and "chat_id" in data


_NOT_CONFIGURED_MESSAGE = (
    "[tgtqdm] no Telegram credentials found, showing a local progress bar only.\n"
    "         call tgtqdm.configure(api_token=..., chat_id=...) near the top of your\n"
    f"         script, set ${ENV_API_TOKEN} and ${ENV_CHAT_ID}, or drop a\n"
    "         telegram_info.json next to it. set $TGTQDM_DISABLE=1 to silence this."
)
