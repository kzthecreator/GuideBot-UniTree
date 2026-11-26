"""Authenticate the local noVNC WebSocket and capture its real framebuffer.

Read-only: sends no key or pointer events, and never presses the live Enter gate.
Secrets stay in the private desktop directory, not tool output or Git.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
import warnings

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))


def capture(directory, wrong_password=False):
    import numpy as np
    from websockets.sync.client import connect
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        from cryptography.hazmat.primitives.ciphers import Cipher, modes
        from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
    from GuideBot.navigation.mapping.offline_mapping import write_png
    status=json.loads((directory/'status.json').read_text())
    if status.get('state')!='running' or 'port' not in status:
        raise RuntimeError('Browser desktop is not running: '+str(status.get('error') or status.get('state')))
    password=(directory/'vnc-password').read_text().strip()
    with connect('ws://127.0.0.1:%d/websockify'%status['port'],subprotocols=['binary'],max_size=32*1024*1024,open_timeout=5) as ws:
        buffer=bytearray()
        def read(length):
            while len(buffer)<length:
                frame=ws.recv(timeout=15)
                if not isinstance(frame,bytes):raise ValueError('Expected binary VNC frame')
                buffer.extend(frame)
            data=bytes(buffer[:length]);del buffer[:length];return data
        version=read(12)
        if not version.startswith(b'RFB '):raise ValueError('Not an RFB server')
        ws.send(b'RFB 003.008\n')
        count=read(1)[0];types=read(count)
        if 2 not in types or 1 in types:raise ValueError('Server must require VNC authentication')
        ws.send(b'\x02');challenge=read(16)
        secret=('wrongpwd' if wrong_password else password).encode('ascii')[:8].ljust(8,b'\0')
        key=bytes(int(format(byte,'08b')[::-1],2) for byte in secret)
        cipher=Cipher(TripleDES(key+key+key),modes.ECB()).encryptor()
        ws.send(cipher.update(challenge)+cipher.finalize())
        result=struct.unpack('!I',read(4))[0]
        if wrong_password:
            if result==0:raise ValueError('Wrong password was accepted')
            return dict(authentication_rejected=True)
        if result!=0:raise ValueError('VNC authentication failed')
        ws.send(b'\x01')
        header=read(24);width,height=struct.unpack('!HH',header[:4]);read(struct.unpack('!I',header[20:24])[0])
        fmt=struct.pack('!BBBBHHHBBB3x',32,24,0,1,255,255,255,16,8,0)
        ws.send(b'\x00\0\0\0'+fmt)
        ws.send(struct.pack('!BBHi',2,0,1,0))  # Raw encoding: inspect exact rendered pixels.
        ws.send(struct.pack('!BBHHHH',3,0,0,0,width,height))
        pixels=np.zeros((height,width,3),dtype=np.uint8)
        total=0
        while total<width*height:
            kind=read(1)[0]
            if kind==2:continue  # Bell
            if kind==3:
                rest=read(7);read(struct.unpack('!I',rest[3:])[0]);continue
            if kind!=0:raise ValueError('Unexpected server message: '+str(kind))
            rest=read(3);rectangles=struct.unpack('!H',rest[1:])[0]
            for _ in range(rectangles):
                x,y,w,h,encoding=struct.unpack('!HHHHi',read(12))
                if encoding!=0:raise ValueError('Unexpected framebuffer encoding')
                data=np.frombuffer(read(w*h*4),dtype=np.uint8).reshape(h,w,4)
                pixels[y:y+h,x:x+w]=data[:,:,[2,1,0]]
                total+=w*h
        output=directory/'browser-framebuffer.png'
        write_png(output,pixels)
        return dict(authenticated=True,width=width,height=height,framebuffer_pixels=total,
                    screenshot=str(output),keyboard_events_sent=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path.home()/'.local/state/guidebot/navigation/browser-rviz/current')
    parser.add_argument('--wrong-password',action='store_true')
    args=parser.parse_args()
    print(json.dumps(capture(args.directory.resolve(),args.wrong_password),indent=2))
