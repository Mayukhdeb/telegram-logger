# telegram-logger
who needs work-life balance when you can watch your logs on the phone?

I made this because I wanted to watch my scripts go brr while I'm away from my computer

```
pip install git+https://github.com/Mayukhdeb/telegram-logger.git
```

```python
from telegram_logger import TelegramLogger

logger = TelegramLogger(
    api_token="...",
    chat_id=123
)

## when you log for the first time, it will send a message
logger.log(message="Lettuce begin", timestamp=False)

## when you log again, it will update the existing message
logger.log(message="Legume resume", timestamp=False)
```

## Getting your API token and chat ID

- For your own API token, go to [t.me/botfather](https://t.me/botfather) in telegram and create a new bot
- For your chat id, go to [t.me/userinfobot](https://t.me/userinfobot) in telegram

Alternatively, you can also safely store your api token and chat ID in a json and initialize your logger from the filename. This is usually safer for dummies

```python
logger = TelegramLogger.from_json(
    filename="telegram_info.json"
)
```

The json file should look like this:
```json
{
    "api_token": "TOKEN",
    "chat_id": 123456789
}
```

