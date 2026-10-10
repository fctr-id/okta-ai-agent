"""Short-lived discovery evidence, addressed by server-issued test IDs."""
import json
import logging
from pathlib import Path
import re
import shutil
import tempfile
import time

logger = logging.getLogger(__name__)
_CACHE_NAME = re.compile(r"api-tests-[a-z0-9_]{8}\Z")
_TEST_ID = re.compile(r"api-test-[0-9a-f]{32}\Z")
STALE_SECONDS = 24 * 60 * 60


def _json(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=True, default=str)


def result_preview(value, budget=4000):
    """Return valid JSON, allocating space across sections instead of slicing text.

    Reduced containers are explicitly marked; their samples are never presented
    as complete results. The original response is kept separately on disk.
    """
    original_chars = len(_json(value))

    def compact(item, allowance, depth=0):
        if len(_json(item)) <= allowance:
            return item
        kind = 'object' if isinstance(item, dict) else 'array' if isinstance(item, list) else 'value'
        summary = {'preview_only': True, 'type': kind}
        if isinstance(item, (dict, list, str)):
            summary['count'] = len(item)
        if depth >= 8 or allowance < 180:
            return summary
        if isinstance(item, dict):
            entries = list(item.items())[:24]
            overhead = len(_json({key: None for key, _ in entries})) + 100
            share = (allowance - overhead) // max(len(entries), 1)
            summary['fields'] = {key: compact(child, share, depth + 1) for key, child in entries}
            summary['omitted_fields'] = len(item) - len(entries)
        elif isinstance(item, list):
            sample = item[:1]
            summary['sample'] = [compact(child, allowance - 120, depth + 1) for child in sample]
            summary['omitted_items'] = len(item) - len(sample)
        elif isinstance(item, str):
            summary['sample'] = item[:max(0, allowance // 8)]
        if len(_json(summary)) > allowance:
            # Extremely wide objects or long keys must not break the budget.
            return {'preview_only': True, 'type': kind, 'count': len(item) if isinstance(item, (dict, list, str)) else None}
        return summary

    data = compact(value, budget - 100)
    return {'truncated': data != value, 'original_chars': original_chars, 'data': data}


class DiscoveryResults:
    """Temporary exact responses and code; only this instance's IDs can be read."""
    def __init__(self, artifacts_file: Path):
        artifacts_file.parent.mkdir(parents=True, exist_ok=True)
        self._directory = tempfile.TemporaryDirectory(prefix='api-tests-', dir=artifacts_file.parent)
        self.directory = Path(self._directory.name)
        self._ids = set()
        self.saved = {}

    def put(self, test_id, code, result):
        if not _TEST_ID.fullmatch(test_id):
            raise ValueError('Invalid test ID')
        (self.directory / f'{test_id}.json').write_text(_json({'code': code, 'result': result}), encoding='utf-8')
        self._ids.add(test_id)

    def get(self, test_id):
        if test_id not in self._ids:
            raise ValueError('Unknown test ID for this discovery run')
        return json.loads((self.directory / f'{test_id}.json').read_text(encoding='utf-8'))

    def cleanup(self):
        try:
            self._directory.cleanup()
        except OSError:
            logger.warning('Could not remove temporary discovery results; stale cleanup will retry')
        self._ids.clear()


def cleanup_stale_discovery_results(root: Path):
    """Next-query sweep of abandoned caches only; durable results are untouched."""
    root = root.resolve()
    cutoff = time.time() - STALE_SECONDS
    for candidate in root.glob('sessions/*/turns/*/artifacts/api-tests-*'):
        try:
            if not _CACHE_NAME.fullmatch(candidate.name) or not candidate.is_dir():
                continue
            # Reject links/junctions at every level before recursive deletion.
            paths = [candidate, *list(candidate.parents)[:5]]
            if any(path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400 for path in paths):
                continue
            if not candidate.resolve().is_relative_to(root):
                continue
            entries = list(candidate.iterdir())
            if any(not entry.is_file() or entry.is_symlink() or getattr(entry.lstat(), 'st_file_attributes', 0) & 0x400
                   or not re.fullmatch(r'api-test-[0-9a-f]{32}\.json', entry.name) for entry in entries):
                continue
            if max(path.stat().st_mtime for path in [candidate, *entries]) >= cutoff:
                continue
            shutil.rmtree(candidate)
        except OSError:
            logger.warning('Could not remove a stale discovery cache; will retry on a later query')
