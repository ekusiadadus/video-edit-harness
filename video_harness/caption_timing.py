"""Observed word occurrences for reviewed caption grouping, without ASR."""

from fractions import Fraction
import hashlib

from .edl import remap_subtitles, group_captions, _srt_time
from .common import write, fingerprint


def caption_timing(plan, mapping, *, retime=None, audio_cuts=None):
    if retime is not None and audio_cuts is not None:
        raise ValueError('Caption timing needs a joint mapping for retime and J/L cuts')
    if retime is not None:
        compiled = retime['proposal']['mapping']
        rate = Fraction(compiled['fps'])
        captions = retime['proposal']['captions']
        occurrences = retime['word_protection']['word_occurrences']
        if len(captions) != len(occurrences):
            raise ValueError('Retimed caption occurrences differ from word protection')
        cues = []
        for caption, word in zip(captions, occurrences):
            expected = f"word:{word['word_id']}:{word['occurrence_index']}"
            if caption['id'] != expected or caption['status'] != 'mapped':
                raise ValueError('Retimed caption must retain its observed word occurrence')
            cues.append({'id': word['word_id'], 'occurrence_index': word['occurrence_index'],
                         'start': float(Fraction(caption['output_first_frame'], 1) / rate),
                         'end': float(Fraction(caption['output_end_frame_exclusive'], 1) / rate),
                         'text': caption['text']})
        junctions = []
        for first in retime['edit_junction_frames']:
            position = next((i for i, base in enumerate(compiled['frame_map']) if base >= first), None)
            if position is not None:
                junctions.append(float(Fraction(position, 1) / rate))
        basis = 'retimed_observed_word_frames'
    elif audio_cuts is not None:
        from .audio_cuts import RATE
        rate = RATE
        cues = [{'id': word['id'], 'start': word['output_first_sample'] / rate,
                 'end': word['output_end_sample'] / rate, 'text': word['text']}
                for word in audio_cuts['word_occurrences']]
        rows = audio_cuts['audio_map']
        junctions = [row['output_first_sample'] / rate for previous, row in zip(rows, rows[1:])
                     if previous['source_path'] != row['source_path'] or
                     previous['source_end_sample'] != row['source_first_sample']]
        basis = 'observed_audio_word_samples'
    else:
        cues = remap_subtitles(plan, keep=mapping['keep'])
        junctions, elapsed = [], 0.0
        for start, end in mapping['keep'][:-1]:
            elapsed += end - start
            junctions.append(elapsed)
        basis = 'frame_aligned_source_word_times'
    from .caption_groups import annotate_occurrences, caption_stream_sha256
    words = annotate_occurrences(cues)
    return {'version': 1, 'words': words, 'junctions': junctions, 'timing_basis': basis,
            'word_stream_sha256': caption_stream_sha256(words)}


def captions_srt(captions):
    return ''.join(f"{index}\n{_srt_time(cue['start'])} --> {_srt_time(cue['end'])}\n{cue['text']}\n\n"
                   for index, cue in enumerate(captions, 1))


def verify_caption_evidence(evidence, subtitles_sha256):
    from .caption_groups import caption_stream_sha256
    if not isinstance(evidence, dict) or evidence.get('version') != 1:
        raise ValueError('Expected version 1 caption evidence')
    stream_sha = caption_stream_sha256(evidence['words'])
    if evidence['word_stream_sha256'] != stream_sha:
        raise ValueError('Caption word stream hash differs')
    report = evidence['grouping']
    if report['status'] != 'review_required':
        raise ValueError('Caption evidence cannot establish perceptual acceptance')
    if evidence['grouping_method'] == 'explicit_word_groups':
        if report['word_stream_sha256'] != stream_sha:
            raise ValueError('Caption grouping refers to a different word stream')
    elif evidence['grouping_method'] != 'legacy_automatic_proposal':
        raise ValueError('Unsupported caption grouping method')
    rendered_sha = hashlib.sha256(captions_srt(report['captions']).encode('utf-8')).hexdigest()
    if evidence['subtitles_sha256'] != subtitles_sha256 or rendered_sha != subtitles_sha256:
        raise ValueError('Caption evidence does not describe these subtitles')
    return evidence


def write_caption_evidence(out, plan, mapping, *, grouping=None, retime=None, audio_cuts=None):
    evidence_path = out / 'caption-evidence.json'
    if evidence_path.exists():
        raise FileExistsError(evidence_path)
    stream = caption_timing(plan, mapping, retime=retime, audio_cuts=audio_cuts)
    if grouping is not None:
        from .caption_groups import group_reviewed_captions
        report = group_reviewed_captions(stream['words'], grouping, junctions=stream['junctions'])
        method = 'explicit_word_groups'
    else:
        report = {'captions': group_captions(stream['words'], junctions=stream['junctions']),
                  'status': 'review_required', 'diagnostics': []}
        method = 'legacy_automatic_proposal'
    subtitle = out / 'subtitles.srt'
    subtitle.write_text(captions_srt(report['captions']), encoding='utf-8')
    evidence = {**stream, 'grouping_method': method, 'grouping': report,
                'subtitles_sha256': fingerprint(subtitle)['sha256'],
                'acceptance': 'Exact-render wording, readability and listening review required'}
    write(evidence_path, evidence)
    return evidence
