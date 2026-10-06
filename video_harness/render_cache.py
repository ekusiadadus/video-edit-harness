"""Verified, process-safe immutable artifacts for repeat edit renders."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

from .common import fingerprint


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _auxiliary_inventory(folder, paths):
    """Bind required sidecars to their bytes, including directory contents."""
    if (not isinstance(paths, list) or any(not isinstance(name, str) for name in paths)
            or len(set(paths)) != len(paths)):
        raise ValueError('Invalid cache auxiliary paths')
    inventory = {}
    for name in paths:
        if (not isinstance(name, str) or not name or Path(name).is_absolute()
                or any(part in ('', '.', '..') for part in name.split('/'))):
            raise ValueError('Invalid cache auxiliary path')
        path = folder / name
        if not path.exists() or path.is_symlink():
            raise ValueError('Missing or linked cache auxiliary: ' + name)
        members = [path] if path.is_file() else list(path.rglob('*'))
        if any(member.is_symlink() for member in members):
            raise ValueError('Linked cache auxiliary content: ' + name)
        files = [member for member in members if member.is_file()]
        if not files:
            raise ValueError('Empty cache auxiliary: ' + name)
        for member in sorted(files):
            ref = fingerprint(member)
            inventory[str(member.relative_to(folder))] = {'sha256': ref['sha256'], 'bytes': ref['bytes']}
    return inventory


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

    def get(self, stage, inputs, extension, destination, builder, log_destination=None, *,
            auxiliary_paths=None):
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
                    if auxiliary_paths is not None:
                        hit = (hit and data.get('auxiliary_paths') == auxiliary_paths
                               and data.get('auxiliary_files') == _auxiliary_inventory(folder, auxiliary_paths))
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
                    if auxiliary_paths is not None:
                        data['auxiliary_paths'] = list(auxiliary_paths)
                        data['auxiliary_files'] = _auxiliary_inventory(private, auxiliary_paths)
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
            if auxiliary_paths is not None:
                event['auxiliary_meta_sha256'] = fingerprint(meta)['sha256']
            self.events.append(event)
            return event

    def copy_auxiliary(self, event, destinations):
        """Copy sealed sidecars from the exact cache event without overwriting."""
        stage, key = event.get('stage'), event.get('key')
        if (not isinstance(stage, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', stage)
                or not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key)):
            raise ValueError('Invalid auxiliary cache event')
        folder = self.root / stage / key
        meta = folder / 'meta.json'
        if folder.is_symlink() or meta.is_symlink():
            raise ValueError('Linked cache auxiliary metadata')
        lock = self.root / '.locks' / stage / (key + '.lock')
        with lock.open('a+b') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.check_source(deep=True)
            if fingerprint(meta)['sha256'] != event.get('auxiliary_meta_sha256'):
                raise ValueError('Cache auxiliary metadata changed')
            data = json.loads(meta.read_text())
            paths = data.get('auxiliary_paths')
            if (not isinstance(destinations, dict) or not isinstance(paths, list)
                    or set(destinations) != set(paths)
                    or _auxiliary_inventory(folder, paths) != data.get('auxiliary_files')):
                raise ValueError('Cache auxiliary content changed')
            for target in destinations.values():
                if Path(target).exists() or Path(target).is_symlink():
                    raise FileExistsError(target)
            copied = {}
            for name in paths:
                source, target = folder / name, Path(destinations[name])
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    with source.open('rb') as incoming, target.open('xb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                for relative, expected in data['auxiliary_files'].items():
                    if relative == name or relative.startswith(name + '/'):
                        member = target if relative == name else target / Path(relative).relative_to(name)
                        ref = fingerprint(member)
                        if {'sha256': ref['sha256'], 'bytes': ref['bytes']} != expected:
                            raise ValueError('Cache auxiliary copy differs')
                        copied[relative] = ref
            if (fingerprint(meta)['sha256'] != event['auxiliary_meta_sha256']
                    or _auxiliary_inventory(folder, paths) != data['auxiliary_files']):
                raise ValueError('Cache auxiliary changed during copy')
            self.check_source(deep=True)
            return copied

    def report(self):
        self.check_source(deep=True)
        return {'events': self.events, 'reused': sum(e['reused'] for e in self.events),
                'built': sum(not e['reused'] for e in self.events),
                'artifact_bytes': sum(e['bytes'] for e in self.events)}
