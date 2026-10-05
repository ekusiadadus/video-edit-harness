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


def validate_junction_coverage(coverage, render_sha256, junction_ids):
    if not isinstance(coverage, dict) or coverage.get('render_sha256') != render_sha256:
        raise ValueError('Boundary review needs coverage bound to this exact render')
    require_note(coverage.get('note'))
    mode = coverage.get('mode')
    if mode == 'full_listening':
        if coverage.get('reviewed_ids') or coverage.get('waived'):
            raise ValueError('Full listening uses one declaration without junction selections')
    elif mode == 'selected':
        reviewed = coverage.get('reviewed_ids', [])
        waived = coverage.get('waived', [])
        if not isinstance(reviewed, list) or not isinstance(waived, list) or not all(isinstance(w, dict) for w in waived):
            raise ValueError('Invalid selected junction coverage')
        waived_ids = [w.get('id') for w in waived]
        if junction_ids and not reviewed:
            raise ValueError('A passing boundary review must include at least one listened junction')
        for waiver in waived:
            require_note(waiver.get('reason'))
        if (len(set(reviewed)) != len(reviewed) or len(set(waived_ids)) != len(waived_ids)
                or set(reviewed) & set(waived_ids) or set(reviewed) | set(waived_ids) != set(junction_ids)):
            raise ValueError('Junction coverage must account for every selected cut or explicit waiver')
    else:
        raise ValueError('Junction coverage mode must be full_listening or selected')


