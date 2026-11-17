"""Optional FP32 ONNX encoder experiment; frontend and predictor stay upstream.

Exported weights live outside the repository. Each export must pass variable
length encoder and timestamp comparisons before it is used for replay.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from GuideBot.conversation.timestamps import MonotonicBackend, text_units


def attach(backend, path, threads=1):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')
    session = ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])
    torch = backend.torch
    class Encoder(torch.nn.Module):
        def forward(self, features, lengths):
            encoded, encoded_lengths = session.run(None, {'features':features.numpy(), 'lengths':lengths.numpy()})
            return torch.from_numpy(encoded), torch.from_numpy(encoded_lengths), None
    backend.model.model.encoder = Encoder()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    backend = MonotonicBackend(threads=1, reuse_predictor=True)
    torch = backend.torch
    original = backend.model.model.encoder
    from funasr.models.sanm.encoder import SANMEncoderExport
    exported = SANMEncoderExport(copy.deepcopy(original)).eval()
    path = args.output/'encoder.onnx'
    if not path.exists():
        with torch.inference_mode():
            torch.onnx.export(exported, (torch.randn(1,100,560),torch.tensor([100],dtype=torch.int32)),
                              str(path), input_names=['features','lengths'],
                              output_names=['encoded','encoded_lengths'], opset_version=17,
                              dynamic_axes={'features':{1:'frames'},'encoded':{1:'frames'}},
                              do_constant_folding=True)
    from funasr.utils.load_utils import extract_fbank
    audio, rate = sf.read('recordings/long-reply/reply.wav', dtype='int16')
    assert rate == 16000
    results = []
    for duration in (.59,1.,3.86,8.,16.,32.,45.48):
        pcm = audio[:round(duration*16000)].astype('<i2').tobytes()
        labels = text_units('测'*240)
        torch.manual_seed(1729)
        features,lengths = extract_fbank([np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768],
                                       frontend=backend.model.kwargs['frontend'])
        with torch.inference_mode():
            expected, _, _ = original(features,lengths)
        for repeat in range(2):
            backend.model.model.encoder = original
            torch.manual_seed(1729)
            normal, estimate = backend.align(pcm, labels)
            normal_profile = dict(backend.last_profile)
            attach(backend,path)
            with torch.inference_mode():
                actual, _, _ = backend.model.model.encoder(features,lengths)
            error = float((actual-expected).abs().max())
            torch.manual_seed(1729)
            converted, converted_estimate = backend.align(pcm,labels)
            row = dict(duration=duration,repeat=repeat,encoder_max_error=error,
                       exact_timestamps=normal==converted,normal_count=estimate,onnx_count=converted_estimate,
                       normal_profile=normal_profile,onnx_profile=dict(backend.last_profile))
            results.append(row)
            (args.output/'comparison.json').write_text(json.dumps(results,indent=2))
            print(json.dumps(row),flush=True)
            if len(normal)!=len(converted):
                raise AssertionError('ONNX changed character count')


if __name__ == '__main__':
    main()
