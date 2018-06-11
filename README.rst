aionursery
==========

.. image:: https://travis-ci.com/malinoff/aionursery.svg?branch=master
  :target: https://travis-ci.com/malinoff/aionursery

.. image:: https://codecov.io/gh/malinoff/aionursery/branch/master/graph/badge.svg
  :target: https://codecov.io/gh/malinoff/aionursery


This library implements a Nursery object, similar to trio's Nursery_ for ``asyncio``.

.. _Nursery: http://trio.readthedocs.io/en/latest/reference-core.html#nurseries-and-spawning

.. code-block:: python

    async def child():
        ...

    async def parent():
        async with aionursery.Nursery() as nursery:
            # Make two concurrent calls to child
            nursery.start_soon(child())
            nursery.start_soon(child())


Tasks form a tree: when you run your main coroutine (via ``asyncio.get_event_loop().run_until_complete`` or ``asyncio.run``), this creates an initial task, and all your other tasks will be children, grandchildren, etc. of the main task.

The body of the ``async with`` block acts like an initial task that's running inside the nursery, and then each call to ``nursery.start_soon`` adds another task that runs in parallel.

Keep in mind that:

* If any task inside the nursery raises an unhandled exception, then the nursery immediately cancels all the tasks inside the nursery.

* Since all of the tasks are running concurrently inside the async with block, the block does not exit until all tasks have completed. If you’ve used other concurrency frameworks, then you can think of it as, the de-indentation at the end of the async with automatically “joins” (waits for) all of the tasks in the nursery.

* Once all the tasks have finished, then:
  * The nursery is marked as “closed”, meaning that no new tasks can be started inside it.
  * Any unhandled exceptions are re-raised inside the parent task. If there are multiple exceptions, then they’re collected up into a single MultiError exception.

Since all tasks are descendents of the initial task, one consequence of this is that the parent can’t finish until all tasks have finished.

Please note that you can't reuse an already exited nursery. Trying to re-open it again, or to ``start_soon`` more tasks in it will raise ``NurseryClosed``.

Shielding some tasks from being cancelled
-----------------------------------------

Sometimes, however, you need to have an opposite behavior: a child must execute no matter what exceptions are raised in other tasks.
Imagine a payment transaction running in one task, and an sms sending in another.
You certainly don't want an sms sending error to cancel a payment transaction.

For that, you can ``asyncio.shield`` your tasks before starting them in the nursery:

.. code-block:: python

    async def perform_payment():
        ...

    async def send_sms():
        ...

    async def parent():
        async with Nursery() as nursery:
            nursery.start_soon(asyncio.shield(perform_payment()))
            nursery.start_soon(send_sms())


Getting results from children
-----------------------------

If your background tasks are not quite long-lived and return some useful values that you want to process, you can gather all tasks into a list and use ``asyncio.wait`` (or similar functions) as usual:

.. code-block:: python

    async def parent():
        async with Nursery() as nursery:
            task_foo = nursery.start_soon(foo())
            task_bar = nursery.start_soon(bar())
            results = await asyncio.wait([task_foo, task_bar])


If your background tasks are long-lived, you should use ``asyncio.Queue`` to pass objects between children and parent tasks:

.. code-block:: python

    async def child(queue):
        while True:
            data = await from_external_system()
            await queue.put(data)

    async def parent():
        queue = asyncio.Queue()
        async with Nursery() as nursery:
            nursery.start_soon(child(queue))
            while some_condition():
                data = await queue.get()
                await do_stuff_with(data)


Integration with ``async_timeout``
----------------------------------

You can wrap a nursery in a ``async_timeout.timeout`` context manager.
When timeout happens, the whole nursery cancels:

.. code-block:: python

    from async_timeout import timeout

    async def child():
        await asyncio.sleep(1000 * 1000)

    async def parent():
        async with timeout(10):
            async with Nursery() as nursery:
                nursery.start_soon(child())
                await asyncio.sleep(1000 * 1000)
