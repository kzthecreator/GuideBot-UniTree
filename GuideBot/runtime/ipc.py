"""Private JSONL RPC; core inter-module contracts live in ROS message types."""
import json
import socket
import socketserver
import threading

MAX_BYTES = 262144


def call(path, value, timeout=8):
    data = json.dumps(value, allow_nan=False, ensure_ascii=False).encode() + b'\n'
    if len(data) > MAX_BYTES:
        raise ValueError('IPC request too large')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(data)
        with connection.makefile('rb') as reader:
            raw = reader.readline(MAX_BYTES + 1)
    if not raw.endswith(b'\n') or len(raw) > MAX_BYTES:
        raise RuntimeError('Invalid IPC reply')
    result = json.loads(raw)
    if not result.get('ok'):
        raise RuntimeError(result.get('error', 'IPC rejected'))
    return result.get('value')


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, path, handler):
        self.handler = handler
        super().__init__(str(path), Handler)
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=2)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(8)
        try:
            raw = self.rfile.readline(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES or not raw.endswith(b'\n'):
                raise ValueError('IPC framing rejected')
            request = json.loads(raw)
            value = self.server.handler(request)
            result = {'ok': True, 'value': value}
        except Exception as error:
            # Never return arbitrary exception bodies, which may contain credentials.
            result = {'ok': False, 'error': type(error).__name__}
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode() + b'\n'
        if len(encoded) > MAX_BYTES:
            encoded = b'{"ok": false, "error": "reply too large"}\n'
        self.wfile.write(encoded)
