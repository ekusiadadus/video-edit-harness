"""Reuse the sealed pre-effects picture for unadopted interval-only revisions."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import time

from .common import fingerprint, read, run, write
from .effect_preview import _excerpt, _check_excerpt, _media_shape, _page
from .feedback import map_output
from .production import resolve_production, verify_production
from .runs import evidence_run
from .session import check_ref, digest
from .video_effects import render_effects


def export_change_preview(original, candidate, cfg, mapping, folder, first, end, metadata):
    """This artifact is not a full candidate render and cannot satisfy adoption."""
    if original.get('preview') is not False:
        raise ValueError('Change preview requires a full original render')
    for ref in original['files'].values():
        check_ref(ref)
    for key in ('project', 'plan', 'brief'):
        check_ref(candidate[key])
        check_ref(original[key])
    if any(candidate[key] != original[key] for key in ('plan', 'brief')):
        raise ValueError('Change preview requires the same selected plan and brief')
    if cfg != read(candidate['project']['path']) or mapping != read(original['files']['mapping']['path']):
        raise ValueError('Change preview settings or mapping changed')
    original_cfg = read(original['project']['path'])
    left, right = deepcopy(cfg), deepcopy(original_cfg)
    left.pop('video_effects', None); right.pop('video_effects', None)
    if left != right:
        raise ValueError('Change preview may change effects only')
    if 'effects' not in original['files']:
        raise ValueError('Render an original effect candidate to retain its input first')
    expected_sha = read(original['files']['effects']['path'])['input_sha256']
    picture = None
    for name in ('before-effects.mp4', 'visual-overlays.mp4', 'visual-depth.mp4', 'visual-graded.mp4',
                 'visual-transitioned.mp4', 'visual-retimed.mp4', 'visual-base.mp4'):
        path = Path(original['path']) / name
        if path.is_file() and fingerprint(path)['sha256'] == expected_sha:
            picture = fingerprint(path)
            break
    if picture is None:
        raise ValueError('Sealed pre-effects input is missing or changed; render a fresh original')
    rate = Fraction(str(mapping['fps']))
    count = mapping['frame_count']
    if (type(first) is not int or type(end) is not int or not 0 <= first < end <= count
            or Fraction(end-first, 1)/rate > 30):
        raise ValueError('Change preview needs existing output frames within 30 seconds')
    shape = _media_shape(picture['path'], rate, count)
    production = resolve_production(cfg, mapping)
    verify_production(production)
    effects = production.get('effects', {'version': 1, 'mapping_sha256': digest(mapping), 'preset': None, 'events': []})
    post_filter = None
    if cfg.get('edit_basis') == 'visual':
        from .visual_editing import visual_pipeline_version, _composed_output_filter
        if visual_pipeline_version(cfg) == 2:
            post_filter = _composed_output_filter(False)
        else:
            from .editing import _video_filter
            post_filter = _video_filter(cfg, check_ref(original['files']['lut']), False)
    finished = original['files']['video']
    _media_shape(finished['path'], rate, count)
    folder = Path(folder)
    begun = time.monotonic()
    started = False
    try:
        with evidence_run({'source': picture['path']}, 'change-preview', folder,
            {'candidate_project_sha256': candidate['project']['sha256'],
             'original_video_sha256': finished['sha256'], 'first_frame': first, 'end_frame_exclusive': end}) as manifest:
            started = True
            intermediate = folder / ('effect-window.mp4' if post_filter else 'after.mp4')
            from .temporal_effect_phase import picture_binding
            effect_evidence = render_effects(picture['path'], effects, intermediate,
                production['assets'], production.get('composition'), capture_temporal_samples=False,
                output_window=(first, end), audio_source=finished['path'],
                project_picture_sha256=picture_binding(cfg))
            write(folder / 'effects.json', effect_evidence)
            if post_filter:
                run(['ffmpeg', '-hide_banner', '-nostdin', '-n', '-i', str(intermediate),
                     '-map', '0:v:0', '-map', '0:a:0', '-vf', post_filter,
                     '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
                     '-c:a', 'copy', '-map_metadata', '-1', '-movflags', '+faststart', str(folder / 'after.mp4')],
                     folder / 'post-filter.log')
            _excerpt(finished['path'], folder / 'before.mp4', first, end, rate, folder / 'before-render.log')
            for name in ('before', 'after'):
                _check_excerpt(folder / (name+'.mp4'), end-first, rate, shape, folder / (name+'-decode.log'))
            check_ref(picture)
            check_ref(finished)
            check_ref(candidate['project'])
            for ref in original['files'].values():
                check_ref(ref)
            for key in ('project', 'plan', 'brief'):
                check_ref(original[key])
                check_ref(candidate[key])
            check_ref(metadata['comparison_selection'])
            verify_production(production)
            page = folder / 'preview.html'
            page.write_text(_page({'path':'before.mp4', 'sha256':finished['sha256']},
                {'path':'after.mp4', 'sha256':candidate['project']['sha256']}, first, end, rate,
                after_reference_label='候補設定SHA-256（全編は未描画）', partial=True), encoding='utf-8')
            write(folder / 'preview.json', {
                'version': 1, 'kind': 'unadopted_effect_window', 'run_id': manifest['run_id'],
                'candidate_id': candidate['id'], 'candidate_project': candidate['project'],
                'original_render_id': original['id'], 'original_video': finished,
                'retained_pre_effects': picture, 'mapping': original['files']['mapping'],
                'first_frame': first, 'end_frame_exclusive': end, 'fps': str(rate),
                'audio_sample_bounds': {'sample_rate':48000, 'first_sample':round(Fraction(first*48000,1)/rate),
                                        'end_sample_exclusive':round(Fraction(end*48000,1)/rate)},
                'parent_source_mapping': map_output(mapping, float(Fraction(first, 1)/rate), float(Fraction(end, 1)/rate)),
                'excerpts': {name:fingerprint(folder / (name+'.mp4')) for name in ('before','after')},
                'page': fingerprint(page), 'metadata': metadata,
                'clock': 'Effects consume the full original clock and history before output-frame trim',
                'processing': 'Reuse original assembly/grade/overlays/audio; encode selected effect frames only',
                'post_filter': post_filter, 'elapsed_seconds': time.monotonic()-begun,
                'review_status': 'pending_full_render', 'adopted': False, 'full_render': False})
    except BaseException:
        if started:
            for name in ('before.mp4', 'after.mp4', 'effect-window.mp4', 'preview.html', 'preview.json'):
                (folder / name).unlink(missing_ok=True)
        raise
    return fingerprint(folder / 'preview.json')
