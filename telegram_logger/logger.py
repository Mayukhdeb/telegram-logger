import requests
import time
from functools import wraps
import json

def safe_telegram_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print(f"[TelegramLogger ERROR in {func.__name__}]: {e}")
            return None
    return wrapper

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
    def __init__(self, api_token: str, chat_id: int):

        assert isinstance(api_token, str), f"api_token must be a string and not: {type(api_token)}"
        assert isinstance(chat_id, int), f"chat_id must be a string and not: {type(chat_id)}"
        self.api_token = api_token
        self.chat_id = chat_id
        self.message_id = None

    def get_timestamp(self):
        t = time.time()
        return time.strftime('%Y-%m-%d %I:%M:%S %p', time.localtime(t))

    @safe_telegram_call
    def send_initial_message(self, text: str) -> int:
        url = f"https://api.telegram.org/bot{self.api_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text
        }
        response = requests.post(url, json=payload).json()
        assert response["ok"], (
            "Big oof, Chances are that your api_token or chat_id is wrong.\n"
            "For your own API token, go to \033[94mhttps://t.me/botfather\033[0m in Telegram and create a new bot.\n"
            "For your chat id, go to \033[94mhttps://t.me/userinfobot\033[0m in Telegram."
        )
        return response["result"]["message_id"]

    @safe_telegram_call
    def update_message(self, message: str):
        url = f"https://api.telegram.org/bot{self.api_token}/editMessageText"
        payload = {
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "text": message
        }
        response = requests.post(url, json=payload)
        return response.json()

    def log(self, message: str, timestamp = False) -> None:
        if timestamp:
            message = f"[{self.get_timestamp()}]\n{message}"
        if self.message_id is None:
            self.message_id = self.send_initial_message(message)
        else:
            self.update_message(
                message=message
            )

    @classmethod
    def from_json(cls, filename: str):
        data = json.load(open(filename, "r"))
        assert isinstance(data, dict), f"data must be a dict and not: {type(data)}"
        assert "api_token" in data, f"api_token not found in {filename}"
        assert "chat_id" in data, f"chat_id not found in {filename}"

        return cls(
            api_token=data["api_token"],
            chat_id=data["chat_id"]
        )