def process_birth(pid):
    """Best-effort process identity; some sandboxes forbid invoking ps."""
    try:
        return subprocess.check_output(['ps', '-p', str(pid), '-o', 'lstart='], text=True).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def operation_liveness(operation):
    """Only a missing PID or a proven birth mismatch makes an operation stale."""
    try:
        os.kill(operation['pid'], 0)
    except ProcessLookupError:
        return 'stale'
    except OSError:
        return 'unknown'
    expected = operation.get('process_birth')
    if not expected:
        return 'unknown'
    actual = process_birth(operation['pid'])
    if actual is None:
        return 'unknown'
    return 'active' if actual == expected else 'stale'


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
        brief = make_brief(cfg, brief_data or {})
        source = fingerprint(cfg['source'])
        inherited_permission = cfg.get('cloud_permission')
        if inherited_permission is not None:
            if (not isinstance(inherited_permission, dict) or inherited_permission.get('source_sha256') != source['sha256']
                    or inherited_permission.get('policy') not in ('allow', 'deny')
                    or not isinstance(inherited_permission.get('providers'), list)
                    or not isinstance(inherited_permission.get('basis'), str)
                    or not inherited_permission['basis'].strip()):
                raise ValueError('Project cloud permission does not match this source')
            if inherited_permission['policy'] == 'deny' and inherited_permission['providers']:
                raise ValueError('Denied cloud permission cannot list providers')
            if inherited_permission['policy'] == 'allow' and (not inherited_permission['providers']
                    or set(inherited_permission['providers']) - {'openai', 'azure'}):
                raise ValueError('Invalid project cloud providers')
        folder = Path(folder).resolve()
        folder.mkdir(parents=True, exist_ok=False)
        (folder / 'checkpoints').mkdir()
        for name in ('artifacts', 'renders', 'reviews', 'feedback', 'deliveries', 'handoffs'):
            (folder / name).mkdir()
        write(folder / 'artifacts/project-0000.json', cfg)
        write(folder / 'artifacts/brief-0000.json', brief)
        session = cls(folder)
        state = {'version': 1, 'id': uuid.uuid4().hex, 'created_at': now(), 'generation': 0,
                 'phase': 'needs_transcript', 'source': source,
                 'project': fingerprint(folder / 'artifacts/project-0000.json'),
                 'brief': fingerprint(folder / 'artifacts/brief-0000.json'), 'transcript': None,
                 'plan': None, 'renders': [], 'feedback': [], 'reviews': [], 'deliveries': [],
                 'derivatives': [], 'cloud_permission': deepcopy(inherited_permission),
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
        for item in state.get('derivatives', []):
            check_ref(item['result'])
            check_ref(item['video'])
            if item.get('technical_verification'):
                check_ref(item['technical_verification'])
            for key in ('subtitles_source', 'font_source'):
                if item.get(key) and item[key].get('path'):
                    check_ref(item[key])
            result = read(item['result']['path'])
            if result.get('video') != item['video'] or result.get('framing') != item['framing']:
                raise ValueError('Portrait export evidence changed')
            for review in item['reviews']:
                check_ref(review['artifact'])
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
            next_action = ('Process identity is unavailable; wait for the owner to finish or retry resume after its PID exits.'
                           if not state['operation'].get('process_birth') else
                           'Resume the interrupted operation or wait for its process to finish.')
        elif not state['transcript']:
            permission = state.get('cloud_permission') or {}
            next_action = ('Attach a verified transcript; cloud transcription is denied for this source.'
                           if permission.get('policy') == 'deny' else
                           'Attach a verified transcript or record source-bound cloud permission before transcription.')
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
                'operation': state['operation'], 'deliveries': state['deliveries'],
                'derivatives': state.get('derivatives', []), 'cloud_permission': state.get('cloud_permission')}

    def resume(self, actor='codex'):
        actor_name(actor)
        with self._lock():
            state = self._load()
            self._verify(state)
            op = state['operation']
            if op:
                liveness = operation_liveness(op)
                if liveness != 'stale':
                    result = self.status(deep=True)
                    result['operation_liveness'] = liveness
                    if liveness == 'unknown':
                        result['next_action'] = 'Operation owner identity is unavailable; do not recover it until its PID is confirmed gone.'
                    return result
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
            cfg = read(state['project']['path'])
            cfg['cloud_permission'] = state.get('cloud_permission')
            path = transcribe(cfg, folder, provider='auto')
            self._attach(state, path)
            routing = fingerprint(folder / 'routing.json') if (folder / 'routing.json').is_file() else None
            self._save(state, 'cloud_transcript_attached', actor, {'routing': routing})
        return state['transcript']

    def set_cloud_policy(self, policy, actor, note, providers=()):
        """Persist a decision for this exact source before any cloud transcription."""
        actor_name(actor)
        require_note(note)
        if policy not in ('allow', 'deny'):
            raise ValueError('Cloud policy must be allow or deny')
        providers = list(providers)
        if policy == 'allow' and (not providers or len(set(providers)) != len(providers)
                                  or set(providers) - {'openai', 'azure'}):
            raise ValueError('Allow policy needs explicit OpenAI/Azure providers')
        if policy == 'deny' and providers:
            raise ValueError('Deny policy cannot name providers')
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            value = {'source_sha256': state['source']['sha256'], 'policy': policy,
                     'providers': providers, 'basis': note.strip(), 'actor': actor, 'at': now()}
            state['cloud_permission'] = value
            self._save(state, 'cloud_policy_set', actor, {'policy': policy, 'providers': providers})
        return value

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
                         'process_birth': process_birth(os.getpid())}
            operation['process_identity_status'] = 'known' if operation['process_birth'] else 'unknown'
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
            plan = read(render['files']['plan']['path'])
            junction_ids = ([item['id'] for item in plan['sequence'][:-1]] if plan.get('version') == 3
                            else [item['id'] for item in plan['cuts']])
            boundary_pass = next(e for e in entries if e['id'] == 'cut_boundaries')['status'] == 'pass'
            coverage = report.get('junction_coverage')
            if boundary_pass and (len(junction_ids) > 24 or coverage is not None):
                validate_junction_coverage(coverage, render['files']['video']['sha256'], junction_ids)
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

    def register_derivative(self, rid, result_path, actor='codex'):
        """Attach an existing portrait export to the exact primary render."""
        actor_name(actor)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            render = self._find_render(state, rid)
            self._verify_render(render)
            result_path = Path(result_path).resolve()
            result = read(result_path)
            if result.get('technical_status') != 'pass' or result.get('source') != render['files']['video']:
                raise ValueError('Portrait result must be a passed export of this exact render')
            video = result.get('video')
            if not isinstance(video, dict) or fingerprint(video['path']) != video:
                raise ValueError('Portrait output changed')
            technical_verification = None
            if read(render['project']['path']).get('evidence_kind') != 'synthetic':
                from .common import probe
                from .media import stream_bounds, verify
                source_media = probe(render['files']['video']['path'])
                source_range = stream_bounds(source_media, 'video')
                if abs(float(result['duration']) - (source_range[1] - source_range[0])) > .05:
                    raise ValueError('Portrait duration does not match the source render')
                check_folder = self.root / 'artifacts' / ('portrait-check-' + uuid.uuid4().hex[:12])
                media = verify(video['path'], check_folder, expected_duration=source_range[1] - source_range[0],
                               require_audio=True, expected_audio_range=stream_bounds(source_media, 'audio'))
                stream = next((s for s in media['streams'] if s['codec_type'] == 'video'), None)
                if (stream is None or (stream.get('width'), stream.get('height'), stream.get('sample_aspect_ratio')) != (1080, 1920, '1:1')
                        or abs(stream_bounds(media, 'video')[0]) > .05):
                    raise ValueError('Portrait result does not match verified 1080x1920 Rec.709 media')
                technical_verification = fingerprint(check_folder / 'verification.json')
            for key in ('subtitles_source', 'font_source'):
                if result.get(key) and result[key].get('path'):
                    check_ref(result[key])
            value = {'id': uuid.uuid4().hex[:12], 'render_id': rid, 'render_sha256': render['files']['video']['sha256'],
                     'plan': render['plan'], 'project': render['project'], 'result': fingerprint(result_path),
                     'video': video, 'framing': result['framing'], 'subtitles_source': result.get('subtitles_source'),
                     'font_source': result.get('font_source'), 'technical_verification': technical_verification,
                     'reviews': []}
            state.setdefault('derivatives', []).append(value)
            self._save(state, 'derivative_registered', actor, {'derivative_id': value['id'], 'render_id': rid})
        return value

    def review_derivative(self, derivative_id, report, actor='human'):
        actor_name(actor)
        with self._lock():
            state = self._load()
            self._idle(state)
            self._verify(state)
            item = next((d for d in state.get('derivatives', []) if d['id'] == derivative_id), None)
            if item is None:
                raise ValueError('Unknown derivative ID')
            check_ref(item['result'])
            check_ref(item['video'])
            if report.get('video_sha256') != item['video']['sha256']:
                raise ValueError('Portrait review must name the exact video SHA256')
            expected = {'framing': {'visual'}, 'captions': {'visual', 'text'},
                        'audio': {'listening'}, 'playback': {'playback'}}
            checks = report.get('checks')
            if not isinstance(checks, list) or len(checks) != len(expected) or {c.get('id') for c in checks} != set(expected):
                raise ValueError('Portrait review needs framing, captions, audio and playback checks')
            synthetic = read(self._find_render(state, item['render_id'])['project']['path']).get('evidence_kind') == 'synthetic'
            for check in checks:
                require_note(check.get('note'))
                if check.get('status') not in ('pass', 'fail', 'pending') or check.get('basis') not in expected[check['id']] | {'synthetic'}:
                    raise ValueError('Invalid portrait review basis or status')
                if check['basis'] == 'synthetic' and not synthetic:
                    raise ValueError('Synthetic proof is only for a synthetic fixture')
            value = {'version': 1, 'derivative_id': derivative_id, 'video_sha256': item['video']['sha256'],
                     'actor': actor, 'at': now(), 'checks': checks,
                     'passed': all(c['status'] == 'pass' for c in checks)}
            ref = self._artifact('derivative-review', value)
            item['reviews'].append({'artifact': ref, 'passed': value['passed']})
            self._save(state, 'derivative_reviewed', actor, {'derivative_id': derivative_id, 'passed': value['passed']})
        return value

    def inspect(self, rid, start=0, duration=8):
        from .inspection import inspect_render
        state = self._load()
        self._verify(state)
        render = self._find_render(state, rid)
        return inspect_render(render, self.root / 'inspections' / uuid.uuid4().hex[:12], start, duration)

    def audition_junctions(self, rid, offset=0, limit=24, ids=None):
        from .editing import audition
        state = self._load()
        self._verify(state)
        render = self._find_render(state, rid)
        folder = self.root / 'auditions' / rid / uuid.uuid4().hex[:12]
        plan = read(render['files']['plan']['path'])
        if ids is not None:
            available = ([item['id'] for item in plan['sequence'][:-1]] if plan.get('version') == 3
                         else [item['id'] for item in plan['cuts']])
            mapping = {str(identifier): identifier for identifier in available}
            if any(str(identifier) not in mapping for identifier in ids):
                raise ValueError('Unknown junction ID')
            ids = [mapping[str(identifier)] for identifier in ids]
        audition(read(render['project']['path']), plan, folder,
                 cut_ids=ids, offset=offset, limit=limit)
        return read(folder / 'junctions.json')

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
                 'Cloud policy: ' + json.dumps(state.get('cloud_permission'), ensure_ascii=False),
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

    def package(self, rid, target='fcp', actor='codex', derivative_id=None):
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
            derivative = None
            if derivative_id is not None:
                derivative = next((d for d in state.get('derivatives', []) if d['id'] == derivative_id), None)
                if derivative is None or derivative['render_id'] != rid or derivative['render_sha256'] != render['files']['video']['sha256']:
                    raise ValueError('Portrait derivative does not belong to this exact render')
                if not derivative['reviews'] or not derivative['reviews'][-1]['passed']:
                    raise ValueError('Portrait derivative needs a passing exact-video review')
                check_ref(derivative['video'])
                check_ref(derivative['result'])
            did = uuid.uuid4().hex[:12]
            path = bundle(render, state['brief'], target, self.root / 'deliveries' / did,
                          accepted=self._accepted(state, render), derivative=derivative)
            item = {'id': did, 'render_id': rid, 'artifact': fingerprint(path), 'checks': [],
                    'target': target, 'derivative_id': derivative_id}
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
            derivative = None
            if delivery.get('derivative_id'):
                derivative = next((d for d in state.get('derivatives', []) if d['id'] == delivery['derivative_id']), None)
                if derivative is None or derivative['render_id'] != render['id'] or not derivative['reviews'] or not derivative['reviews'][-1]['passed']:
                    raise ValueError('Selected portrait review is missing or no longer passing')
                check_ref(derivative['video'])
                if manifest.get('portrait', {}).get('video_sha256') != derivative['video']['sha256']:
                    raise ValueError('Selected portrait differs from delivery')
            synthetic = read(render['project']['path']).get('evidence_kind') == 'synthetic'
            result = {'session_id': state['id'], 'delivery_id': did, 'render_id': render['id'],
                      'status': 'synthetic_complete' if synthetic else 'complete', 'at': now(),
                      'actor': actor_name(actor), 'delivery': delivery['artifact'], 'checks': latest,
                      'creative_review': [r for r in state['reviews'] if r['render_id'] == render['id']][-1]['artifact']}
            folder = Path(delivery['artifact']['path']).parent
            proof_dir = folder / 'evidence'
            proof_dir.mkdir(exist_ok=True)
            proof_refs = {'creative_review': result['creative_review'], 'project': render['project']}
            if derivative:
                proof_refs['portrait_review'] = derivative['reviews'][-1]['artifact']
            for check in delivery['checks']:
                proof_refs['delivery_check_' + check['check']] = check['artifact']
            proof_files = {}
            for label, ref in proof_refs.items():
                check_ref(ref)
                copied = proof_dir / (label + '.json')
                if copied.exists():
                    if fingerprint(copied)['sha256'] != ref['sha256']:
                        raise ValueError('Existing delivery proof changed: ' + label)
                else:
                    shutil.copy2(ref['path'], copied)
                if fingerprint(copied)['sha256'] != ref['sha256']:
                    raise ValueError('Delivery proof changed during copy')
                proof_files[label] = str(copied.relative_to(folder))
            portable = {'version': 1, 'status': result['status'], 'session_id': state['id'],
                        'delivery_id': did, 'render_id': render['id'], 'render_sha256': render['files']['video']['sha256'],
                        'portrait_video_sha256': derivative['video']['sha256'] if derivative else None,
                        'portrait': manifest.get('portrait'),
                        'checks': latest, 'manual_checks_remaining': [], 'evidence': proof_files,
                        'at': result['at'], 'files': []}
            for file in sorted(folder.rglob('*')):
                if file.is_file() and file.name != 'completion.json':
                    identity = fingerprint(file)
                    portable['files'].append({'path': str(file.relative_to(folder)), 'sha256': identity['sha256'],
                                              'bytes': identity['bytes']})
            completion_path = folder / 'completion.json'
            if completion_path.exists():
                from .delivery import verify_completion
                prior = verify_completion(folder)
                if (prior['delivery_id'] != did or prior['render_sha256'] != render['files']['video']['sha256']
                        or prior['portrait_video_sha256'] != portable['portrait_video_sha256']):
                    raise ValueError('Existing portable completion does not match this delivery')
            else:
                write(completion_path, portable)
            result['portable_completion'] = fingerprint(completion_path)
            artifact = self._artifact('completion', result)
            state['phase'] = result['status']
            state['completion'] = artifact
            self._save(state, 'finished', actor, {'completion': artifact})
        return result
