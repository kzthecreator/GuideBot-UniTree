"""Sensor CDR framing, real Mid360 layouts, and read-only preview routes."""
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
from types import SimpleNamespace as NS
import unittest
import urllib.request
import urllib.error
import numpy as np
from runtime.ipc.sensor_wire import send, receive
from GuideBot.perception.preview import cloud_preview
from test.tools.navigation.web_preview import start


class CaptureTests(unittest.TestCase):
    def test_framed_cdr_survives_stream_socket_and_eof_is_explicit(self):
        a,b=socket.socketpair()
        try:
            payload=b'\x00\x01\x00\x00'+bytes(range(255))*2000
            worker=threading.Thread(target=lambda:send(a,dict(track='cloud',received_ns=123),payload))
            worker.start();header,result=receive(b);worker.join(timeout=2)
            self.assertEqual(result,payload);self.assertEqual(header['received_ns'],123)
            a.close()
            with self.assertRaises(EOFError):receive(b)
        finally:a.close();b.close()

    def test_untrusted_size_or_unknown_track_is_rejected_before_payload_read(self):
        for metadata in [dict(track='cloud',size=9*1024*1024,received_ns=0),
                         dict(track='lowcmd',size=1,received_ns=0),
                         dict(track='imu',size=1)]:
            a,b=socket.socketpair()
            try:
                raw=json.dumps(metadata).encode();a.sendall(struct.pack('!I',len(raw))+raw)
                with self.assertRaises(ValueError):receive(b)
            finally:a.close();b.close()

    def test_mid360_unaligned_fields_row_padding_and_nan(self):
        # Actual Mid360 has a 22-byte point step; organized clouds may pad rows.
        fields=[NS(name=n,offset=i*4,datatype=7,count=1) for i,n in enumerate('xyz')]
        data=bytearray(48)
        struct.pack_into('<fff',data,0,1,2,3)
        struct.pack_into('<fff',data,24,float('nan'),5,6)
        msg=NS(fields=fields,width=1,height=2,point_step=22,row_step=24,data=data,is_bigendian=False)
        result=np.frombuffer(cloud_preview(msg),dtype='<f4').reshape(-1,3)
        self.assertEqual(result.tolist(),[[1.,2.,3.]])
        msg.data=b'\0'
        with self.assertRaises(ValueError):cloud_preview(msg)

    def test_http_exposes_only_viewer_preview_and_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'preview.bin').write_bytes(struct.pack('<fff',1,2,3))
            (root/'bridge-status.json').write_text(json.dumps(dict(published=dict(cloud=1))))
            (root/'samples.cdr').write_bytes(b'private-raw-recording')
            server,thread=start(root,0)
            try:
                base='http://127.0.0.1:'+str(server.server_port)
                with urllib.request.urlopen(base+'/cloud') as r:self.assertEqual(len(r.read()),12)
                with urllib.request.urlopen(base+'/status') as r:self.assertEqual(json.load(r)['bridge']['published']['cloud'],1)
                with urllib.request.urlopen(base+'/') as r:self.assertIn('canvas',r.read().decode())
                for path in ['/samples.cdr','/../samples.cdr']:
                    with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(base+path)
            finally:server.shutdown();server.server_close();thread.join(timeout=2)

    def test_recorded_cdr_replay_preserves_every_frame_without_robot_imports(self):
        from test.tools.navigation.replay import run
        from runtime.ipc.sensor_wire import receive
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);endpoint=root/'replay.sock'
            (root/'samples.cdr').write_bytes(b'abcdefghijkl')
            rows=[dict(track='imu',received_ns=1000000000,size=4,offset=0),
                  dict(track='odom',received_ns=1000000001,size=4,offset=4),
                  dict(track='cloud',received_ns=1000000002,size=4,offset=8)]
            (root/'samples.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in rows))
            server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(endpoint));server.listen(1)
            result=[]
            def collect():
                c,_=server.accept()
                with c:
                    for _ in rows:result.append(receive(c))
            thread=threading.Thread(target=collect);thread.start()
            try:run(root,str(endpoint),root)
            finally:thread.join(timeout=3);server.close()
            self.assertEqual([payload for _,payload in result],[b'abcd',b'efgh',b'ijkl'])
            self.assertEqual([header['track'] for header,_ in result],['imu','odom','cloud'])

    def test_missing_capture_is_rejected_before_any_process_starts(self):
        import contextlib
        import io
        from unittest.mock import patch
        from test.tools.navigation.lab import main
        with tempfile.TemporaryDirectory() as tmp:
            with patch('sys.argv',['lab.py','replay','--capture',tmp,'--web']), \
                    patch('subprocess.Popen') as process, contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as raised:main()
                self.assertEqual(raised.exception.code,2)
                process.assert_not_called()
                self.assertIn('Capture file not found:',errors.getvalue())
