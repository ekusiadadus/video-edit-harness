"""Local returned-media A/B diagnostics; never native execution or rights approval."""
import json
from fractions import Fraction
from pathlib import Path

import numpy as np

from .common import fingerprint, read, run, write
from .native_finishing import inspect_native_result


def _decode(path, output, extra):
    log = Path(output).with_suffix('.log')
    run(['ffmpeg', '-hide_banner', '-nostdin', '-n', '-v', 'error', '-xerror',
         '-protocol_whitelist', 'file,pipe', '-f', 'mov', '-i', str(path),
         *extra, str(output)], log)
    return Path(output)


def compare_native_results(before, after, output):
    """Fully decode both files, compare exact PCM and reduced picture per frame.

    Unequal media clocks remain separate diagnostics; never resample or stretch
    either file to manufacture equality. Audio equality does not identify a song.
    """
    before, after = Path(before).resolve(), Path(after).resolve()
    original = [fingerprint(path) for path in (before, after)]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    reports = [inspect_native_result(path, output/name) for path, name in
               ((before, 'before-inspection'), (after, 'after-inspection'))]
    probes = [read(output/name/'probe.json') for name in ('before-inspection', 'after-inspection')]
    audio_streams = [next((s for s in p['streams'] if s['codec_type']=='audio'), None) for p in probes]
    audio = {'comparable': False, 'pcm_equal': None,
             'scope': 'first audio stream, exact native sample rate/channels; no resampling',
             'music_identity_verified': False, 'audio_placement_verified': False}
    if all(audio_streams) and all(audio_streams[0].get(k)==audio_streams[1].get(k)
            for k in ('sample_rate', 'channels', 'channel_layout')):
        pcm = [_decode(path, output/(name+'.f32le'), ['-map','0:a:0','-vn','-f','f32le'])
               for path, name in ((before,'before-audio'),(after,'after-audio'))]
        channels = audio_streams[0]['channels']
        audio_refs = [fingerprint(path) for path in pcm]
        samples = [ref['bytes']//(4*channels) for ref in audio_refs]
        if any(ref['bytes']%(4*channels) for ref in audio_refs):
            raise ValueError('Incomplete native PCM frame')
        audio.update(comparable=True, pcm_equal=audio_refs[0]['bytes']==audio_refs[1]['bytes'] and audio_refs[0]['sha256']==audio_refs[1]['sha256'], sample_frames=samples,
                     same_sample_count=samples[0]==samples[1],
                     sample_rate=int(audio_streams[0]['sample_rate']),channels=channels,
                     pcm_sha256=[ref['sha256'] for ref in audio_refs])
    picture = {'comparable': False, 'whole_picture_equal': None,
               'scope': 'every decoded frame, aspect-preserving reduced RGB; not full-resolution pixel equality',
               'native_effect_identity_verified': False}
    layouts = [r['picture'] for r in reports]
    if all(layouts[0].get(k)==layouts[1].get(k) for k in ('width','height','frame_rate')):
        scale = min(1,160/max(layouts[0]['width'],layouts[0]['height']))
        width,height = [max(2,int(layouts[0][k]*scale)//2*2) for k in ('width','height')]
        raw = [_decode(path,output/(name+'.rgb'),['-map','0:v:0','-an','-vf',f'scale={width}:{height}',
                '-pix_fmt','rgb24','-fps_mode','passthrough','-f','rawvideo'])
               for path,name in ((before,'before-picture'),(after,'after-picture'))]
        stride=width*height*3
        sizes = [path.stat().st_size for path in raw]
        if any(size%stride for size in sizes):
            raise ValueError('Incomplete native RGB frame')
        counts=[size//stride for size in sizes]
        picture.update(comparable=counts[0]==counts[1],sample_width=width,sample_height=height,
                       decoded_frame_counts=counts)
        clocks = []
        for path, name, probe in zip((before, after), ('before', 'after'), probes):
            log = run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                       '-f', 'mov', '-i', str(path), '-select_streams', 'v:0',
                       '-show_frames', '-show_entries', 'frame=best_effort_timestamp',
                       '-of', 'json'], output/(name+'-frame-clock.log'))
            frames = json.loads(log.split('\n', 1)[1])['frames']
            stream = next(s for s in probe['streams'] if s['codec_type']=='video')
            base = Fraction(stream['time_base'])
            clocks.append([str(int(f['best_effort_timestamp'])*base)
                           if 'best_effort_timestamp' in f else None for f in frames])
        clock_equal = (len(clocks[0])==counts[0] and len(clocks[1])==counts[1]
                       and clocks[0]==clocks[1] and all(x is not None for x in clocks[0]))
        picture.update(frame_timestamps_equal=clock_equal)
        picture['comparable'] = counts[0]==counts[1] and clock_equal
        if picture['comparable']:
            differences = []
            reduced_equal = True
            with raw[0].open('rb') as first, raw[1].open('rb') as second:
                while True:
                    a, b = first.read(stride*120), second.read(stride*120)
                    if not a:
                        break
                    reduced_equal = reduced_equal and a==b
                    delta = (np.frombuffer(a, dtype=np.uint8).astype(np.float32)
                             - np.frombuffer(b, dtype=np.uint8).astype(np.float32)).reshape(-1,stride)
                    differences.extend(float(x) for x in np.sqrt(np.mean(delta*delta,axis=1)))
            picture.update(reduced_picture_equal=reduced_equal,
                           frame_rms_difference=differences,
                           largest_difference_frame=int(np.argmax(differences)) if differences else None)
    if [fingerprint(path) for path in (before,after)] != original:
        raise ValueError('Native comparison input changed')
    result={'version':1,'kind':'native_return_comparison','before':original[0],'after':original[1],
            'full_av_decode':'pass','audio':audio,'picture':picture,'status':'awaiting_comparison_review',
            'source_relationship_verified':False,'native_api_response_verified':False,
            'human_whole_watch_listen':False,'cross_platform_rights_verified':False,'published':False,
            'evidence': {str(p.relative_to(output)):fingerprint(p) for p in output.rglob('*') if p.is_file()}}
    write(output/'comparison.json',result)
    return result
