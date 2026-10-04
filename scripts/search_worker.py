"""Private stdio-only SDK worker; never import config, app stores or Discord."""
import contextlib
import json
import os
import sys


def search(data):
    if os.getenv('INEBOTTEN_OFFLINE_TESTS') == '1' or os.getenv('INEBOTTEN_OFFLINE') == '1':
        raise RuntimeError('offline_provider_disabled')
    provider = data['provider']
    query = data['query']
    if not isinstance(query, str) or not 1 <= len(query) <= 1000:
        raise ValueError('invalid_query')
    count = data['max_results']
    if type(count) is not int or not 1 <= count <= 5:
        raise ValueError('invalid_result_limit')
    timeout = max(.01, min(float(data['timeout']), 3))
    if provider == 'tavily':
        from tavily import TavilyClient
        client = TavilyClient(api_key=data['key'])
        try:
            client.session.trust_env = False
            return client.search(query=query, timeout=timeout, search_depth='advanced',
                                 max_results=count, include_raw_content=True).get('results', [])
        finally:
            client.session.close()
    if provider == 'google':
        from googlesearch import search as google_search
        return [{'url': url} for url in google_search(query, num_results=count, lang='no',
                                                       timeout=timeout, ssl_verify=True, unique=True)]
    if provider == 'duckduckgo':
        from ddgs import DDGS
        DDGS.threads = 1
        with DDGS(timeout=timeout) as client:
            return client.text(query, region=data['region'], max_results=count, backend='duckduckgo')
    raise ValueError('unsupported_provider')


def main():
    try:
        raw = sys.stdin.buffer.read(8193)
        if len(raw) > 8192:
            raise ValueError('oversized_input')
        data = json.loads(raw)
        with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            results = search(data)
        bounded = []
        limits = {'url': 2048, 'href': 2048, 'title': 300, 'body': 3000, 'content': 3000,
                  'raw_content': 3000, 'snippet': 3000, 'published_at': 64, 'published_date': 64, 'date': 64}
        for row in results[:5]:
            if isinstance(row, dict):
                bounded.append({key: value[:limit] for key, limit in limits.items()
                                if isinstance(value := row.get(key), str)})
        reply = {'status': 'ok', 'results': bounded}
    except Exception as error:
        reply = {'status': 'unavailable', 'reason': type(error).__name__, 'results': []}
    sys.stdout.write(json.dumps(reply, ensure_ascii=False))


if __name__ == '__main__':
    main()
