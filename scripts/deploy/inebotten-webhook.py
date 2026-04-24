#!/usr/bin/env python3
"""Minimal GitHub webhook listener for Inebotten deployments."""

import hashlib
import hmac
import json
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


SECRET = os.environ.get("WEBHOOK_SECRET", "").encode()
PORT = int(os.environ.get("WEBHOOK_PORT", "9000"))
BRANCH = os.environ.get("WEBHOOK_BRANCH", "refs/heads/master")
UPDATE_SERVICE = os.environ.get("UPDATE_SERVICE", "inebotten-update.service")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def _send(self, code, body):
        payload = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, "ok\n")
        else:
            self._send(404, "not found\n")

    def do_POST(self):
        if self.path != "/github-webhook":
            self._send(404, "not found\n")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)

        signature = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
        if not SECRET or not hmac.compare_digest(signature, expected):
            self._send(403, "bad signature\n")
            return

        event = self.headers.get("X-GitHub-Event", "")
        if event == "ping":
            self._send(200, "pong\n")
            return
        if event != "push":
            self._send(202, "ignored event\n")
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send(400, "bad json\n")
            return

        if payload.get("ref") != BRANCH:
            self._send(202, "ignored branch\n")
            return

        subprocess.Popen(
            ["systemctl", "start", UPDATE_SERVICE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._send(202, "update queued\n")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Listening on 0.0.0.0:{PORT}", flush=True)
    server.serve_forever()
