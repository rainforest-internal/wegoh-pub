"""Account-library links explicitly contributed by accepted trip members."""
import hashlib
import json
from datetime import timezone
from private_records import VisitCipher
from team_friends import blocked
from team_room_music import ID, PLAYLIST_ADD_RATE, PLAYLIST_LIMIT, track_link
from team_rooms import failure

PLAY_RATE = 60


def can_reorder(access, viewer):
    return access['role'] == 'dj' or access['ownerId'] == viewer


def now_playing(service, conn, trip, viewer, visible):
    """Latest trip-playlist item each accepted member started from their vehicle."""
    trips = service.auth.trip_service
    result = []
    for account, raw in conn.execute('SELECT account_id,protected FROM team_trip_members WHERE trip_id=%s '
                                     'ORDER BY account_id', (trip,)).fetchall():
        playback = trips.member_payload(trip, account, raw).get('musicPlayback')
        if not playback or playback['itemId'] not in visible:
            continue
        if account != viewer and blocked(conn, viewer, account):
            continue
        person = service.rooms.person(account, connection=conn)
        if person:
            result.append(dict(itemId=playback['itemId'], startedBy=person, startedAt=playback['startedAt']))
    return sorted(result, key=lambda entry: (entry['startedAt'], entry['startedBy']['id']), reverse=True)


def list_saved_playlists(service, conn, trip, room, actor, native):
    """One trip playlist per account: the vehicle and the iPhone see the same items in the same order.

    Typed links follow the account's trip music consent and, on a vehicle, its
    device-wide room-music:read purpose; the per-room receiveMusic flag has no
    vehicle path to turn it on, so it does not gate this list.
    """
    viewer = actor['id']
    access = service.rooms.access(conn, room, viewer, trip_context=True)
    include_manual = access['consents']['music'] and (
        not native or 'room-music:read' in actor.get('approvedPurposes', []))
    playlist = service.shared_playlist(conn, room, viewer, access, trip_context=True, saved_only=not include_manual)
    items = [dict(id=entry['id'], title=entry['track']['title'], url=entry['track']['url'],
                  addedBy=entry['addedBy'], reviewState=entry['review']['state'])
             for entry in playlist['tracks'] if entry['track']]
    return dict(tripId=trip, items=items, limit=playlist['limit'], canAdd=playlist['canAdd'],
                canReorder=can_reorder(access, viewer),
                nowPlaying=now_playing(service, conn, trip, viewer, {item['id'] for item in items}))


def _visible_ids(service, conn, trip, room, actor, native):
    return [item['id'] for item in list_saved_playlists(service, conn, trip, room, actor, native)['items']]


def move_saved_playlist(service, conn, trip, room, actor, native, item, data):
    """Place one visible item right after another visible item, or first when afterId is null."""
    after = data['afterId']
    if (not isinstance(item, str) or not ID.fullmatch(item)
            or after is not None and (not isinstance(after, str) or not ID.fullmatch(after) or after == item)):
        failure(400, 'Invalid playlist order')
    service.rooms.graph_lock(conn)
    access = service.rooms.access(conn, room, actor['id'], trip_context=True)
    if not can_reorder(access, actor['id']):
        failure(403, 'Only the DJ or trip owner may reorder trip music')
    rows = conn.execute('SELECT track_id,position FROM team_room_playlist_tracks WHERE room_id=%s '
                        'ORDER BY position FOR UPDATE', (room,)).fetchall()
    visible = _visible_ids(service, conn, trip, room, actor, native)
    if item not in visible or after is not None and after not in visible:
        failure(409, 'Music list changed; reload before reordering')
    current = [row[0] for row in rows]
    order = [track for track in current if track != item]
    order.insert(0 if after is None else order.index(after) + 1, item)
    if order != current:
        # Reuse the same position values so later additions still append after every existing item.
        for track, position in zip(order, [row[1] for row in rows]):
            conn.execute('UPDATE team_room_playlist_tracks SET position=%s WHERE room_id=%s AND track_id=%s',
                         (position, room, track))
        service.rooms.notify(conn, room, sections=('music',))
    return list_saved_playlists(service, conn, trip, room, actor, native)


