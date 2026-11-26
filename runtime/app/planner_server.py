"""Session-owned native llama.cpp server. Never initializes audio or robot SDKs."""
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlparse

import requests

from GuideBot.gesture.provider import local_base_url, provider_name


class PlannerServer:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.process = self.log = None
        self.http = requests.Session()
        self.http.trust_env = False

    def ready(self):
        base = local_base_url()
        try:
            health = self.http.get(base+'/health', timeout=1)
            if health.status_code != 200:
                return False
            models = self.http.get(base+'/models', timeout=1)
            models.raise_for_status()
            expected = os.environ.get('GUIDEBOT_PLANNER_MODEL', 'qwen3-1.7b')
            return expected in [row.get('id') for row in models.json().get('data', [])]
        except (requests.RequestException, ValueError, TypeError):
            return False

    def start(self):
        if provider_name() != 'local_qwen':
            return self
        # Explicit opt-in: speculative batching can change quote selection.
        speculation = os.environ.get('GUIDEBOT_QWEN_SPECULATION', 'off')
        modes = {
            'off': [],
            'ngram-simple': ['--spec-type', 'ngram-simple',
                             '--spec-ngram-simple-size-n', '8',
                             '--spec-ngram-simple-size-m', '16'],
            'ngram-map-k': ['--spec-type', 'ngram-map-k',
                            '--spec-ngram-map-k-size-n', '4',
                            '--spec-ngram-map-k-size-m', '16',
                            '--spec-ngram-map-k-min-hits', '1'],
        }
        if speculation not in modes:
            raise ValueError('GUIDEBOT_QWEN_SPECULATION must be off, ngram-simple, or ngram-map-k')
        if self.ready():
            return self  # Reuse an explicitly running service; never stop its process.
        data = Path.home()/'.local/share/guidebot'
        binary = Path(os.environ.get('GUIDEBOT_LLAMA_SERVER', str(data/'deps/llama.cpp/build/bin/llama-server')))
        model = Path(os.environ.get('GUIDEBOT_QWEN_MODEL', str(data/'models/qwen3-1.7b/Qwen3-1.7B-Q8_0.gguf')))
        if not binary.is_file() or not model.is_file():
            raise RuntimeError('Local Qwen installation missing; see docs/setup.md')
        port = urlparse(local_base_url()).port or 80
        self.directory.mkdir(parents=True, exist_ok=True)
        self.log = (self.directory/'qwen-server.log').open('w')
        args = [str(binary), '--model', str(model), '--alias',
                os.environ.get('GUIDEBOT_PLANNER_MODEL', 'qwen3-1.7b'),
                '--host', '127.0.0.1', '--port', str(port), '--ctx-size', '4096',
                '--parallel', '1', '--threads', '4', '--threads-batch', '4', '--device', 'CUDA0', '--n-gpu-layers', '99',
                '--log-verbosity', '4', '--fit', 'off', '--cache-type-k', 'f16', '--cache-type-v', 'f16', '--jinja', '--reasoning', 'off', '--no-webui']
        args.extend(modes[speculation])
        try:
            environment = {key: value for key, value in os.environ.items()
                           if not key.startswith(('DEEPSEEK_', 'STEP_', 'DOUBAO_'))}
            self.process = subprocess.Popen(args, stdout=self.log, stderr=subprocess.STDOUT, env=environment)
            deadline = time.monotonic()+90
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    break
                if self.ready():
                    return self
                time.sleep(.2)
            raise RuntimeError('Local Qwen startup failed; see '+str(self.directory/'qwen-server.log'))
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()
        self.http.close()
