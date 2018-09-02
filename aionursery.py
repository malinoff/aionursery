import asyncio
import textwrap
import traceback

__all__ = ('Nursery', 'NurseryClosed', 'MultiError')


class Nursery:
    """
    Manages concurrent tasks.
    """

    def __init__(self):
        self._loop = asyncio.get_event_loop()
        self._children = set()
        self._pending_excs = []
        self._parent_task = None
        self.closed = False

    def start_soon(self, coro) -> asyncio.Task:
        """
        Creates a new child task inside this nursery.

        Note that there's no guarantee it will ever be executed, for example,
        when the parent task immediately cancels this child.
        """
        if self.closed:
            raise NurseryClosed
        task = asyncio.ensure_future(coro, loop=self._loop)
        task.add_done_callback(self._child_finished)
        self._children.add(task)
        return task

    def cancel_remaining(self):
        """
        Cancel all remaining running tasks.
        """
        current_task = asyncio.Task.current_task()
        for task in self._children:
            if task is current_task:
                continue
            task.cancel()

    def _child_finished(self, task):
        self._children.remove(task)
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            pass
        else:
            if exc is not None:
                self._add_exc(exc)

    def _add_exc(self, exc):
        self._pending_excs.append(exc)
        self._loop.call_soon(self._parent_task.cancel)

    async def __aenter__(self):
        if self.closed:
            raise NurseryClosed
        self._parent_task = asyncio.Task.current_task(self._loop)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is asyncio.CancelledError and not self._pending_excs:
            # Parent was cancelled, cancel all children
            for child in self._children.copy():
                child.cancel()
        elif exc is not None and exc_type is not asyncio.CancelledError:
            self._add_exc(exc)
        try:
            while self._children:
                await asyncio.gather(*self._children, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        self.closed = True
        if self._pending_excs:
            raise MultiError(self._pending_excs)

    def __del__(self):
        assert not self._children


class NurseryClosed(Exception):
    """
    Raises when somebody tries to use a closed nursery.
    """


class MultiError(Exception):
    """
    Gathers multiple exceptions into one, providing a sane __str__.
    All raised exceptions are available as ``exceptions`` property.
    """

    def __init__(self, exceptions):
        self.exceptions = exceptions

    def __str__(self):
        lines = [super().__str__()]
        for idx, exc in enumerate(self.exceptions):
            tb_lines = ''.join(traceback.format_exception(
                type(exc), exc, exc.__traceback__,
            ))
            lines += [
                'Details of embedded exception {}:\n'.format(idx),
                textwrap.indent(tb_lines, '  '),
            ]
        return '\n'.join(lines)
