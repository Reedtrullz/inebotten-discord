from unittest.mock import AsyncMock, patch

import pytest

from scripts import deployment_health
from utils.deployment_contract import built_revision


def test_healthcheck_rejects_short_source_stale_revision_and_degraded_subsystems():
    healthy = {'status':'healthy','revision':'a'*40,'readiness':'ready'}
    assert deployment_health.is_healthy(healthy, 'a'*40)
    assert not deployment_health.is_healthy(healthy, 'aaaaaaa')
    assert not deployment_health.is_healthy(healthy, 'b'*40)
    assert not deployment_health.is_healthy({**healthy,'readiness':'degraded'}, 'a'*40)
    assert not deployment_health.is_healthy({**healthy,'status':'starting'}, 'a'*40)


def test_revision_only_accepts_full_baked_metadata(tmp_path):
    assert built_revision(tmp_path) is None
    (tmp_path/'commit_hash.txt').write_text('abcdef0')
    assert built_revision(tmp_path) is None
    (tmp_path/'commit_hash.txt').write_text('a'*40+'\n')
    assert built_revision(tmp_path) == 'a'*40


def test_health_probe_does_not_follow_redirect_to_another_route(tmp_path, monkeypatch):
    import json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if self.path=='/health':
                self.send_response(302);self.send_header('Location','/another-route');self.end_headers()
            else:
                self.send_response(200);self.end_headers()
                self.wfile.write(json.dumps({'status':'healthy','revision':'a'*40,'readiness':'ready'}).encode())
        def log_message(self,*a):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    (tmp_path/'commit_hash.txt').write_text('a'*40)
    monkeypatch.setattr(deployment_health,'Path',lambda *a:tmp_path/'scripts'/'probe.py')
    monkeypatch.setenv('CONSOLE_PORT',str(server.server_port))
    try:
        assert deployment_health.main()==1
        assert requests==['/health']
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
