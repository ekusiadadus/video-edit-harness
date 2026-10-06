"""Composite a verified grayscale foreground mask without changing picture timing."""
from fractions import Fraction


def background_graph(label, mask_input_index, event, rate, count):
    rate = Fraction(rate)
    first = int(Fraction(event['output_start']) * rate)
    end = int(Fraction(event['output_end']) * rate)
    if not 0 <= first < end <= count:
        raise ValueError('Background mask must cover existing output frames')
    params = event['parameters']; strength = event['strength']
    dim = 1 - (1 - params['background_dim']) * strength
    saturation = 1 - (1 - params['background_saturation']) * strength
    prefix = f'masked{mask_input_index}'
    reset = f'settb=expr={rate.denominator}/{rate.numerator},setpts=N'
    feather = f",gblur=sigma={params['feather_pixels']:.9f}" if params['feather_pixels'] else ''
    spans = []
    if first:
        spans.append(('prefix', 0, first))
    spans.append(('effect', first, end))
    if end < count:
        spans.append(('suffix', end, count))
    branches = [prefix + name + 'src' for name, _, _ in spans]
    parts = ([f'[{label}]split={len(spans)}' + ''.join(f'[{b}]' for b in branches)]
             if len(spans) > 1 else [])
    if len(spans) == 1:
        branches = [label]
    assembled = []
    for (name, start, stop), source in zip(spans, branches):
        target = prefix + name
        chain = f'[{source}]trim=start_frame={start}:end_frame={stop},{reset}'
        if name != 'effect':
            parts.append(chain + f'[{target}]')
        else:
            fg, bg, mask = prefix + 'fg', prefix + 'bg', prefix + 'mask'
            parts.extend([
                chain + f',split[{fg}][{bg}]',
                f'[{fg}]format=gbrp[{fg}rgb]',
                f'[{bg}]hue=s={saturation:.9f},format=gbrp,'
                f"lutrgb=r='val*{dim:.9f}':g='val*{dim:.9f}':b='val*{dim:.9f}'[{bg}rgb]",
                f'[{mask_input_index}:v]trim=end_frame={end-first},{reset},format=gray,'
                f'lut=y=255-val{feather},format=gbrp[{mask}]',
                f'[{fg}rgb][{bg}rgb][{mask}]maskedmerge,format=yuv420p,{reset}[{target}]',
            ])
        assembled.append(target)
    output = prefix + 'out'
    if len(assembled) == 1:
        parts[-1] = parts[-1].removesuffix(f'[{assembled[0]}]') + f'[{output}]'
    else:
        parts.append(''.join(f'[{part}]' for part in assembled) +
                     f'concat=n={len(assembled)}:v=1:a=0,{reset}[{output}]')
    return ';'.join(parts), output
