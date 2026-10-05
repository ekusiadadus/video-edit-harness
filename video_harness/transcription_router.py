"""Cloud-only transcription: OpenAI first, Azure second, with bounded fallback."""
from copy import deepcopy
from pathlib import Path
import os

from .common import ROOT, fingerprint, write
from .privacy import permitted_providers, require_cloud_permission
from .runs import unique_id


def transcribe(cfg, out=None, provider=None, model=None, language=None):
    from .cloud_transcript import ProviderFailure, transcribe_cloud
    effective = deepcopy(cfg)
    options = effective.setdefault('transcription', {})
    choice = provider or options.get('provider', 'auto')
    if choice not in ('auto', 'openai', 'azure'):
        raise ValueError('Transcription provider must be auto, openai, or azure; no local ASR is used')
    if model:
        options['cloud_model'] = model
    if language:
        options['language'] = language
    order = permitted_providers(effective, choice)
    out = Path(out) if out else ROOT / 'output' / f'transcription-{unique_id()}'
    out.mkdir(parents=True, exist_ok=False)
    report = {'source': fingerprint(effective['source']), 'requested_provider': choice,
              'order': order,
              'attempts': [], 'status': 'failed', 'local_inference': False}
    for name in report['order']:
        require_cloud_permission(effective, name)
        if fingerprint(effective['source']) != report['source']:
            report['attempts'].append({'provider': name, 'status': 'aborted_source_changed'})
            write(out / 'routing.json', report)
            raise ValueError('Source changed during transcription; no fallback upload was attempted')
        configured = bool(os.getenv('OPENAI_API_KEY')) if name == 'openai' else all(
            os.getenv(key) for key in ('AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_ENDPOINT',
                                      'AZURE_OPENAI_TRANSCRIPTION_DEPLOYMENT', 'AZURE_OPENAI_TIMESTAMP_DEPLOYMENT'))
        if not configured:
            report['attempts'].append({'provider': name, 'status': 'not_configured'})
            continue
        try:
            result = transcribe_cloud(effective, name)
            report['attempts'].append({'provider': name, 'status': 'pass'})
            report['status'] = 'pass'
            report['transcript'] = str(result)
            report['transcript_sha256'] = fingerprint(result)['sha256']
            write(out / 'routing.json', report)
            return result
        except Exception as exc:
            # API exception messages can contain request payloads or credential-adjacent data.
            report['attempts'].append({'provider': name, 'status': 'failed',
                                       'error_type': type(exc).__name__,
                                       'http_status': getattr(exc, 'status_code', None)})
            if fingerprint(effective['source']) != report['source']:
                report['attempts'][-1]['status'] = 'aborted_source_changed'
                write(out / 'routing.json', report)
                raise ValueError('Source changed during transcription; no fallback upload was attempted') from None
            if not isinstance(exc, ProviderFailure):
                report['attempts'][-1]['status'] = 'aborted_local_error'
                report['status'] = 'aborted_local_error'
                write(out / 'routing.json', report)
                raise ValueError(f'Local transcription validation failed; no fallback upload was attempted. See {out / "routing.json"}') from None
    write(out / 'routing.json', report)
    raise ValueError(f'Cloud transcription failed or is not configured. See {out / "routing.json"}')
