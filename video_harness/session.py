"""Durable editing sessions shared by Codex, Claude Code and the human editor."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import hashlib
import html
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid

from .common import fingerprint, project, read, write
from .edl import validate_plan

ACTORS = ('human', 'codex', 'claude_code', 'automation')
CHECKS = ('meaning', 'pacing', 'audio_only', 'cut_boundaries', 'captions', 'color')
FCP_CHECKS = ('fcp_import', 'fcp_playback', 'fcp_grade', 'fcp_captions', 'fcp_mix')


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def actor_name(actor):
    if actor not in ACTORS:
        raise ValueError('Actor must be human, codex, claude_code, or automation')
    return actor


def require_note(note):
    if not isinstance(note, str) or not note.strip():
        raise ValueError('Record the reason for this editing decision')
    return note.strip()


def check_ref(ref):
    if not isinstance(ref, dict) or fingerprint(ref['path']) != ref:
        raise ValueError('Session artifact changed: ' + str(ref.get('path') if isinstance(ref, dict) else ref))
    return Path(ref['path'])


class Session:
    def __init__(self, folder):
        self.root = Path(folder).resolve()
        if not (self.root / 'checkpoints').is_dir():
            raise ValueError('Not an editing session')

    @classmethod
    def start(cls, project_path, folder, brief_data=None, actor='codex'):
        from .editorial import make_brief
        actor_name(actor)
        cfg = project(project_path)
        folder = Path(folder).resolve()
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'checkpoints').mkdir()
        for name in ('artifacts', 'renders', 'reviews', 'feedback', 'deliveries', 'handoffs'):
            (folder / name).mkdir()
        write(folder / 'artifacts/project-0000.json', cfg)
        brief = make_brief(cfg, brief_data or {})
        write(folder / 'artifacts/brief-0000.json', brief)
        session = cls(folder)
        state = {'version': 1, 'id': uuid.uuid4().hex, 'created_at': now(), 'generation': 0,
                 'phase': 'needs_transcript', 'source': fingerprint(cfg['source']),
                 'project': fingerprint(folder / 'artifacts/project-0000.json'),
                 'brief': fingerprint(folder / 'artifacts/brief-0000.json'), 'transcript': None,
                 'plan': None, 'renders': [], 'feedback': [], 'reviews': [], 'deliveries': [],
                 'operation': None, 'last_actor': actor, 'history': []}
        with session._lock():
            session._save(state, 'started', actor)
        return session

    @contextmanager
    def _lock(self):
        with (self.root / '.session.lock').open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Another operation is updating this editing session') from None
            yield

    def _load(self):
        # Immutable checkpoints are the durable source. state.json is a convenience pointer.
        files = sorted((self.root / 'checkpoints').glob('*.json'))
        if not files:
            raise ValueError('Session has no committed checkpoint')
        sealed = read(files[-1])
        state = sealed['state']
        if digest(state) != sealed.get('sha256'):
            raise ValueError('Session checkpoint changed; cannot resume safely')
        return state

    def _save(self, state, event, actor, detail=None):
        actor_name(actor)
        state['generation'] += 1
        state['updated_at'] = now()
        state['last_actor'] = actor
        item = {'generation': state['generation'], 'at': now(), 'event': event,
                'actor': actor, 'detail': detail or {}}
        state['history'].append(item)
        sealed = {'state': state, 'sha256': digest(state)}
        target = self.root / 'checkpoints' / f"{state['generation']:08d}.json"
        # Publish the checkpoint only after its contents are fully durable.
        fd, temporary = tempfile.mkstemp(prefix='.checkpoint-', dir=target.parent)
        try:
            with os.fdopen(fd, 'w') as handle:
                json.dump(sealed, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            if target.exists():
                raise FileExistsError(target)
            os.rename(temporary, target)
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
        pointer = self.root / '.state.tmp'
        pointer.write_text(json.dumps(sealed, ensure_ascii=False, indent=2, allow_nan=False))
        pointer.replace(self.root / 'state.json')
        with (self.root / 'journal.jsonl').open('a') as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())

    def _verify(self, state, deep=True):
        if deep:
            check_ref(state['source'])
        for key in ('project', 'brief', 'transcript', 'plan', 'packed', 'completion'):
            if state.get(key):
                check_ref(state[key])
        if state.get('transcript'):
            from .transcript import load_transcript
            load_transcript(state['transcript']['path'])
        if state.get('plan'):
            validate_plan(read(state['plan']['path']), verify_source=deep)
        for collection in ('feedback', 'reviews', 'deliveries'):
            for item in state[collection]:
                check_ref(item['artifact'])
        if deep:
            for render in state['renders']:
                self._verify_render(render)

    @staticmethod
    def _verify_render(render):
        check_ref(render['plan'])
        check_ref(render['project'])
        if render.get('brief'):
            check_ref(render['brief'])
        for ref in render['files'].values():
            check_ref(ref)
        result = read(render['files']['result']['path'])
        if result.get('technical_status') != 'pass':
            raise ValueError('Render is not technically verified')
        folder = Path(render['path'])
        for name, sha in result.get('artifacts', {}).items():
            file = folder / name
            if not file.is_file() or fingerprint(file)['sha256'] != sha:
                raise ValueError('Rendered evidence changed: ' + name)

    @staticmethod
    def _idle(state):
        if state['operation']:
            raise ValueError('A session operation is in progress; use status/resume')

    def _artifact(self, label, value):
        path = self.root / 'artifacts' / f'{label}-{uuid.uuid4().hex[:12]}.json'
        write(path, value)
        return fingerprint(path)

    def status(self, deep=False):
        state = self._load()
        self._verify(state, deep)
        pending = [item for item in state['feedback'] if item['status'] != 'resolved']
        latest = state['renders'][-1] if state['renders'] else None
        if state['operation']:
            next_action = 'Resume the interrupted operation or wait for its process to finish.'
        elif not state['transcript']:
            next_action = 'Attach a verified transcript or run cloud transcription (OpenAI then Azure).'
        elif not state['plan']:
            next_action = 'Read packed transcript and brief, then propose a story with exact word IDs.'
        elif read(state['plan']['path']).get('status') != 'reviewed_selection':
            next_action = 'Inspect the plan, then explicitly select it with an actor and reason.'
        elif not latest or latest['plan'] != state['plan'] or latest['project'] != state['project']:
            next_action = 'Render the current plan/project; unchanged verified stages can be reused.'
        elif pending:
            next_action = 'Address pending feedback, render the revision and verify its resolution.'
        elif not self._accepted(state, latest):
            next_action = 'Inspect the current render and record content, audio and visual checks.'
        else:
            next_action = 'Create a delivery package and complete its FCP/manual checks as needed.'
        return {'session': str(self.root), 'session_id': state['id'], 'generation': state['generation'],
                'phase': state['phase'], 'brief': state['brief'], 'project': state['project'],
                'transcript': state['transcript'], 'packed': state.get('packed'), 'plan': state['plan'], 'latest_render': latest,
                'pending_feedback': pending, 'next_action': next_action,
                'last_actor': state['last_actor'], 'deep_verified': deep,
                'operation': state['operation'], 'deliveries': state['deliveries']}

    def resume(self, actor='codex'):
        actor_name(actor)
        with self._lock():
            state = self._load()
            self._verify(state)
            op = state['operation']
            if op:
                try:
                    os.kill(op['pid'], 0)
                    running = True
                    if op.get('process_birth'):
                        birth = subprocess.check_output(['ps', '-p', str(op['pid']), '-o', 'lstart='], text=True).strip()
                        running = birth == op['process_birth']
                except (ProcessLookupError, subprocess.CalledProcessError):
                    running = False
                except PermissionError:
                    running = True
                if running:
                    return self.status(deep=True)
                result = Path(op['path']) / 'result.json'
                if op['kind'] == 'render' and result.is_file() and read(result).get('technical_status') == 'pass':
                    self._register_render(state, op)
                    state['phase'] = 'needs_review'
                else:
                    state['phase'] = 'operation_interrupted'
                state['operation'] = None
            self._save(state, 'resumed', actor)
        return self.status(deep=True)

    def _pack(self, state, data):
        from .editorial import pack_transcript
        state['packed'] = self._artifact('packed', pack_transcript(data, read(state['brief']['path'])))

    def _attach(self, state, path):
        from .transcript import load_transcript, save_transcript
        data = load_transcript(path, state['source']['path'])
        folder = self.root / 'artifacts' / ('transcript-' + uuid.uuid4().hex[:12])
        copied = save_transcript(folder, data)
        state['transcript'] = fingerprint(copied)
        state['plan'] = None
        self._pack(state, data)
        state['phase'] = 'needs_plan'

    def attach_transcript(self, path, actor='codex'):
        actor_name(actor)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            self._attach(state, path)
            self._save(state, 'transcript_attached', actor)
        return state['transcript']

    def transcribe(self, actor='codex'):
        """Cloud-only ASR; cached requests survive process interruption before attachment."""
        from .transcription_router import transcribe
        actor_name(actor)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            folder = self.root / 'artifacts' / ('cloud-routing-' + uuid.uuid4().hex[:12])
            path = transcribe(read(state['project']['path']), folder, provider='auto')
            self._attach(state, path)
            routing = fingerprint(folder / 'routing.json') if (folder / 'routing.json').is_file() else None
            self._save(state, 'cloud_transcript_attached', actor, {'routing': routing})
        return state['transcript']

    def correct_transcript(self, changes, actor, note):
        from .transcript_revision import revise_transcript
        actor_name(actor)
        require_note(note)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            if not state['transcript']:
                raise ValueError('Attach a transcript first')
            path = revise_transcript(state['transcript']['path'], self.root / 'artifacts' / ('transcript-' + uuid.uuid4().hex[:12]), changes, actor, note)
            self._attach(state, path)
            self._save(state, 'transcript_corrected', actor, {'note': note})
        return state['transcript']

    def context(self, start=None, end=None, words=False):
        from .feedback import seconds
        state = self._load()
        self._verify(state, deep=False)
        if not state.get('packed'):
            raise ValueError('Attach a transcript first')
        packed = read(state['packed']['path'])
        lo = seconds(start) if start is not None else 0
        hi = seconds(end) if end is not None else packed['duration']
        if hi <= lo or hi > packed['duration'] + 1e-6:
            raise ValueError('Invalid source context interval')
        phrases = [p for p in packed['phrases'] if p['start'] < hi and p['end'] > lo]
        result = {'source': packed['source'], 'brief': packed['brief'], 'duration': packed['duration'],
                  'phrases': phrases, 'warnings': read(state['transcript']['path']).get('warnings', [])}
        if words:
            result['words'] = [w for w in packed['words'] if w['start'] < hi and w['end'] > lo]
        return result

    def set_brief(self, data, actor, note):
        from .editorial import make_brief
        require_note(note)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            value = make_brief(read(state['project']['path']), data)
            state['brief'] = self._artifact('brief', value)
            if state['transcript']:
                self._pack(state, read(state['transcript']['path']))
            state['plan'] = None
            state['phase'] = 'needs_plan' if state['transcript'] else 'needs_transcript'
            self._save(state, 'brief_revised', actor, {'note': note})
        return state['brief']

    def propose(self, spec=None, plan_path=None, actor='codex'):
        from .editorial import build_story_plan
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            if not state['transcript']:
                raise ValueError('Attach a transcript first')
            if plan_path:
                plan = read(plan_path)
                validate_plan(plan, verify_source=True)
                if plan['transcript'] != read(state['transcript']['path']):
                    raise ValueError('Plan does not use this session transcript revision')
                if plan.get('version') == 3 and plan.get('brief') != read(state['brief']['path']):
                    raise ValueError('Plan does not use this session brief')
                plan = deepcopy(plan)
                plan['status'] = 'review_required'
                plan['review'] = None
            else:
                plan = build_story_plan(read(state['project']['path']), read(state['transcript']['path']), read(state['brief']['path']), spec)
            state['plan'] = self._artifact('plan', plan)
            state['phase'] = 'needs_selection'
            self._save(state, 'plan_proposed', actor)
        return state['plan']

    def approve(self, actor, note):
        from .editorial import approve_story
        require_note(note)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            if not state['plan']:
                raise ValueError('Propose a plan first')
            plan = read(state['plan']['path'])
            if plan['version'] == 3:
                updated = approve_story(plan, actor, note)
            else:
                updated = deepcopy(plan)
                updated.update(status='reviewed_selection', review={'actor': actor_name(actor), 'note': note})
            previous = state['plan']
            updated['parent_plan'] = previous
            validate_plan(updated, verify_source=True)
            state['plan'] = self._artifact('plan', updated)
            for feedback in state['feedback']:
                if feedback['status'] == 'addressed' and feedback.get('addressed_by') == previous:
                    feedback['addressed_by'] = state['plan']
            state['phase'] = 'needs_render'
            self._save(state, 'plan_selected', actor, {'note': note})
        return state['plan']

    def revise(self, operations, actor, note, feedback_id=None):
        from .editorial import revise_story, revise_pause_plan
        require_note(note)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            if not state['plan']:
                raise ValueError('No current plan')
            if feedback_id and not any(f['id'] == feedback_id and f['status'] == 'pending' for f in state['feedback']):
                raise ValueError('Select pending feedback')
            plan = read(state['plan']['path'])
            if plan['version'] == 3:
                updated = revise_story(plan, operations, actor, note)
            else:
                updated = revise_pause_plan(plan, operations, actor, note)
            updated['parent_plan'] = state['plan']
            state['plan'] = self._artifact('plan', updated)
            if feedback_id:
                item = next(f for f in state['feedback'] if f['id'] == feedback_id)
                item.update(status='addressed', addressed_by=state['plan'], addressed_project=state['project'])
            state['phase'] = 'needs_selection'
            self._save(state, 'plan_revised', actor, {'note': note, 'feedback_id': feedback_id})
        return state['plan']

    def update_project(self, changes, actor, note):
        from .profiles import resolve
        from .regions import region_filter
        require_note(note)
        allowed = {'input_color', 'white_balance_gains', 'use_case', 'style', 'style_intensity',
                   'adjustments', 'audio', 'review_regions', 'region_corrections', 'render_cache_root'}
        if not isinstance(changes, dict) or set(changes) - allowed:
            raise ValueError('Only color/audio/render project settings can change here')
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            cfg = read(state['project']['path'])
            cfg.update(deepcopy(changes))
            if cfg['input_color'] not in ('apple_log', 'rec709'):
                raise ValueError('Unsupported input color')
            resolve(cfg)
            region_filter(cfg)
            state['project'] = self._artifact('project', cfg)
            state['phase'] = 'needs_render'
            self._save(state, 'project_revised', actor, {'note': note, 'keys': sorted(changes)})
        return state['project']

    def render(self, preview=True, actor='codex'):
        from .editing import render_edit
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            if not state['plan'] or read(state['plan']['path']).get('status') != 'reviewed_selection':
                raise ValueError('Explicitly select the current plan before rendering')
            rid = uuid.uuid4().hex[:12]
            out = self.root / 'renders' / rid
            operation = {'kind': 'render', 'id': rid, 'path': str(out), 'pid': os.getpid(),
                         'preview': preview, 'plan': state['plan'], 'project': state['project'], 'brief': state['brief'], 'started_at': now(),
                         'process_birth': subprocess.check_output(['ps', '-p', str(os.getpid()), '-o', 'lstart='], text=True).strip()}
            state['operation'] = operation
            state['phase'] = 'rendering'
            self._save(state, 'render_started', actor, {'render_id': rid})
        begun = time.monotonic()
        try:
            render_edit(read(operation['project']['path']), read(operation['plan']['path']), out, preview)
        except BaseException as exc:
            with self._lock():
                state = self._load()
                state['operation'] = None
                state['phase'] = 'render_failed'
                self._save(state, 'render_failed', actor, {'render_id': rid, 'error_type': type(exc).__name__})
            raise
        with self._lock():
            state = self._load()
            self._verify(state)
            if not state['operation'] or state['operation']['id'] != rid:
                raise ValueError('Session render changed concurrently')
            operation['elapsed_seconds'] = time.monotonic() - begun
            item = self._register_render(state, operation)
            state['operation'] = None
            state['phase'] = 'needs_review'
            self._save(state, 'render_completed', actor, {'render_id': rid})
        self.review_page(rid)
        return item

    def _register_render(self, state, operation):
        folder = Path(operation['path'])
        files = {label: fingerprint(folder / filename) for label, filename in
                 [('result', 'result.json'), ('video', 'video.mp4'), ('audio', 'audio-only.mp3'),
                  ('mapping', 'frame-mapping.json'), ('plan', 'plan.json'), ('xml', 'timeline.fcpxml'),
                  ('subtitles', 'subtitles.srt'), ('lut', 'look.cube')]}
        item = {key: operation[key] for key in ('id', 'path', 'preview', 'plan', 'project', 'started_at')}
        item.update(files=files, brief=operation.get('brief', state['brief']), elapsed_seconds=operation.get('elapsed_seconds'), registered_at=now())
        self._verify_render(item)
        if item['plan'] != state['plan'] or item['project'] != state['project']:
            raise ValueError('Interrupted render does not match current session inputs')
        state['renders'].append(item)
        return item

    @staticmethod
    def _find_render(state, rid):
        item = next((r for r in state['renders'] if r['id'] == rid), None)
        if item is None:
            raise ValueError('Unknown render ID')
        return item

    def add_feedback(self, rid, start, end, action, note, actor='human', cut_id=None, sequence_id=None, render_sha256=None):
        from .feedback import map_output
        require_note(note)
        if action not in ('comment', 'remove', 'restore', 'retime', 'reorder', 'color', 'audio', 'caption'):
            raise ValueError('Unknown feedback action')
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            render = self._find_render(state, rid)
            self._verify_render(render)
            if render_sha256 is not None and render_sha256 != render['files']['video']['sha256']:
                raise ValueError('Feedback targets a different video revision')
            mapped = map_output(read(render['files']['mapping']['path']), start, end)
            possible_ids = {span['sequence_id'] for span in mapped['source_spans']}
            for boundary in mapped['boundaries']:
                possible_ids.update((boundary['left_sequence_id'], boundary['right_sequence_id']))
            if sequence_id is not None and sequence_id not in possible_ids:
                raise ValueError('Feedback sequence ID does not match the mapped output time')
            if cut_id is not None and cut_id not in {cut['id'] for cut in read(render['files']['plan']['path']).get('cuts', [])}:
                raise ValueError('Feedback cut ID does not belong to this rendered plan')
            value = {'version': 1, 'id': uuid.uuid4().hex[:12], 'render_id': rid,
                     'render_sha256': render['files']['video']['sha256'], 'plan': render['plan'],
                     **mapped, 'action': action, 'note': note, 'actor': actor_name(actor),
                     'cut_id': cut_id, 'sequence_id': sequence_id, 'created_at': now()}
            target = self.root / 'feedback' / (value['id'] + '.json')
            write(target, value)
            item = {'id': value['id'], 'artifact': fingerprint(target), 'status': 'pending'}
            state['feedback'].append(item)
            state['phase'] = 'needs_feedback'
            self._save(state, 'feedback_added', actor, {'feedback_id': value['id'], 'render_id': rid})
        return value

    def address_feedback(self, feedback_id, actor, note):
        require_note(note)
        actor_name(actor)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            item = next((f for f in state['feedback'] if f['id'] == feedback_id), None)
            if not item or item['status'] == 'resolved' or not state['plan']:
                raise ValueError('Select unresolved feedback and a current candidate plan')
            item.update(status='addressed', addressed_by=state['plan'], addressed_project=state['project'],
                        address_actor=actor, address_note=note)
            self._save(state, 'feedback_addressed', actor, {'feedback_id': feedback_id, 'note': note})
        return item

    def dismiss_feedback(self, feedback_id, actor, note):
        require_note(note)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            item = next((f for f in state['feedback'] if f['id'] == feedback_id), None)
            if not item:
                raise ValueError('Unknown feedback ID')
            item.update(status='resolved', resolution='no_change', actor=actor_name(actor), note=note)
            self._save(state, 'feedback_resolved_without_change', actor, {'feedback_id': feedback_id, 'note': note})
        return item

    @staticmethod
    def _accepted(state, render):
        reports = [r for r in state['reviews'] if r['render_id'] == render['id']]
        if not reports:
            return False
        return reports[-1]['passed']

    def review(self, rid, report, actor):
        actor_name(actor)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            render = self._find_render(state, rid)
            self._verify_render(render)
            if report.get('render_sha256') != render['files']['video']['sha256']:
                raise ValueError('Review must name the exact rendered video SHA256')
            entries = report.get('checks')
            if not isinstance(entries, list) or len(entries) != len(CHECKS) or {e.get('id') for e in entries} != set(CHECKS):
                raise ValueError('Review needs each check exactly once: ' + ', '.join(CHECKS))
            for entry in entries:
                require_note(entry.get('note'))
                if entry.get('status') not in ('pass', 'fail', 'pending') or entry.get('basis') not in ('listening', 'visual', 'text', 'signal', 'synthetic'):
                    raise ValueError('Invalid review status or observation basis')
                expected = {'meaning': {'text', 'listening'}, 'pacing': {'listening'},
                            'audio_only': {'listening'}, 'cut_boundaries': {'listening'},
                            'captions': {'text', 'visual'}, 'color': {'visual'}}
                if entry['status'] == 'pass' and entry['basis'] != 'synthetic' and entry['basis'] not in expected[entry['id']]:
                    raise ValueError('Acceptance requires appropriate observation; audio/pacing need listening and color needs visual review')
                if entry['basis'] == 'synthetic' and read(render['project']['path']).get('evidence_kind') != 'synthetic':
                    raise ValueError('Synthetic observations are only for explicitly synthetic fixtures')
            passed = all(e['status'] == 'pass' for e in entries)
            value = {'version': 1, 'render_id': rid, 'actor': actor, 'at': now(), 'report': report,
                     'passed': passed, 'observation_kind': 'declared_review_not_automatic_quality_measurement'}
            path = self.root / 'reviews' / (uuid.uuid4().hex[:12] + '.json')
            write(path, value)
            state['reviews'].append({'render_id': rid, 'artifact': fingerprint(path), 'passed': passed})
            # Resolution is tied to an actual reviewed render of the revised plan, not just a note.
            if passed:
                resolved_ids = report.get('resolved_feedback_ids', [])
                for fid in resolved_ids:
                    item = next((f for f in state['feedback'] if f['id'] == fid), None)
                    if not item or item['status'] != 'addressed' or item.get('addressed_by') != render['plan'] or item.get('addressed_project') != render['project']:
                        raise ValueError('Feedback resolution does not match this revised render')
                    item.update(status='resolved', verified_by=fingerprint(path))
            state['phase'] = 'review_accepted' if passed else 'needs_review'
            self._save(state, 'render_reviewed', actor, {'render_id': rid, 'passed': passed})
        return value

    def inspect(self, rid, start=0, duration=8):
        from .inspection import inspect_render
        state = self._load()
        self._verify(state)
        render = self._find_render(state, rid)
        return inspect_render(render, self.root / 'inspections' / uuid.uuid4().hex[:12], start, duration)

    def evaluate(self):
        from .assessment import assess
        return assess(self)

    def review_page(self, rid):
        state = self._load()
        render = self._find_render(state, rid)
        self._verify_render(render)
        folder = self.root / 'review-pages' / rid
        folder.mkdir(parents=True, exist_ok=True)
        # Static UI downloads a bound feedback file; it never silently writes session decisions.
        media = Path(os.path.relpath(render['files']['video']['path'], folder)).as_posix()
        payload = json.dumps({'render_id': rid, 'render_sha256': render['files']['video']['sha256']})
        page = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>編集の指摘</title>
<style>body{font:16px system-ui;max-width:950px;margin:auto;padding:24px;background:#171717;color:#eee}video{width:100%;max-height:60vh}label{display:block;margin:14px 0}textarea{width:100%;height:80px}button,select,input{font:inherit;padding:8px}a{color:#bdf}</style>
<h1>編集の指摘</h1><p>気になる箇所で動画を止め、指摘を保存してください。</p><video id="video" controls src="MEDIA"></video>
<label>時刻（秒） <input id="time" type="number" min="0" step="0.001"><button id="capture">現在の時刻</button></label>
<label>変更 <select id="action"><option value="comment">コメント</option><option value="remove">削る</option><option value="restore">戻す</option><option value="retime">間を調整</option><option value="color">色</option><option value="audio">音声</option><option value="caption">字幕</option></select></label>
<label>指摘 <textarea id="note"></textarea></label><button id="save">指摘ファイルを保存</button><p id="message"></p>
<script>const binding=BINDING;document.getElementById('capture').onclick=()=>{document.getElementById('time').value=document.getElementById('video').currentTime.toFixed(3)};
document.getElementById('save').onclick=()=>{const time=Number(document.getElementById('time').value),note=document.getElementById('note').value.trim();if(!note||!Number.isFinite(time)||time<0){document.getElementById('message').textContent='時刻と指摘を入力してください';return}const data={...binding,start:time,end:null,action:document.getElementById('action').value,note,actor:'human'};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='feedback-'+binding.render_id+'.json';link.click();URL.revokeObjectURL(url);document.getElementById('message').textContent='指摘を保存しました。編集エージェントにこのファイルを渡してください。'};</script></html>'''
        path = folder / 'index.html'
        path.write_text(page.replace('MEDIA', html.escape(media, quote=True)).replace('BINDING', payload))
        return path

    def handoff(self, actor='codex'):
        state = self.status(deep=True)
        text = [f"Session: {self.root}", f"Phase: {state['phase']}", f"Next: {state['next_action']}",
                f"Brief: {state['brief']['path']}", f"Project: {state['project']['path']}"]
        for key in ('transcript', 'packed', 'plan'):
            if state[key]:
                text.append(f"{key.title()}: {state[key]['path']}")
        for item in state['pending_feedback']:
            text.append(f"Feedback {item['id']} ({item['status']}): {item['artifact']['path']}")
        text += ['Do not repeat transcription if the verified revision exists.',
                 'Actor changes do not turn agent observations into human listening approval.',
                 'Use session resume to verify inputs before continuing.']
        path = self.root / 'handoffs' / (uuid.uuid4().hex[:12] + '.txt')
        path.write_text('\n'.join(text) + '\n')
        with self._lock():
            current = self._load()
            self._save(current, 'handoff_written', actor, {'path': str(path)})
        return path

    def import_fcp(self, xml_path, actor, note):
        from .fcp_import import import_fcpxml
        require_note(note)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            if not state['plan']:
                raise ValueError('A reference plan is required for FCP import')
            xml_path = Path(xml_path).resolve()
            identity = fingerprint(xml_path)
            new_plan, report = import_fcpxml(read(state['plan']['path']), xml_path, actor, note)
            result = self._artifact('fcp-import', report)
            if new_plan is None:
                raise ValueError('Unsupported FCP timeline; reference plan retained. Report: ' + result['path'])
            copy = self.root / 'artifacts' / ('fcp-returned-' + uuid.uuid4().hex[:12] + '.fcpxml')
            shutil.copy2(xml_path, copy)
            if fingerprint(xml_path) != identity or fingerprint(copy)['sha256'] != identity['sha256']:
                raise ValueError('FCPXML changed during import')
            new_plan['parent_plan'] = state['plan']
            new_plan['returned_xml'] = fingerprint(copy)
            state['plan'] = self._artifact('plan', new_plan)
            state['phase'] = 'needs_selection'
            self._save(state, 'fcp_timeline_imported', actor, {'report': result, 'xml': fingerprint(copy)})
        return {'plan': state['plan'], 'report': result}

    def package(self, rid, target='fcp', actor='codex'):
        from .delivery import bundle
        if target not in ('fcp', 'mp4'):
            raise ValueError('Delivery target must be fcp or mp4')
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            render = self._find_render(state, rid)
            if render['plan'] != state['plan'] or render['project'] != state['project']:
                raise ValueError('Delivery requires the current plan and project render')
            did = uuid.uuid4().hex[:12]
            path = bundle(render, state['brief'], target, self.root / 'deliveries' / did,
                          accepted=self._accepted(state, render))
            item = {'id': did, 'render_id': rid, 'artifact': fingerprint(path), 'checks': [], 'target': target}
            state['deliveries'].append(item)
            state['phase'] = 'delivery_pending'
            self._save(state, 'delivery_packaged', actor, {'delivery_id': did})
        return item

    def delivery_check(self, did, check, status, basis, actor, note, evidence=None):
        require_note(note)
        if check not in FCP_CHECKS or status not in ('pass', 'fail', 'pending'):
            raise ValueError('Invalid FCP delivery check')
        if basis not in ('gui', 'playback', 'visual', 'listening', 'synthetic'):
            raise ValueError('Use actual GUI/playback/visual/listening observations')
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            item = next((d for d in state['deliveries'] if d['id'] == did), None)
            if item is None:
                raise ValueError('Unknown delivery ID')
            render = self._find_render(state, item['render_id'])
            if basis == 'synthetic' and read(render['project']['path']).get('evidence_kind') != 'synthetic':
                raise ValueError('Synthetic proof is not a real FCP verification')
            if status == 'pass' and basis != 'synthetic':
                expected = {'fcp_import': {'gui'}, 'fcp_playback': {'playback'},
                            'fcp_grade': {'visual'}, 'fcp_captions': {'visual'}, 'fcp_mix': {'listening'}}
                if basis not in expected[check]:
                    raise ValueError('Observation does not verify this FCP check')
            record = {'delivery_id': did, 'check': check, 'status': status, 'basis': basis,
                      'actor': actor_name(actor), 'note': note, 'at': now(),
                      'evidence': fingerprint(evidence) if evidence else None,
                      'render_sha256': render['files']['video']['sha256']}
            ref = self._artifact('delivery-check', record)
            item['checks'].append({'check': check, 'status': status, 'artifact': ref})
            self._save(state, 'delivery_checked', actor, {'delivery_id': did, 'check': check, 'status': status})
        return record

    def finish(self, did, actor='codex'):
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            delivery = next((d for d in state['deliveries'] if d['id'] == did), None)
            if not delivery:
                raise ValueError('Unknown delivery ID')
            render = self._find_render(state, delivery['render_id'])
            if render['preview'] or render['plan'] != state['plan'] or render['project'] != state['project']:
                raise ValueError('Finish requires a full-resolution render of the current inputs')
            if not self._accepted(state, render):
                raise ValueError('Finish requires a passing review bound to this final render')
            if any(f['status'] != 'resolved' for f in state['feedback']):
                raise ValueError('Feedback remains unresolved')
            manifest = read(delivery['artifact']['path'])
            for ref in manifest['files'].values():
                check_ref(ref)
            latest = {}
            for item in delivery['checks']:
                check_ref(item['artifact'])
                observation = read(item['artifact']['path'])
                if observation.get('evidence'):
                    check_ref(observation['evidence'])
                latest[item['check']] = item['status']
            pending = [key for key in manifest['manual_checks_required'] if latest.get(key) != 'pass']
            if pending:
                raise ValueError('Delivery checks remain: ' + ', '.join(pending))
            synthetic = read(render['project']['path']).get('evidence_kind') == 'synthetic'
            result = {'session_id': state['id'], 'delivery_id': did, 'render_id': render['id'],
                      'status': 'synthetic_complete' if synthetic else 'complete', 'at': now(),
                      'actor': actor_name(actor), 'delivery': delivery['artifact'], 'checks': latest,
                      'creative_review': [r for r in state['reviews'] if r['render_id'] == render['id']][-1]['artifact']}
            artifact = self._artifact('completion', result)
            state['phase'] = result['status']
            state['completion'] = artifact
            self._save(state, 'finished', actor, {'completion': artifact})
        return result
