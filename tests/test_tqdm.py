import io
from typing import Any, List

import pytest

import tgtqdm
from tgtqdm import TelegramLogger, tqdm, trange
from tgtqdm.std import (
    format_interval,
    format_num,
    format_sizeof,
    registry,
)


class RecordingLogger:
    """Stands in for TelegramLogger and records what would be sent."""

    def __init__(self) -> None:
        self.messages: List[str] = []
        self.forced: List[bool] = []

    def log(self, message: str, timestamp: bool = False, force: bool = False) -> None:
        self.messages.append(message)
        self.forced.append(force)

    @property
    def last(self) -> str:
        return self.messages[-1]


@pytest.fixture
def spy() -> RecordingLogger:
    return RecordingLogger()


@pytest.fixture
def bar(spy):
    """A factory for bars that are local-only except for the recording logger."""

    def factory(*args: Any, **kwargs: Any) -> tqdm:
        kwargs.setdefault("logger", spy)
        kwargs.setdefault("file", io.StringIO())
        kwargs.setdefault("mininterval", 0)
        kwargs.setdefault("ncols", 60)
        return tqdm(*args, **kwargs)

    return factory


class TestFormattingHelpers:
    @pytest.mark.parametrize(
        "seconds,expected",
        [(None, "?"), (0, "00:00"), (9, "00:09"), (75, "01:15"), (3725, "1:02:05")],
    )
    def test_format_interval(self, seconds, expected):
        assert format_interval(seconds) == expected

    @pytest.mark.parametrize(
        "value,expected", [(1, "1.00"), (12.3, "12.3"), (1234, "1.23k"), (1234567, "1.23M")]
    )
    def test_format_sizeof(self, value, expected):
        assert format_sizeof(value) == expected

    def test_format_num(self):
        assert format_num(1) == "1"
        assert format_num(0.123456) == "0.123"


class TestBarRendering:
    def test_looks_like_tqdm(self, bar):
        b = bar(range(100))
        b.n = 50
        line = b.format_meter(ncols=60)
        assert line.startswith(" 50%|")
        assert "| 50/100 [" in line
        assert "it/s" in line
        assert len(line) == 60

    def test_desc_is_a_prefix(self, bar):
        assert bar(range(10), desc="train").format_meter(ncols=60).startswith("train:   0%")

    def test_unknown_total_omits_the_bar(self, bar):
        line = bar(iter([1, 2, 3])).format_meter(ncols=60)
        assert "|" not in line
        assert line.startswith("0it [")

    def test_ascii_bar(self, bar):
        b = bar(range(10), ascii=True)
        b.n = 5
        assert "#" in b.format_meter(ncols=60)
        assert "█" not in b.format_meter(ncols=60)

    def test_custom_ascii_charset(self, bar):
        b = bar(range(10), ascii=" .oO")
        b.n = 5
        assert "O" in b.format_meter(ncols=60)

    def test_bar_is_full_at_completion(self, bar):
        b = bar(range(10))
        b.n = 10
        line = b.format_meter(ncols=60)
        assert line.startswith("100%|")
        assert " " not in line.split("|")[1]

    def test_narrow_width_degrades_gracefully(self, bar):
        b = bar(range(1000), desc="a long description here")
        b.n = 500
        line = b.format_meter(ncols=10)
        assert "500/1000" in line

    def test_postfix_is_appended(self, bar):
        b = bar(range(10))
        b.set_postfix(loss=0.5, stage="warmup", refresh=False)
        assert "loss=0.5, stage=warmup" in b.format_meter(ncols=80)

    def test_unit_and_unit_scale(self, bar):
        b = bar(range(2000), unit="B", unit_scale=True)
        b.n = 1500
        line = b.format_meter(ncols=80)
        assert "1.50k/2.00k" in line
        assert "B/s" in line

    def test_overshooting_total_clamps_the_bar(self, bar):
        b = bar(range(10))
        b.n = 20
        assert b.format_meter(ncols=60).startswith("100%|")


