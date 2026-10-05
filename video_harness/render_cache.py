"""Verified, process-safe immutable artifacts for repeat edit renders."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from .common import fingerprint


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class RenderCache:
    def __init__(self, root, source, expected):
        self.root = Path(root)
        self.source = source
        self.expected = expected
        self.events = []
        if fingerprint(source) != expected:
            raise ValueError('Source changed before cached render')
        self._identity = self._stat_identity()

    def _stat_identity(self):
        stat = Path(self.source).stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def check_source(self, deep=False):
        if self._stat_identity() != self._identity or (deep and fingerprint(self.source) != self.expected):
            raise ValueError('Source changed during cached render')

    def get(self, stage, inputs, extension, destination, builder, log_destination=None):
        """Builder receives private artifact and log paths, and must complete both."""
        self.check_source()
        key = digest({'stage': stage, 'inputs': inputs})
        folder = self.root / stage / key
        self.root.mkdir(parents=True, exist_ok=True)
        folder.parent.mkdir(parents=True, exist_ok=True)
        lock_dir = self.root / '.locks' / stage
        lock_dir.mkdir(parents=True, exist_ok=True)
        begun = time.monotonic()
        with (lock_dir / (key + '.lock')).open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.check_source()
            artifact = folder / ('artifact' + extension)
            log = folder / 'build.log'
            meta = folder / 'meta.json'
            hit = False
            if folder.exists():
                try:
                    data = json.loads(meta.read_text())
                    hit = (data['key'] == key and data['inputs'] == inputs
                           and fingerprint(artifact)['sha256'] == data['artifact_sha256']
                           and fingerprint(log)['sha256'] == data['log_sha256'])
                except (OSError, ValueError, KeyError, TypeError):
                    hit = False
                if not hit:
                    raise ValueError(f'Corrupted cache artifact: {stage}/{key}')
            else:
                with tempfile.TemporaryDirectory(prefix='.' + key + '-', dir=folder.parent) as temp:
                    private = Path(temp)
                    built = private / artifact.name
                    built_log = private / log.name
                    builder(built, built_log)
                    self.check_source()
                    if not built.is_file() or not built_log.is_file():
                        raise ValueError(f'Cache builder did not create artifact and log: {stage}')
                    data = {'key': key, 'inputs': inputs,
                            'artifact_sha256': fingerprint(built)['sha256'],
                            'log_sha256': fingerprint(built_log)['sha256'],
                            'artifact_bytes': built.stat().st_size}
                    (private / 'meta.json').write_text(json.dumps(data, sort_keys=True))
                    os.rename(private, folder)
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream, artifact.open('rb') as source:
                shutil.copyfileobj(source, stream)
            if fingerprint(destination)['sha256'] != data['artifact_sha256']:
                raise ValueError('Cache copy failed integrity check')
            if log_destination is not None:
                log_destination = Path(log_destination)
                log_destination.parent.mkdir(parents=True, exist_ok=True)
                with log_destination.open('xb') as stream, log.open('rb') as source:
                    shutil.copyfileobj(source, stream)
            event = {'stage': stage, 'key': key, 'reused': hit, 'bytes': data['artifact_bytes'],
                     'elapsed_seconds': round(time.monotonic() - begun, 3)}
            self.events.append(event)
            return event

    def report(self):
        self.check_source(deep=True)
        return {'events': self.events, 'reused': sum(e['reused'] for e in self.events),
                'built': sum(not e['reused'] for e in self.events),
                'artifact_bytes': sum(e['bytes'] for e in self.events)}
