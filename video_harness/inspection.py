"""Bounded render inspection assets; producing evidence does not constitute listening."""
from pathlib import Path
from .common import fingerprint, read, run, write
from .feedback import seconds, map_output


def inspect_render(render, folder, start=0, duration=8):
    start, duration = seconds(start), seconds(duration)
    if not .25 <= duration <= 30:
        raise ValueError('Inspection duration must be 0.25..30 seconds')
    video = render['files']['video']
    if fingerprint(video['path']) != video:
        raise ValueError('Inspection video revision changed')
    mapping = read(render['files']['mapping']['path'])
    end = min(mapping['duration'], start + duration)
    if start >= end:
        raise ValueError('Inspection starts outside this render')
    mapped = map_output(mapping, start, end)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    length = end-start
    run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-ss', str(start), '-i', video['path'],
         '-t', str(length), '-vf', f'fps={6/length},scale=320:-2,tile=3x2', '-frames:v', '1',
         str(folder/'filmstrip.jpg')], folder/'filmstrip.log')
    run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-ss', str(start), '-i', video['path'],
         '-t', str(length), '-filter_complex', 'aformat=channel_layouts=mono,showwavespic=s=960x180:colors=white',
         '-frames:v', '1', str(folder/'waveform.png')], folder/'waveform.log')
    run(['ffmpeg', '-v', 'error', '-nostdin', '-n', '-ss', str(start), '-i', video['path'],
         '-t', str(length), '-vn', '-c:a', 'libmp3lame', '-b:a', '192k',
         str(folder/'listen.mp3')], folder/'listen.log')
    plan = read(render['files']['plan']['path'])
    words = []
    for span in mapped['source_spans']:
        for word in plan.get('transcript', {}).get('words', []):
            if word['start'] < span['source_end'] and word['end'] > span['source_start']:
                words.append({**word, 'sequence_id': span['sequence_id']})
    files = {p.name: fingerprint(p) for p in folder.iterdir() if p.is_file()}
    if fingerprint(video['path']) != video:
        raise ValueError('Render changed during inspection')
    result = {'render_id': render['id'], 'render_sha256': video['sha256'], **mapped,
              'words': words, 'files': files,
              'filmstrip_sample_times': [start + i*length/6 for i in range(6)],
              'review_status': 'pending', 'note': 'Sampled images and waveform are inspection aids; listen to the excerpt and record the observation separately.'}
    write(folder/'inspection.json', result)
    return fingerprint(folder/'inspection.json')
