"""Conservative transcript-word protection on a pre-retime source edit."""

from fractions import Fraction
import math

from .edl import remap_subtitles, validate_plan
from .render_cache import digest


def _rate(value):
    if isinstance(value, bool):
        raise ValueError('Invalid fps')
    try:
        rate = Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('Invalid fps') from exc
    if rate <= 0 or not math.isfinite(float(rate)):
        raise ValueError('Invalid fps')
    return rate


def _seconds(value, label):
    if isinstance(value, bool):
        raise ValueError(f'Invalid {label}')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'Invalid {label}') from exc
    if not math.isfinite(result):
        raise ValueError(f'Invalid {label}')
    return result


def derive_speech_protection(plan, mapping, *, fps, frame_count):
    """Locate every retained word; all unlisted audio still needs human review.

    Frame intervals are half-open. Fractional word boundaries expand outward so
    every frame touched by a word remains protected during retime selection.
    """
    if not isinstance(plan, dict) or not isinstance(mapping, dict):
        raise ValueError('Plan and mapping must be objects')
    validate_plan(plan)
    rate = _rate(fps)
    if type(frame_count) is not int or frame_count <= 0:
        raise ValueError('Invalid frame_count')
    if mapping.get('source') != plan['source']:
        raise ValueError('Mapping source differs from plan source')
    if 'fps' in mapping and _rate(mapping['fps']) != rate:
        raise ValueError('Mapping fps differs from output fps')
    if 'frame_count' in mapping and mapping['frame_count'] != frame_count:
        raise ValueError('Mapping frame_count differs from output frame_count')
    duration = _seconds(mapping.get('duration'), 'mapping duration')
    expected_duration = float(Fraction(frame_count, 1) / rate)
    if abs(duration - expected_duration) > 1e-6:
        raise ValueError('Mapping duration differs from frame dimensions')
    keeps = mapping.get('keep')
    if not isinstance(keeps, list) or not keeps:
        raise ValueError('Mapping has no keep spans')
    aligned = []
    for span in keeps:
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise ValueError('Invalid mapping keep span')
        start, end = (_seconds(span[0], 'keep start'), _seconds(span[1], 'keep end'))
        if not 0 <= start < end:
            raise ValueError('Invalid mapping keep span')
        aligned.append((start, end))
    if abs(sum(end - start for start, end in aligned) - duration) > 1e-6:
        raise ValueError('Mapping keep duration differs from output duration')

    # The mapping comes from frame-aligned FCPXML spans. Rebuild output offsets
    # from integer frame lengths, not accumulated binary-float source times.
    snapped = []
    total_frames = 0
    tolerance = Fraction(1, 1_000_000)
    for start, end in aligned:
        source_first = round(Fraction(str(start)) * rate)
        source_end = round(Fraction(str(end)) * rate)
        if (source_end <= source_first or
            abs(Fraction(str(start)) - Fraction(source_first, 1) / rate) > tolerance or
            abs(Fraction(str(end)) - Fraction(source_end, 1) / rate) > tolerance):
            raise ValueError('Mapping keep boundaries are not frame aligned')
        snapped.append((source_first, source_end, total_frames))
        total_frames += source_end - source_first
    if total_frames != frame_count:
        raise ValueError('Mapping keep frames differ from frame_count')

    # Subtitle remapping validates alignment against the reviewed edit and
    # supplies its displayed times. Raw transcript times supply frame bounds.
    cues = remap_subtitles(plan, keep=aligned)
    occurrences = []
    cue_index = 0
    for (keep_start, keep_end), (source_first, source_end, output_first) in zip(aligned, snapped):
        snapped_start = Fraction(source_first, 1) / rate
        output_start = Fraction(output_first, 1) / rate
        output_end = output_start + Fraction(source_end - source_first, 1) / rate
        for word in plan['transcript']['words']:
            left = max(keep_start, word['start'])
            right = min(keep_end, word['end'])
            if left >= right:
                continue
            full = keep_start <= word['start'] and word['end'] <= keep_end
            if not full and plan['version'] == 3:
                # remap_subtitles already rejects this; keep the invariant local.
                raise ValueError('Aligned keep would partially drop a retained word')
            raw_start = max(output_start, output_start + Fraction(str(left)) - snapped_start)
            raw_end = min(output_end, output_start + Fraction(str(right)) - snapped_start)
            if full:
                if cue_index >= len(cues) or cues[cue_index]['id'] != word['id']:
                    raise ValueError('Subtitle word IDs differ from retained words')
                cue = cues[cue_index]
                cue_index += 1
                item = dict(word_id=word['id'], start=cue['start'], end=cue['end'],
                            partial=False)
            else:
                # Legacy v2 subtitles omit a partially clipped word, but its
                # retained audio still needs protection.
                item = dict(word_id=word['id'], start=round(float(raw_start), 6),
                            end=round(float(raw_end), 6), partial=True)
            occurrences.append((raw_start, raw_end, item))
    if cue_index != len(cues):
        raise ValueError('Subtitle word IDs differ from retained words')
    occurrences.sort(key=lambda entry: (entry[0], entry[1]))

    per_word = {}
    frames = []
    result_occurrences = []
    for raw_start, raw_end, item in occurrences:
        item['occurrence_index'] = per_word.get(item['word_id'], 0)
        per_word[item['word_id']] = item['occurrence_index'] + 1
        start = math.floor(raw_start * rate)
        end = math.ceil(raw_end * rate)
        if start < 0 or end > frame_count:
            raise ValueError('Word timing outside output frame bounds')
        if end <= start:
            raise ValueError('Word has no output frames')
        item['start_frame'] = start
        item['end_frame_exclusive'] = end
        frames.append((start, end))
        result_occurrences.append(item)
    merged = []
    for start, end in sorted(frames):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return {'version': 1, 'input_mapping_sha256': digest(mapping),
            'plan_sha256': digest(plan), 'transcript_sha256': plan['transcript_sha256'],
            'source_sha256': plan['source']['sha256'], 'fps': str(fps),
            'frame_count': frame_count, 'protected_intervals': merged,
            'word_occurrences': result_occurrences, 'review_required': True,
            'scope': 'transcript_word_intervals_only'}
