"""GPU FP32 full-prefix alignment; sliding 5/10/15/20s failed drift checks.

The 120s window equals the existing reply length limit. Every update computes
the entire received prefix; startup warmup and action replan recovery remain.
"""

ALIGNMENT_OPTIONS = dict(window=120., step=.5, tail=.1, resync_every=0., final_repair=True)
BACKEND_OPTIONS = dict(threads=1, reuse_predictor=True, quantized=False, count_offset=-1)
