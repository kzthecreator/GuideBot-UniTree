"""Description-based action definitions and validated preview timing (no I/O)."""
import math


def description_action(entry, meta, *, description='', label='', enabled=False):
    name = entry['name']
    frames = len(meta.get('keyframe_times_ms', []))
    kind = 'pose' if frames == 1 or (not frames and entry['type'] == 'pose') else 'motion'
    return dict(
        id=name, motion_name=name, asset_type=entry['type'], kind=kind,
        name=label or meta.get('label') or name,
        description=description or meta.get('description') or label or name,
        selection_mode='description',
        gesture_group=meta.get('gesture_group', 'prosody' if entry['category']=='prosody' else 'semantic'),
        gesture_subcategory=meta.get('gesture_subcategory', ''),
        semantic_intents=[], example_phrases=[], interaction_functions=[],
        when_to_use='', avoid_when='', context_requirements=[],
        trigger_source='llm_description', hold_policy='until_next_action_or_state_change',
        post_action_policy='scheduler_decides_no_automatic_neutral',
        release_conditions=['action_switch_needed'],
        parameters={'duration_s': {'type':'number', 'minimum':0.1, 'maximum':600}} if kind=='motion' else {},
        required=['duration_s'] if kind=='motion' else [],
        llm_selectable=enabled, verified=enabled, enabled=enabled)


def confirmed_timing(meta):
    receipt = meta.get('preview_confirmation')
    if receipt is None:
        return None
    if (not isinstance(receipt, dict) or receipt.get('sha256') != meta.get('sha256')
            or receipt.get('version') != meta.get('version')
            or receipt.get('timing_profile') != meta.get('timing_profile')
            or type(receipt.get('total_ms')) is not int or not 1 <= receipt['total_ms'] <= 600000):
        raise ValueError('Preview confirmation no longer matches motion or timing')
    profile = receipt['timing_profile']
    total = receipt['total_ms']
    if total < profile['minimum_total_ms']:
        raise ValueError('Confirmed preview duration is shorter than timing profile')
    weights = profile['phase_weights']
    weight_sum = sum(weights.values())
    if not math.isfinite(weight_sum) or weight_sum <= 0:
        raise ValueError('Invalid confirmed preview weights')
    minimum = profile['minimum_total_ms']
    return dict(preview_total_ms=total, minimum_total_ms=minimum,
                transition_s=minimum/1000*weights['transition']/weight_sum,
                core_s=minimum/1000*weights['core']/weight_sum,
                hold_s=minimum/1000*weights['hold']/weight_sum)
