"""Speech timing policy. No geometry or kinematic duration estimates."""
import math

# Bound online inference work; offline narration still uses full-audio alignment.
ALIGNMENT_OPTIONS = dict(window=12., step=.5, tail=.1, resync_every=0., final_repair=False, cursor_from_starts=True)
BACKEND_OPTIONS = dict(threads=1, reuse_predictor=True, quantized=False, count_offset=-1)

TRANSITION_S = 1.0
DEADLINE_GUARD_S = .1  # Includes the native 50 ms deadline check; not motion time.


def phases(asset):
    meta = asset['metadata']
    profile = meta.get('timing_profile')
    core = 0.
    if asset['frames'] > 1:
        if profile:
            weights = profile['phase_weights']
            core = profile['minimum_total_ms']/1000 * weights['core']/sum(weights.values())
        else:
            core = meta['nominal_duration_ms']/1000
    hold = 0.
    if profile:
        # A fixed entry already covers part of the approved total. Only retain
        # a hold when needed for that floor; semantic holds are requested separately.
        hold = max(0., profile['minimum_total_ms']/1000-TRANSITION_S-core)
    return TRANSITION_S, math.ceil(core*1000)/1000, math.ceil(hold*1000)/1000


def compile_intent(asset, keyframes, anchors, hold_s=0.):
    """Fit one uniform core scale to speech keyframes, never below approval."""
    entry, minimum, saved_hold = phases(asset)
    points = asset['points']
    times = asset['metadata'].get('keyframe_times_ms')
    if not times:
        times = [0.]
        for duration,_ in points[1:]:
            times.append(times[-1]+duration)
    first, last = times[0], times[-1]
    weights = asset['metadata'].get('timing_profile', {}).get('frame_weights')
    if weights:
        positions = [0.]
        for weight in weights:
            positions.append(positions[-1]+weight/sum(weights))
    else:
        positions = [(t-first)/(last-first) if last > first else 0. for t in times]
    fractions = [positions[row['frame']] for row in keyframes]
    targets = [anchors[row['unit']]['start'] for row in keyframes]
    core = minimum
    if len(targets) > 1:
        span = fractions[-1]-fractions[0]
        if span <= 0:
            raise ValueError('keyframes_not_increasing')
        fitted = (targets[-1]-targets[0])/span
        if fitted + .001 < minimum:
            raise ValueError('keywords_too_close_for_approved_core')
        core = max(minimum, fitted)
    arrival = targets[0]-fractions[0]*core
    if any(abs(arrival+fraction*core-target) > .025 for fraction,target in zip(fractions,targets)):
        raise ValueError('inconsistent_keyframe_timing')
    start = arrival-entry
    hold = max(saved_hold, hold_s)
    end = arrival+core+hold
    if start < 0 or end+DEADLINE_GUARD_S > 300 or core > 600:
        raise ValueError('intent_outside_playback_window')
    return dict(start_s=start, arrival_s=arrival, end_s=end,
                transition_s=entry, core_s=core, hold_s=hold,
                deadline_s=end+DEADLINE_GUARD_S)
