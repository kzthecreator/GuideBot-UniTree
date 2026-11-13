"""LocalVQE C API and timestamped G1 reference adapter (16 kHz mono PCM16)."""

from collections import deque
import ctypes
import os
from pathlib import Path
import threading
import time

import numpy as np

from audio import RATE


def installation():
    shared = Path('/opt/localvqe')
    return Path(os.environ.get('LOCALVQE_HOME', shared if shared.is_dir() else
                Path.home()/'.local/share/guidebot/deps/LocalVQE'))


class Processor:
    def __init__(self, model=None, library=None, threads=None):
        root = installation()
        self.model = Path(model or os.environ.get('LOCALVQE_MODEL', root/'models/localvqe-v1.2-1.3M-f32.gguf'))
        threads = int(os.environ.get('LOCALVQE_THREADS', '2')) if threads is None else threads
        path = Path(library or os.environ.get('LOCALVQE_LIBRARY', root/'ggml/build/liblocalvqe.so'))
        if not path.is_file() or not self.model.is_file():
            raise RuntimeError(f'LocalVQE library/model missing: {path}; {self.model}')
        self.lib = ctypes.CDLL(str(path))
        handle = ctypes.c_size_t
        self.pointer = ctypes.POINTER(ctypes.c_int16)
        signatures = {
            'localvqe_options_new': ([], handle),
            'localvqe_options_free': ([handle], None),
            'localvqe_options_set_model_path': ([handle, ctypes.c_char_p], ctypes.c_int),
            'localvqe_options_set_threads': ([handle, ctypes.c_int], ctypes.c_int),
            'localvqe_new_with_options': ([handle], handle),
            'localvqe_free': ([handle], None),
            'localvqe_last_error': ([handle], ctypes.c_char_p),
            'localvqe_set_noise_gate': ([handle, ctypes.c_int, ctypes.c_float], ctypes.c_int),
            'localvqe_process_s16': ([handle, self.pointer, self.pointer, ctypes.c_int, self.pointer], ctypes.c_int),
            'localvqe_process_frame_s16': ([handle, self.pointer, self.pointer, ctypes.c_int, self.pointer], ctypes.c_int),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = arguments, result
        self.context = 0
        options = self.lib.localvqe_options_new()
        if not options:
            raise RuntimeError('LocalVQE options allocation failed')
        try:
            if self.lib.localvqe_options_set_model_path(options, os.fsencode(self.model)):
                raise RuntimeError('LocalVQE rejected model path')
            if self.lib.localvqe_options_set_threads(options, threads):
                raise ValueError('LocalVQE threads must be 0..32')
            self.context = self.lib.localvqe_new_with_options(options)
        finally:
            self.lib.localvqe_options_free(options)
        if not self.context:
            raise RuntimeError('LocalVQE model initialization failed; see native loader output')
        if self.lib.localvqe_set_noise_gate(self.context, 0, -90.):
            self.close()
            raise RuntimeError('Could not disable LocalVQE output gate')

    def process(self, microphone, reference, streaming=False):
        if not self.context:
            raise RuntimeError('LocalVQE is closed')
        mic = np.ascontiguousarray(microphone, dtype='<i2')
        ref = np.ascontiguousarray(reference, dtype='<i2')
        if mic.ndim != 1 or ref.shape != mic.shape:
            raise ValueError('LocalVQE requires equal-length mono inputs')
        if (streaming and len(mic) != 256) or (not streaming and len(mic) < 512):
            raise ValueError('LocalVQE requires 256 samples per streaming hop or >=512 per clip')
        output = np.empty_like(mic)
        function = self.lib.localvqe_process_frame_s16 if streaming else self.lib.localvqe_process_s16
        code = function(self.context, mic.ctypes.data_as(self.pointer), ref.ctypes.data_as(self.pointer),
                        len(mic), output.ctypes.data_as(self.pointer))
        if code:
            message = self.lib.localvqe_last_error(self.context)
            raise RuntimeError(f'LocalVQE processing failed ({code}): {message.decode() if message else "unknown"}')
        return output

    def close(self):
        if self.context:
            self.lib.localvqe_free(self.context)
            self.context = 0


class LocalVQEEcho:
    frame_samples = 256

    def __init__(self, delay_ms=0, model=None):
        if not 0 <= delay_ms <= 1000:
            raise ValueError('Reference delay must be 0..1000 ms')
        self.processor = Processor(model=model)
        self.delay = delay_ms/1000
        self.lock = threading.Lock()
        self.reference = deque()
        self.reference_until = 0.
        self.capture_until = None
        self.pending = bytearray()
        self.stats = {'frames': 0, 'reference_frames': 0, 'input_energy': 0., 'output_energy': 0.,
                      'processing_seconds': 0., 'max_hop_ms': 0., 'backend': 'LocalVQE',
                      'model': str(self.processor.model)}

    def add_reference(self, pcm, submitted_at):
        with self.lock:
            start = max(submitted_at+self.delay, self.reference_until)
            samples = np.frombuffer(pcm, dtype='<i2').copy()
            self.reference.append((start, samples))
            self.reference_until = start+len(samples)/RATE
            while self.reference and self.reference[0][0] < submitted_at-4:
                self.reference.popleft()

    def stop_reference(self, stopped_at):
        with self.lock:
            self.reference = deque((start, samples[:min(len(samples), max(0, round((stopped_at-start)*RATE)))])
                                   for start, samples in self.reference if start < stopped_at)
            self.reference_until = stopped_at

    def process(self, pcm, received_at):
        with self.lock:
            observed = received_at-len(pcm)/(2*RATE)
            if self.capture_until is None or abs(observed-self.capture_until) > .25:
                self.capture_until = observed
                self.pending.clear()
            # Keep a continuous sample clock between discontinuities. Packet
            # arrival jitter must not shift the reference by samples every hop.
            start = self.capture_until-len(self.pending)/(2*RATE)
            self.capture_until += len(pcm)/(2*RATE)
            self.pending.extend(pcm)
            size = len(self.pending)//512*512
            recorded = np.frombuffer(bytes(self.pending[:size]), dtype='<i2')
            del self.pending[:size]
            far = np.zeros(len(recorded), dtype='<i2')
            for ref_start, samples in self.reference:
                offset = round((ref_start-start)*RATE)
                left, right = max(0, offset), min(len(recorded), offset+len(samples))
                if left < right:
                    far[left:right] = samples[left-offset:right-offset]
            output = []
            for offset in range(0, len(recorded), 256):
                near, ref = recorded[offset:offset+256], far[offset:offset+256]
                began = time.monotonic()
                result = self.processor.process(near, ref, streaming=True)
                elapsed = time.monotonic()-began
                self.stats['processing_seconds'] += elapsed
                self.stats['max_hop_ms'] = max(self.stats['max_hop_ms'], elapsed*1000)
                self.stats['frames'] += 1
                if np.any(ref):
                    self.stats['reference_frames'] += 1
                    self.stats['input_energy'] += float(np.sum(near.astype(float)**2))
                    self.stats['output_energy'] += float(np.sum(result.astype(float)**2))
                output.append(result.tobytes())
            while self.reference and self.reference[0][0]+len(self.reference[0][1])/RATE < start-1:
                self.reference.popleft()
            return b''.join(output)

    def close(self):
        with self.lock:
            self.processor.close()