class TestBarFormat:
    def test_custom_format(self, bar):
        b = bar(range(10), bar_format="{n_fmt}/{total_fmt} {desc}", desc="x")
        b.n = 3
        assert b.format_meter(ncols=60) == "3/10 x"

    def test_bar_placeholder_is_filled_to_width(self, bar):
        b = bar(range(10), bar_format="|{bar}|")
        b.n = 5
        line = b.format_meter(ncols=20)
        assert len(line) == 20
        assert line.startswith("|") and line.endswith("|")

    def test_unknown_placeholder_falls_back(self, bar):
        b = bar(range(10), bar_format="{nonsense}")
        ## a bad format string must not crash the loop
        assert "0/10" in b.format_meter(ncols=60)


class TestIteration:
    def test_yields_items_unchanged(self, bar):
        assert list(bar([1, 2, 3])) == [1, 2, 3]

    def test_counts_to_total(self, spy, bar):
        b = bar(range(5))
        list(b)
        assert b.n == 5
        assert "5/5" in spy.last

    def test_final_message_is_forced(self, spy, bar):
        list(bar(range(3)))
        assert spy.forced[-1] is True

    def test_re_iteration_restarts(self, spy, bar):
        b = bar([1, 2])
        list(b)
        list(b)
        assert b.n == 2

    def test_generator_without_total(self, spy, bar):
        assert list(bar(i for i in range(4))) == [0, 1, 2, 3]
        assert "4it" in spy.last

    def test_empty_iterable(self, spy, bar):
        ## tqdm renders a zero total as an unknown one
        assert list(bar([])) == []
        assert spy.last.startswith("0it [")

    def test_stdout_line_is_terminated(self, spy):
        out = io.StringIO()
        list(tqdm(range(3), logger=spy, file=out, mininterval=0))
        assert out.getvalue().endswith("\n")

    def test_break_still_closes_the_bar(self, spy):
        out = io.StringIO()
        b = tqdm(range(100), logger=spy, file=out, mininterval=0)
        for _ in b:
            break
        assert b.closed is True
        assert out.getvalue().endswith("\n")

    def test_exception_propagates_and_closes(self, spy, bar):
        b = bar(range(10))
        with pytest.raises(RuntimeError):
            for _ in b:
                raise RuntimeError("boom")
        assert b.closed is True

    def test_iterating_without_an_iterable_raises(self, bar):
        with pytest.raises(TypeError):
            list(bar(total=10))

    def test_mininterval_limits_updates(self, spy, bar):
        list(bar(range(50), mininterval=1000))
        ## only the initial draw and the forced final one
        assert len(spy.messages) == 2

    def test_miniters_limits_updates(self, spy, bar):
        list(bar(range(10), miniters=5))
        assert [m.split("|")[0].strip() for m in spy.messages] == [
            "0%",
            "50%",
            "100%",
            "100%",
        ]

    def test_telegram_line_always_keeps_its_bar(self, spy, bar):
        ## a long rate or description must not squeeze the bar out of the message
        list(bar(range(10), desc="a fairly long description for a bar"))
        assert "|" in spy.last


