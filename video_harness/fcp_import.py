"""Import only a simple, single-source FCP cut decision as a new v3 plan."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET

from .common import fingerprint
from .edl import validate_plan
from .fcp_check import _timeline
from .render_cache import digest


def import_fcpxml(reference_plan, xml, actor, note):
    if not str(actor).strip() or not str(note).strip():
        raise ValueError('FCP import requires review actor and note')
    validate_plan(reference_plan, verify_source=True)
    if reference_plan.get('version') != 3:
        raise ValueError('FCP import requires a v3 reference plan')
    xml = Path(xml)
    tree = ET.parse(xml)
    root = tree.getroot()
    report = {'xml': fingerprint(xml), 'reference_plan_sha256': digest(reference_plan),
              'status': 'unverified', 'scope': 'flat single-source clip order and rational time ranges',
              'gui_playback': 'not_verified', 'effects': 'not_verified', 'reasons': []}
    try:
        if root.tag != 'fcpxml' or len(root.findall('.//project')) != 1:
            raise ValueError('Expected one FCPXML project')
        if root.find('.//timeMap') is not None or root.find('.//conform-rate') is not None:
            raise ValueError('Retime is unsupported for FCP import')
        unsupported = {'timeMap', 'conform-rate', 'filter', 'filter-video', 'filter-audio',
                       'filter-audio-mixer', 'filter-color', 'transition', 'title',
                       'caption', 'audio', 'video', 'gap', 'sync-clip', 'mc-clip',
                       'multicam', 'ref-clip', 'compound-clip'}
        present = sorted({node.tag for node in root.iter() if node.tag in unsupported})
        if present:
            raise ValueError('Unsupported FCP effects or structure: ' + ', '.join(present))
        timeline = _timeline(xml)
        if len(root.findall('./resources/asset')) != 1 or root.findall('./resources/media'):
            raise ValueError('Extra or nested media assets are unsupported')
        if timeline['unsupported_effects']:
            raise ValueError('Unsupported clip effects: ' + ', '.join(timeline['unsupported_effects']))
        clips = timeline['clips']
        if any(node.get('lane') is not None or node.get('srcEnable') is not None
               or node.get('audioRole') is not None for node in root.findall('.//spine/asset-clip')):
            raise ValueError('Layered or audio-modified FCP clips are unsupported')
        if not clips:
            raise ValueError('Empty FCP timeline')
        expected_source = str(Path(reference_plan['source']['path']).resolve())
        if any(c['source'] != expected_source for c in clips):
            raise ValueError('Extra or different media asset in FCP timeline')
        elapsed = Fraction(0)
        for clip in clips:
            if clip['offset'] != elapsed:
                raise ValueError('FCP timeline has a gap, overlap, or noncontiguous offset')
            elapsed += clip['duration']
        if elapsed != timeline['duration']:
            raise ValueError('FCP sequence duration differs from contiguous clips')
        words = reference_plan['transcript']['words']
        # Preserve an old span's editorial intent where the imported span overlaps it.
        sequence = []
        for index, clip in enumerate(clips, 1):
            start, end = float(clip['start']), float(clip['start'] + clip['duration'])
            if not 0 <= start < end <= reference_plan['duration'] + 1e-6:
                raise ValueError('FCP clip exceeds source media')
            if any((word['start'] < start < word['end']) or
                   (word['start'] < end < word['end']) for word in words):
                raise ValueError('FCP boundary makes a partial-word cut')
            covered = [w for w in words if start <= w['start'] and w['end'] <= end]
            if not covered:
                raise ValueError('FCP clip contains no complete transcript words')
            match = max(reference_plan['sequence'], key=lambda s:
                        max(0, min(end, s['end']) - max(start, s['start'])), default=None)
            goals = match.get('goal_ids', []) if match else []
            if not goals:
                goals = [reference_plan['brief']['goals'][0]['id']]
            sequence.append({'id': f'fcp-{index}', 'start': start, 'end': end,
                             'start_word_id': covered[0]['id'], 'end_word_id': covered[-1]['id'],
                             'chapter_id': match.get('chapter_id', 'fcp-import') if match else 'fcp-import',
                             'reason': f'Imported FCP edit: {note}', 'goal_ids': goals,
                             'fade_in_seconds': 0, 'fade_out_seconds': 0})
        kept_ids = {word['id'] for word in words if any(span['start'] <= word['start']
                    and word['end'] <= span['end'] for span in sequence)}
        new_plan = deepcopy(reference_plan)
        new_plan['sequence'] = sequence
        new_plan['omitted_word_ids'] = [word['id'] for word in words if word['id'] not in kept_ids]
        new_plan['omissions'] = ([{'word_ids': new_plan['omitted_word_ids'],
            'reason': f'Imported FCP edit: {note}', 'goal_ids': sequence[0]['goal_ids']}]
            if new_plan['omitted_word_ids'] else [])
        new_plan['status'] = 'review_required'
        new_plan.pop('review', None)
        new_plan['parent_plan'] = {'sha256': digest(reference_plan), 'kind': 'reference_plan'}
        new_plan['fcp_import'] = {'xml': report['xml'], 'scope': report['scope'],
                                  'gui_playback': 'not_verified', 'effects': 'not_verified',
                                  'imported_by': actor, 'import_note': note,
                                  'selection_review': 'required'}
        validate_plan(new_plan, verify_source=True)
        report['status'] = 'imported'
        report['sequence_count'] = len(sequence)
        return new_plan, report
    except (ValueError, KeyError, TypeError) as exc:
        report['reasons'].append(str(exc))
        return None, report
