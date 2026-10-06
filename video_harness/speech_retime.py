"""Bind speech retiming to the reviewed edit and observed nonspoken frames."""

from bisect import bisect_right
from copy import deepcopy
from fractions import Fraction

from .common import fingerprint
from .edl import group_captions
from .render_cache import digest
from .retime import prepare_retime
from .speech_protection import derive_speech_protection
from .video_effects import _probe, _stream, _verified_rate


def _dimensions(source):
    info = _probe(source, count=True)
    video = _stream(info, 'video')
    if not video:
        raise ValueError('Speech retime source needs video')
    count = int(video['nb_read_frames'])
    return str(_verified_rate(source, video, count)), count


def _observations(value, count, protected):
    if not isinstance(value, list):
        raise ValueError('nonspoken_intervals must be a list of observed intervals')
    rows = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {'first_frame', 'end_frame_exclusive', 'reason'}:
            raise ValueError('Nonspoken interval needs frame bounds and an observation reason')
        first, end = row['first_frame'], row['end_frame_exclusive']
        if (type(first) is not int or type(end) is not int or not 0 <= first < end <= count or
                not isinstance(row['reason'], str) or not row['reason'].strip()):
            raise ValueError('Invalid observed nonspoken interval')
        if any(first < b and a < end for a, b in protected):
            raise ValueError('Observed nonspoken interval conflicts with a retained word')
        rows.append(deepcopy(row))
    rows.sort(key=lambda row: (row['first_frame'], row['end_frame_exclusive'], row['reason']))
    return rows


def _covers(first, end, rows):
    cursor = first
    for row in rows:
        if row['first_frame'] > cursor:
            return False
        cursor = max(cursor, row['end_frame_exclusive'])
        if cursor >= end:
            return True
    return False


def _request(request, protection, count):
    if not isinstance(request, dict) or 'operations' not in request or set(request) - {
            'operations', 'nonspoken_intervals', 'protected_intervals', 'audio_backend'}:
        raise ValueError('Speech retime request needs operations and observed nonspoken_intervals')
    observed = _observations(request.get('nonspoken_intervals', []), count,
                             protection['protected_intervals'])
    operations = request['operations']
    if not isinstance(operations, list):
        raise ValueError('operations must be a list')
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError('Invalid retime operation')
        if operation.get('kind') == 'ramp':
            first, end = operation.get('source_first_frame'), operation.get('source_end_frame_exclusive')
        elif operation.get('kind') == 'freeze':
            first = operation.get('source_frame')
            end = first + 1 if type(first) is int else None
        else:
            raise ValueError('Invalid retime operation')
        if type(first) is not int or type(end) is not int or not _covers(first, end, observed):
            raise ValueError('Every retimed source frame needs an observed nonspoken interval')
    user = request.get('protected_intervals', [])
    if not isinstance(user, list):
        raise ValueError('protected_intervals must be a list')
    normalized = {'operations': deepcopy(operations),
                  'protected_intervals': deepcopy(protection['protected_intervals']) + deepcopy(user)}
    if 'audio_backend' in request:
        normalized['audio_backend'] = request['audio_backend']
    return normalized, observed


def prepare_speech_retime(source, plan, mapping, request, actor, reason):
    """Prepare an unadopted retime with words and observations bound to one source."""
    rate, count = _dimensions(source)
    protection = derive_speech_protection(plan, mapping, fps=rate, frame_count=count)
    normalized, observed = _request(request, protection, count)
    words = {word['id']: word['text'] for word in plan['transcript']['words']}
    captions = []
    for occurrence in protection['word_occurrences']:
        captions.append({'id': f"word:{occurrence['word_id']}:{occurrence['occurrence_index']}",
                         'text': words[occurrence['word_id']],
                         'source_first_frame': occurrence['start_frame'],
                         'source_end_frame_exclusive': occurrence['end_frame_exclusive']})
    normalized['captions'] = captions
    proposal = prepare_retime(source, normalized, actor, reason)
    spans = _source_spans(mapping, Fraction(rate), count)
    return {'version': 2, 'proposal': proposal,
            'input_mapping_sha256': digest(mapping),
            'word_protection': protection,
            'nonspoken_intervals': observed,
            'edit_junction_frames': [row['base_output_first_frame'] for row in spans[1:]]}


