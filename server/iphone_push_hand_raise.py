from fastapi import HTTPException

from team_friends import blocked
from team_trip_context import resolve_trip_context
from team_trip_route_segments import TeamTripRouteSegments
from team_trip_signal_contexts import GROUP_RULE


def hand_raise_visible(conn, event, auth, now):
    trip, signal = event['trip_id'], event['resource_id']
    actor, recipient = event['actor_id'], event['recipient_id']
    signals = auth.trip_signal_contexts
    try:
        context = resolve_trip_context(auth, conn, trip, recipient, states=('active',), locked_for_read=True)
        members = signals.members(conn, trip, context['roomId'])
        if (actor == recipient or actor not in members or recipient not in members
                or (actor != context['ownerId'] and blocked(conn, actor, context['ownerId']))):
            return False
        row = signals.visible(conn, context, signal, recipient, members)
        segments = TeamTripRouteSegments(auth.trip_service)
        for account in (actor, recipient):
            segments.check_shared(conn, trip, account)
    except HTTPException as error:
        if error.status_code in (403, 404, 409):
            return False
        raise

    sender, value, _, saved, _ = row
    if not signals.is_hand_raise(conn, trip, signal, value, saved):
        return False
    if any(members[peer]['joinedAt'] != saved['roster'].get(peer, {}).get('joinedAt')
           for peer in (actor, recipient)):
        return False
    resolution = signals.resolution(conn, context, row, members)
    if event['kind'] == 'hand_raise':
        if sender != actor or resolution != 'pending':
            return False
        current = signals.current(conn, context, members)
        if not current or current[0] != signal:
            return False
        if saved.get('decisionRule') == GROUP_RULE:
            group = signals.member_group(saved['groupRoster'], recipient)
            return group in saved['requiredCarIds'] and group not in saved['groupResponses']
        return True

    if (event['kind'] != 'hand_raise_reaction' or sender != recipient or actor not in saved['votes']
            or resolution not in ('pending', 'agreed', 'passed')):
        return False
    if saved.get('decisionRule') == GROUP_RULE:
        groups = signals.groups(conn, context, members)
        group = signals.member_group(groups, actor)
        return (group in saved['requiredCarIds']
                and signals.member_group(groups, recipient) == saved['requesterCarId']
                and saved['groupResponses'].get(group, {}).get('accountId') == actor
                and not blocked(conn, recipient, groups[group]['driverId']))
    return actor in {car['driverId'] for car in auth.trip_service.cars(conn, trip).values()}
