"""Representative Python analyzer characterization fixture."""

from collections import deque as Queue  # noqa: F401 - import artifact baseline
import os.path as paths

MAXIMUM = 3
Alias = dict[str, int]


def helper(item: int, /, *, flag: bool = False) -> str:
    """Build a stable string value."""
    if flag:
        raise ValueError(item)
    return paths.join(str(item))


class Worker:
    """Run a callback through a representative method."""

    def run(self, value: int) -> str:
        """Call the helper through a callable reference."""
        callback = helper
        return callback(value)
