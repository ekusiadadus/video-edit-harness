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
    a = command('visual-plan')
    a.add_argument('--plan-file', type=Path, required=True, help='Frame-grounded v4 visual EDL JSON')
    a = command('propose-beats', note=True)
    a.add_argument('render_id')
    a.add_argument('--spec-file', type=Path, required=True, help='Exact music beat map and nonspoken allowed intervals')
    command('approve', note=True)
    a = command('revise', note=True)
    a.add_argument('--operations-file', type=Path, required=True, help='JSON array of span operations')
    a.add_argument('--feedback-id')
    a = command('project', note=True)
    a.add_argument('--changes-file', type=Path, required=True, help='Color/audio/render settings JSON object')
    a = command('render')
    a.add_argument('--full', action='store_true', help='Render full resolution; default is preview')
    a.add_argument('--candidate-id', help='Render an immutable comparison candidate')
    a = command('candidate', note=True)
    a.add_argument('--changes-file', type=Path, required=True)
    a = command('select-comparison', note=True)
    a.add_argument('--data-file', type=Path, required=True, help='Downloaded exact-render comparison selection proposal')
    a = command('effects', note=True)
    a.add_argument('render_id')
    a.add_argument('--operations-file', type=Path, required=True, help='Add, update or remove local effects on this render')
    a = command('motion-template', note=True)
    a.add_argument('render_id')
    a.add_argument('--request-file', type=Path, required=True, help='Versioned compound local-effect recipe; remains unadopted')
    a = command('depth-layer', note=True)
    a.add_argument('render_id')
    a.add_argument('--manifest', type=Path, required=True, help='Validated field manifest bound to retained visual-graded.mp4')
    a.add_argument('--asset-id', required=True, help='Registered same-canvas RGBA image asset')
    a.add_argument('--threshold', type=float, default=.5)
    a.add_argument('--softness', type=float, default=.1)
    a.add_argument('--strength', type=float, default=1)
    a = command('audio-cuts', note=True)
    a.add_argument('render_id')
    a.add_argument('--request-file', type=Path, required=True, help='Observed source-bound J/L audio handles')
    a=command('transitions',note=True)
    a.add_argument('render_id')
    a.add_argument('--request-file',type=Path,required=True,help='Explicit adjacent dissolve/push events and source-handle windows')
    a=command('motion-cuts',note=True)
    a.add_argument('render_id')
    a.add_argument('--request-file',type=Path,required=True,help='Observed endpoint choices, subject ROIs and nonspoken source intervals')
    a=command('tracking-source',actor=None)
    a.add_argument('render_id')
    a=command('retime-source',actor=None)
    a.add_argument('render_id')
    a=command('caption-source',actor=None)
    a.add_argument('render_id')
    a=command('caption-groups',note=True)
    a.add_argument('render_id')
    a.add_argument('--spec-file',type=Path,required=True,
                   help='Exact word-occurrence groups, language, protected phrases and reading thresholds')
    a=command('retime',note=True)
    a.add_argument('render_id')
    a.add_argument('--request-file',type=Path,required=True)
    a.add_argument('--timeline-settings', choices=['migrate', 'clear'], default='migrate',
                   help='Migrate compatible visual settings; clear explicitly removes old timeline settings')
    a=command('track-effect',note=True)
    a.add_argument('render_id')
    a.add_argument('--box',type=float,nargs=4,required=True)
    a.add_argument('--first-frame',type=int,required=True)
    a.add_argument('--end-frame',type=int,required=True)
    a.add_argument('--algorithm',choices=['lk','csrt','pose'],default='csrt')
    a.add_argument('--model',type=Path)
    a.add_argument('--effect',choices=['tracked_zoom','tracked_title','tracked_background'],default='tracked_zoom')
    a.add_argument('--background-parameters-file',type=Path,help='Background dim, saturation and feather JSON')
    a.add_argument('--mask-corrections-file',type=Path,help='Absolute output frame numbers to full-size binary PNG paths')
    a.add_argument('--mask-backend',choices=['grabcut','pose'],default='grabcut',
                   help='Optional pose masks require --algorithm pose and --model')
    a.add_argument('--mask-threshold',type=float,default=.5,help='Pose-mask foreground probability threshold')
    a.add_argument('--title-parameters-file',type=Path,help='Label text, placement and readable style JSON')
    a.add_argument('--title-version',type=int,choices=[1,2],default=1,
                   help='1: explicit lines; 2: measured Japanese/English wrapping (text-layout extra)')
    a.add_argument('--max-scale',type=float,default=1.12)
    a.add_argument('--strength',type=float,default=.65)
    a.add_argument('--corrections-file',type=Path)
    a = command('direction', note=True)
    a.add_argument('--request-file', type=Path, required=True, help='Structured explicit editing direction')
    a.add_argument('--preference', type=Path, help='Explicitly saved immutable preference')
    a.add_argument('--trend-profile', type=Path, help='Dated platform/purpose-matching trend JSON')
    a = command('adopt-candidate', note=True)
    a.add_argument('candidate_id')
    a = command('compare-candidates', actor=None)
    a.add_argument('--mode', choices=['effects','timing','structure'], default='effects',
                   help='effects: same mapping; timing: same cuts; structure: different plans with independent full playback')
    a.add_argument('render_ids', nargs='+')
    a = command('native-finish', note=True)
    a.add_argument('render_id')
    a.add_argument('--request-file', type=Path, required=True, help='TikTok-native music/effect references and timing')
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
    a = command('preview-effects', actor=None)
    a.add_argument('render_id')
    a.add_argument('--effect-ids', nargs='+', help='Changed effect ids; default: all changed effects')
    a.add_argument('--context-frames', type=int, default=8)
    a = command('preview-changes', actor=None)
    a.add_argument('candidate_id')
    a.add_argument('--effect-ids', nargs='+', help='Changed effect ids; default: all changed effects')
    a.add_argument('--context-frames', type=int, default=8)
    command('evaluate', actor=None)
    a = sub.add_parser('compare', help='Compare operational evidence for same source and brief')
    a.add_argument('sessions', nargs='+', type=Path)
    command('handoff')
    a = command('import-fcp', note=True)
    a.add_argument('xml', type=Path)
    a = command('import-production-fcp', note=True)
    a.add_argument('render_id')
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
    if action == 'visual-plan': return session.propose_visual(_object(args.plan_file), args.actor)
    if action == 'propose-beats': return session.propose_beats(args.render_id, _object(args.spec_file), args.actor, args.note)
    if action == 'render': return session.render(preview=not args.full, actor=args.actor, candidate_id=args.candidate_id)
    if action == 'candidate': return session.create_candidate(_object(args.changes_file), args.actor, args.note)
    if action == 'select-comparison': return session.candidate_from_selection(_object(args.data_file), args.actor, args.note)
    if action == 'effects': return session.propose_effects(args.render_id, _array(args.operations_file), args.actor, args.note)
    if action == 'motion-template': return session.propose_motion_template(args.render_id, _object(args.request_file), args.actor, args.note)
    if action == 'depth-layer': return session.propose_depth_layer(args.render_id, args.manifest, args.asset_id,
        args.threshold, args.softness, args.strength, args.actor, args.note)
    if action == 'audio-cuts': return session.propose_audio_cuts(args.render_id,_object(args.request_file),args.actor,args.note)
    if action == 'transitions': return session.propose_transitions(args.render_id,_object(args.request_file),args.actor,args.note)
    if action == 'motion-cuts': return session.propose_motion_cut(args.render_id,_object(args.request_file),args.actor,args.note)
    if action == 'tracking-source': return session.tracking_source(args.render_id)
    if action == 'retime-source': return session.retime_source(args.render_id)
    if action == 'caption-source': return session.caption_source(args.render_id)
    if action == 'caption-groups': return session.propose_caption_groups(args.render_id,_object(args.spec_file),args.actor,args.note)
    if action == 'retime': return session.propose_retime(args.render_id,_object(args.request_file),args.actor,args.note,timeline_settings=args.timeline_settings)
    if action == 'track-effect':
        from .tracking_cli import read_corrections
        return session.propose_tracking(args.render_id,args.box,args.first_frame,args.end_frame,args.actor,args.note,
            algorithm=args.algorithm,model_path=args.model,max_scale=args.max_scale,strength=args.strength,
            corrections=read_corrections(args.corrections_file) if args.corrections_file else None,
            effect=args.effect,title_parameters=_object(args.title_parameters_file) if args.title_parameters_file else None,
            title_version=args.title_version,
            background_parameters=_object(args.background_parameters_file) if args.background_parameters_file else None,
            mask_corrections=_read_mask_corrections(args.mask_corrections_file) if args.mask_corrections_file else None,
            mask_backend=args.mask_backend,mask_threshold=args.mask_threshold)
    if action == 'direction':
        return session.propose_direction(_object(args.request_file), args.actor, args.note,
                                         preference=args.preference,
                                         trend=_object(args.trend_profile) if args.trend_profile else None)
    if action == 'adopt-candidate': return session.adopt_candidate(args.candidate_id, args.actor, args.note)
    if action == 'compare-candidates': return session.compare_candidates(args.render_ids, mode=args.mode)
    if action == 'native-finish': return session.native_finish(args.render_id, _object(args.request_file), args.actor, args.note)
    if action == 'feedback': return _feedback(session, args)
    if action == 'dismiss-feedback': return session.dismiss_feedback(args.feedback_id, args.actor, args.note)
    if action == 'address-feedback': return session.address_feedback(args.feedback_id, args.actor, args.note)
    if action == 'review': return session.review(args.render_id, _object(args.data_file), args.actor)
    if action == 'register-vertical': return session.register_derivative(args.render_id, args.result, args.actor)
    if action == 'review-vertical': return session.review_derivative(args.derivative_id, _object(args.data_file), args.actor)
    if action == 'audition-junctions': return session.audition_junctions(args.render_id, args.offset, args.limit, args.ids)
    if action == 'review-page': return session.review_page(args.render_id)
    if action == 'inspect': return session.inspect(args.render_id, args.start, args.duration)
    if action == 'preview-effects': return session.preview_effects(args.render_id, args.effect_ids, args.context_frames)
    if action == 'preview-changes': return session.preview_changes(args.candidate_id, args.effect_ids, args.context_frames)
    if action == 'evaluate': return session.evaluate()
    if action == 'handoff': return session.handoff(actor=args.actor)
    if action == 'import-fcp': return session.import_fcp(args.xml, args.actor, args.note)
    if action == 'import-production-fcp': return session.import_production_fcp(args.render_id, args.xml, args.actor, args.note)
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


def _read_mask_corrections(path):
    import re
    data=_object(path)
    if any(not re.fullmatch('0|[1-9][0-9]*',key) or not isinstance(value,str) or not value.strip() for key,value in data.items()):
        raise ValueError('Mask corrections map absolute frame numbers to PNG paths')
    return {int(key):str(Path(value).resolve(strict=True)) for key,value in data.items()}
