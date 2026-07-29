import json
import time
import functools
from typing import Any, Callable, Dict, Optional, TypeVar, Union, cast

import requests

## telegram rejects messages longer than this
MAX_MESSAGE_LENGTH = 4096

## telegram allows roughly one edit per second per chat before it starts
## replying with 429s, so we throttle by default
DEFAULT_MIN_INTERVAL = 1.0

DEFAULT_TIMEOUT = 10.0

ChatId = Union[int, str]

F = TypeVar("F", bound=Callable[..., Any])

HELP_TEXT = (
    "Chances are that your api_token or chat_id is wrong.\n"
    "For your own API token, go to \033[94mhttps://t.me/botfather\033[0m in Telegram and create a new bot.\n"
    "For your chat id, go to \033[94mhttps://t.me/userinfobot\033[0m in Telegram."
)


class TelegramError(RuntimeError):
    """Raised when the telegram API replies with ``ok: false``."""


## substrings telegram uses when the token or chat is the actual problem
_CREDENTIAL_HINTS = (
    "unauthorized",
    "forbidden",
    "chat not found",
    "chat_id is empty",
    "bot was blocked",
    "bot was kicked",
    "user is deactivated",
)


def _looks_like_a_credentials_problem(description: str) -> bool:
    if not description:
        ## no description at all is most often a malformed token
        return True
    lowered = description.lower()
    return any(hint in lowered for hint in _CREDENTIAL_HINTS)


def safe_telegram_call(func: F) -> F:
    """
    Logging to telegram is never worth crashing the user's script over, so any
    exception raised inside ``func`` is printed and ``None`` is returned instead.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:  ## noqa: BLE001 - deliberately broad
            print(f"[TelegramLogger ERROR in {func.__name__}]: {e}")
            return None

    return cast(F, wrapper)


"""
for your own bot, go to t.me/botfather in telegram
for your chat id, go to t.me/userinfobot in telegram
"""


class TelegramLogger:
    """
    usage:
    logger = TelegramLogger(api_token=TOKEN, chat_id=USER_ID)
    logger.log("Hello world") ## sends a message
    logger.log("Hello world2") ## updates the existing message
    """

    def __init__(
        self,
        api_token: str,
        chat_id: ChatId,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not isinstance(api_token, str):
            raise TypeError(f"api_token must be a str and not: {type(api_token)}")
        if not api_token:
            raise ValueError("api_token must not be empty")
        ## bool is a subclass of int, and a bool chat_id is always a mistake
        if isinstance(chat_id, bool) or not isinstance(chat_id, (int, str)):
            raise TypeError(f"chat_id must be an int or a str and not: {type(chat_id)}")
        if min_interval < 0:
            raise ValueError(f"min_interval must be >= 0 and not: {min_interval}")
        if timeout <= 0:
            raise ValueError(f"timeout must be > 0 and not: {timeout}")

        self.api_token = api_token
        self.chat_id = chat_id
        self.min_interval = min_interval
        self.timeout = timeout
        self.message_id: Optional[int] = None
        self._last_sent_at: Optional[float] = None
        self._last_text: Optional[str] = None

    def get_timestamp(self) -> str:
        t = time.time()
        return time.strftime("%Y-%m-%d %I:%M:%S %p", time.localtime(t))

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.api_token}/{method}"

    def _post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = requests.post(self._url(method), json=payload, timeout=self.timeout)
        try:
            data = response.json()
        except ValueError as e:
            raise TelegramError(
                f"telegram returned a non-JSON response (status {response.status_code})"
            ) from e
        if not isinstance(data, dict) or not data.get("ok"):
            description = ""
            if isinstance(data, dict):
                description = str(data.get("description", ""))
            message = f"{method} failed: {description}"
            ## the "check your credentials" advice is only helpful when the
            ## failure actually looks like a credentials problem
            if _looks_like_a_credentials_problem(description):
                message = f"{message}\n{HELP_TEXT}"
            raise TelegramError(message)
        return data

    @staticmethod
    def truncate(text: str) -> str:
        """Trim ``text`` down to what telegram will actually accept."""
        if len(text) <= MAX_MESSAGE_LENGTH:
            return text
        suffix = "\n...[truncated]"
        return text[: MAX_MESSAGE_LENGTH - len(suffix)] + suffix

    @safe_telegram_call
    def send_initial_message(self, text: str) -> Optional[int]:
        data = self._post(
            "sendMessage", {"chat_id": self.chat_id, "text": self.truncate(text)}
        )
        message_id = data["result"]["message_id"]
        return int(message_id)

    @safe_telegram_call
    def update_message(self, message: str) -> Optional[Dict[str, Any]]:
        if self.message_id is None:
            raise TelegramError("no message to update yet, call log() first")
        return self._post(
            "editMessageText",
            {
                "chat_id": self.chat_id,
                "message_id": self.message_id,
                "text": self.truncate(message),
            },
        )

    def log(self, message: str, timestamp: bool = False, force: bool = False) -> None:
        """
        Send ``message``, or edit the previously sent message if there is one.

        Calls that arrive less than ``min_interval`` seconds after the previous
        one are dropped, unless ``force`` is set. The first call and any call
        that follows a failure are never dropped.
        """
        if not isinstance(message, str):
            message = str(message)
        if timestamp:
            message = f"[{self.get_timestamp()}]\n{message}"

        if self.message_id is not None and not force and self._should_throttle():
            return
        ## telegram errors out on an edit that does not change anything
        if self.message_id is not None and message == self._last_text:
            return

        if self.message_id is None:
            self.message_id = self.send_initial_message(message)
            if self.message_id is None:
                ## the send failed; don't remember the text so the next call retries
                return
        else:
            if self.update_message(message=message) is None:
                return

        self._last_sent_at = time.monotonic()
        self._last_text = message

    def _should_throttle(self) -> bool:
        if self.min_interval <= 0 or self._last_sent_at is None:
            return False
        return (time.monotonic() - self._last_sent_at) < self.min_interval

    def reset(self) -> None:
        """Forget the current message so the next :meth:`log` sends a new one."""
        self.message_id = None
        self._last_sent_at = None
        self._last_text = None

    @classmethod
    def from_json(cls, filename: str, **kwargs: Any) -> "TelegramLogger":
        with open(filename, "r") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise TypeError(f"{filename} must contain a JSON object and not: {type(data)}")
        for key in ("api_token", "chat_id"):
            if key not in data:
                raise KeyError(f"{key} not found in {filename}")

        return cls(api_token=data["api_token"], chat_id=data["chat_id"], **kwargs)
