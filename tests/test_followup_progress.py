"""Exercise follow-up phase events through the actual SSE callback without a model."""
import ast
import asyncio
import logging
from pathlib import Path
import time
from typing import Any, Dict
import unittest


class FollowUpProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_phase_survives_aggregator_and_sse_queue_without_tool_calls(self):
        namespace = dict(globals(), logger=logging.getLogger(__name__), event_queue=asyncio.Queue())
        for filename, node_type, name in [
            ('src/core/agents/orchestrator.py', ast.ClassDef, 'EventAggregator'),
            ('src/api/routers/react_stream.py', ast.AsyncFunctionDef, 'event_callback'),
        ]:
            tree = ast.parse(Path(filename).read_text(encoding='utf-8'))
            nodes = [node for node in ast.walk(tree) if isinstance(node, node_type) and node.name == name]
            self.assertEqual(len(nodes), 1)
            exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, 'exec'), namespace)
        aggregator = namespace['EventAggregator'](namespace['event_callback'])
        for phase in (None, 'processor', 'review', 'analysis'):
            aggregator.set_phase(phase)
            await aggregator.step_start({'title': 'Progress', 'text': 'Working on the question'})
            event = namespace['event_queue'].get_nowait()
            self.assertEqual(event['type'], 'STEP-START')
            self.assertEqual(event['phase'], phase or 'planning')
            self.assertEqual(event['tools'], [])


if __name__ == '__main__':
    unittest.main()
