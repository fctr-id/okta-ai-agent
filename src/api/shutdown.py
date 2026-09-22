"""Bounded cleanup for application-owned background services."""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def stop_services(background_tasks, closers, timeout=5.0):
    tasks = {}
    for name, task in background_tasks.items():
        if task is not None:
            task.cancel()
            tasks[task] = name
    for name, close in closers.items():
        tasks[asyncio.create_task(close(), name=f'shutdown:{name}')] = name
    if not tasks:
        return
    logger.info('Shutdown: stopping %s', ', '.join(tasks.values()))
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in done:
        if not task.cancelled() and task.exception() is not None:
            logger.warning('Shutdown: %s failed (%s)', tasks[task], type(task.exception()).__name__)
    for task in pending:
        logger.warning('Shutdown: %s exceeded %.1fs cleanup limit', tasks[task], timeout)
        task.cancel()
        task.add_done_callback(lambda completed: None if completed.cancelled() else completed.exception())

