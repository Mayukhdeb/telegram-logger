"""
Examples for tgtqdm.

The json file referenced below looks like this:
{
    "api_token": "your_api_token_here",
    "chat_id": 000000000
}
"""

import time

import tgtqdm

"""
Example 1: the drop-in replacement for tqdm.

Configure once, then use `tqdm` exactly as you always have. If a
telegram_info.json sits next to the script you can skip configure() entirely.
"""
tgtqdm.configure(json_filename="telegram_info.json")

from tgtqdm import tqdm, trange  ## noqa: E402 - after configure(), for clarity

for i in tqdm(range(33), desc="running something"):
    time.sleep(0.1)

## manual mode, postfixes and nesting all work
with tqdm(total=100, desc="manual") as pbar:
    for step in range(10):
        time.sleep(0.05)
        pbar.set_postfix(loss=1 / (step + 1))
        pbar.update(10)

for epoch in trange(2, desc="epochs"):
    for batch in tqdm(range(20), desc="batch", leave=False):
        time.sleep(0.02)


"""
Example 2: the original tgtqdm bar, with per-call credentials
"""
for i in tgtqdm.tgtqdm(
    range(10),
    api_token="TOKEN",
    chat_id=123456789,
    desc="running something else",  ## description to show in the telegram message
    update_every_n_iters=2,  ## control how often to update the telegram message
):
    time.sleep(0.1)


"""
Example 3: manual logger usage
"""
logger = tgtqdm.TelegramLogger.from_json(filename="telegram_info.json")

## when you log for the first time, it will send a message
logger.log(message="Lettuce begin", timestamp=False)

## when you log again, it will update the existing message
logger.log(message="Legume resume", timestamp=False, force=True)
