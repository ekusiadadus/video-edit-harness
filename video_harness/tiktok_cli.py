"""Explicit, read-only TikTok API commands. No posting or media upload."""
from __future__ import annotations

import argparse
import getpass
import json
import sys

from . import tiktok_api as api


def parser():
    root = argparse.ArgumentParser(prog='video-harness tiktok-api')
    actions = root.add_subparsers(dest='action', required=True)
    actions.add_parser('status', help='Local configuration and Keychain state only')
    actions.add_parser('configure', help='Privately prompt and save developer credentials in macOS Keychain')
    auth = actions.add_parser('auth-url', help='Create a desktop PKCE authorization URL and private pending state')
    auth.add_argument('--scopes', default='user.info.basic,video.list',
                      help='Comma-separated approved read scopes')
    connect = actions.add_parser('connect', help='Listen on registered 127.0.0.1 callback and exchange tokens')
    connect.add_argument('--network', action='store_true', help='Explicitly allow OAuth token request')
    connect.add_argument('--scopes', default='user.info.basic,video.list',
                         help='Comma-separated approved read scopes')
    exchange = actions.add_parser('exchange', help='Read callback URL privately and store tokens in Keychain')
    exchange.add_argument('--network', action='store_true', help='Explicitly allow OAuth token request')
    refresh = actions.add_parser('refresh', help='Refresh Keychain tokens without displaying them')
    refresh.add_argument('--network', action='store_true', help='Explicitly allow OAuth token request')
    profile = actions.add_parser('profile', help='Read authorized basic account fields')
    profile.add_argument('--network', action='store_true', help='Explicitly allow Display API request')
    videos = actions.add_parser('videos', help='Read a page of authorized public video metadata')
    videos.add_argument('--network', action='store_true', help='Explicitly allow Display API request')
    videos.add_argument('--max-count', type=int, default=10)
    videos.add_argument('--cursor', type=int)
    return root


def _callback():
    if sys.stdin.isatty():
        return getpass.getpass('Paste TikTok callback URL (hidden): ').strip()
    value = sys.stdin.readline(4097).strip()
    if len(value) > 4096:
        raise api.TikTokAPIError('TikTok callback URL is too long')
    return value


def _private_line(prompt):
    if sys.stdin.isatty():
        return getpass.getpass(prompt).strip()
    value = sys.stdin.readline(4097).strip()
    if len(value) > 4096:
        raise api.TikTokAPIError('TikTok credential input is too long')
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == 'status':
            result = api.status()
        elif args.action == 'configure':
            key = _private_line('TikTok client key (hidden): ')
            secret = _private_line('TikTok client secret (hidden): ')
            redirect = _private_line('Registered loopback redirect URI (hidden): ')
            result = api.configure(key, secret, redirect)
        elif args.action == 'auth-url':
            result = api.auth_url(scopes=args.scopes.split(','))
        else:
            if not args.network:
                raise api.TikTokAPIError('Network access requires --network for this command')
            if args.action == 'exchange':
                result = api.exchange(_callback())
            elif args.action == 'connect':
                result = api.connect(scopes=args.scopes.split(','),
                    on_url=lambda authorization: print(json.dumps(authorization,
                        ensure_ascii=False), flush=True))
            elif args.action == 'refresh':
                result = api.refresh()
            elif args.action == 'profile':
                result = api.profile()
            else:
                result = api.videos(max_count=args.max_count, cursor=args.cursor)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except api.TikTokAPIError as exc:
        # Error strings in this module are fixed, never interpolated from an
        # OAuth callback, HTTP error body or Keychain output.
        parser().error(str(exc))


if __name__ == '__main__':
    main()