def play_saved_playlist(service, conn, trip, room, actor, native, data):
    """Record the item this member's vehicle opened; the external player itself is never controlled here."""
    if not native:
        failure(403, 'Play trip music from the vehicle')
    item = data['itemId']
    if not isinstance(item, str) or not ID.fullmatch(item):
        failure(400, 'Invalid playlist item')
    service.rooms.graph_lock(conn)
    account = actor['id']
    service.auth.rate('trip-music-play:' + account, limit=PLAY_RATE)
    if item not in _visible_ids(service, conn, trip, room, actor, native):
        failure(409, 'Music list changed; reload before playing')
    trips = service.auth.trip_service
    raw, now = conn.execute('SELECT protected,clock_timestamp() FROM team_trip_members '
                            'WHERE trip_id=%s AND account_id=%s FOR UPDATE', (trip, account)).fetchone()
    member = trips.member_payload(trip, account, raw)
    if member['state'] != 'accepted':
        failure()
    member['musicPlayback'] = dict(itemId=item, startedAt=now.astimezone(timezone.utc).isoformat())
    conn.execute('UPDATE team_trip_members SET protected=%s WHERE trip_id=%s AND account_id=%s',
                 (trips.protect('member:' + account, trip, member), trip, account))
    service.rooms.notify(conn, room, sections=('music',))
    return list_saved_playlists(service, conn, trip, room, actor, native)


def add_saved_playlist(service, conn, trip, room, actor, native, data):
    if native and 'playlists:read' not in actor['scopes']:
        failure(403, 'SCOPE_DENIED')
    if (not all(isinstance(data[key], str) and ID.fullmatch(data[key]) for key in ('playlistId', 'trackId'))
            or type(data['playlistRevision']) is not int or not 1 <= data['playlistRevision'] <= 2147483647
            or data['rightsConfirmed'] is not True or data['reviewConsent'] is not True):
        failure(400, 'Invalid saved playlist selection')
    owner = actor['id']
    source = service.playlist(conn, owner, data['playlistId'], data['playlistRevision'], lock=True)
    selected = next((track for track in source['tracks'] if track['id'] == data['trackId']), None)
    if not selected:
        failure(409, 'Music list changed; choose it again')
    url = track_link(selected['url'])
    joined, = conn.execute('SELECT joined_at FROM team_room_members WHERE room_id=%s AND account_id=%s '
                           'AND left_at IS NULL', (room, owner)).fetchone()
    key = json.dumps([room, owner, joined.isoformat(), data['playlistId'], data['trackId']], separators=(',', ':'))
    identifier = hashlib.sha256(key.encode()).hexdigest()[:32]
    projection = dict(name='플레이리스트', tracks=[dict(id=identifier, title=selected['title'], url=url)])
    existing = conn.execute('SELECT 1 FROM team_room_playlist_tracks WHERE room_id=%s AND track_id=%s',
                            (room, identifier)).fetchone()
    if not existing:
        service.auth.rate('room-playlist-add:' + owner, limit=PLAYLIST_ADD_RATE)
        count, = conn.execute('SELECT count(*) FROM team_room_playlist_tracks WHERE room_id=%s', (room,)).fetchone()
        if count >= PLAYLIST_LIMIT:
            failure(409, 'Room playlist limit reached; delete a track first')
        value = dict(source=dict(playlistId=data['playlistId'], trackId=data['trackId']), projection=projection)
        protected = VisitCipher().protect('team-room-playlist:' + room + ':' + owner, identifier, value)
        conn.execute('INSERT INTO team_room_playlist_tracks(room_id,track_id,account_id,member_joined_at,protected) '
                     'VALUES(%s,%s,%s,%s,%s)', (room, identifier, owner, joined, protected))
    service.content.request(conn, 'room-music', room + ':' + identifier, owner, projection, True)
    return list_saved_playlists(service, conn, trip, room, actor, native)