class TestManualMode:
    def test_update_advances(self, spy, bar):
        b = bar(total=10)
        b.update(3)
        assert b.n == 3
        assert "3/10" in spy.last

    def test_update_defaults_to_one(self, bar):
        b = bar(total=10)
        b.update()
        assert b.n == 1

    def test_update_none_is_treated_as_one(self, bar):
        b = bar(total=10)
        b.update(None)
        assert b.n == 1

    def test_context_manager_closes(self, spy, bar):
        with bar(total=10) as b:
            b.update(10)
        assert b.closed is True
        assert spy.forced[-1] is True

    def test_close_is_idempotent(self, spy, bar):
        b = bar(total=1)
        b.close()
        before = len(spy.messages)
        b.close()
        assert len(spy.messages) == before

    def test_reset(self, bar):
        b = bar(total=10)
        b.update(5)
        b.reset()
        assert b.n == 0

    def test_reset_with_new_total(self, bar):
        b = bar(total=10)
        b.reset(total=20)
        assert b.total == 20

    def test_unpause_does_not_lose_progress(self, bar):
        b = bar(total=10)
        b.update(5)
        b.unpause()
        assert b.n == 5

    def test_set_description(self, spy, bar):
        b = bar(total=10)
        b.set_description("epoch 1")
        assert spy.last.startswith("epoch 1: ")

    def test_set_description_none_clears_it(self, bar):
        b = bar(total=10, desc="x")
        b.set_description(None)
        assert b.desc == ""

    def test_set_postfix_str(self, spy, bar):
        b = bar(total=10)
        b.set_postfix_str("lr=1e-3")
        assert "lr=1e-3" in spy.last

    def test_initial_offset(self, spy, bar):
        b = bar(total=10, initial=4)
        assert b.n == 4
        assert "4/10" in spy.messages[0]

    def test_format_dict_keys(self, bar):
        d = bar(total=10).format_dict
        for key in ("n", "total", "elapsed", "rate", "unit", "prefix"):
            assert key in d


class TestDisabled:
    def test_disable_skips_telegram_and_stdout(self, spy):
        out = io.StringIO()
        assert list(tqdm(range(3), logger=spy, file=out, disable=True)) == [0, 1, 2]
        assert spy.messages == []
        assert out.getvalue() == ""

    def test_disable_none_uses_isatty(self, spy):
        out = io.StringIO()  ## not a tty
        b = tqdm(range(3), logger=spy, file=out, disable=None)
        assert b.disable is True

    def test_telegram_false_keeps_the_bar_local(self):
        out = io.StringIO()
        tgtqdm.configure(api_token="T", chat_id=1)
        b = tqdm(range(3), file=out, telegram=False, mininterval=0)
        assert b.logger is None
        list(b)
        assert "3/3" in out.getvalue()

    def test_env_disable_keeps_the_bar_local(self, monkeypatch):
        from tgtqdm import config

        monkeypatch.setenv(config.ENV_DISABLE, "1")
        b = tqdm(range(3), file=io.StringIO(), mininterval=0)
        assert b.logger is None

    def test_update_on_a_disabled_bar_is_a_noop(self, spy):
        b = tqdm(total=10, logger=spy, disable=True)
        assert b.update(5) is None
        assert spy.messages == []


class TestCredentialSources:
    def test_uses_the_configured_logger(self, spy):
        tgtqdm.configure(logger=spy)
        b = tqdm(range(2), file=io.StringIO(), mininterval=0)
        list(b)
        assert spy.messages

    def test_per_bar_credentials_win(self, spy):
        tgtqdm.configure(logger=spy)
        b = tqdm(range(2), file=io.StringIO(), api_token="OWN", chat_id=9)
        assert isinstance(b.logger, TelegramLogger)
        assert b.logger.chat_id == 9

    def test_per_bar_json(self, tmp_path, spy):
        import json

        path = tmp_path / "c.json"
        path.write_text(json.dumps({"api_token": "T", "chat_id": 77}))
        b = tqdm(range(2), file=io.StringIO(), json_filename=str(path))
        assert b.logger.chat_id == 77

    def test_unconfigured_bar_still_works(self, capsys):
        out = io.StringIO()
        assert list(tqdm(range(3), file=out, mininterval=0)) == [0, 1, 2]
        assert "3/3" in out.getvalue()
        assert "no Telegram credentials found" in capsys.readouterr().out

    def test_end_to_end_against_a_faked_api(self, poster):
        tgtqdm.configure(api_token="T", chat_id=123, min_interval=0)
        list(tqdm(range(3), file=io.StringIO(), mininterval=0))
        assert poster.methods[0] == "sendMessage"
        assert set(poster.methods[1:]) == {"editMessageText"}
        assert "3/3" in poster.texts[-1]


