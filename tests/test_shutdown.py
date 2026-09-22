import asyncio
import ast
import logging
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.api.shutdown import stop_services


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_slack_closes_connection_on_cancellation(self):
        tree = ast.parse(Path('src/integrations/slack/slack_app.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'start_socket_mode')
        handler = SimpleNamespace(start_async=AsyncMock(side_effect=asyncio.CancelledError),
                                  close_async=AsyncMock())
        ns = {'settings': SimpleNamespace(SLACK_OPERATION_MODE='socket', SLACK_APP_TOKEN='xapp-test'),
              'get_or_create_slack_app': lambda: object(), 'logger': logging.getLogger('test')}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<socket-mode>', 'exec'), ns)
        module = SimpleNamespace(AsyncSocketModeHandler=lambda *args: handler)
        with patch.dict(sys.modules, {'slack_bolt.adapter.socket_mode.async_handler': module}):
            with self.assertRaises(asyncio.CancelledError):
                await ns['start_socket_mode']()
        handler.close_async.assert_awaited_once()

    async def test_cancelled_service_finishes_cleanup(self):
        closed = asyncio.Event()

        async def service():
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                closed.set()

        task = asyncio.create_task(service())
        await asyncio.sleep(0)
        await stop_services({'socket': task}, {})
        self.assertTrue(closed.is_set())
        self.assertTrue(task.cancelled())

    async def test_slow_cleanup_is_bounded_and_other_services_close(self):
        closed = asyncio.Event()

        async def slow():
            await asyncio.Event().wait()

        async def fast():
            closed.set()

        with self.assertLogs('src.api.shutdown', logging.WARNING) as logs:
            await stop_services({}, {'slow': slow, 'fast': fast}, timeout=0.01)
        self.assertTrue(closed.is_set())
        self.assertIn('slow exceeded', logs.output[0])
        await asyncio.sleep(0)

    async def test_cleanup_failure_does_not_skip_other_services(self):
        closed = asyncio.Event()

        async def fail():
            raise RuntimeError('private provider message')

        async def fast():
            closed.set()

        with self.assertLogs('src.api.shutdown', logging.WARNING) as logs:
            await stop_services({}, {'broken': fail, 'fast': fast})
        self.assertTrue(closed.is_set())
        self.assertIn('RuntimeError', logs.output[0])
        self.assertNotIn('private provider message', logs.output[0])


class LauncherShutdownTests(unittest.TestCase):
    def test_windows_interrupt_signals_python_and_waits_before_force_kill(self):
        tree = ast.parse(Path('scripts/start_server.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_command')
        process = Mock()
        process.wait.side_effect = [KeyboardInterrupt, 0]
        process.poll.return_value = None
        ns = {'subprocess': subprocess, 'threading': threading,
              'os': SimpleNamespace(name='nt'),
              'signal': SimpleNamespace(CTRL_BREAK_EVENT=1),
              'stream_output': Mock()}
        wait_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'wait_for_process')
        ns['time'] = time
        exec(compile(ast.Module(body=[wait_node], type_ignores=[]), '<wait>', 'exec'), ns)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<launcher>', 'exec'), ns)
        with patch.object(subprocess, 'Popen', return_value=process) as popen, \
                patch.object(subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, create=True), \
                patch.object(threading, 'Thread'), patch('builtins.print'):
            self.assertTrue(ns['run_command'](['python', '-m', 'uvicorn', 'app:app']))
        self.assertFalse(popen.call_args.kwargs['shell'])
        self.assertEqual(popen.call_args.kwargs['creationflags'], 512)
        process.send_signal.assert_called_once_with(1)
        process.wait.assert_called_with(timeout=0.2)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_real_process_wait_dispatches_pending_interrupt_promptly(self):
        # Isolate the interrupt from the test runner. No app imports or network calls.
        code = '''
import _thread
import subprocess
import sys
import threading
import time
from scripts.start_server import wait_for_process
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
timer = threading.Timer(0.25, _thread.interrupt_main)
started = time.monotonic()
timer.start()
try:
    wait_for_process(child)
except KeyboardInterrupt:
    assert time.monotonic() - started < 2, 'Interrupt was delayed by process wait'
else:
    raise AssertionError('Interrupt was not dispatched')
finally:
    timer.cancel()
    child.terminate()
    child.wait(timeout=3)
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
