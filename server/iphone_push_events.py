"""Check that a queued personal notification still describes a visible event."""
import hashlib

from fastapi import HTTPException

from team_friends import blocked, pair_ids, restore_pair


def push_event_visible(conn, event, auth, now):
    actor, recipient = event['actor_id'], event['recipient_id']
    if actor == recipient:
        return False
    try:
        for account in (actor, recipient):
            auth.current_account(account, connection=conn)
    except HTTPException as error:
        if error.status_code in (401, 403, 404):
            return False
        raise

    kind = event['kind']
    if kind in ('friend_request', 'friend_accepted'):
        a, b = pair_ids(actor, recipient)
        protected = conn.execute(
            'SELECT protected FROM team_friend_pairs WHERE account_a=%s AND account_b=%s', (a, b)
        ).fetchone()
        if not protected or hashlib.sha256(protected[0]).hexdigest() != event['resource_id']:
            return False
        value = restore_pair(a, b, protected[0])
        pending = kind == 'friend_request'
        return (not value['blockedBy'] and value['state'] == ('pending' if pending else 'accepted')
                and value['requestedBy'] == (actor if pending else recipient))

    if blocked(conn, actor, recipient):
        return False
    if kind == 'trip_invitation':
        from iphone_push_invitations import invitation_visible
        return invitation_visible(conn, event, auth, now)
    if kind in ('hand_raise', 'hand_raise_reaction'):
        from iphone_push_hand_raise import hand_raise_visible
        return hand_raise_visible(conn, event, auth, now)
    return False
