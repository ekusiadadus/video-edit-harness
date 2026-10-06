"""Build a frame-bounded, causal temporal mix for one visual effect event."""
from __future__ import annotations

from fractions import Fraction
import math
import re


_LABEL = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")


def build_trail_graph(input_label, output_label, event, rate, count):
    """Return an FFmpeg graph fragment and the temporal-mix provenance.

    The caller supplies a validated canonical event and a CFR input with exactly
    ``count`` frames. The event stream is trimmed before tmix, so its history
    begins at the event's first frame even when an earlier scene precedes it.
    """
    if not all(isinstance(label, str) and _LABEL.fullmatch(label)
               for label in (input_label, output_label)) or input_label == output_label:
        raise ValueError('Motion trail needs distinct simple filter labels')
    rate = Fraction(rate)
    if rate <= 0 or type(count) is not int or count <= 0:
        raise ValueError('Motion trail needs positive FPS and frame count')
    if event['type'] != 'motion_trail':
        raise ValueError('Expected a motion_trail event')
    start = Fraction(event['output_start']) * rate
    end = Fraction(event['output_end']) * rate
    if start.denominator != 1 or end.denominator != 1:
        raise ValueError('Motion trail bounds must be exact output frames')
    first, last = int(start), int(end)
    if not 0 <= first < last <= count:
        raise ValueError('Motion trail must cover existing output frames')

    params = event['parameters']
    history = params['history_frames']
    decay = params['decay']
    strength = event['strength']
    if type(history) is not int or not 2 <= history <= 4:
        raise ValueError('history_frames must be 2..4')
    if (isinstance(decay, bool) or not isinstance(decay, (int, float)) or
            not math.isfinite(decay) or not .1 <= decay <= .6):
        raise ValueError('decay must be finite and in [0.1, 0.6]')
    if (isinstance(strength, bool) or not isinstance(strength, (int, float)) or
            not math.isfinite(strength) or not 0 < strength <= 1):
        raise ValueError('strength must be finite and in (0, 1]')

    # FFmpeg vf_mix.c stores tmix frames oldest to newest and pairs weights
    # with those slots. During warmup, it clones the first event frame.
    weights = [float(strength) * float(decay) ** age
               for age in range(history - 1, 0, -1)] + [1.0]
    total = sum(weights)
    weight_arg = ' '.join(f'{weight:.12g}' for weight in weights)
    frame_tb = f'{rate.denominator}/{rate.numerator}'
    reset = f'settb=expr={frame_tb},setpts=N'
    parts = []
    spans = []
    if first:
        spans.append(('prefix', 0, first))
    spans.append(('effect', first, last))
    if last < count:
        spans.append(('suffix', last, count))
    if len(spans) > 1:
        branches = [f'{output_label}_{name}_src' for name, _, _ in spans]
        parts.append(f'[{input_label}]split={len(spans)}' + ''.join(f'[{b}]' for b in branches))
    else:
        branches = [input_label]

    assembled = []
    for (name, begin, finish), source in zip(spans, branches):
        target = f'{output_label}_{name}'
        chain = f'[{source}]trim=start_frame={begin}:end_frame={finish},{reset}'
        if name == 'effect':
            chain += f',tmix=frames={history}:weights={weight_arg}:scale=0,{reset}'
        parts.append(f'{chain}[{target}]')
        assembled.append(target)
    if len(assembled) == 1:
        # The sole branch is the effect; name the public output exactly.
        parts[-1] = parts[-1].removesuffix(f'[{assembled[0]}]') + f'[{output_label}]'
    else:
        parts.append(''.join(f'[{label}]' for label in assembled) +
                     f'concat=n={len(assembled)}:v=1:a=0,{reset}[{output_label}]')

    evidence = {
        'window_first_frame': first,
        'window_end_frame_exclusive': last,
        'history_frames': history,
        'decay': float(decay),
        'strength': float(strength),
        'weights_oldest_to_newest': weights,
        'normalized_weights_oldest_to_newest': [weight / total for weight in weights],
        'causal_frame_offsets_oldest_to_newest': list(range(1 - history, 1)),
        'warmup': 'first event frame replicated into unavailable history slots',
        'warmup_frames': min(history - 1, last - first),
        'source_frame_count': count,
        'output_frame_count': count,
        'frame_rate': str(rate),
    }
    return ';'.join(parts), evidence
