"""Source-bound permission checks for cloud transcription."""

from .common import fingerprint

PROVIDERS = ('openai', 'azure')


def require_cloud_permission(cfg, provider):
    """Reject any upload without a matching, explicit source/provider grant.

    The permission is data in the project/session, not inferred from credentials,
    an actor name, or an earlier upload of a different source.
    """
    if provider not in PROVIDERS:
        raise ValueError('Cloud provider must be openai or azure')
    permission = cfg.get('cloud_permission')
    if not isinstance(permission, dict) or permission.get('policy', 'unknown') == 'unknown':
        raise ValueError('Cloud upload permission is unknown for this source; set an explicit source-bound policy before transcription')
    if permission.get('policy') == 'deny':
        raise ValueError('Cloud upload is denied for this source')
    if permission.get('policy') != 'allow':
        raise ValueError('Invalid cloud upload policy')
    source_hash = fingerprint(cfg['source'])['sha256']
    if permission.get('source_sha256') != source_hash:
        raise ValueError('Cloud upload permission does not match the current source SHA-256')
    allowed = permission.get('providers')
    if not isinstance(allowed, list) or not allowed or any(p not in PROVIDERS for p in allowed):
        raise ValueError('Cloud upload permission needs explicit OpenAI/Azure providers')
    if provider not in allowed:
        raise ValueError(f'Cloud upload permission does not include {provider}')
    if not isinstance(permission.get('basis'), str) or not permission['basis'].strip():
        raise ValueError('Cloud upload permission needs a recorded basis')
    return permission


def permitted_providers(cfg, requested='auto'):
    """Return only providers covered by this source's permission grant."""
    if requested != 'auto':
        require_cloud_permission(cfg, requested)
        return [requested]
    permission = cfg.get('cloud_permission')
    if not isinstance(permission, dict) or permission.get('policy', 'unknown') != 'allow':
        require_cloud_permission(cfg, 'openai')
    allowed = permission.get('providers', [])
    if not isinstance(allowed, list) or not allowed:
        require_cloud_permission(cfg, 'openai')
    result = [provider for provider in PROVIDERS if provider in allowed]
    if not result:
        raise ValueError('Cloud upload permission needs an OpenAI or Azure provider')
    for provider in result:
        require_cloud_permission(cfg, provider)
    return result
