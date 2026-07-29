"""
A near drop-in replacement for ``tqdm.std.tqdm`` that mirrors the bar into a
single, continuously edited Telegram message.

    import tgtqdm
    tgtqdm.configure(api_token="...", chat_id=123)

    from tgtqdm import tqdm
    for x in tqdm(range(100)):
        ...
"""

import shutil
import sys
import threading
import time
from numbers import Number
from typing import (
    Any,
    Callable,
    Dict,
    IO,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sized,
    Tuple,
    TypeVar,
    Union,
)

from . import config
from .logger import TelegramLogger

T = TypeVar("T")

ASCII_BAR = " 123456789#"
UNICODE_BAR = " ▏▎▍▌▋▊▉█"

## the bar inside the Telegram message is a fixed number of characters wide,
## since there is no terminal width to measure and the message wraps by itself
TELEGRAM_BAR_WIDTH = 20

## at most this many bar lines are kept in the Telegram message, so that a
## script running hundreds of loops does not grow it without bound
MAX_TELEGRAM_LINES = 15


def format_interval(t: Optional[float]) -> str:
    """``1234`` -> ``'20:34'``, matching tqdm's ``format_interval``."""
    if t is None:
        return "?"
    mins, s = divmod(int(t), 60)
    h, m = divmod(mins, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_sizeof(num: float, suffix: str = "", divisor: float = 1000) -> str:
    """``1234`` -> ``'1.23k'``, matching tqdm's ``format_sizeof``."""
    for unit in ("", "k", "M", "G", "T", "P", "E", "Z"):
        if abs(num) < 999.5:
            if abs(num) < 99.95:
                if abs(num) < 9.995:
                    return f"{num:1.2f}{unit}{suffix}"
                return f"{num:2.1f}{unit}{suffix}"
            return f"{num:3.0f}{unit}{suffix}"
        num /= divisor
    return f"{num:3.1f}Y{suffix}"


def format_num(n: Union[int, float]) -> str:
    """Intelligently format a number, matching tqdm's ``format_num``."""
    formatted = f"{n:.3g}"
    shortest = str(n)
    return shortest if len(shortest) < len(formatted) else formatted


def _bool_env_disabled() -> bool:
    return config._disabled_by_env()


class _Registry:
    """
    Holds every live bar so that they can be rendered into one Telegram message.

    Nested bars therefore show up as multiple lines in the same message, and a
    ``leave=True`` bar stays visible after it finishes, mirroring tqdm.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._bars: List["tqdm[Any]"] = []

    @property
    def lock(self) -> "threading.RLock":
        return self._lock

    def add(self, bar: "tqdm[Any]") -> None:
        with self._lock:
            self._bars.append(bar)
            self._trim()

    def remove(self, bar: "tqdm[Any]") -> None:
        with self._lock:
            if bar in self._bars:
                self._bars.remove(bar)

    def clear(self) -> None:
        with self._lock:
            self._bars.clear()

    def _trim(self) -> None:
        while len(self._bars) > MAX_TELEGRAM_LINES:
            for bar in self._bars:
                ## drop finished bars first, oldest to newest
                if bar.closed:
                    self._bars.remove(bar)
                    break
            else:
                del self._bars[0]

    def render(self) -> str:
        with self._lock:
            return "\n".join(
                bar.format_meter(bar_width=TELEGRAM_BAR_WIDTH) for bar in self._bars
            )

    def publish(self, logger: Optional[TelegramLogger], force: bool = False) -> None:
        if logger is None:
            return
        text = self.render()
        if not text:
            return
        logger.log(message=text, force=force)


_registry = _Registry()


def registry() -> _Registry:
    """The shared bar registry. Exposed mostly for tests."""
    return _registry


class tqdm(Iterable[T]):
    """
    Drop-in replacement for :class:`tqdm.tqdm` that also renders to Telegram.

    Every argument :class:`tqdm.tqdm` accepts is accepted here. The ones that
    only affect terminal cosmetics (``colour``, ``dynamic_ncols``, ``nrows``,
    ``position``, ``lock_args``, ``gui``, ...) are accepted and ignored so that
    existing code keeps working unchanged.

    Extra keyword arguments specific to this library:

    ``telegram``
        Set to ``False`` to keep this bar local only.
    ``api_token`` / ``chat_id`` / ``json_filename`` / ``logger``
        Per-bar credentials, overriding :func:`tgtqdm.configure`.
    """

    ## tqdm exposes these as class attributes; some libraries read them
    monitor_interval = 0
    _lock = _registry.lock

    def __init__(
        self,
        iterable: Optional[Iterable[T]] = None,
        desc: Optional[str] = None,
        total: Optional[float] = None,
        leave: bool = True,
        file: Optional[IO[str]] = None,
        ncols: Optional[int] = None,
        mininterval: float = 0.1,
        maxinterval: float = 10.0,
        miniters: Optional[float] = None,
        ascii: Optional[Union[bool, str]] = None,  ## noqa: A002 - tqdm's name
        disable: Optional[bool] = False,
        unit: str = "it",
        unit_scale: Union[bool, float] = False,
        dynamic_ncols: bool = False,
        smoothing: float = 0.3,
        bar_format: Optional[str] = None,
        initial: float = 0,
        position: Optional[int] = None,
        postfix: Optional[Mapping[str, Any]] = None,
        unit_divisor: float = 1000,
        write_bytes: bool = False,
        lock_args: Optional[Tuple[Any, ...]] = None,
        nrows: Optional[int] = None,
        colour: Optional[str] = None,
        delay: float = 0.0,
        gui: bool = False,
        telegram: bool = True,
        api_token: Optional[str] = None,
        chat_id: Optional[Any] = None,
        json_filename: Optional[str] = None,
        logger: Optional[TelegramLogger] = None,
        **kwargs: Any,
    ) -> None:
        if total is None and isinstance(iterable, Sized):
            try:
                total = len(iterable)
            except (TypeError, AttributeError):
                total = None
        if total is not None and total < 0:
            total = None

        ## tqdm treats disable=None as "disable when not a tty"
        if disable is None:
            stream = file if file is not None else sys.stderr
            disable = not getattr(stream, "isatty", lambda: False)()

        self.iterable = iterable
        self.desc = desc or ""
        self.total = total
        self.leave = leave
        self.fp = file
        self.ncols = ncols
        self.mininterval = max(0.0, mininterval)
        self.maxinterval = maxinterval
        self.miniters = miniters
        self.ascii = ascii
        self.disable = bool(disable)
        self.unit = unit
        self.unit_scale = unit_scale
        self.unit_divisor = unit_divisor
        self.smoothing = smoothing
        self.bar_format = bar_format
        self.initial = initial
        self.position = position
        self.dynamic_ncols = dynamic_ncols
        self.colour = colour
        self.delay = delay
        self.gui = gui

        self.n: float = initial
        self.last_print_n: float = initial
        self.start_t = self.last_print_t = time.monotonic()
        self._ema_rate: Optional[float] = None
        self.closed = False
        self._telegram = telegram and not _bool_env_disabled()
        self._explicit_logger: Optional[TelegramLogger] = None
        self._wrote_to_stream = False
        self.postfix: Optional[str] = None
        if postfix:
            self.set_postfix(postfix, refresh=False)

        if self._telegram:
            self._explicit_logger = self._resolve_logger(
                logger, api_token, chat_id, json_filename
            )

        if not self.disable:
            _registry.add(self)
            if self.delay <= 0:
                self.refresh()

    ## ------------------------------------------------------------------ setup

    def _resolve_logger(
        self,
        logger: Optional[TelegramLogger],
        api_token: Optional[str],
        chat_id: Optional[Any],
        json_filename: Optional[str],
    ) -> Optional[TelegramLogger]:
        if logger is not None:
            return logger
        if api_token is not None and chat_id is not None:
            return TelegramLogger(api_token=api_token, chat_id=chat_id)
        if json_filename is not None:
            return TelegramLogger.from_json(json_filename)
        return None

    @property
    def logger(self) -> Optional[TelegramLogger]:
        """The logger this bar publishes to, or ``None`` if it is local only."""
        if not self._telegram or self.disable:
            return None
        if self._explicit_logger is not None:
            return self._explicit_logger
        return config.get_logger()

    @property
    def _stream(self) -> IO[str]:
        ## resolved lazily so a patched sys.stderr is respected
        return self.fp if self.fp is not None else sys.stderr

    ## --------------------------------------------------------------- geometry

    def _terminal_ncols(self) -> int:
        if self.ncols is not None:
            return max(0, self.ncols)
        try:
            columns = shutil.get_terminal_size().columns
        except Exception:  ## noqa: BLE001
            columns = 80
        ## leave a column free so the line does not wrap
        return max(10, columns - 1)

    ## ------------------------------------------------------------- formatting

    @property
    def format_dict(self) -> Dict[str, Any]:
        """The values available to ``bar_format``, as in tqdm."""
        elapsed = time.monotonic() - self.start_t
        n = self.n - self.initial
        rate = self._ema_rate if self._ema_rate else (n / elapsed if elapsed else None)
        return {
            "n": self.n,
            "total": self.total,
            "elapsed": elapsed,
            "ncols": self.ncols,
            "nrows": None,
            "prefix": self.desc,
            "ascii": self.ascii,
            "unit": self.unit,
            "unit_scale": self.unit_scale,
            "rate": rate,
            "bar_format": self.bar_format,
            "postfix": self.postfix,
            "unit_divisor": self.unit_divisor,
            "initial": self.initial,
            "colour": self.colour,
        }

    def _format_count(self, value: float) -> str:
        scale = self.unit_scale
        if scale:
            divisor = self.unit_divisor
            if isinstance(scale, Number) and not isinstance(scale, bool):
                return format_sizeof(value * float(scale), divisor=divisor)
            return format_sizeof(value, divisor=divisor)
        return str(int(value)) if float(value).is_integer() else format_num(value)

    def _format_rate(self, rate: Optional[float]) -> str:
        """Rates are formatted exactly as tqdm does, inverting when below 1/s."""
        if not rate:
            return f"?{self.unit}/s"
        inverted = rate < 1
        value = 1 / rate if inverted else rate
        unit = f"s/{self.unit}" if inverted else f"{self.unit}/s"
        if self.unit_scale:
            return format_sizeof(value, divisor=self.unit_divisor) + unit
        return f"{value:5.2f}{unit}"

    def format_meter(
        self, ncols: Optional[int] = None, bar_width: Optional[int] = None
    ) -> str:
        """
        Render this bar as a single line of text.

        ``ncols`` caps the width of the whole line, as tqdm does in a terminal.
        ``bar_width`` instead pins the bar itself to an exact width and lets the
        line be as long as it needs to be, which is what the Telegram message
        wants.
        """
        d = self.format_dict
        elapsed: float = d["elapsed"]
        rate: Optional[float] = d["rate"]

        n_fmt = self._format_count(self.n)
        total_fmt = self._format_count(self.total) if self.total is not None else "?"
        rate_fmt = self._format_rate(rate)
        elapsed_str = format_interval(elapsed)
        postfix = f", {self.postfix}" if self.postfix else ""
        prefix = f"{self.desc}: " if self.desc else ""

        if self.total:
            fraction = min(1.0, max(0.0, self.n / self.total))
            percentage = fraction * 100
            remaining = (self.total - self.n) / rate if rate else None
            remaining_str = format_interval(remaining)
            l_bar = f"{prefix}{percentage:3.0f}%|"
            r_bar = (
                f"| {n_fmt}/{total_fmt} "
                f"[{elapsed_str}<{remaining_str}, {rate_fmt}{postfix}]"
            )
        else:
            fraction = 0.0
            percentage = 0.0
            remaining = None
            remaining_str = "?"
            l_bar = prefix
            r_bar = f"{n_fmt}{self.unit} [{elapsed_str}, {rate_fmt}{postfix}]"

        if self.bar_format is not None:
            return self._apply_bar_format(
                l_bar=l_bar,
                r_bar=r_bar,
                n_fmt=n_fmt,
                total_fmt=total_fmt,
                elapsed_str=elapsed_str,
                remaining_str=remaining_str,
                rate_fmt=rate_fmt,
                percentage=percentage,
                fraction=fraction,
                ncols=ncols,
                bar_width=bar_width,
            )

        ## a zero total is rendered like an unknown one, as tqdm does
        if not self.total:
            return l_bar + r_bar

        if bar_width is None:
            width = ncols if ncols is not None else self._terminal_ncols()
            bar_width = width - len(l_bar) - len(r_bar)
        if bar_width < 1:
            ## no room for the bar itself, fall back to the numbers alone
            return (
                f"{prefix}{percentage:3.0f}% {n_fmt}/{total_fmt} "
                f"[{elapsed_str}<{remaining_str}, {rate_fmt}{postfix}]"
            )
        return l_bar + self._draw_bar(fraction, bar_width) + r_bar

    def _apply_bar_format(
        self,
        l_bar: str,
        r_bar: str,
        n_fmt: str,
        total_fmt: str,
        elapsed_str: str,
        remaining_str: str,
        rate_fmt: str,
        percentage: float,
        fraction: float,
        ncols: Optional[int],
        bar_width: Optional[int] = None,
    ) -> str:
        assert self.bar_format is not None
        d = self.format_dict
        values: Dict[str, Any] = {
            "n": self.n,
            "n_fmt": n_fmt,
            "total": self.total,
            "total_fmt": total_fmt,
            "percentage": percentage,
            "elapsed": elapsed_str,
            "elapsed_s": d["elapsed"],
            "remaining": remaining_str,
            "remaining_s": (self.total - self.n) / d["rate"]
            if self.total and d["rate"]
            else 0,
            "rate": d["rate"] or 0,
            "rate_fmt": rate_fmt,
            "rate_noinv": d["rate"] or 0,
            "rate_noinv_fmt": rate_fmt,
            "rate_inv": 1 / d["rate"] if d["rate"] else 0,
            "rate_inv_fmt": rate_fmt,
            "unit": self.unit,
            "unit_divisor": self.unit_divisor,
            "postfix": self.postfix or "",
            "desc": self.desc,
            "l_bar": l_bar,
            "r_bar": r_bar,
            "bar": "",
            "colour": self.colour or "",
            "eta": remaining_str,
        }
        try:
            rendered = self.bar_format.format(**values)
        except (KeyError, IndexError, ValueError):
            ## an exotic bar_format is not worth crashing the loop over
            return l_bar + r_bar
        if "{bar}" not in self.bar_format:
            return rendered
        if bar_width is None:
            width = ncols if ncols is not None else self._terminal_ncols()
            bar_width = max(1, width - len(rendered))
        values["bar"] = self._draw_bar(fraction, bar_width)
        try:
            return self.bar_format.format(**values)
        except (KeyError, IndexError, ValueError):
            return l_bar + r_bar

    def _draw_bar(self, fraction: float, width: int) -> str:
        charset = self.ascii if isinstance(self.ascii, str) else None
        if charset is None:
            charset = ASCII_BAR if self.ascii else UNICODE_BAR
        n_states = len(charset) - 1
        exact = fraction * width * n_states
        filled, partial = divmod(int(exact), n_states)
        bar = charset[-1] * filled
        if filled < width:
            bar += charset[partial]
            bar += charset[0] * (width - filled - 1)
        return bar[:width]

    ## ------------------------------------------------------------- displaying

    def _should_refresh(self) -> bool:
        if self.miniters is not None and (self.n - self.last_print_n) < self.miniters:
            return False
        return (time.monotonic() - self.last_print_t) >= self.mininterval

    def _delayed(self) -> bool:
        return self.delay > 0 and (time.monotonic() - self.start_t) < self.delay

    def display(self, force: bool = False) -> None:
        """Write the bar to the local stream and publish the Telegram message."""
        if self.disable or self._delayed():
            return
        self._write(self.format_meter())
        _registry.publish(self.logger, force=force)

    def refresh(
        self,
        nolock: bool = False,
        lock_args: Optional[Tuple[Any, ...]] = None,
        force: bool = False,
    ) -> None:
        """Force a redraw, as in tqdm."""
        self.display(force=force)
        self.last_print_t = time.monotonic()
        self.last_print_n = self.n

    def _write(self, line: str) -> None:
        stream = self._stream
        try:
            stream.write(f"\r{line}")
            stream.flush()
            self._wrote_to_stream = True
        except (ValueError, OSError):
            ## a closed or detached stream must not kill the loop
            pass

    def clear(self, nolock: bool = False) -> None:
        """Erase the bar from the local stream."""
        if self.disable:
            return
        try:
            self._stream.write("\r" + " " * self._terminal_ncols() + "\r")
            self._stream.flush()
        except (ValueError, OSError):
            pass

    @classmethod
    def write(
        cls, s: str, file: Optional[IO[str]] = None, end: str = "\n", nolock: bool = False
    ) -> None:
        """Print a message without breaking the bar, as in tqdm."""
        stream = file if file is not None else sys.stderr
        try:
            stream.write("\r")
            stream.write(s)
            stream.write(end)
            stream.flush()
        except (ValueError, OSError):
            pass

    ## ---------------------------------------------------------------- updating

    def update(self, n: Optional[float] = 1) -> Optional[bool]:
        """Advance the bar by ``n``. Returns ``True`` if it was redrawn."""
        if self.disable:
            return None
        if n is None:
            n = 1
        previous_t = self.last_print_t
        self.n += n
        if self._should_refresh():
            self._update_rate(previous_t)
            self.refresh()
            return True
        return False

    def _update_rate(self, previous_t: float) -> None:
        now = time.monotonic()
        delta_t = now - previous_t
        delta_n = self.n - self.last_print_n
        if delta_t <= 0 or delta_n <= 0:
            return
        instant = delta_n / delta_t
        if self.smoothing and self._ema_rate is not None:
            self._ema_rate += self.smoothing * (instant - self._ema_rate)
        else:
            self._ema_rate = instant

    def reset(self, total: Optional[float] = None) -> None:
        """Restart the counter, as in tqdm."""
        self.n = 0
        self.last_print_n = 0
        self.start_t = self.last_print_t = time.monotonic()
        self._ema_rate = None
        if total is not None:
            self.total = total

    def unpause(self) -> None:
        """Discard the time spent since the last update, as in tqdm."""
        now = time.monotonic()
        self.start_t += now - self.last_print_t
        self.last_print_t = now

    def set_description(self, desc: Optional[str] = None, refresh: bool = True) -> None:
        self.desc = f"{desc}" if desc else ""
        if refresh:
            self.refresh()

    def set_description_str(
        self, desc: Optional[str] = None, refresh: bool = True
    ) -> None:
        self.desc = desc or ""
        if refresh:
            self.refresh()

    def set_postfix(
        self,
        ordered_dict: Optional[Mapping[str, Any]] = None,
        refresh: bool = True,
        **kwargs: Any,
    ) -> None:
        parts: List[str] = []
        items: Dict[str, Any] = {}
        if ordered_dict is not None:
            items.update(ordered_dict)
        items.update(kwargs)
        for key, value in items.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                text = format_num(value)
            elif isinstance(value, str):
                text = value
            else:
                text = str(value)
            parts.append(f"{key}={text}")
        self.postfix = ", ".join(parts)
        if refresh:
            self.refresh()

    def set_postfix_str(self, s: str = "", refresh: bool = True) -> None:
        self.postfix = str(s)
        if refresh:
            self.refresh()

    ## ---------------------------------------------------------------- lifecycle

    def close(self) -> None:
        """Finish the bar. Idempotent, as in tqdm."""
        if self.closed:
            return
        self.closed = True
        if self.disable:
            _registry.remove(self)
            return

        if not self.leave:
            _registry.remove(self)
            self.clear()
        else:
            self._write(self.format_meter())
            if self._wrote_to_stream:
                try:
                    self._stream.write("\n")
                    self._stream.flush()
                except (ValueError, OSError):
                    pass
        ## the final state must never be lost to throttling
        _registry.publish(self.logger, force=True)

    def __enter__(self) -> "tqdm[T]":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  ## noqa: BLE001 - never raise from a finaliser
            pass

    ## ---------------------------------------------------------------- iterating

    def __iter__(self) -> Iterator[T]:
        if self.iterable is None:
            raise TypeError("this tqdm has no iterable to iterate over")
        if self.disable:
            yield from self.iterable
            return

        ## re-iterating starts from scratch, like a fresh bar
        self.reset(total=self.total)
        try:
            for item in self.iterable:
                yield item
                self.update(1)
        finally:
            self.close()

    def __len__(self) -> int:
        if self.total is not None:
            return int(self.total)
        if isinstance(self.iterable, Sized):
            return len(self.iterable)
        raise TypeError("this tqdm wraps an iterable of unknown length")

    def __repr__(self) -> str:
        return self.format_meter(bar_width=TELEGRAM_BAR_WIDTH)

    def __bool__(self) -> bool:
        if self.total is not None:
            return self.total > 0
        if self.iterable is None:
            return False
        return bool(self.iterable)

    ## ---------------------------------------------------------------- extras

    @classmethod
    def pandas(cls, **tqdm_kwargs: Any) -> None:
        """
        Register ``progress_apply`` on pandas objects, as ``tqdm.pandas()`` does.
        """
        from pandas.core.frame import DataFrame
        from pandas.core.series import Series

        try:
            from pandas.core.groupby.generic import DataFrameGroupBy, SeriesGroupBy

            groupby_classes: Tuple[type, ...] = (DataFrameGroupBy, SeriesGroupBy)
        except ImportError:  ## pragma: no cover - very old pandas
            groupby_classes = ()

        def inner_generator(method: str = "apply") -> Callable[..., Any]:
            def inner(df: Any, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
                total = tqdm_kwargs.pop("total", getattr(df, "size", None))
                if isinstance(df, DataFrame):
                    axis = kwargs.get("axis", 0)
                    axis = 0 if axis in (0, "index") else 1
                    total = df.shape[1 - axis] if method == "apply" else df.size
                bar = cls(total=total, **tqdm_kwargs)

                def wrapper(*a: Any, **kw: Any) -> Any:
                    bar.update(1)
                    return func(*a, **kw)

                try:
                    return getattr(df, method)(wrapper, *args, **kwargs)
                finally:
                    bar.close()

            return inner

        Series.progress_apply = inner_generator("apply")  ## type: ignore[attr-defined]
        Series.progress_map = inner_generator("map")  ## type: ignore[attr-defined]
        DataFrame.progress_apply = inner_generator("apply")  ## type: ignore[attr-defined]
        DataFrame.progress_applymap = inner_generator(  ## type: ignore[attr-defined]
            "applymap"
        )
        for klass in groupby_classes:
            setattr(klass, "progress_apply", inner_generator("apply"))

    @staticmethod
    def get_lock() -> "threading.RLock":
        return _registry.lock

    @staticmethod
    def set_lock(lock: Any) -> None:
        """Accepted for tqdm compatibility; this implementation has its own lock."""


def trange(*args: int, **kwargs: Any) -> tqdm[int]:
    """``trange(n)`` is shorthand for ``tqdm(range(n))``, as in tqdm."""
    return tqdm(range(*args), **kwargs)
