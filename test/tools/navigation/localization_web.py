"""Loopback-only fixed-map viewer; whitelist routes, no controls or raw files."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading


def start(map_png, map_info, get_status, port=8765):
    page = Path(__file__).resolve().parents[3]/'test/tools/navigation/web/localization.html'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            route = self.path.split('?',1)[0]
            if route=='/':
                data, kind = page.read_bytes(), 'text/html; charset=utf-8'
            elif route=='/map.png':
                data, kind = map_png, 'image/png'
            elif route=='/status':
                data = json.dumps(dict(map=map_info, **get_status()), allow_nan=False).encode()
                kind = 'application/json'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    return server, thread
