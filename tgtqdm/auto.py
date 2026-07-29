"""
Mirror of ``tqdm.auto`` so that ``from tgtqdm.auto import tqdm, trange`` works
in code written against tqdm. There is no notebook-specific widget here: the
Telegram message is the rich display.
"""

from .std import tqdm, trange

__all__ = ["tqdm", "trange"]
