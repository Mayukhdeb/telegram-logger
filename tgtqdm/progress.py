import sys
import time
from typing import IO, Iterable, Iterator, Optional, Sized, Tuple, TypeVar

from .logger import ChatId, TelegramLogger

T = TypeVar("T")


def format_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "ETA: --"
    if seconds >= 3600:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"ETA: {hours}h {mins}m {secs}s"
    if seconds >= 60:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"ETA: {mins}m {secs}s"
    return f"ETA: {int(seconds)}s"


class tgtqdm(Iterable[T]):
    """
    A tqdm-like progress bar that logs to Telegram.
    Usage:
    ```
    from tgtqdm import tgtqdm
    for item in tgtqdm(iterable, api_token=TOKEN, chat_id=USER_ID, desc="Processing"):
        # do something with item
        # the progress bar will automatically update
    ```
    """

    def __init__(
        self,
        iterable: Iterable[T],
        json_filename: Optional[str] = None,
        api_token: Optional[str] = None,
        chat_id: Optional[ChatId] = None,
        desc: str = "",
        update_every_n_iters: int = 1,
        total: Optional[int] = None,
        logger: Optional[TelegramLogger] = None,
        file: Optional[IO[str]] = None,
    ) -> None:
        if update_every_n_iters < 1:
            raise ValueError(
                f"update_every_n_iters must be >= 1 and not: {update_every_n_iters}"
            )

        self.iterable = iterable

        if logger is not None:
            self.logger = logger
        elif json_filename is not None:
            self.logger = TelegramLogger.from_json(filename=json_filename)
        else:
            if api_token is None:
                raise ValueError("api_token must be provided when json_filename is None")
            if chat_id is None:
                raise ValueError("chat_id must be provided when json_filename is None")
            self.logger = TelegramLogger(api_token=api_token, chat_id=chat_id)

        if total is None:
            total = len(iterable) if isinstance(iterable, Sized) else None
        self.total = total
        self.current = 0
        self.desc = desc
        self.update_every_n_iters = update_every_n_iters
        self.file = file

    def __len__(self) -> int:
        if self.total is None:
            raise TypeError("this tgtqdm wraps an iterable of unknown length")
        return self.total

    @property
    def _stream(self) -> IO[str]:
        ## resolved lazily so that a patched sys.stdout is respected
        return self.file if self.file is not None else sys.stdout

    def _lines(self, elapsed: float) -> Tuple[str, str]:
        """Return ``(telegram_message, stdout_line)`` for the current state."""
        if self.total:
            percent_text = f"{int(self.current / self.total * 100):3d}%"
            if 0 < self.current < self.total:
                eta: Optional[float] = (elapsed / self.current) * (
                    self.total - self.current
                )
            else:
                eta = None
            eta_text = format_eta(eta)
            counter = f"[{self.current}/{self.total}] {percent_text}"
            message = f"{counter}\n{eta_text}"
            stdout_line = f"{counter} {eta_text}"
        else:
            message = f"[{self.current}]"
            stdout_line = message

        if self.desc:
            message = f"{self.desc}: {message}"
            stdout_line = f"{self.desc}: {stdout_line}"
        return message, stdout_line

    def _write(self, line: str) -> None:
        stream = self._stream
        try:
            stream.write(f"{line}\r")
            stream.flush()
        except (ValueError, OSError):
            ## a closed or detached stream should not kill the loop
            pass

    def __iter__(self) -> Iterator[T]:
        start_time = time.monotonic()
        self.current = 0
        wrote_anything = False
        final_message: Optional[str] = None

        try:
            for item in self.iterable:
                self.current += 1
                message, stdout_line = self._lines(time.monotonic() - start_time)

                is_last = self.current == self.total
                ## only log to telegram every n iterations, but never skip the end
                if self.current % self.update_every_n_iters == 0 or is_last:
                    self.logger.log(message=message, timestamp=True, force=is_last)
                    final_message = None
                else:
                    ## remember it so the final state is not lost to throttling
                    final_message = message
                self._write(stdout_line)
                wrote_anything = True
                yield item

            if final_message is not None:
                self.logger.log(message=final_message, timestamp=True, force=True)
        finally:
            if wrote_anything:
                try:
                    self._stream.write("\n")
                    self._stream.flush()
                except (ValueError, OSError):
                    pass

    def __repr__(self) -> str:
        total = self.total if self.total is not None else "?"
        return f"tgtqdm(desc={self.desc!r}, current={self.current}, total={total})"
