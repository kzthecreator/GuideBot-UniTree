"""Best measured FunASR configuration; still best effort, not a deadline guarantee.

Full-prefix inference avoids accumulated sliding-cursor drift. The window equals
the existing response length limit; it does not delay inference until 120s.
See docs/experiments/realtime-optimization.md for frozen-reference validation.
"""

ALIGNMENT_OPTIONS = dict(window=120., step=.5, tail=.1, resync_every=0., final_repair=True)
BACKEND_OPTIONS = dict(threads=1, reuse_predictor=True, quantized=True, count_offset=-1)
