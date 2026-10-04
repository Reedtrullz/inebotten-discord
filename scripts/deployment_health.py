#!/usr/bin/env python3
"""Minimal standard-library readiness probe for the baked full source revision."""
import json
import os
from pathlib import Path
import re
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def local_opener():
    return build_opener(ProxyHandler({}), _NoRedirect())


def is_healthy(value, revision):
    return (isinstance(revision, str) and bool(re.fullmatch('[0-9a-f]{40}', revision))
            and isinstance(value, dict) and value.get('status') == 'healthy'
            and value.get('revision') == revision and value.get('readiness') == 'ready')


def main():
    try:
        revision = (Path(__file__).resolve().parents[1] / 'commit_hash.txt').read_text(encoding='ascii').strip()
        port = int(os.environ.get('CONSOLE_PORT', '8080'))
        if not 1 <= port <= 65535:
            return 1
        opener = local_opener()
        with opener.open(f'http://127.0.0.1:{port}/health', timeout=3) as response:
            raw = response.read(32769)
        return 0 if len(raw) <= 32768 and is_healthy(json.loads(raw), revision) else 1
    except (OSError, UnicodeError, ValueError):
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
