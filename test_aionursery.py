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

    with pytest.raises(ValueError) as excinfo:
        async with Nursery():
            raise error
    assert excinfo.value is error


@pytest.mark.asyncio
async def test_child_crash_basic():
    """
    A child exception is propagated to the parent coroutine.
    """
    error = ValueError('whoops')

    async def child():
        raise error

    try:
        async with Nursery() as nursery:
            nursery.start_soon(child())
    except ValueError as exc:
        assert exc is error


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

    error = ValueError('crashed')

    async def crasher():
        raise error

    with pytest.raises(ValueError) as excinfo:
        async with Nursery() as nursery:
            nursery.start_soon(looper())
            nursery.start_soon(crasher())

    assert looper_cancelled
    assert excinfo.value is error


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

    assert set(type(exc)
               for exc in excinfo.value.exceptions) == {ValueError, KeyError}


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

    assert set(type(exc)
               for exc in excinfo.value.exceptions) == {ValueError, KeyError}


@pytest.mark.asyncio
async def test_child_crash_wakes_parent():
    """
    If a child task crashes, the context manager's body is cancelled.
    """
    async def crasher():
        raise ValueError

    with pytest.raises(ValueError):
        async with Nursery() as nursery:
            nursery.start_soon(crasher())
            await asyncio.sleep(1000 * 1000)


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
    except RuntimeError:
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
        foo = exc
    try:
        raise KeyError('bar')
    except KeyError as exc:
        bar = exc

    foo_traceback = ''.join(traceback.format_exception(
        type(foo), foo, foo.__traceback__
    ))
    bar_traceback = ''.join(traceback.format_exception(
        type(bar), bar, bar.__traceback__
    ))

    error = MultiError([foo, bar])

    assert 'Details of embedded exception 0:' in str(error)
    assert textwrap.indent(foo_traceback, '  ') in str(error)

    assert 'Details of embedded exception 1:' in str(error)
    assert textwrap.indent(bar_traceback, '  ') in str(error)


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

    async with async_timeout.timeout(0.01):
        try:
            async with Nursery() as nursery:
                nursery.start_soon(sleepy())
                await asyncio.sleep(1000 * 1000)
        except asyncio.CancelledError:
            parent_cancelled = True

    assert parent_cancelled and child_cancelled
