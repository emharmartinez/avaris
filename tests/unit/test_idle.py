from avaris.api.lifecycle import IdleWatch


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_expires_after_the_timeout_without_a_request() -> None:
    clock = FakeClock()
    watch = IdleWatch(60, clock)
    clock.t += 59
    assert not watch.expired(busy=False)
    clock.t += 1
    assert watch.expired(busy=False)


def test_a_request_restarts_the_countdown() -> None:
    clock = FakeClock()
    watch = IdleWatch(60, clock)
    clock.t += 50
    watch.touch()
    clock.t += 50
    assert not watch.expired(busy=False)
    assert watch.idle_s() == 50


def test_a_running_job_never_expires_and_restarts_the_countdown() -> None:
    clock = FakeClock()
    watch = IdleWatch(60, clock)
    clock.t += 600
    assert not watch.expired(busy=True)
    clock.t += 59
    assert not watch.expired(busy=False)
    clock.t += 1
    assert watch.expired(busy=False)
