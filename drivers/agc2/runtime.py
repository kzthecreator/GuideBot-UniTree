"""Streaming standalone WebRTC AGC2, 10 ms frames, no second AEC/NS."""
import ctypes
import os
import math
from pathlib import Path
import numpy as np


class AGC2:
    frame_bytes = 320

    def __init__(self, library=None, *, speed=3., noise_dbfs=-50., margin_db=24., ceiling_dbfs=-1.):
        path = library or os.environ.get('GUIDEBOT_AGC2_LIBRARY') or (
            Path.home() / '.local/share/guidebot/deps/webrtc-apm/libguidebot_agc2.so')
        self.lib = ctypes.CDLL(str(path))
        self.lib.guidebot_agc2_new_config.argtypes = [ctypes.c_float] * 4
        self.lib.guidebot_agc2_new_config.restype = ctypes.c_void_p
        self.lib.guidebot_agc2_process.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self.lib.guidebot_agc2_process.restype = ctypes.c_int
        self.lib.guidebot_agc2_free.argtypes = [ctypes.c_void_p]
        self.lib.guidebot_agc2_boundary_samples.argtypes = [ctypes.c_void_p]
        self.lib.guidebot_agc2_boundary_samples.restype = ctypes.c_uint64
        self.context = self.lib.guidebot_agc2_new_config(speed, noise_dbfs, margin_db, ceiling_dbfs)
        if not self.context:
            raise RuntimeError('AGC2 initialization failed')
        self.pending = bytearray()
        self.settings = dict(speed=speed, noise_dbfs=noise_dbfs, margin_db=margin_db,
                             ceiling_dbfs=ceiling_dbfs)
        self.stats = dict(samples=0, energy=0., peak=0, full_scale_samples=0,
                          above_minus1_samples=0, limiter_boundary_samples=0, settings=dict(self.settings))

    def process(self, pcm):
        self.pending.extend(pcm)
        output = bytearray()
        while len(self.pending) >= self.frame_bytes:
            frame = bytes(self.pending[:self.frame_bytes])
            del self.pending[:self.frame_bytes]
            source = ctypes.create_string_buffer(frame)
            destination = ctypes.create_string_buffer(self.frame_bytes)
            if self.lib.guidebot_agc2_process(self.context, source, destination):
                raise RuntimeError('AGC2 processing failed')
            output.extend(destination.raw)
        result = bytes(output)
        if result:
            values = np.frombuffer(result, dtype='<i2').astype(np.float64)
            self.stats['samples'] += len(values)
            self.stats['energy'] += float(np.dot(values, values))
            self.stats['peak'] = max(self.stats['peak'], int(np.max(np.abs(values))))
            self.stats['full_scale_samples'] += int(np.sum(np.abs(values) >= 32767))
            self.stats['above_minus1_samples'] += int(np.sum(np.abs(values) > 32768*10**(-1/20)))
            self.stats['limiter_boundary_samples'] = self.lib.guidebot_agc2_boundary_samples(self.context)
        return result

    def close(self):
        if self.context:
            energy = self.stats['energy']
            count = self.stats['samples']
            self.stats['rms_dbfs'] = (10*math.log10(energy/count/32768**2)
                                      if count and energy else None)
            peak = self.stats['peak']
            self.stats['peak_dbfs'] = 20*math.log10(peak/32768) if peak else None
            self.lib.guidebot_agc2_free(self.context)
            self.context = None
