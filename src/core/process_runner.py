"""Bounded local process supervision. This does not provide OS access isolation."""
import asyncio
import json
from pathlib import Path
import sys
from dataclasses import dataclass

EXECUTION_TIMEOUT = 120
DISCOVERY_TIMEOUT = 60
STDOUT_LIMIT = 8 * 1024 * 1024
STDERR_LIMIT = 1024 * 1024
INPUT_LIMIT = 4 * 1024 * 1024
LINE_LIMIT = 64 * 1024
WORKER_RESULT = '__TAKO_WORKER_RESULT__'
WORKER_EVENT = '__TAKO_WORKER_EVENT__'


@dataclass
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


async def run_process(args, *, cwd, timeout=EXECUTION_TIMEOUT, cancellation_check=None,
                      on_stderr=None, input_data=None, stdout_limit=STDOUT_LIMIT,
                      stderr_limit=STDERR_LIMIT):
    """Drain bounded pipes while independently supervising even a silent child."""
    if timeout <= 0 or stdout_limit <= 0 or stderr_limit <= 0:
        raise ValueError('Execution limits must be positive')
    if input_data is not None and len(input_data) > INPUT_LIMIT:
        raise ValueError('Worker input exceeds the size limit')
    if cancellation_check and cancellation_check():
        raise asyncio.CancelledError()
    proc = None
    tasks = []
    completion = None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout

    async def read_stream(stream, limit, callback=None):
        captured = bytearray()
        pending = bytearray()
        while chunk := await stream.read(16384):
            if len(captured) + len(chunk) > limit:
                raise ValueError('Execution output exceeds the size limit')
            captured.extend(chunk)
            if callback:
                pending.extend(chunk)
                while b'\n' in pending:
                    line, _, remainder = pending.partition(b'\n')
                    pending = bytearray(remainder)
                    if len(line) > LINE_LIMIT:
                        raise ValueError('Execution progress line exceeds the size limit')
                    await callback(line.decode('utf-8', errors='replace').rstrip('\r'))
                if len(pending) > LINE_LIMIT:
                    raise ValueError('Execution progress line exceeds the size limit')
        if callback and pending:
            await callback(pending.decode('utf-8', errors='replace').rstrip('\r'))
        return bytes(captured)

    async def write_input():
        if proc.stdin:
            try:
                proc.stdin.write(input_data)
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass  # Return the child's bounded error output below.
            finally:
                proc.stdin.close()

    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=cwd, stdin=asyncio.subprocess.PIPE if input_data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        tasks = [asyncio.create_task(read_stream(proc.stdout, stdout_limit)),
                 asyncio.create_task(read_stream(proc.stderr, stderr_limit, on_stderr)),
                 asyncio.create_task(write_input()), asyncio.create_task(proc.wait())]
        completion = asyncio.gather(*tasks)
        while not completion.done():
            if cancellation_check and cancellation_check():
                raise asyncio.CancelledError()
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError(f'Execution exceeded {timeout:g} seconds')
            await asyncio.wait({completion}, timeout=min(0.1, remaining))
        stdout, stderr, _, returncode = completion.result()
        return ProcessResult(returncode, stdout, stderr)
    finally:
        if proc is not None:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            # Cancel blocked readers/callbacks before waiting for pipe transports.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            async def discard(stream):
                while await stream.read(16384):
                    pass
            await asyncio.gather(discard(proc.stdout), discard(proc.stderr), proc.wait())
        if completion is not None:
            completion.cancel()
            await asyncio.gather(completion, return_exceptions=True)


async def run_worker(mode, payload, *, timeout=DISCOVERY_TIMEOUT, cancellation_check=None,
                     on_stderr=None):
    result = await run_process(
        [sys.executable, '-u', '-m', 'src.core.execution_worker', mode],
        cwd=Path(__file__).resolve().parents[2], timeout=timeout,
        cancellation_check=cancellation_check, on_stderr=on_stderr,
        input_data=json.dumps(payload, default=str).encode('utf-8'),
    )
    if result.returncode:
        raise ValueError('Local execution worker failed: ' + result.stderr.decode('utf-8', errors='replace')[-2000:])
    lines = result.stdout.decode('utf-8').splitlines()
    for line in reversed(lines):
        if line.startswith(WORKER_RESULT):
            return json.loads(line[len(WORKER_RESULT):])
    raise ValueError('Local execution worker returned no result')
