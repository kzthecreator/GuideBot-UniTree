"""Internal host process. No interactive or direct conversation entry."""
import argparse
import json
import os
from pathlib import Path
import signal
import threading

from .ipc import Server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    from .workers.voice import VoiceWorker
    config = json.loads((args.root/'worker.json').read_text())
    worker = VoiceWorker(config['options'], args.root, config['session_id'], None)
    server = Server(args.root/'ipc/resources.sock', worker.rpc)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    (args.root/'worker.ready').write_text('ready')
    try:
        stopped.wait()
    finally:
        worker.close()
        server.close()


if __name__ == '__main__':
    main()