def verify_speech_setting(source, plan, mapping, setting):
    """Rebuild the proposal from source, plan, mapping, and its observed request."""
    if not isinstance(setting, dict) or set(setting) != {
            'version', 'proposal', 'input_mapping_sha256', 'word_protection',
            'nonspoken_intervals', 'edit_junction_frames'} or setting['version'] != 2:
        raise ValueError('Expected a source-bound speech retime setting')
    proposal = setting['proposal']
    if not isinstance(proposal, dict):
        raise ValueError('Invalid speech retime proposal')
    request = proposal.get('request')
    if not isinstance(request, dict):
        raise ValueError('Invalid speech retime request')
    supplied = {key: deepcopy(request[key]) for key in
                ('operations', 'audio_backend') if key in request}
    mandatory = setting['word_protection']
    protected = request.get('protected_intervals')
    if (not isinstance(mandatory, dict) or not isinstance(protected, list) or
            protected[:len(mandatory.get('protected_intervals', []))] != mandatory.get('protected_intervals')):
        raise ValueError('Mandatory word protection is missing')
    supplied['protected_intervals'] = deepcopy(protected[len(mandatory['protected_intervals']):])
    supplied['nonspoken_intervals'] = deepcopy(setting['nonspoken_intervals'])
    observed = prepare_speech_retime(source, plan, mapping, supplied,
                                     proposal.get('actor'), proposal.get('reason'))
    current_source = fingerprint(source)
    expected_source = proposal.get('source')
    if (not isinstance(expected_source, dict) or
            any(current_source.get(key) != expected_source.get(key) for key in ('sha256', 'bytes'))):
        raise ValueError('Speech retime source changed')
    # The retained assembly can be copied into a new immutable render folder.
    # Its content identity is stable while its absolute path changes.
    observed['proposal']['source'] = deepcopy(expected_source)
    if observed != setting:
        raise ValueError('Speech retime setting differs from source, plan, or mapping')
    return observed


def _source_spans(mapping, rate, count):
    keeps = mapping.get('keep')
    if not isinstance(keeps, list) or not keeps:
        raise ValueError('Speech mapping has no keep spans')
    ids = mapping.get('sequence_ids')
    if ids is not None and (not isinstance(ids, list) or len(ids) != len(keeps)):
        raise ValueError('Speech mapping sequence IDs differ from keep spans')
    original_rows = mapping.get('sequence')
    if original_rows is not None and (not isinstance(original_rows, list) or
                                      len(original_rows) != len(keeps) or
                                      any(not isinstance(row, dict) for row in original_rows)):
        raise ValueError('Speech mapping sequence differs from keep spans')
    result = []
    cursor = 0
    for index, span in enumerate(keeps):
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise ValueError('Invalid speech keep span')
        first = round(Fraction(str(span[0])) * rate)
        end = round(Fraction(str(span[1])) * rate)
        if end <= first or any(abs(Fraction(str(value)) - Fraction(frame, 1) / rate) > Fraction(1, 1000000)
                                 for value, frame in zip(span, (first, end))):
            raise ValueError('Speech keep span is not frame aligned')
        original = original_rows[index] if original_rows is not None else {}
        row_id = original.get('id', ids[index] if ids else f'keep-{index + 1}')
        if ids is not None and row_id != ids[index]:
            raise ValueError('Speech sequence row ID differs from sequence_ids')
        if not isinstance(row_id, str) or not row_id:
            raise ValueError('Speech sequence row ID is invalid')
        result.append({'id': row_id,
                       'source_first_frame': first, 'source_end_frame_exclusive': end,
                       'base_output_first_frame': cursor,
                       'base_output_end_frame_exclusive': cursor + end - first,
                       'source_start': float(Fraction(first, 1) / rate),
                       'source_end': float(Fraction(end, 1) / rate),
                       'chapter_id': original.get('chapter_id')})
        cursor += end - first
    if cursor != count:
        raise ValueError('Speech keep spans differ from base frame count')
    return result


