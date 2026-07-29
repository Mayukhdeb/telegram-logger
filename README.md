# tgtqdm

<p align="center">
    <img src="images/banner.png" alt="tgtqdm banner" width="50%" />
</p>

who needs work-life balance when you can watch your logs on the phone?

I made this because I wanted to watch my scripts go brr while I'm away from my computer

```bash
pip install tgtqdm
```

## drop-in replacement for tqdm

Change one import and your existing progress bars start showing up on your phone:

```python
-from tqdm import tqdm
+from tgtqdm import tqdm
```

That's it. Everything else keeps working — `desc`, `total`, `leave`, `unit_scale`,
`bar_format`, `set_postfix`, `update()`, `with tqdm(...) as pbar`, `trange`,
nested bars, `tqdm.write()`, `tqdm.pandas()`, and `from tgtqdm.auto import tqdm`.
Arguments that only affect terminal cosmetics (`colour`, `position`, `ncols`, ...)
are accepted so nothing breaks. You still get the normal bar in your terminal;
Telegram gets a copy of it in a single message that keeps getting edited.

```python
from tgtqdm import tqdm

for epoch in tqdm(range(10), desc="epochs"):
    for batch in tqdm(loader, desc="batch", leave=False):
        ...
```

## configuring credentials

The one thing you need is a bot token and a chat id. Set them once near the top
of your script:

```python
import tgtqdm
tgtqdm.configure(api_token="TOKEN", chat_id=123456789)
```

If you never call `configure()`, credentials are looked up automatically, in
this order:

1. `TGTQDM_API_TOKEN` and `TGTQDM_CHAT_ID` environment variables
2. the JSON file at `$TGTQDM_CONFIG`
3. `telegram_info.json` or `.tgtqdm.json` in the current directory
4. the same two filenames in your home directory

so you can also just drop a file next to your script and change nothing else:

```json
{
    "api_token": "TOKEN",
    "chat_id": 123456789
}
```

If no credentials are found you get a one-time notice and a perfectly normal
local progress bar — your script still runs. Set `TGTQDM_DISABLE=1` to turn
Telegram off entirely (and silence the notice), or pass `telegram=False` to a
single bar.

**How do I get an API token and a chat ID?**

- For your own API token, go to [t.me/botfather](https://t.me/botfather) in telegram and create a new bot
- For your chat id, go to [t.me/userinfobot](https://t.me/userinfobot) in telegram

## logging plain messages

```python
from tgtqdm import TelegramLogger

logger = TelegramLogger(
    api_token="...",
    chat_id=123
)

## when you log for the first time, it will send a message
logger.log(message="Lettuce begin", timestamp=False)

## when you log again, it will update the existing message
logger.log(message="Legume resume", timestamp=False, force=True)
```

Or, keeping your token out of your source:

```python
logger = TelegramLogger.from_json(filename="telegram_info.json")
```

## things worth knowing

Telegram rate-limits edits to roughly one per second per chat, so by default
updates that arrive less than a second after the previous one are dropped. Pass
`min_interval=0` to turn that off, or `log(..., force=True)` to push a single
update through anyway. The final state of a bar is always forced, so the last
thing you see is never a stale one.

Nothing in here will crash your script: if Telegram is unreachable, rate-limits
you, or your credentials are wrong, the error is printed and your loop carries on.

The original `tgtqdm` class is still there and unchanged if you were using it:

```python
from tgtqdm import tgtqdm

for i in tgtqdm(range(33), json_filename="telegram_info.json", desc="running something"):
    ...
```

## development

```bash
pip install -e ".[dev]"
pytest
mypy
```
