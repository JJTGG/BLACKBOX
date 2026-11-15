from __future__ import annotations
import os
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from .http_api import Handler, API

class ApplicationHandler(Handler):
    def do_GET(self):
        if self.path in ('/','/index.html'):
            body=Path(__file__).resolve().parent.parent.joinpath('web','index.html').read_bytes()
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
        return super().do_GET()

def serve_application(store, auth, host='127.0.0.1', port=8080):
    ApplicationHandler.api=API(store,auth)
    from http.server import ThreadingHTTPServer
    return ThreadingHTTPServer((host,port),ApplicationHandler)
