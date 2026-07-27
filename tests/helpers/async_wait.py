"""Poll-based waits for async delivery in tests.

A fixed `await asyncio.sleep(0.1)` before asserting on event-bus delivery
assumes delivery always finishes inside that window. It usually does — until
the runner is under CPU contention (a busy CI box), at which point the
assertion fails even though nothing is actually broken. `wait_until` polls the
real condition instead of guessing a duration, so it passes as soon as the
condition is true and only fails when it truly never becomes true.
"""
import asyncio
from typing import Callable


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0, interval: float = 0.005,
                      sleep=asyncio.sleep, describe: Callable[[], object] | None = None) -> None:
    """Poll `predicate` on the real clock.

    `sleep` defaults to asyncio.sleep but can be overridden with an
    unpatched reference when the test under test has mocked
    `asyncio.sleep` at the module level (mocking it there patches the
    module object itself, so this poll loop would otherwise call the
    mock too and never actually wait).

    `describe` is what makes a rare timeout worth anything. Without it the
    failure reads `condition not met within 5.0s: <lambda at 0x7f...>`, which
    says nothing about WHAT the state actually was — and a flake you cannot
    reproduce is then a flake you cannot diagnose either. Pass a callable
    returning the observed state and it lands in the message.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            observed = ""
            if describe is not None:
                try:
                    observed = f" — observed: {describe()!r}"
                except Exception as e:            # a broken describe must not
                    observed = f" — describe() raised {e!r}"   # mask the timeout
            raise AssertionError(
                f"condition not met within {timeout}s: {predicate}{observed}"
            )
        await sleep(interval)


async def wait_for_dlq(bus, event_name: str, timeout: float | None = None) -> None:
    """Wait for `_dlq.<event_name>` to appear in the bus trace history.

    A DLQ event only fires after every retry has exhausted its exponential
    backoff (`backoff * 2**(attempt-1)`), so it can appear well past
    `wait_until`'s 2.0s default — waiting for a DLQ with plain `wait_until`
    fails even when the plugin is correct.

    By default the deadline is not guessed: it is derived from the
    retries/backoff the subscribers of `event_name` actually declared, plus
    the standard 2.0s delivery slack — so it stays correct whatever a flow
    declares (3, 5 or 10 retries) with no number to keep in sync. Pass
    `timeout` only to override that computed ceiling.
    """
    if timeout is None:
        schedule = 0.0
        for (ev, _cb), opts in getattr(bus, "_sub_options", {}).items():
            if ev == event_name and opts.retries > 0:
                total = sum(opts.backoff * (2 ** (attempt - 1))
                            for attempt in range(1, opts.retries + 1))
                schedule = max(schedule, total)
        timeout = schedule + 2.0
    dlq_event = f"_dlq.{event_name}"
    await wait_until(
        lambda: any(r.envelope.event == dlq_event for r in bus.get_trace_history()),
        timeout=timeout,
    )
