"""FP32 FunASR configuration selected after the Foxy regression comparison; still best effort, not a deadline guarantee.

Full-prefix inference avoids accumulated sliding-cursor drift. The window equals
the existing response length limit; it does not delay inference until 120s.
FP32 selection: docs/experiments/timestamp-runtime-retest-20261125.md.
Earlier scheduling evidence: docs/experiments/realtime-optimization.md.
"""

ALIGNMENT_OPTIONS = dict(window=120., step=.5, tail=.1, resync_every=0., final_repair=True)
BACKEND_OPTIONS = dict(threads=1, reuse_predictor=True, quantized=False, count_offset=-1)
