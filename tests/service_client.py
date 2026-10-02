"""Python 의존성은 모의하고 이전된 HTTP는 실제 격리 Spring을 검증한다."""
from __future__ import annotations

import os
import httpx
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from fastapi.testclient import TestClient

on_job_submitted = None
_server = None


class PythonBridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def relay(self):
        client = self.server.target
        size = int(self.headers.get('Content-Length', '0'))
        reply = client.request(self.command, self.path, headers=dict(self.headers),
                               content=self.rfile.read(size), follow_redirects=False)
        self.send_response(reply.status_code)
        for name, value in reply.headers.multi_items():
            if name.lower() not in {'content-length', 'transfer-encoding', 'connection', 'content-encoding'}:
                self.send_header(name, value)
        self.send_header('Content-Length', str(len(reply.content)))
        self.end_headers()
        self.wfile.write(reply.content)

    do_GET = do_POST = do_PATCH = do_DELETE = do_PUT = relay


class ServiceTransport(httpx.BaseTransport):
    def __init__(self, python_transport):
        self.python = python_transport
        self.native = httpx.HTTPTransport()
        self.root = os.environ["TEST_CORE_URL"].rstrip("/")
        self.native_requests = []

    def handle_request(self, request):
        if request.url.path.startswith('/api/'):
            self.native_requests.append((request.method, request.url.path))
            url = self.root + request.url.raw_path.decode()
            forwarded = httpx.Request(request.method, url, headers=request.headers, content=request.read())
            reply = self.native.handle_request(forwarded)
            if request.method == 'POST' and reply.status_code in (200, 201, 202) and on_job_submitted:
                reply.read()
                try:
                    body = __import__('json').loads(reply.content)
                except ValueError:
                    body = {}
                if isinstance(body, dict) and body.get('job_id'):
                    on_job_submitted(body['job_id'])
            return reply
        return self.python.handle_request(request)

    def close(self):
        self.native.close()
        self.python.close()


class ServiceTestClient(TestClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._transport = ServiceTransport(self._transport)
        self.python_client = TestClient(*args, **kwargs)

    def __enter__(self):
        global _server
        if _server is None:
            _server = ThreadingHTTPServer(('0.0.0.0', 8015), PythonBridgeHandler)
            threading.Thread(target=_server.serve_forever, daemon=True).start()
        self.python_client.__enter__()
        _server.target = self.python_client
        return super().__enter__()

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.python_client.__exit__(*args)
