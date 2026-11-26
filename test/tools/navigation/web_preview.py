"""Loopback-only, read-only preview. Never exposes arbitrary capture files."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading


def start(directory, port=8765):
    root=Path(directory)
    page=Path(__file__).resolve().parents[3]/'test/tools/navigation/web/index.html'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            route=self.path.split('?',1)[0]
            if route=='/':data=page.read_bytes();kind='text/html; charset=utf-8'
            elif route=='/cloud':
                path=root/'preview.bin'
                if not path.exists():self.send_error(404);return
                data=path.read_bytes();kind='application/octet-stream'
            elif route=='/status':
                try:bridge=json.loads((root/'bridge-status.json').read_text())
                except (OSError,json.JSONDecodeError):bridge={}
                data=json.dumps(dict(bridge=bridge,recording=(root/'record.enabled').exists())).encode();kind='application/json'
            else:self.send_error(404);return
            self.send_response(200);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    return server,thread
