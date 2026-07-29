import io
from typing import Any, List, Optional

import pytest

from tgtqdm import TelegramLogger, format_eta, tgtqdm


class RecordingLogger:
    """Stands in for TelegramLogger and records what would be sent."""

    def __init__(self) -> None:
        self.messages: List[str] = []
        self.forced: List[bool] = []

    def log(self, message: str, timestamp: bool = False, force: bool = False) -> None:
        self.messages.append(message)
        self.forced.append(force)


@pytest.fixture
def spy() -> RecordingLogger:
    return RecordingLogger()


def run(iterable, spy, **kwargs) -> Any:
    out = io.StringIO()
    bar = tgtqdm(iterable, logger=spy, file=out, **kwargs)
    items = list(bar)
    return bar, items, out.getvalue()


class TestConstruction:
    def test_requires_credentials(self):
        with pytest.raises(ValueError, match="api_token"):
            tgtqdm(range(3))

    def test_requires_chat_id(self):
        with pytest.raises(ValueError, match="chat_id"):
            tgtqdm(range(3), api_token="T")

    def test_rejects_zero_update_interval(self):
        ## used to blow up with ZeroDivisionError mid-loop
        with pytest.raises(ValueError):
            tgtqdm(range(3), api_token="T", chat_id=1, update_every_n_iters=0)

    def test_builds_logger_from_json(self, credentials_file):
        bar = tgtqdm(range(3), json_filename=str(credentials_file))
        assert isinstance(bar.logger, TelegramLogger)
        assert bar.logger.chat_id == 123

    def test_infers_total_from_sized_iterable(self, spy):
        assert tgtqdm([1, 2, 3], logger=spy).total == 3

    def test_total_is_none_for_generators(self, spy):
        assert tgtqdm((i for i in range(3)), logger=spy).total is None

    def test_explicit_total_wins(self, spy):
        assert tgtqdm((i for i in range(3)), logger=spy, total=3).total == 3

    def test_len(self, spy):
        assert len(tgtqdm(range(4), logger=spy)) == 4

    def test_len_raises_without_total(self, spy):
        with pytest.raises(TypeError):
            len(tgtqdm((i for i in range(3)), logger=spy))


class TestIteration:
    def test_yields_every_item_unchanged(self, spy):
        _, items, _ = run([10, 20, 30], spy)
        assert items == [10, 20, 30]

    def test_logs_once_per_iteration(self, spy):
        run(range(3), spy)
        assert [m.split("\n")[0] for m in spy.messages] == [
            "[1/3]  33%",
            "[2/3]  66%",
            "[3/3] 100%",
        ]
        ## the last iteration has nothing left to estimate
        assert spy.messages[-1].endswith("ETA: --")

    def test_desc_is_prefixed(self, spy):
        run(range(1), spy, desc="training")
        assert spy.messages[0].startswith("training: ")

    def test_final_iteration_is_forced(self, spy):
        run(range(3), spy)
        assert spy.forced == [False, False, True]

    def test_update_every_n_iters(self, spy):
        run(range(6), spy, update_every_n_iters=3)
        assert [m.split("\n")[0] for m in spy.messages] == [
            "[3/6]  50%",
            "[6/6] 100%",
        ]

    def test_last_state_is_logged_even_if_not_on_the_interval(self, spy):
        ## 5 items with n=3 means iteration 5 is neither a multiple nor == total
        run(range(5), spy, update_every_n_iters=3)
        assert spy.messages[-1].split("\n")[0] == "[5/5] 100%"
        assert spy.forced[-1] is True

    def test_unknown_total_still_reports_the_final_count(self, spy):
        run((i for i in range(5)), spy, update_every_n_iters=3)
        assert spy.messages[-1] == "[5]"
        assert spy.forced[-1] is True

    def test_empty_iterable_logs_nothing(self, spy):
        _, items, output = run([], spy)
        assert items == []
        assert spy.messages == []
        assert output == ""

    def test_counter_resets_between_iterations(self, spy):
        ## re-iterating used to keep counting up from the previous run
        out = io.StringIO()
        bar = tgtqdm([1, 2], logger=spy, file=out)
        list(bar)
        spy.messages.clear()
        list(bar)
        assert [m.split("\n")[0] for m in spy.messages] == ["[1/2]  50%", "[2/2] 100%"]

    def test_partial_iteration_still_ends_the_stdout_line(self, spy):
        out = io.StringIO()
        for _ in tgtqdm(range(10), logger=spy, file=out):
            break
        assert out.getvalue().endswith("\n")

    def test_exception_in_body_propagates(self, spy):
        out = io.StringIO()
        with pytest.raises(RuntimeError):
            for _ in tgtqdm(range(3), logger=spy, file=out):
                raise RuntimeError("boom")
        assert out.getvalue().endswith("\n")

    def test_closed_stream_does_not_break_the_loop(self, spy):
        out = io.StringIO()
        out.close()
        assert list(tgtqdm(range(3), logger=spy, file=out)) == [0, 1, 2]

    def test_writes_progress_to_stdout(self, spy, capsys):
        list(tgtqdm(range(2), logger=spy, desc="hey"))
        captured = capsys.readouterr().out
        assert "hey: [2/2] 100%" in captured
        assert captured.endswith("\n")

    def test_repr(self, spy):
        assert "current=0" in repr(tgtqdm(range(3), logger=spy))


class TestEta:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (None, "ETA: --"),
            (-1, "ETA: --"),
            (0, "ETA: 0s"),
            (5.7, "ETA: 5s"),
            (59, "ETA: 59s"),
            (60, "ETA: 1m 0s"),
            (125, "ETA: 2m 5s"),
            (3600, "ETA: 1h 0m 0s"),
            (7325, "ETA: 2h 2m 5s"),
        ],
    )
    def test_formats(self, seconds: Optional[float], expected: str):
        assert format_eta(seconds) == expected

    def test_eta_is_reported_mid_run(self, spy, monkeypatch):
        from tgtqdm import progress

        clock = [0.0]

        def fake_monotonic() -> float:
            clock[0] += 1.0
            return clock[0]

        monkeypatch.setattr(progress.time, "monotonic", fake_monotonic)
        run(range(4), spy)
        assert "ETA: " in spy.messages[1]
        assert spy.messages[1] != "[2/4]  50%\nETA: --"


def test_end_to_end_against_a_faked_api(poster, credentials_file):
    """A full loop should send once and then only edit that message."""
    logger = TelegramLogger.from_json(str(credentials_file), min_interval=0.0)
    out = io.StringIO()
    assert list(tgtqdm(range(3), logger=logger, file=out)) == [0, 1, 2]
    assert poster.methods == ["sendMessage", "editMessageText", "editMessageText"]
    assert all(call["json"]["chat_id"] == 123 for call in poster.calls)
