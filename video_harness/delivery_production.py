"""Licensed, relocatable media dependencies for production FCP deliveries."""
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
import shutil
import xml.etree.ElementTree as ET

from .common import fingerprint, probe, read, write
from .production import verify_production


def preflight(render, production):
    from .production_fcp import inspect_production_xml
    ref = render['files'].get('fcp_production')
    if not ref or fingerprint(ref['path']) != ref:
        raise ValueError('FCP production handoff evidence is missing or changed')
    evidence = read(ref['path'])
    mode = evidence.get('mode')
    if mode not in ('mix', 'editable'):
        raise ValueError('This render permits finished-video-only delivery')
    picture_ref = None
    if mode == 'mix':
        picture_ref = render['files'].get('finished_picture')
        if not picture_ref or fingerprint(picture_ref['path']) != picture_ref or evidence.get('picture_file') != picture_ref:
            raise ValueError('Silent finished-picture evidence is missing or changed')
        picture_streams = probe(picture_ref['path'])['streams']
        if not any(stream['codec_type'] == 'video' for stream in picture_streams) or any(stream['codec_type'] == 'audio' for stream in picture_streams):
            raise ValueError('Finished picture must have video and no audio stream')
    operation = 'mixed_audio_handoff' if mode == 'mix' else 'raw_asset_handoff'
    verify_production(production, operation)
    xml_ref = render['files']['xml']
    if fingerprint(xml_ref['path']) != xml_ref or Path(evidence['xml']).resolve() != Path(xml_ref['path']).resolve():
        raise ValueError('FCP handoff XML does not match sealed render')
    inspect_production_xml(xml_ref['path'], expected=evidence)
    registry = {str(Path(a['path']).resolve()): a for a in production.get('source_assets', []) + production['assets']}
    if mode == 'editable':
        project_ref = render['project']
        if fingerprint(project_ref['path']) != project_ref:
            raise ValueError('FCP source project changed')
        registry.update({str(Path(a['path']).resolve()): a for a in read(project_ref['path']).get('assets', [])})
    generated = {str(Path(r['path']).resolve()): r['sha256'] for r in evidence.get('resources', [])}
    tree = ET.parse(xml_ref['path'])
    dependencies = []
    seen = set()
    for node in tree.findall('./resources/asset/media-rep'):
        parsed = urlparse(node.get('src', ''))
        if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost') or parsed.query or parsed.fragment:
            raise ValueError('Render XML must reference explicit local source files')
        path = Path(unquote(parsed.path)).resolve(strict=True)
        identity = fingerprint(path)
        key = str(path)
        kind = None
        if mode == 'mix' and identity == picture_ref:
            kind = 'finished_video'
        elif mode == 'mix' and render['files'].get('final_mix') == identity:
            kind = 'final_pcm'
        elif mode == 'editable' and key in registry:
            from .assets import validate_asset
            validate_asset(registry[key], production['policy'], 'raw_asset_handoff')
            if identity['sha256'] != registry[key]['sha256']:
                raise ValueError('FCP asset changed')
            kind = 'licensed_raw_asset'
        elif mode == 'editable' and generated.get(key) == identity['sha256'] and path.suffix.lower() == '.png' and path.parent == Path(render['path']).resolve():
            # Only raster titles generated and sealed by the exporter are
            # eligible here; arbitrary referenced files never acquire rights.
            if not path.name.startswith('production-timeline-') or not path.name.endswith('-title.png'):
                raise ValueError('Unknown generated FCP media dependency')
            kind = 'generated_title'
        else:
            raise ValueError('FCP dependency has no handoff authorization: ' + path.name)
        if key not in seen:
            seen.add(key)
            dependencies.append({'identity': identity, 'kind': kind})
    if not dependencies:
        raise ValueError('Production XML has no media dependencies')
    if mode == 'mix' and {item['kind'] for item in dependencies} != {'finished_video', 'final_pcm'}:
        raise ValueError('Mix XML must reference silent finished picture and final PCM exactly')
    return {'mode': mode, 'evidence': evidence, 'tree': tree, 'dependencies': dependencies}


def copy_dependencies(prepared, folder):
    """Copy verified media and replace absolute references with relative URLs."""
    folder = Path(folder)
    media = folder / 'media'
    media.mkdir()
    files, paths, inventory = {}, {}, []
    for item in prepared['dependencies']:
        original = item['identity']
        source = Path(original['path'])
        if fingerprint(source) != original:
            raise ValueError('FCP dependency changed during delivery')
        # Content-derived names avoid collisions between equal basenames.
        name = original['sha256'] + source.suffix.lower()
        target = media / name
        if not target.exists():
            shutil.copy2(source, target)
        copied = fingerprint(target)
        if copied['sha256'] != original['sha256'] or fingerprint(source) != original:
            raise ValueError('FCP dependency copy changed')
        relative = 'media/' + name
        paths[str(source.resolve())] = './' + quote(relative)
        files['media:' + name] = copied
        inventory.append({'path': relative, 'sha256': copied['sha256'], 'bytes': copied['bytes'], 'kind': item['kind']})
    for node in prepared['tree'].findall('./resources/asset/media-rep'):
        key = str(Path(unquote(urlparse(node.get('src')).path)).resolve())
        node.set('src', paths[key])
    xml = folder / 'timeline.fcpxml'
    content = ET.tostring(prepared['tree'].getroot(), encoding='utf-8', xml_declaration=True)
    content = content.replace(b'?>\n', b'?>\n<!DOCTYPE fcpxml>\n', 1)
    with xml.open('xb') as stream:
        stream.write(content)
    files['xml'] = fingerprint(xml)
    manifest = {'version': 1, 'mode': prepared['mode'], 'dependencies': inventory,
                'xml_sha256': files['xml']['sha256'], 'media_urls': 'relative_to_XML',
                'gui_import': 'unverified', 'manual_remaining': prepared['evidence']['manual_remaining']}
    write(folder / 'fcp-dependencies.json', manifest)
    files['fcp_dependencies'] = fingerprint(folder / 'fcp-dependencies.json')
    return files


def verify_dependencies(folder):
    from .production_fcp import resolve_media_path, inspect_production_xml
    folder = Path(folder)
    manifest = read(folder / 'fcp-dependencies.json')
    xml = folder / 'timeline.fcpxml'
    if fingerprint(xml)['sha256'] != manifest['xml_sha256']:
        raise ValueError('Portable FCPXML changed')
    expected = {}
    for item in manifest['dependencies']:
        relative = Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'media':
            raise ValueError('Unsafe FCP dependency path')
        path = folder / relative
        if fingerprint(path)['sha256'] != item['sha256']:
            raise ValueError('FCP dependency bytes changed')
        expected[str(path.resolve())] = item['sha256']
    actual = {str(resolve_media_path(n.get('src'), xml)): None for n in ET.parse(xml).findall('./resources/asset/media-rep')}
    if set(actual) != set(expected):
        raise ValueError('FCP dependency inventory differs from XML')
    inspect_production_xml(xml)
    return manifest
