"""Replay preserved CDR samples over local IPC, without robot DDS or SDK imports."""
import json
from pathlib import Path
import socket
import time
from runtime.ipc.sensor_wire import send, MAX_PAYLOAD, TRACKS


def run(capture, endpoint, directory, duration=None):
    root=Path(capture);output=Path(directory)/'source-status.json'
    stats=dict(replay=True,sources={},errors=[])
    start=time.monotonic();wall=time.time_ns();first=None;previous=None
    try:
        with (root/'samples.cdr').open('rb') as data, (root/'samples.jsonl').open() as index, \
                socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
            connection.settimeout(3);connection.connect(endpoint)
            total=(root/'samples.cdr').stat().st_size
            for line in index:
                row=json.loads(line)
                if row.get('track') not in TRACKS or any(type(row.get(k)) is not int for k in ('size','offset','received_ns')):
                    raise ValueError('Invalid capture index')
                if not 0 < row['size'] <= MAX_PAYLOAD or row['offset'] < 0 or row['offset']+row['size'] > total:
                    raise ValueError('Capture payload outside file bounds')
                stamp=row['received_ns']
                if previous is not None and stamp < previous:raise ValueError('Capture receive clock moved backwards')
                first=stamp if first is None else first;previous=stamp
                elapsed=(stamp-first)/1e9
                if duration is not None and elapsed>=duration:break
                while time.monotonic()-start < elapsed:
                    time.sleep(max(0.,min(.02,elapsed-(time.monotonic()-start))))
                data.seek(row['offset']);payload=data.read(row['size'])
                send(connection,dict(track=row['track'],received_ns=wall+stamp-first),payload)
                item=stats['sources'].setdefault(row['track'],dict(count=0))
                item['count']+=1
    except KeyboardInterrupt:pass
    except Exception as error:
        stats['errors'].append(type(error).__name__+': '+str(error))
        raise
    finally:
        stats['elapsed_s']=time.monotonic()-start
        output.write_text(json.dumps(stats,indent=2))
