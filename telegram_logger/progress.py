from .logger import TelegramLogger
import time

class tgtqdm:
    """
    A tqdm-like progress bar that logs to Telegram.
    Usage:
    ```
    from telegram_logger import tgtqdm
    for item in tgtqdm(iterable, api_token=TOKEN, chat_id=USER_ID, desc="Processing"):
        # do something with item
        # the progress bar will automatically update
    ```
    """
    def __init__(self, iterable, json_filename: str = None, api_token: str=None, chat_id: int=None, desc: str = "", update_every_n_iters: int = 1):
        self.iterable = iterable

        if json_filename is None:
            assert api_token is not None, "api_token must be provided"
            assert chat_id is not None, "chat_id must be provided"
            self.logger =  TelegramLogger(api_token=api_token, chat_id=chat_id)
        else:
            self.logger = TelegramLogger.from_json(filename=json_filename)
        self.total = len(iterable) if hasattr(iterable, '__len__') else None
        self.current = 0
        self.desc = desc
        self.update_every_n_iters = update_every_n_iters

    def __iter__(self):
        start_time = time.time()

        def format_eta(seconds):
            if seconds is None or seconds < 0:
                return "ETA: --"
            if seconds >= 3600:
                hours = int(seconds // 3600)
                mins = int((seconds % 3600) // 60)
                secs = int(seconds % 60)
                return f"ETA: {hours}h {mins}m {secs}s"
            elif seconds >= 60:
                mins = int(seconds // 60)
                secs = int(seconds % 60)
                return f"ETA: {mins}m {secs}s"
            else:
                return f"ETA: {int(seconds)}s"

        for item in self.iterable:
            self.current += 1
            elapsed = time.time() - start_time
            if self.total:
                percent = self.current / self.total
                percent_text = f"{int(percent * 100):3d}%"
                if self.current > 0 and self.current < self.total:
                    eta = (elapsed / self.current) * (self.total - self.current)
                else:
                    eta = None
                eta_text = format_eta(eta)
                progress_line = f"[{self.current}/{self.total}] {percent_text}\n{eta_text}"
                progress_stdout = f"{self.desc}: [{self.current}/{self.total}] {percent_text} {eta_text}" if self.desc else f"[{self.current}/{self.total}] {percent_text} {eta_text}"
            else:
                progress_line = f"[{self.current}]"
                progress_stdout = f"{self.desc}: [{self.current}]" if self.desc else f"[{self.current}]"

            # Only log to Telegram every n iterations
            if self.current % self.update_every_n_iters == 0 or self.current == self.total:
                if self.desc:
                    message = f"{self.desc}: {progress_line}"
                else:
                    message = progress_line
                self.logger.log(message=message, timestamp=True)
            print(progress_stdout, end='\r', flush=True)
            yield item
# No print() at the end; do not move to next line after completion
