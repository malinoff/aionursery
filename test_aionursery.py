"""
Unit tests for aionursery.py
"""
import asyncio
import textwrap
import traceback

import pytest
import async_timeout

from aionursery import Nursery, NurseryClosed, MultiError


@pytest.mark.asyncio
async def test_parent_block_error_basic():
    """
    Context manager's body raises properly.
    """
    error = ValueError('whoops')

    with pytest.raises(MultiError) as excinfo:
        async with Nursery():
            raise error

    assert len(excinfo.value) == 1
    assert excinfo.value[0] is error


@pytest.mark.asyncio
async def test_child_crash_basic():
    """
    A child exception is propagated to the parent coroutine.
    """
    error = ValueError('whoops')

    async def child():
        raise error

    with pytest.raises(MultiError) as excinfo:
        async with Nursery() as nursery:
            nursery.start_soon(child())

    assert len(excinfo.value) == 1
    assert excinfo.value[0] is error


@pytest.mark.asyncio
async def test_basic_interleave():
    """
    Children are running one after another; when all finished, the task nursery
    is joined with no errors.
    """
    async def looper(whoami, record):
        for i in range(3):
            record.append((whoami, i))
            await asyncio.sleep(0)

    record = []
    async with Nursery() as nursery:
        nursery.start_soon(looper('a', record))
        nursery.start_soon(looper('b', record))

    assert record == [
        ('a', 0), ('b', 0), ('a', 1), ('b', 1), ('a', 2), ('b', 2)
    ]


@pytest.mark.asyncio
async def test_child_crash_propagation():
    """
    An error in one child cancels other children
    and the context manager's body.
    """
    looper_cancelled = False

    async def looper():
        nonlocal looper_cancelled
        try:
            while True:
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            looper_cancelled = True
            raise

    error = ValueError('crashed')

    async def crasher():
        raise error

    with pytest.raises(MultiError) as excinfo:
        async with Nursery() as nursery:
            nursery.start_soon(looper())
            nursery.start_soon(crasher())

    assert looper_cancelled
    assert len(excinfo.value) == 1
    assert excinfo.value[0] is error


@pytest.mark.asyncio
async def test_parent_and_child_both_crash():
    """
    When both parent and child crash, errors are propagated
    as a MultiError.
    """
    async def crasher():
        raise ValueError

    with pytest.raises(MultiError) as excinfo:
        async with Nursery() as nursery:
            nursery.start_soon(crasher())
            raise KeyError

    assert set(type(exc) for exc in excinfo.value) == {ValueError, KeyError}


@pytest.mark.asyncio
async def test_two_child_crashes():
    """
    Multiple child crashes are propagated as a MultiError.
    """
    async def crasher(etype):
        raise etype

    with pytest.raises(MultiError) as excinfo:
        async with Nursery() as nursery:
            nursery.start_soon(crasher(KeyError))
            nursery.start_soon(crasher(ValueError))

    assert set(type(exc) for exc in excinfo.value) == {ValueError, KeyError}


@pytest.mark.asyncio
async def test_child_crash_wakes_parent():
    """
    If a child task crashes, the context manager's body is cancelled.
    """
    error = ValueError('crashed')

    async def crasher():
        raise error

    with pytest.raises(MultiError) as excinfo:
        async with Nursery() as nursery:
            nursery.start_soon(crasher())
            await asyncio.sleep(1000 * 1000)

    assert len(excinfo.value) == 1
    assert excinfo.value[0] is error


@pytest.mark.asyncio
async def test_child_can_spawn_children():
    """
    A child task can spawn even more children tasks.
    """
    i = 0

    async def child(nursery):
        nonlocal i
        i += 1
        if i == 3:
            return
        await asyncio.sleep(0)
        nursery.start_soon(child(nursery))

    async with Nursery() as nursery:
        nursery.start_soon(child(nursery))


