import time
from collections.abc import Callable

Monotonic = Callable[[], float]


class IdleWatch:
    # Seconds since the last request; a running job counts as activity, so the countdown
    # restarts once it ends
    def __init__(self, timeout_s: float, monotonic: Monotonic = time.monotonic) -> None:
        self.timeout_s = timeout_s
        self.monotonic = monotonic
        self._last = monotonic()

    def touch(self) -> None:
        self._last = self.monotonic()

    def idle_s(self) -> float:
        return self.monotonic() - self._last

    def expired(self, busy: bool) -> bool:
        if busy:
            self.touch()
            return False
        return self.idle_s() >= self.timeout_s
