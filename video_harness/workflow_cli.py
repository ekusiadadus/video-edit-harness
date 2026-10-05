"""Durable editing-session commands shared by Codex and Claude Code."""

import argparse
import json
from pathlib import Path

from .session import ACTORS, Session


def _json(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, (dict, list)):
        raise ValueError('Expected a JSON object or array: ' + str(path))
    return value


def _object(path):
    value = _json(path)
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object: ' + str(path))
    return value


def _array(path):
    value = _json(path)
    if not isinstance(value, list):
        raise ValueError('Expected a JSON array: ' + str(path))
    return value


def parser():
    p = argparse.ArgumentParser(prog='video-harness session',
                                description='Durable transcript-backed editing session')
    sub = p.add_subparsers(dest='action', required=True)

    def command(name, *, actor='codex', note=False):
        cmd = sub.add_parser(name)
        cmd.add_argument('session', type=Path)
        if actor is not None:
            cmd.add_argument('--actor', choices=ACTORS, default=actor)
        if note:
            cmd.add_argument('--note', required=True)
        return cmd

    a = sub.add_parser('start')
    a.add_argument('project', type=Path)
    a.add_argument('session', type=Path)
    a.add_argument('--brief-file', type=Path, help='JSON object with audience, goals, must-keep IDs and target duration')
    a.add_argument('--actor', choices=ACTORS, default='codex')
    a = command('status', actor=None)
    a.add_argument('--deep', action='store_true', help='Verify source and render artifacts')
    command('resume')
    a = command('context', actor=None)
    a.add_argument('--start', type=float, help='First source second to include')
    a.add_argument('--end', type=float, help='Last source second to include')
    a.add_argument('--words', action='store_true', help='Include exact timed word IDs')
    command('transcribe')
    a = command('cloud-policy', note=True)
    a.add_argument('policy', choices=('allow', 'deny'))
    a.add_argument('--providers', nargs='*', choices=('openai', 'azure'), default=[])
    a = command('transcript')
    a.add_argument('transcript', type=Path, help='Sealed transcript.json from cloud transcription')
    a = command('correct-transcript', note=True)
    a.add_argument('--changes-file', type=Path, required=True, help='JSON array of {word_id,text}')
    a = command('brief', note=True)
    a.add_argument('--data-file', type=Path, required=True, help='Brief input JSON object')
    a = command('plan')
    source = a.add_mutually_exclusive_group(required=True)
    source.add_argument('--spec-file', type=Path, help='Story spec JSON object')
    source.add_argument('--plan-file', type=Path, help='Existing v2/v3 plan JSON')
    command('approve', note=True)
    a = command('revise', note=True)
    a.add_argument('--operations-file', type=Path, required=True, help='JSON array of span operations')
    a.add_argument('--feedback-id')
    a = command('project', note=True)
    a.add_argument('--changes-file', type=Path, required=True, help='Color/audio/render settings JSON object')
    a = command('render')
    a.add_argument('--full', action='store_true', help='Render full resolution; default is preview')
    a = command('feedback', actor='human')
    a.add_argument('render_id', nargs='?')
    a.add_argument('--data-file', type=Path, help='Review-page feedback JSON with render ID and video hash')
    a.add_argument('--start', help='Seconds, MM:SS, or HH:MM:SS')
    a.add_argument('--end', help='End time; defaults to start')
    a.add_argument('--action', dest='feedback_action', choices=('comment', 'remove', 'restore', 'retime', 'reorder', 'color', 'audio', 'caption'))
    a.add_argument('--note')
    a.add_argument('--cut-id', type=int)
    a.add_argument('--sequence-id')
    a.add_argument('--render-sha256')
    a = command('dismiss-feedback', note=True)
    a.add_argument('feedback_id')
    a = command('address-feedback', note=True)
    a.add_argument('feedback_id')
    a = command('review')
    a.add_argument('render_id')
    a.add_argument('--data-file', type=Path, required=True, help='JSON report with render_sha256 and six checks')
    a = command('register-vertical')
    a.add_argument('render_id')
    a.add_argument('result', type=Path, help='result.json from a portrait export of this render')
    a = command('review-vertical', actor='human')
    a.add_argument('derivative_id')
    a.add_argument('--data-file', type=Path, required=True, help='JSON checks bound to portrait video_sha256')
    a = command('audition-junctions', actor=None)
    a.add_argument('render_id')
    a.add_argument('--offset', type=int, default=0)
    a.add_argument('--limit', type=int, default=24)
    a.add_argument('--ids', nargs='*')
    a = command('review-page', actor=None)
    a.add_argument('render_id')
    a = command('inspect', actor=None)
    a.add_argument('render_id')
    a.add_argument('--start', type=float, default=0)
    a.add_argument('--duration', type=float, default=8)
    command('evaluate', actor=None)
    a = sub.add_parser('compare', help='Compare operational evidence for same source and brief')
    a.add_argument('sessions', nargs='+', type=Path)
    command('handoff')
    a = command('import-fcp', note=True)
    a.add_argument('xml', type=Path)
    a = command('package')
    a.add_argument('render_id')
    a.add_argument('--target', choices=('fcp', 'mp4'), default='fcp')
    a.add_argument('--derivative-id', help='Include a separately reviewed portrait derivative')
    a = command('delivery-check', note=True)
    a.add_argument('delivery_id')
    a.add_argument('check', choices=('fcp_import', 'fcp_playback', 'fcp_grade', 'fcp_captions', 'fcp_mix'))
    a.add_argument('status', choices=('pass', 'fail', 'pending'))
    a.add_argument('basis', choices=('gui', 'playback', 'visual', 'listening', 'synthetic'))
    a.add_argument('--evidence', type=Path)
    a = command('finish')
    a.add_argument('delivery_id')
    return p


