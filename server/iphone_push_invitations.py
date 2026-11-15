from hashlib import sha256

from team_friends import blocked, linked
from team_trip_context import LIVE_STATES


def enqueue_invitation(conn, trip, actor, target, membership):
    from iphone_push import enqueue_push

    enqueue_push(conn, kind='trip_invitation', actor=actor, recipients=[target],
                 resource_id=sha256(membership).hexdigest(), trip_id=trip)


def invitation_visible(conn, event, auth, now):
    trip, actor, target = event['trip_id'], event['actor_id'], event['recipient_id']
    row = conn.execute(
        'SELECT t.owner_id, peer.protected, sender.protected FROM team_trips t '
        'JOIN team_trip_members peer ON peer.trip_id=t.trip_id AND peer.account_id=%s '
        'JOIN team_trip_members sender ON sender.trip_id=t.trip_id AND sender.account_id=%s '
        'JOIN team_rooms r ON r.trip_id=t.trip_id AND r.owner_id=t.owner_id '
        'WHERE t.trip_id=%s AND t.state IN (%s,%s) AND t.deleted_at IS NULL AND r.closed_at IS NULL '
        'AND r.archived_at IS NULL AND (r.expires_at IS NULL OR r.expires_at > clock_timestamp())',
        (target, actor, trip, *LIVE_STATES)).fetchone()
    if not row:
        return False
    owner, pending, inviter = row
    if sha256(pending).hexdigest() != event['resource_id'] or not linked(conn, actor, target):
        return False
    trips = auth.trip_service
    membership = trips.member_payload(trip, target, pending)
    sender = trips.member_payload(trip, actor, inviter)
    return (membership['state'] == 'pending' and membership['via'] == 'friend' and sender['state'] == 'accepted'
            and (actor == owner or sender['permissions']['invite'])
            and bool(trips.person(owner, connection=conn))
            and (actor == owner or not blocked(conn, owner, actor))
            and (target == owner or not blocked(conn, owner, target)))
