"""Composite a verified grayscale foreground mask without changing picture timing."""
from fractions import Fraction


def background_graph(label, mask_input_index, event, rate):
    rate=Fraction(rate)
    first=int(Fraction(event['output_start'])*rate)
    end=int(Fraction(event['output_end'])*rate)
    params=event['parameters'];strength=event['strength']
    dim=1-(1-params['background_dim'])*strength
    saturation=1-(1-params['background_saturation'])*strength
    prefix=f'masked{mask_input_index}'
    base,clip,foreground,background,mask,composite=(prefix+name for name in ('base','clip','fg','bg','mask','composite'))
    output=prefix+'out'
    reset=f'settb=expr={rate.denominator}/{rate.numerator},setpts=N'
    feather=f",gblur=sigma={params['feather_pixels']:.9f}" if params['feather_pixels'] else ''
    graph=(f'[{label}]split[{base}][{clip}];'
           f'[{clip}]trim=start_frame={first}:end_frame={end},{reset},split[{foreground}][{background}];'
           f'[{foreground}]format=gbrp[{foreground}rgb];'
           f'[{background}]hue=s={saturation:.9f},format=gbrp,'
           f"lutrgb=r='val*{dim:.9f}':g='val*{dim:.9f}':b='val*{dim:.9f}'[{background}rgb];"
           f'[{mask_input_index}:v]trim=end_frame={end-first},{reset},format=gray,lut=y=255-val{feather},format=gbrp[{mask}];'
           f'[{foreground}rgb][{background}rgb][{mask}]maskedmerge,format=yuv420p,'
           f'setpts=PTS+{first*rate.denominator}/{rate.numerator}/TB[{composite}];'
           f'[{base}][{composite}]overlay=eof_action=pass:repeatlast=0:'
           f"enable='gte(n,{first})*lt(n,{end})'[{output}]")
    return graph,output
