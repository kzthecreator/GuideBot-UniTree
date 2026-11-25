"""Typed ROS converters; import only in the configured ROS process."""
from copy import deepcopy

from rosidl_runtime_py.convert import message_to_ordereddict
from rosidl_runtime_py.set_message import set_message_fields
from guidebot_interfaces.msg import ActionPlan, InteractionContext, PlanningInput
from GuideBot.gesture.catalog import Plan
from .protocol import context_from_wire, context_to_wire


def to_dict(message):
    return dict(message_to_ordereddict(message))


def message(cls, values):
    result = cls()
    set_message_fields(result, deepcopy(values))
    return result


def plan_message(plan):
    row = plan.as_dict()
    duration = row.get('duration_s')
    return message(ActionPlan, dict(action=row['action'], start_unit=row['start_unit'],
                   arrival_unit=row['arrival_unit'], has_duration=duration is not None,
                   duration_s=float(duration or 0)))


def plan_from_message(row):
    return Plan(row.action, row.start_unit, row.arrival_unit,
                {'duration_s': row.duration_s} if row.has_duration else {})


def planning_message(payload, session, generation, context_version=0, expiry=0):
    value = dict(session_id=session, generation=generation, response_id=payload['response_id'],
                 units=payload['units'], eligible_anchor_ids=list(payload['eligible_anchor_ids']),
                 targets=[dict(id=t['id'], label=t.get('label', t.get('name', ''))) for t in payload['targets']],
                 existing_actions=[to_dict(plan_message(Plan(r['action'], r['start_unit'], r['arrival_unit'],
                      {k:v for k,v in r.items() if k == 'duration_s'}))) for r in payload['existing_actions']],
                 response_complete=payload['response_complete'],
                 context=context_to_wire(payload['interaction_context'], session, generation,
                                         context_version, expiry))
    return message(PlanningInput, value)


def planning_payload(value):
    result = to_dict(value)
    return dict(response_id=value.response_id, units=result['units'],
                eligible_anchor_ids=result['eligible_anchor_ids'], targets=result['targets'],
                existing_actions=[plan_from_message(p).as_dict() for p in value.existing_actions],
                response_complete=value.response_complete,
                interaction_context=context_from_wire(result['context']))