class TestNesting:
    def test_nested_bars_share_one_message(self, spy):
        out = io.StringIO()
        outer = tqdm(range(2), desc="outer", logger=spy, file=out, mininterval=0)
        for _ in outer:
            inner = tqdm(range(2), desc="inner", logger=spy, file=out, mininterval=0)
            list(inner)
        assert "outer:" in spy.last and "inner:" in spy.last

    def test_leave_false_removes_the_line(self, spy):
        out = io.StringIO()
        outer = tqdm(range(1), desc="outer", logger=spy, file=out, mininterval=0)
        for _ in outer:
            list(
                tqdm(
                    range(2),
                    desc="inner",
                    leave=False,
                    logger=spy,
                    file=out,
                    mininterval=0,
                )
            )
        assert "inner:" not in spy.last

    def test_registry_is_bounded(self, spy):
        from tgtqdm.std import MAX_TELEGRAM_LINES

        for _ in range(MAX_TELEGRAM_LINES + 10):
            list(tqdm(range(1), logger=spy, file=io.StringIO(), mininterval=0))
        assert len(spy.last.split("\n")) <= MAX_TELEGRAM_LINES


class TestMisc:
    def test_trange(self, spy):
        b = trange(4, logger=spy, file=io.StringIO(), mininterval=0)
        assert list(b) == [0, 1, 2, 3]

    def test_trange_with_start_and_step(self, spy):
        b = trange(1, 7, 2, logger=spy, file=io.StringIO())
        assert list(b) == [1, 3, 5]

    def test_len(self, bar):
        assert len(bar(range(7))) == 7

    def test_len_of_unknown_length_raises(self, bar):
        with pytest.raises(TypeError):
            len(bar(i for i in range(3)))

    def test_bool(self, bar):
        assert bool(bar(range(3))) is True
        assert bool(bar(range(0))) is False

    def test_repr_is_the_bar(self, bar):
        assert "0/10" in repr(bar(range(10)))

    def test_write_does_not_raise(self):
        out = io.StringIO()
        tqdm.write("hello", file=out)
        assert out.getvalue() == "\rhello\n"

    def test_clear_erases_the_line(self, spy):
        out = io.StringIO()
        b = tqdm(total=10, logger=spy, file=out, ncols=20)
        b.clear()
        assert out.getvalue().endswith("\r" + " " * 20 + "\r")

    def test_closed_stream_does_not_break_the_loop(self, spy):
        out = io.StringIO()
        out.close()
        assert list(tqdm(range(3), logger=spy, file=out, mininterval=0)) == [0, 1, 2]

    def test_unexpected_kwargs_are_ignored(self, spy):
        ## tqdm swallows unknown kwargs; code written for it must keep working
        b = tqdm(
            range(3),
            logger=spy,
            file=io.StringIO(),
            something_new=True,
            position=2,
            colour="green",
            dynamic_ncols=True,
            nrows=5,
            lock_args=(),
            write_bytes=False,
            gui=False,
            maxinterval=5,
            smoothing=0.1,
        )
        assert list(b) == [0, 1, 2]

    def test_delay_suppresses_early_output(self, spy):
        out = io.StringIO()
        b = tqdm(range(3), logger=spy, file=out, mininterval=0, delay=1000)
        b.update(1)
        assert out.getvalue() == ""
        assert spy.messages == []

    def test_get_lock_and_set_lock_exist(self):
        tqdm.set_lock(object())
        assert tqdm.get_lock() is registry().lock

    def test_negative_total_is_treated_as_unknown(self, bar):
        assert bar(total=-1).total is None

    def test_rate_is_reported(self, bar, monkeypatch):
        from tgtqdm import std

        clock = [0.0]
        monkeypatch.setattr(std.time, "monotonic", lambda: clock[0])
        b = bar(total=10)
        clock[0] = 2.0
        b.update(4)
        assert "?it/s" not in b.format_meter(ncols=80)
        assert "<" in b.format_meter(ncols=80)