def _feedback(session, args):
    if args.data_file:
        data = _object(args.data_file)
        rid = args.render_id or data.get('render_id')
        if args.render_id and data.get('render_id') and args.render_id != data['render_id']:
            raise ValueError('Feedback file and argument name different renders')
        if not rid or not data.get('render_sha256'):
            raise ValueError('Feedback file needs a render ID and exact video SHA256')
        return session.add_feedback(rid, data.get('start'), data.get('end'),
                                    data.get('action'), data.get('note'),
                                    data.get('actor', args.actor), data.get('cut_id'),
                                    data.get('sequence_id'), data.get('render_sha256'))
    if not all((args.render_id, args.start is not None, args.feedback_action, args.note)):
        raise ValueError('Explicit feedback needs render ID, --start, --action and --note')
    return session.add_feedback(args.render_id, args.start, args.end, args.feedback_action,
                                args.note, args.actor, args.cut_id, args.sequence_id,
                                args.render_sha256)


def dispatch(args):
    if args.action == 'start':
        session = Session.start(args.project, args.session,
                                _object(args.brief_file) if args.brief_file else None,
                                actor=args.actor)
        return session.status(deep=True)
    if args.action == 'compare':
        from .assessment import compare
        return compare([Session(folder) for folder in args.sessions])
    session = Session(args.session)
    action = args.action
    if action == 'status': return session.status(deep=args.deep)
    if action == 'resume': return session.resume(actor=args.actor)
    if action == 'context': return session.context(args.start, args.end, args.words)
    if action == 'transcribe': return session.transcribe(actor=args.actor)
    if action == 'cloud-policy': return session.set_cloud_policy(args.policy, args.actor, args.note, args.providers)
    if action == 'transcript': return session.attach_transcript(args.transcript, actor=args.actor)
    if action == 'correct-transcript': return session.correct_transcript(_array(args.changes_file), args.actor, args.note)
    if action == 'brief': return session.set_brief(_object(args.data_file), args.actor, args.note)
    if action == 'plan': return session.propose(spec=_object(args.spec_file) if args.spec_file else None,
                                                 plan_path=args.plan_file, actor=args.actor)
    if action == 'approve': return session.approve(args.actor, args.note)
    if action == 'revise': return session.revise(_array(args.operations_file), args.actor, args.note, args.feedback_id)
    if action == 'project': return session.update_project(_object(args.changes_file), args.actor, args.note)
    if action == 'render': return session.render(preview=not args.full, actor=args.actor)
    if action == 'feedback': return _feedback(session, args)
    if action == 'dismiss-feedback': return session.dismiss_feedback(args.feedback_id, args.actor, args.note)
    if action == 'address-feedback': return session.address_feedback(args.feedback_id, args.actor, args.note)
    if action == 'review': return session.review(args.render_id, _object(args.data_file), args.actor)
    if action == 'register-vertical': return session.register_derivative(args.render_id, args.result, args.actor)
    if action == 'review-vertical': return session.review_derivative(args.derivative_id, _object(args.data_file), args.actor)
    if action == 'audition-junctions': return session.audition_junctions(args.render_id, args.offset, args.limit, args.ids)
    if action == 'review-page': return session.review_page(args.render_id)
    if action == 'inspect': return session.inspect(args.render_id, args.start, args.duration)
    if action == 'evaluate': return session.evaluate()
    if action == 'handoff': return session.handoff(actor=args.actor)
    if action == 'import-fcp': return session.import_fcp(args.xml, args.actor, args.note)
    if action == 'package': return session.package(args.render_id, args.target, args.actor, args.derivative_id)
    if action == 'delivery-check': return session.delivery_check(args.delivery_id, args.check,
                                                                   args.status, args.basis, args.actor,
                                                                   args.note, args.evidence)
    if action == 'finish': return session.finish(args.delivery_id, actor=args.actor)
    raise ValueError('Unknown session command')


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        result = dispatch(args)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    except (ValueError, FileNotFoundError, FileExistsError, KeyError, TypeError) as error:
        p.exit(2, f'Error: {error}\n')
