"""Compare a generated flat cut timeline with an actual FCP-exported timeline."""
from fractions import Fraction
from pathlib import Path
import xml.etree.ElementTree as ET

from .common import fingerprint, run, write
from .fcp import _uri_path


def validate_dtd(xml, log):
    root = ET.parse(xml).getroot()
    version = root.get('version')
    if root.tag != 'fcpxml' or not version or not all(c in '0123456789.' for c in version):
        raise ValueError('Invalid FCPXML version')
    candidates = list(Path('/Applications').glob(
        f'Final Cut Pro*.app/Contents/Frameworks/Interchange.framework/Versions/A/Resources/FCPXMLv{version.replace(".", "_")}.dtd'))
    if not candidates:
        return {'status': 'not_checked', 'reason': 'Matching installed FCPXML DTD not found'}
    run(['xmllint', '--noout', '--dtdvalid', candidates[0].resolve().as_uri(), str(xml)], log)
    return {'status': 'pass', 'dtd': str(candidates[0]), 'sha256': fingerprint(candidates[0])['sha256']}


def _time(text):
    if text is None or not text.endswith('s'):
        raise ValueError('Missing FCPXML rational time')
    return Fraction(text[:-1])


def _timeline(xml, name=None):
    root = ET.parse(xml).getroot()
    projects = root.findall('.//project')
    if name is not None:
        projects = [p for p in projects if p.get('name') == name]
    if len(projects) != 1:
        raise ValueError('Select exactly one project for FCP comparison')
    project = projects[0]
    sequence = project.find('sequence')
    if sequence is None or sequence.find('spine') is None:
        raise ValueError('Project lacks sequence/spine')
    assets = {a.get('id'): a for a in root.findall('./resources/asset')}
    spine = sequence.find('spine')
    if any(c.tag != 'asset-clip' for c in spine):
        raise ValueError('Comparison supports a flat asset-clip timeline only')
    origin = _time(sequence.get('tcStart', '0s'))
    clips = []
    unsupported = []
    for clip in spine:
        asset = assets.get(clip.get('ref'))
        if asset is None:
            raise ValueError('Missing media asset reference')
        rep = asset.find("media-rep[@kind='original-media']")
        if rep is None:
            raise ValueError('Missing original media representation')
        source = _uri_path(rep.get('src', ''))
        if source is None:
            raise ValueError('Unsupported media URI in roundtrip comparison')
        if clip.find('timeMap') is not None or clip.find('conform-rate') is not None:
            raise ValueError('Retime cannot be compared as a simple source interval')
        offset = _time(clip.get('offset')) - origin
        start = _time(clip.get('start', asset.get('start', '0s'))) - _time(asset.get('start', '0s'))
        duration = _time(clip.get('duration'))
        clips.append({'source': str(source.resolve()), 'offset': offset, 'start': start, 'duration': duration})
        unsupported.extend(node.tag for node in clip if node.tag not in ('note', 'marker', 'chapter-marker', 'rating', 'keyword'))
    return {'name': project.get('name'), 'duration': _time(sequence.get('duration')), 'clips': clips,
            'unsupported_effects': sorted(set(unsupported))}


def compare_roundtrip(expected, returned, output, project_name=None):
    """A matching XML proves timing/media mapping, not playback or effect fidelity."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result = {'reference': fingerprint(expected), 'returned': fingerprint(returned),
              'status': 'failed', 'scope': 'flat timeline media, clip count and rational timing',
              'gui_playback': 'not_verified', 'effect_fidelity': 'not_verified', 'differences': []}
    try:
        result['dtd'] = {'reference': validate_dtd(expected, output / 'reference-dtd.log'),
                         'returned': validate_dtd(returned, output / 'returned-dtd.log')}
        a, b = _timeline(expected), _timeline(returned, project_name)
        if a['duration'] != b['duration']:
            result['differences'].append('Sequence duration differs')
        if len(a['clips']) != len(b['clips']):
            result['differences'].append('Clip count differs')
        for i, (left, right) in enumerate(zip(a['clips'], b['clips']), 1):
            for key in ('source', 'offset', 'start', 'duration'):
                if left[key] != right[key]:
                    result['differences'].append(f'Clip {i}: {key} differs')
        result['clips_expected'] = len(a['clips'])
        result['clips_returned'] = len(b['clips'])
        result['unsupported_effects'] = b['unsupported_effects']
        result['status'] = 'pass' if not result['differences'] else 'failed'
    except (ValueError, ET.ParseError) as exc:
        result['differences'].append(str(exc))
    finally:
        write(output / 'roundtrip.json', result)
    return result
