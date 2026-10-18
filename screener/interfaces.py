"""Point-in-time signal boundary shared with historical research.

Preliminary portfolio simulation lives in backtest.py; this module only exposes signals.
"""
from typing import Protocol

from .data import Bar
from .strategy import Parameters, screen


class HistoricalFeed(Protocol):
    def histories(self, as_of: str) -> dict[tuple[str, str], list[Bar]]:
        """Return only bars available on or before an ISO date."""
        ...


def screen_as_of(feed: HistoricalFeed, as_of: str, parameters: Parameters) -> dict:
    """Reusable signal-only entry point; can be called by a future event loop."""
    return screen(feed.histories(as_of), as_of, parameters)