def remap_speech_mapping(mapping, compiled):
    """Trace every retimed frame through the base assembly to its original source."""
    if not isinstance(mapping, dict) or not isinstance(compiled, dict) or compiled.get('version') != 1:
        raise ValueError('Invalid speech mapping or compiled retime')
    rate = Fraction(compiled['fps'])
    count = compiled['input_frame_count']
    spans = _source_spans(mapping, rate, count)
    output_count = compiled.get('output_frame_count')
    frames = compiled.get('frame_map')
    if (type(output_count) is not int or output_count <= 0 or not isinstance(frames, list) or
            len(frames) != output_count or any(type(f) is not int or not 0 <= f < count for f in frames) or
            any(b < a for a, b in zip(frames, frames[1:]))):
        raise ValueError('Invalid compiled speech frame map')
    if 'fps' in mapping and Fraction(str(mapping['fps'])) != rate:
        raise ValueError('Speech mapping FPS differs from compiled retime')
    if 'frame_count' in mapping and mapping['frame_count'] != count:
        raise ValueError('Speech mapping frame count differs from compiled retime')
    if abs(Fraction(str(mapping['duration'])) - Fraction(count, 1) / rate) > Fraction(1, 1000000):
        raise ValueError('Speech mapping duration differs from base frame count')
    ends = [span['base_output_end_frame_exclusive'] for span in spans]
    references = []
    sequence = []
    for output_frame, base in enumerate(frames):
        index = bisect_right(ends, base)
        span = spans[index]
        source_frame = span['source_first_frame'] + base - span['base_output_first_frame']
        references.append({'output_frame': output_frame, 'base_output_frame': base,
                           'source_frame': source_frame, 'source_span_index': index,
                           'source_span_id': span['id']})
        if not sequence or sequence[-1]['source_span_index'] != index:
            sequence.append({**span, 'source_span_index': index,
                             'output_first_frame': output_frame,
                             'output_end_frame_exclusive': output_frame + 1,
                             'output_start': float(Fraction(output_frame, 1) / rate),
                             'output_end': float(Fraction(output_frame + 1, 1) / rate)})
        else:
            sequence[-1]['output_end_frame_exclusive'] = output_frame + 1
            sequence[-1]['output_end'] = float(Fraction(output_frame + 1, 1) / rate)
    result = deepcopy(mapping)
    result.update({'fps': compiled['fps'], 'frame_count': output_count,
                   'duration': float(Fraction(output_count, 1) / rate),
                   'sequence': sequence,
                   'retime': {'input_mapping_sha256': digest(mapping),
                              'compiled_mapping': deepcopy(compiled), 'frames': references}})
    return result


def remapped_subtitles(setting):
    """Return grouped SRT using exact retimed word frames and edit junctions."""
    if not isinstance(setting, dict) or setting.get('version') != 2:
        raise ValueError('Expected speech retime setting')
    proposal = setting['proposal']
    compiled = proposal['mapping']
    rate = Fraction(compiled['fps'])
    cues = [{'start': float(Fraction(c['output_first_frame'], 1) / rate),
             'end': float(Fraction(c['output_end_frame_exclusive'], 1) / rate),
             'text': c['text']}
            for c in proposal['captions'] if c['status'] == 'mapped']
    # Caption grouping may not cross an original edit junction even after a ramp.
    junctions = []
    for first in setting['edit_junction_frames']:
        position = next((i for i, base in enumerate(compiled['frame_map']) if base >= first), None)
        if position is not None:
            junctions.append(float(Fraction(position, 1) / rate))
    from .edl import _srt_time
    grouped = group_captions(cues, junctions=junctions)
    return ''.join(f"{index}\n{_srt_time(cue['start'])} --> {_srt_time(cue['end'])}\n{cue['text']}\n\n"
                   for index, cue in enumerate(grouped, 1))