@pytest.mark.asyncio
async def test_can_cancel_remaining():
    """
    A child task can cancel other remaining children.
    """

    cancelled = False

    async def runs_forever():
        nonlocal cancelled
        try:
            await asyncio.sleep(1000)
        except asyncio.CancelledError:
            cancelled = True
            raise

    async def canceller(nursery):
        nursery.cancel_remaining()

    async with Nursery() as nursery:
        nursery.start_soon(runs_forever())
        nursery.start_soon(canceller(nursery))
        # This allows children to be actually executed
        await asyncio.sleep(0)
        # This allows to execute cancellation logic in `runs_forever`
        await asyncio.sleep(0)
        # assert within context manager to be sure
        # `runs_forever` hasn't been cancelled by the nursery
        assert cancelled


@pytest.mark.asyncio
async def test_shielded_child_continues_running():
    """
    A shielded child continues running.
    """
    work_done = False

    async def worker():
        nonlocal work_done
        await asyncio.sleep(0)
        work_done = True

    try:
        async with Nursery() as nursery:
            nursery.start_soon(asyncio.shield(worker()))
            raise RuntimeError
    except MultiError:
        pass

    assert work_done


@pytest.mark.asyncio
async def test_nursery_cant_be_reused():
    """
    An already used nursery raises NurseryClosed when used again.
    """
    nursery = Nursery()
    async with nursery:
        pass

    with pytest.raises(NurseryClosed):
        async with nursery:
            pass

    with pytest.raises(NurseryClosed):
        nursery.start_soon(asyncio.sleep(0))


def test_multi_error_contains_all_tracebacks():
    """
    When a MultiError raises, its __str__ contains all tracebacks.
    """
    try:
        raise ValueError('foo')
    except ValueError as exc:
        foo_exc = exc
    try:
        raise KeyError('bar')
    except KeyError as exc:
        bar_exc = exc

    foo_traceback = ''.join(traceback.format_exception(
        type(foo_exc), foo_exc, foo_exc.__traceback__
    ))
    bar_traceback = ''.join(traceback.format_exception(
        type(bar_exc), bar_exc, bar_exc.__traceback__
    ))

    error = MultiError([foo_exc, bar_exc])

    assert 'Details of embedded exception 0:' in str(error)
    assert textwrap.indent(foo_traceback, '  ') in str(error)

    assert 'Details of embedded exception 1:' in str(error)
    assert textwrap.indent(bar_traceback, '  ') in str(error)


@pytest.mark.asyncio
async def test_can_nest_nurseries():
    """
    When nesting nurseries, nested exceptions are gathered into a tree
    of MultiErrors.
    """
    outer_error = RuntimeError('outer')
    inner_error = RuntimeError('inner')

    async def child(outer):
        if outer:
            raise outer_error
        else:
            raise inner_error

    with pytest.raises(MultiError) as exc_info:
        async with Nursery() as outer:
            outer.start_soon(child(outer=True))
            async with Nursery() as inner:
                inner.start_soon(child(outer=False))

    assert len(exc_info.value) == 2
    first, second = exc_info.value
    assert first is outer_error
    assert isinstance(second, MultiError)
    assert second[0] is inner_error


@pytest.mark.asyncio
async def test_timeout_is_respected():
    """
    When using ``async_timeout``, the timeout is respected and all tasks
    (both parent and children) are properly cancelled.
    """
    parent_cancelled = child_cancelled = False

    async def sleepy():
        nonlocal child_cancelled
        try:
            await asyncio.sleep(1000 * 1000)
        except asyncio.CancelledError:
            child_cancelled = True
            raise

    # The outer timeout is for terminating the test
    # in case the code doesn't work as intended.
    async with async_timeout.timeout(1):
        async with async_timeout.timeout(0.01):
            try:
                async with Nursery() as nursery:
                    nursery.start_soon(sleepy())
                    await asyncio.sleep(1000 * 1000)
            except asyncio.CancelledError:
                parent_cancelled = True

    assert parent_cancelled and child_cancelled
