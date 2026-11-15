"""Room-scoped DJ metadata. No audio fetching, copying, playback or vehicle control."""
import json
import re
import secrets
from urllib.parse import urlsplit

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from private_records import PrivateRecordError, VisitCipher
from team_rooms import failure, text
from native_access import native_resource
from native_functional_identity import request_actor,transaction_actor,business_json,resolve_current_device
from native_functional_policy import FunctionalError
from team_data import changed
from team_friends import blocked
from team_trip_context import resolve_trip_context

ID = re.compile(r'[a-f0-9]{32}')
PLAYLIST_LIMIT = 200
PLAYLIST_ADD_RATE = 10


def track_link(value):
    url = text(value, 2048)
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443) or '\\' in url
                or any(c.isspace() for c in value) or not re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname)
                or any(not label or label.startswith('-') or label.endswith('-') for label in parsed.hostname.split('.'))):
            raise ValueError()
    except ValueError:
        failure(400, 'Use an HTTPS track link')
    return url


class TeamRoomMusic:
    def __init__(self, auth, rooms):
        self.auth, self.rooms = auth, rooms
        self.dsn, self.enabled = auth.dsn, auth.enabled

    @property
    def content(self):
        return self.auth.content_service

    @staticmethod
    def restore(room, raw):
        return VisitCipher().restore('team-room-music', room, raw)

    @staticmethod
    def protect(room, value):
        return VisitCipher().protect('team-room-music', room, value)

    def saved(self, conn, room, lock=False):
        row = conn.execute('SELECT revision,protected FROM team_room_music WHERE room_id=%s' +
                           (' FOR UPDATE' if lock else ''), (room,)).fetchone()
        return (row[0], self.restore(room, row[1]) if row[1] is not None else None) if row else (0, None)

    def playlist(self, conn, owner, identifier, revision, *, lock=False):
        row = conn.execute('SELECT protected,revision FROM team_playlists '
                           'WHERE playlist_id=%s AND account_id=%s'+(' FOR SHARE'if lock else''), (identifier, owner)).fetchone()
        if not row or row[1] != revision:
            failure(409, 'Music list changed; choose it again')
        value = VisitCipher().restore('team-playlist:' + owner, identifier, row[0])
        return dict(name=value['name'], tracks=value['tracks'])

    def room_permission(self, *args, **kwargs):
        try:
            return self.auth.room_music_access.require(*args, **kwargs)
        except FunctionalError as error:
            failure(error.status, error.code)

    def current(self, conn, room, value, *, trip_context=False):
        access = self.rooms.access(conn, room, value['ownerId'], None if value.get('nativeOrigin') else 'music', trip_context=trip_context)
        if access['role'] != 'dj':
            failure()
        if value.get('memberJoinedAt'):
            joined = conn.execute('SELECT joined_at FROM team_room_members WHERE room_id=%s AND account_id=%s AND left_at IS NULL', (room, value['ownerId'])).fetchone()
            if not joined or joined[0].isoformat() != value['memberJoinedAt']:
                failure()
        origin=value.get('nativeOrigin')
        if origin is not None:
            if type(origin)is not dict or set(origin)!={'deviceId','grantId'} or any(type(v)is not str or ID.fullmatch(v)is None for v in origin.values()):failure(503,'Invalid music source')
            try:reference=resolve_current_device(self.auth,conn,value['ownerId'],origin['deviceId'],required=frozenset({'rooms:read','room-music:control'}))
            except FunctionalError as error:failure(error.status,error.code)
            if reference.grant_id!=origin['grantId']:failure(403,'Music source permission unavailable')
            self.room_permission(conn,value['ownerId'],origin['deviceId'],origin['grantId'],room,'shareMusic', trip_context=trip_context)
        if value.get('linkProjection'):
            return value['linkProjection']
        if value.get('sharedTrackId'):
            entry = self.shared_entry(conn, room, value['sharedTrackId'], trip_context=trip_context)
            projection = self.content.shared(conn, 'room-music', room + ':' + entry['id'],
                                             entry['ownerId'], entry['projection'])
            if projection is None:
                failure()
            return projection
        return self.playlist(conn, value['ownerId'], value['playlistId'], value['playlistRevision'])

    @staticmethod
    def entry_payload(room, identifier, owner, raw):
        value = VisitCipher().restore('team-room-playlist:' + room + ':' + owner, identifier, raw)
        if isinstance(value, dict) and set(value) == {'name', 'tracks'}:
            return value, None
        if isinstance(value, dict) and set(value) == {'source', 'projection'}:
            source, projection = value['source'], value['projection']
            if (isinstance(source, dict) and set(source) == {'playlistId', 'trackId'}
                    and all(isinstance(ref, str) and ID.fullmatch(ref) for ref in source.values())
                    and isinstance(projection, dict) and set(projection) == {'name', 'tracks'}
                    and isinstance(projection['tracks'], list) and len(projection['tracks']) == 1):
                track = projection['tracks'][0]
                if isinstance(track, dict) and set(track) == {'id', 'title', 'url'} and track['id'] == identifier:
                    return projection, source
        raise PrivateRecordError('Invalid room playlist entry')

    @staticmethod
    def source_tracks(conn, owner, playlist_id):
        row = conn.execute('SELECT protected FROM team_playlists WHERE account_id=%s AND playlist_id=%s',
                           (owner, playlist_id)).fetchone()
        if not row:
            return {}
        playlist = VisitCipher().restore('team-playlist:' + owner, playlist_id, row[0])
        return {track['id']: track for track in playlist['tracks']}

    @staticmethod
    def same_track(current, projection):
        return current is not None and all(current[key] == projection['tracks'][0][key] for key in ('title', 'url'))

    @staticmethod
    def entry_row(conn, room, identifier):
        return conn.execute('SELECT p.account_id,p.protected,p.member_joined_at,m.joined_at '
            'FROM team_room_playlist_tracks p LEFT JOIN team_room_members m '
            'ON m.room_id=p.room_id AND m.account_id=p.account_id AND m.left_at IS NULL '
            'WHERE p.room_id=%s AND p.track_id=%s', (room, identifier)).fetchone()

    def current_saved_entry(self, conn, room, identifier, owner):
        row = self.entry_row(conn, room, identifier)
        if not row or row[0] != owner or row[2] != row[3]:
            return False
        projection, source = self.entry_payload(room, identifier, owner, row[1])
        if source is None:
            return False
        current = self.source_tracks(conn, owner, source['playlistId']).get(source['trackId'])
        return self.same_track(current, projection)

    def shared_entry(self, conn, room, identifier, *, row=None, sources=None, trip_context=False):
        row = row or self.entry_row(conn, room, identifier)
        if not row or row[2] != row[3]:
            failure()
        owner = row[0]
        projection, source = self.entry_payload(room, identifier, owner, row[1])
        if source is not None and not trip_context:
            failure()
        sources = {} if sources is None else sources
        member_key = (owner, source is not None)
        if member_key not in sources:
            sources[member_key] = None
            self.rooms.access(conn, room, owner, None if source is not None else 'music', trip_context=trip_context)
            sources[member_key] = self.rooms.person(owner, connection=conn)
        if not sources[member_key]:
            failure()
        entry = dict(id=identifier, ownerId=owner, addedBy=sources[member_key], projection=projection)
        if source is not None:
            source_key = (owner, source['playlistId'])
            if source_key not in sources:
                sources[source_key] = self.source_tracks(conn, owner, source['playlistId'])
            if not self.same_track(sources[source_key].get(source['trackId']), projection):
                failure()
            entry['source'] = source
        return entry

    def shared_playlist(self, conn, room, viewer, access, *, trip_context=False, saved_only=False):
        tracks, sources = [], {}
        rows = conn.execute('SELECT p.track_id,p.account_id,p.protected,p.member_joined_at,m.joined_at '
            'FROM team_room_playlist_tracks p LEFT JOIN team_room_members m '
            'ON m.room_id=p.room_id AND m.account_id=p.account_id AND m.left_at IS NULL '
            'WHERE p.room_id=%s ORDER BY p.position', (room,)).fetchall()
        for row in rows:
            identifier, owner = row[:2]
            can_delete = viewer in (owner, access['ownerId'])
            blocked_source = owner != viewer and blocked(conn, viewer, owner)
            if trip_context and blocked_source:
                continue
            try:
                if blocked_source:
                    failure()
                entry = self.shared_entry(conn, room, identifier, row=row[1:], sources=sources, trip_context=trip_context)
                if saved_only and 'source' not in entry:
                    continue
                projection = entry['projection'] if owner == viewer else self.content.shared(
                    conn, 'room-music', room + ':' + identifier, owner, entry['projection'])
            except HTTPException as error:
                if error.status_code not in (403, 404):
                    raise
                projection = None
            if projection is None:
                if can_delete and not saved_only:
                    tracks.append(dict(id=identifier, track=None, artist=None, addedBy=None,
                                       canDelete=True, review=None))
                continue
            tracks.append(dict(id=identifier, track=projection['tracks'][0], artist=projection['name'],
                addedBy=entry['addedBy'], canDelete=can_delete,
                review=self.content.review(conn, 'room-music', room + ':' + identifier, owner, projection)))
        return dict(tracks=tracks, limit=PLAYLIST_LIMIT, canAdd=len(rows) < PLAYLIST_LIMIT)

    def projection(self, conn, key, owner):
        room, selection = key.split(':')
        _, value = self.saved(conn, room)
        if not value or value['ownerId'] != owner or value['selectionId'] != selection:
            entry = self.shared_entry(conn, room, selection, trip_context=True)
            if entry['ownerId'] != owner:
                failure()
            return entry['projection']
        return self.current(conn, room, value, trip_context=True)

    def notify(self, conn, key, owner):
        self.rooms.notify(conn, key.split(':')[0], sections=('music',))

    def clear(self, conn, room, owner=None, *, browser_only=False):
        ended = conn.execute('SELECT archived_at IS NOT NULL OR closed_at IS NOT NULL OR expires_at<=clock_timestamp() '
            'FROM team_rooms WHERE room_id=%s AND trip_id IS NULL', (room,)).fetchone()
        if ended and ended[0]:
            self.rooms.archive(conn, room)
            return
        revision, value = self.saved(conn, room, lock=True)
        source_owner = None
        if value and value.get('sharedTrackId'):
            source = conn.execute('SELECT account_id FROM team_room_playlist_tracks WHERE room_id=%s AND track_id=%s',
                                  (room, value['sharedTrackId'])).fetchone()
            source_owner = source[0] if source else None
        if not value or (owner is not None and owner not in (value['ownerId'], source_owner)) or (browser_only and value.get('nativeOrigin') is not None):
            return
        self.content.invalidate(conn, 'room-music', room + ':' + value['selectionId'], value['ownerId'])
        conn.execute('UPDATE team_room_music SET protected=NULL,revision=revision+1,updated_at=now() '
                     'WHERE room_id=%s', (room,))

    def withdraw_trip_context(self, conn, trip, room, account=None):
        self.clear(conn, room, account)
        listen = getattr(self, 'listen_together', None)
        if listen is not None:
            listen.withdraw_trip_context(conn, trip, room, account)

    def withdraw_saved_tracks(self, conn, room, owner):
        rows = conn.execute('SELECT track_id,protected FROM team_room_playlist_tracks WHERE room_id=%s AND account_id=%s',
                            (room, owner)).fetchall()
        for track, raw in rows:
            _, source = self.entry_payload(room, track, owner, raw)
            if source is not None:
                self.remove_shared_track(conn, room, track, owner, erase=False)

    def withdraw_native_source(self, conn, account, device, room=None):
        """Erase only this installation's shared selection, never its playlist."""
        self.rooms.graph_lock(conn)
        affected = set()
        query = 'SELECT m.room_id FROM team_room_music m JOIN team_room_members p USING(room_id) WHERE p.account_id=%s AND m.protected IS NOT NULL'
        args = [account]
        if room is not None: query += ' AND m.room_id=%s'; args.append(room)
        rows = conn.execute(query + ' ORDER BY m.room_id FOR UPDATE OF m', args).fetchall()
        for (room,) in rows:
            _, value = self.saved(conn, room)
            if value and value['ownerId'] == account and value.get('nativeOrigin', {}).get('deviceId') == device:
                self.clear(conn, room, account)
                self.rooms.notify(conn, room, sections=('music',))
                affected.add(room)
        return affected

    def invalidate_playlist(self, conn, owner, identifier):
        # Caller holds the existing social graph lock before playlist mutation.
        for (room,) in conn.execute('SELECT room_id FROM team_room_music WHERE protected IS NOT NULL ORDER BY room_id'):
            _, value = self.saved(conn, room)
            if value and not value.get('sharedTrackId') and value['ownerId'] == owner and value['playlistId'] == identifier:
                self.clear(conn, room, owner)
                self.rooms.notify(conn, room, sections=('music',))
        rows = conn.execute('SELECT p.room_id,p.track_id,p.protected FROM team_room_playlist_tracks p '
            'JOIN team_rooms r USING(room_id) WHERE p.account_id=%s AND r.trip_id IS NOT NULL', (owner,)).fetchall()
        current = self.source_tracks(conn, owner, identifier)
        affected = set()
        for room, track, raw in rows:
            projection, source = self.entry_payload(room, track, owner, raw)
            if source is not None and source['playlistId'] == identifier and not self.same_track(current.get(source['trackId']), projection):
                self.remove_shared_track(conn, room, track, owner, erase=False)
                affected.add(room)
        for room in sorted(affected):
            self.rooms.notify(conn, room, sections=('music',))

    def snapshot(self, conn, room, viewer, native=None, control_reply=False, *, trip_context=False):
        access = self.rooms.access(conn, room, viewer, None if native else 'music', trip_context=trip_context)
        room_permissions = None
        if native and not control_reply:
            room_permissions=self.room_permission(conn,viewer,native['deviceId'],native['grantId'],room,'receiveMusic', trip_context=trip_context)
        revision, value = self.saved(conn, room)
        result = dict(revision=revision, canEdit=access['role'] == 'dj' and (not native or control_reply or room_permissions['permissions']['shareMusic']), selection=None)
        if not native:
            result['playlist'] = self.shared_playlist(conn, room, viewer, access, trip_context=trip_context)
        if not value:
            return result
        if value['ownerId'] != viewer and blocked(conn, viewer, value['ownerId']):
            return result
        if value.get('sharedTrackId'):
            source = conn.execute('SELECT account_id FROM team_room_playlist_tracks WHERE room_id=%s AND track_id=%s', (room, value['sharedTrackId'])).fetchone()
            if source and source[0] != viewer and blocked(conn, viewer, source[0]):
                return result
        try:
            projection = self.current(conn, room, value, trip_context=trip_context)
        except HTTPException as error:
            if error.status_code in (403, 404, 409):
                return result
            raise
        key, owner = room + ':' + value['selectionId'], value['ownerId']
        review = self.content.review(conn, 'room-music', key, owner, projection)
        shared = projection if viewer == owner else self.content.shared(conn, 'room-music', key, owner, projection)
        if shared is None:
            return result
        result['selection'] = dict(id=value['selectionId'], ownerId=owner,
            playlistId=value['playlistId'], playlistRevision=value['playlistRevision'],
            currentTrackId=value['trackId'], name=shared['name'], tracks=shared['tracks'], review=review)
        if value.get('kind') == 'playlist-link':
            result['selection'].update(kind='playlist-link', provider='melon', url=shared['tracks'][0]['url'], title=shared['tracks'][0]['title'])
        return result

    def add_track(self, conn, room, owner, data, native=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        title, artist, url = text(data['title'], 120), text(data['artist'], 80), track_link(data['url'])
        if data['rightsConfirmed'] is not True:
            failure(400, 'Confirm link rights')
        self.auth.rate('room-playlist-add:' + owner, limit=PLAYLIST_ADD_RATE)
        self.rooms.access(conn, room, owner, 'music', trip_context=trip_context)
        count = conn.execute('SELECT count(*) FROM team_room_playlist_tracks WHERE room_id=%s', (room,)).fetchone()[0]
        if count >= PLAYLIST_LIMIT:
            failure(409, 'Room playlist limit reached; delete a track first')
        identifier = secrets.token_hex(16)
        projection = dict(name=artist, tracks=[dict(id=identifier, title=title, url=url)])
        protected = VisitCipher().protect('team-room-playlist:' + room + ':' + owner, identifier, projection)
        conn.execute('INSERT INTO team_room_playlist_tracks(room_id,track_id,account_id,member_joined_at,protected) '
            'SELECT room_id,%s,account_id,joined_at,%s FROM team_room_members WHERE room_id=%s AND account_id=%s AND left_at IS NULL',
            (identifier, protected, room, owner))
        self.rooms.notify(conn, room, sections=('music',))
        return self.snapshot(conn, room, owner, trip_context=trip_context)

    def track_access(self, conn, room, account, track, trip_context):
        row = self.entry_row(conn, room, track)
        if not row:
            failure()
        _, source = self.entry_payload(room, track, row[0], row[1])
        permission = None if trip_context and source is not None else 'music'
        return self.rooms.access(conn, room, account, permission, trip_context=trip_context), row

    def remove_shared_track(self, conn, room, track, owner, *, erase):
        _, selected = self.saved(conn, room)
        if selected and selected.get('sharedTrackId') == track:
            self.clear(conn, room)
        if erase:
            self.content.erase(conn, 'room-music', room + ':' + track, owner)
        else:
            self.content.invalidate(conn, 'room-music', room + ':' + track, owner)
        conn.execute('DELETE FROM team_room_playlist_tracks WHERE room_id=%s AND track_id=%s', (room, track))

    def delete_track(self, conn, room, owner, track, native=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        access, row = self.track_access(conn, room, owner, track, trip_context)
        if owner not in (row[0], access['ownerId']):
            failure(403, 'Only the contributor or room owner may delete this track')
        self.remove_shared_track(conn, room, track, row[0], erase=True)
        self.rooms.notify(conn, room, sections=('music',))
        if not access['consents']['music']:
            revision, _ = self.saved(conn, room)
            playlist = self.shared_playlist(conn, room, owner, access, trip_context=trip_context, saved_only=True)
            return dict(revision=revision, canEdit=False, selection=None, playlist=playlist)
        return self.snapshot(conn, room, owner, trip_context=trip_context)

    def review_track(self, conn, room, owner, track, data, native=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        access, row = self.track_access(conn, room, owner, track, trip_context)
        entry = self.shared_entry(conn, room, track, row=row, trip_context=trip_context)
        if entry['ownerId'] != owner:
            failure()
        if data['consent'] is False:
            _, selected = self.saved(conn, room)
            if selected and selected.get('sharedTrackId') == track:
                self.clear(conn, room)
        return self.content.request(conn, 'room-music', room + ':' + track, owner,
            entry['projection'], data['consent'], expires_at=access['expiresAt'])

    def report_track(self, conn, room, owner, track, data, native=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        _, row = self.track_access(conn, room, owner, track, trip_context)
        entry = self.shared_entry(conn, room, track, row=row, trip_context=trip_context)
        projection = self.content.shared(conn, 'room-music', room + ':' + track, entry['ownerId'], entry['projection'])
        if projection is None or entry['ownerId'] != owner and blocked(conn, owner, entry['ownerId']):
            failure()
        _, selected = self.saved(conn, room)
        if selected and selected.get('sharedTrackId') == track:
            self.clear(conn, room)
        return self.content.report(conn, 'room-music', room + ':' + track, entry['ownerId'], projection, owner, data['reason'])

    def select(self, conn, room, owner, data, native=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        identity = native
        if (type(data['revision']) is not int or not 0 <= data['revision'] <= 2147483647 or
            type(data['playlistRevision']) is not int or not 1 <= data['playlistRevision'] <= 2147483647 or
            any(not isinstance(data[key], str) or not ID.fullmatch(data[key]) for key in ('playlistId', 'trackId')) or
            data['rightsConfirmed'] is not True):
            failure(400, 'Choose a track and confirm link rights')
        self.auth.rate('room-music:' + owner, limit=60)
        access = self.rooms.access(conn, room, owner, None if identity else 'music', trip_context=trip_context)
        if identity:
            self.room_permission(conn,owner,identity['deviceId'],identity['grantId'],room,'shareMusic',data['roomMusicRevision'], trip_context=trip_context)
        if access['role'] != 'dj':
            failure(403, 'Only the DJ may choose room music')
        revision, previous = self.saved(conn, room, lock=True)
        if revision != data['revision']:
            failure(409, 'Room music changed; reload before editing')
        shared_track = not identity and data['playlistId'] == room
        if shared_track:
            if data['playlistRevision'] != 1:
                failure(409, 'Room playlist entry changed')
            entry = self.shared_entry(conn, room, data['trackId'], trip_context=trip_context)
            playlist = self.content.shared(conn, 'room-music', room + ':' + entry['id'], entry['ownerId'], entry['projection'])
            if playlist is None or entry['ownerId'] != owner and blocked(conn, owner, entry['ownerId']):
                failure(409, 'Choose a reviewed room track')
        else:
            playlist = self.playlist(conn, owner, data['playlistId'], data['playlistRevision'], lock=True)
        if data['trackId'] not in {track['id'] for track in playlist['tracks']}:
            failure(400, 'Choose a saved track')
        expected_origin=dict(deviceId=identity['deviceId'],grantId=identity['grantId']) if identity else None
        same = previous and previous.get('nativeOrigin')==expected_origin and all(previous[key] == data[key] for key in ('playlistId', 'playlistRevision')) and not previous.get('linkProjection') and previous.get('sharedTrackId') == (data['trackId'] if shared_track else None)
        if not same:
            self.clear(conn, room)
        selection = previous['selectionId'] if same else secrets.token_hex(16)
        value = dict(ownerId=owner, selectionId=selection, playlistId=data['playlistId'],
                     playlistRevision=data['playlistRevision'], trackId=data['trackId'])
        if trip_context:
            value['memberJoinedAt'] = conn.execute('SELECT joined_at FROM team_room_members WHERE room_id=%s AND account_id=%s AND left_at IS NULL', (room, owner)).fetchone()[0].isoformat()
        if shared_track:
            value['sharedTrackId'] = data['trackId']
        if identity:value['nativeOrigin']=dict(deviceId=identity['deviceId'],grantId=identity['grantId'])
        conn.execute('INSERT INTO team_room_music(room_id,revision,protected) VALUES(%s,%s,%s) '
            'ON CONFLICT(room_id) DO UPDATE SET revision=excluded.revision,protected=excluded.protected,updated_at=now()',
            (room, revision + 1, self.protect(room, value)))
        self.rooms.notify(conn, room, sections=('music',))
        return self.snapshot(conn, room, owner, native=identity, control_reply=bool(identity), trip_context=trip_context)

    def stop(self, conn, room, owner, data, native=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        identity = native
        if type(data['revision']) is not int or data['revision'] < 0:
            failure(400, 'Invalid music revision')
        access = self.rooms.access(conn, room, owner, None if identity else 'music', trip_context=trip_context)
        if identity:
            self.room_permission(conn,owner,identity['deviceId'],identity['grantId'],room,'shareMusic',data['roomMusicRevision'], trip_context=trip_context)
        revision, value = self.saved(conn, room, lock=True)
        if revision != data['revision']:
            failure(409, 'Room music changed; reload before editing')
        if trip_context and access['role'] != 'dj' and (native or access['ownerId'] != owner):
            failure(403, 'Only the DJ or trip owner may stop music sharing')
        if value and value['ownerId'] != owner and access['ownerId'] != owner:
            failure(403, 'Only the DJ or room owner may stop music sharing')
        self.clear(conn, room)
        self.rooms.notify(conn, room, sections=('music',))
        return self.snapshot(conn, room, owner, native=identity, control_reply=bool(identity), trip_context=trip_context)

    def review_request(self, conn, room, owner, data, native=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        if type(data['revision']) is not int or type(data['consent']) is not bool:
            failure(400, 'Explicit review consent required')
        revision, value = self.saved(conn, room, lock=True)
        access = self.rooms.access(conn, room, owner, None if value and value.get('nativeOrigin') else 'music', trip_context=trip_context)
        if revision != data['revision']:
            failure(409, 'Room music changed; reload before editing')
        if not value or value['ownerId'] != owner or access['role'] != 'dj':
            failure()
        projection = self.current(conn, room, value, trip_context=trip_context)
        return self.content.request(conn, 'room-music', room + ':' + value['selectionId'], owner,
                                    projection, data['consent'], expires_at=access['expiresAt'])

    def report_selection(self, conn, room, owner, data, native=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        snapshot = self.snapshot(conn, room, owner, trip_context=trip_context)
        current = snapshot['selection']
        if not current or data['selectionId'] != current['id']:
            failure()
        return self.content.report(conn, 'room-music', room + ':' + current['id'], current['ownerId'],
            dict(name=current['name'], tracks=current['tracks']), owner, data['reason'])

    @staticmethod
    def trip_dto(value, trip, room):
        def public(item):
            if isinstance(item, list):
                return [public(child) for child in item]
            if isinstance(item, dict):
                return {key:(trip + child[len(room):] if key == 'key' and isinstance(child, str) and child.startswith(room + ':')
                    else trip if key == 'playlistId' and child == room else public(child)) for key,child in item.items()}
            return item
        return dict(public(value), tripId=trip, contractVersion=1)

    def select_link(self, conn, room, owner, data, native=None, *, trip_context=False):
        if not trip_context:
            failure(409, 'TRIP_CLIENT_UPDATE_REQUIRED')
        if (type(data['revision']) is not int or not 0 <= data['revision'] <= 2147483647
                or data['kind'] != 'playlist-link' or data['provider'] != 'melon' or data['rightsConfirmed'] is not True):
            failure(400, 'Confirm playlist link rights')
        title, url = text(data['title'], 120), text(data['url'], 2048)
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != 'https' or parsed.hostname not in ('melon.com','www.melon.com','m.melon.com')
                    or parsed.username or parsed.password or parsed.port not in (None,443)
                    or any(c.isspace() or ord(c)<32 for c in data['url']) or '\\' in url):
                raise ValueError()
        except ValueError:
            failure(400, 'Use an HTTPS Melon playlist link')
        self.auth.rate('room-music:' + owner, limit=60)
        access = self.rooms.access(conn, room, owner, None if native else 'music', trip_context=True)
        if access['role'] != 'dj':
            failure(403, 'Only the DJ may choose trip music')
        if native:
            self.room_permission(conn, owner, native['deviceId'], native['grantId'], room, 'shareMusic', data['roomMusicRevision'], trip_context=True)
        revision, previous = self.saved(conn, room, lock=True)
        if revision != data['revision']:
            failure(409, 'Room music changed; reload before editing')
        self.clear(conn, room)
        selection = secrets.token_hex(16)
        projection = dict(name=title, tracks=[dict(id=selection, title=title, url=url)])
        joined = conn.execute('SELECT joined_at FROM team_room_members WHERE room_id=%s AND account_id=%s AND left_at IS NULL', (room, owner)).fetchone()[0]
        value = dict(kind='playlist-link', provider='melon', ownerId=owner, selectionId=selection,
            playlistId=selection, playlistRevision=1, trackId=selection, linkProjection=projection, memberJoinedAt=joined.isoformat())
        if native:
            value['nativeOrigin'] = dict(deviceId=native['deviceId'], grantId=native['grantId'])
        conn.execute('INSERT INTO team_room_music(room_id,revision,protected) VALUES(%s,%s,%s) '
            'ON CONFLICT(room_id) DO UPDATE SET revision=excluded.revision,protected=excluded.protected,updated_at=now()',
            (room, revision+1, self.protect(room, value)))
        self.rooms.notify(conn, room, sections=('music',))
        return self.snapshot(conn, room, owner, native=native, control_reply=bool(native), trip_context=True)

    def trip_router(self):
        from team_trip_saved_playlists import (add_saved_playlist, list_saved_playlists, move_saved_playlist,
                                               play_saved_playlist)
        router = APIRouter()
        if not self.enabled:
            return router
        def endpoint(operation, fields):
            async def handle(trip: str, request: Request, response: Response):
                track = request.path_params.get('track')
                mutate = request.method != 'GET'
                request_actor(self.auth, request, mutate=mutate)
                native = native_resource(request)
                saved_playlists = operation in ('saved_playlists', 'add_saved_playlist', 'move_saved_playlist',
                                                'play_saved_playlist')
                if saved_playlists:
                    response.headers['Cache-Control'] = 'private, no-store'
                if native and operation not in ('snapshot','select','stop') and not saved_playlists:
                    failure(403, 'Use the phone to manage music')
                data = None
                if fields is not None:
                    raw = bytearray()
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > 4096:
                            failure(413, 'Music request too large')
                    try:
                        data = business_json(request, raw, maximum=4096)
                    except (ValueError, UnicodeError):
                        failure(400, 'Invalid JSON')
                    expected = set(fields) | ({'roomMusicRevision'} if native and not saved_playlists else set())
                    if operation == 'select' and isinstance(data, dict) and data.get('kind') == 'playlist-link':
                        expected = {'revision','kind','provider','title','url','rightsConfirmed'} | ({'roomMusicRevision'} if native else set())
                    if type(data) is not dict or set(data) != expected:
                        failure(400, 'Invalid music fields')
                with psycopg.connect(self.dsn) as conn:
                    actor = transaction_actor(self.auth, request, conn, mutate=mutate)
                    context = resolve_trip_context(self.auth, conn, trip, actor['id'])
                    room = context['roomId']
                    identity = actor if native else None
                    if saved_playlists:
                        if operation == 'add_saved_playlist':
                            return add_saved_playlist(self, conn, trip, room, actor, native, data)
                        if operation == 'move_saved_playlist':
                            return move_saved_playlist(self, conn, trip, room, actor, native,
                                                       request.path_params['item'], data)
                        if operation == 'play_saved_playlist':
                            return play_saved_playlist(self, conn, trip, room, actor, native, data)
                        return list_saved_playlists(self, conn, trip, room, actor, native)
                    if operation == 'snapshot':
                        result = self.snapshot(conn, room, actor['id'], native=identity, trip_context=True)
                        if native:
                            result['canEdit'] = result['canEdit'] and 'room-music:control' in request.state.functional_snapshot['approvedPurposes']
                            result['nativeReadOnly'] = not result['canEdit']
                    else:
                        method = self.select_link if operation == 'select' and data.get('kind') == 'playlist-link' else getattr(self, operation)
                        if operation == 'select' and data.get('playlistId') == trip:
                            data = dict(data, playlistId=room)
                        args = [conn, room, actor['id']]
                        if track is not None:
                            args.append(track)
                        if data is not None:
                            args.append(data)
                        result = method(*args, native=identity, trip_context=True)
                    return self.trip_dto(result, trip, room)
            return handle
        base = '/v1/social/trips/{trip}/music'
        routes = (
            ('GET','', 'snapshot', None,200),
            ('GET','/saved-playlists', 'saved_playlists', None,200),
            ('POST','/saved-playlists', 'add_saved_playlist',
             ('playlistId','playlistRevision','trackId','rightsConfirmed','reviewConsent'),200),
            ('PATCH','/saved-playlists/{item}/position', 'move_saved_playlist', ('afterId',),200),
            ('PUT','/now-playing', 'play_saved_playlist', ('itemId',),200),
            ('PUT','', 'select', ('revision','playlistId','playlistRevision','trackId','rightsConfirmed'),200),
            ('DELETE','', 'stop', ('revision',),200),
            ('POST','/playlist', 'add_track', ('title','artist','url','rightsConfirmed'),201),
            ('DELETE','/playlist/{track}', 'delete_track', None,200),
            ('PATCH','/playlist/{track}/review-request', 'review_track', ('consent',),200),
            ('POST','/playlist/{track}/reports', 'report_track', ('reason',),202),
            ('PATCH','/review-request', 'review_request', ('revision','consent'),200),
            ('POST','/reports', 'report_selection', ('selectionId','reason'),202))
        for method, suffix, operation, fields, status in routes:
            router.add_api_route(base+suffix, endpoint(operation, fields), methods=[method], status_code=status, name='trip_music_'+operation)
        from iphone_trip_music import router as iphone_music_router
        router.include_router(iphone_music_router(self))
        from team_trip_listen_together import TripListenTogether
        self.listen_together = TripListenTogether(self)
        router.include_router(self.listen_together.router())
        return router

    def router(self):
        router = APIRouter()
        if not self.enabled:
            return router

        def actor(request, mutate=False):
            return request_actor(self.auth,request,mutate=mutate)['id']

        async def body(request, fields):
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 4096:
                    failure(413, 'Music request too large')
            try:
                value = business_json(request,raw,maximum=4096)
            except (ValueError, UnicodeError):
                failure(400, 'Invalid JSON')
            expected = set(fields) | ({'roomMusicRevision'} if native_resource(request) else set())
            if not isinstance(value, dict) or set(value) != expected:
                failure(400, 'Invalid music fields')
            return value

        def device_snapshot(conn,owner,device):
            try:reference=resolve_current_device(self.auth,conn,owner,device)
            except FunctionalError as error:failure(error.status,error.code)
            return dict(authorizationVersion=1,authority='native-functional',deviceId=device,
                revision=reference.functional_revision,functionalRevision=reference.functional_revision,
                enabled='room-music:read'in reference.approved_purposes)

        @router.get('/v1/devices/{device}/music-permission')
        def device_music(device:str,request:Request):
            owner=actor(request)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn)['id'];self.rooms.graph_lock(conn)
                return device_snapshot(conn,owner,device)

        @router.put('/v1/devices/{device}/music-permission')
        async def allow_device_music(device:str,request:Request):
            owner=actor(request,True);data=await body(request,('revision','enabled'))
            if type(data['revision'])is not int or data['revision']<0 or data['enabled']is not True:failure(400,'Explicit device music permission required')
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id'];self.rooms.graph_lock(conn)
                device_snapshot(conn,owner,device)
                failure(409,'Use current functional permissions')

        @router.delete('/v1/devices/{device}/music-permission')
        def revoke_device_music(device:str,request:Request):
            owner=actor(request,True)
            with psycopg.connect(self.dsn)as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=True)['id'];self.rooms.graph_lock(conn)
                device_snapshot(conn,owner,device)
                failure(409,'Use current functional permissions')

        @router.get('/v1/device/music-permission')
        def own_device_music(request:Request):
            if not native_resource(request):failure()
            owner=actor(request)
            with psycopg.connect(self.dsn)as conn:
                identity=transaction_actor(self.auth,request,conn);self.rooms.graph_lock(conn)
                return device_snapshot(conn,identity['id'],identity['deviceId'])

        @router.get('/v1/social/rooms/{room}/music')
        def get(room: str, request: Request):
            owner = actor(request)
            with psycopg.connect(self.dsn) as conn:
                owner=transaction_actor(self.auth,request,conn,mutate=request.method not in('GET','HEAD'))['id']
                self.rooms.graph_lock(conn)
                identity=getattr(request.state,'device_identity',None) if native_resource(request) else None
                value=self.snapshot(conn, room, owner, native=identity)
                if native_resource(request):
                    value['canEdit']=value['canEdit']and'room-music:control'in request.state.functional_snapshot['approvedPurposes']
                    value['nativeReadOnly']=not value['canEdit']
                return value

        @router.post('/v1/social/rooms/{room}/music/playlist', status_code=201)
        async def add_track(room: str, request: Request):
            owner = actor(request, True)
            if native_resource(request):
                failure(403, 'Use the phone to add music')
            data = await body(request, ('title', 'artist', 'url', 'rightsConfirmed'))
            with psycopg.connect(self.dsn) as conn:
                owner = transaction_actor(self.auth, request, conn, mutate=True)['id']
                identity = getattr(request.state, 'device_identity', None) if native_resource(request) else None
                return self.add_track(conn, room, owner, data, native=identity)

        @router.delete('/v1/social/rooms/{room}/music/playlist/{track}')
        def delete_track(room: str, track: str, request: Request):
            owner = actor(request, True)
            if native_resource(request):
                failure(403, 'Use the phone to manage music')
            with psycopg.connect(self.dsn) as conn:
                owner = transaction_actor(self.auth, request, conn, mutate=True)['id']
                identity = getattr(request.state, 'device_identity', None) if native_resource(request) else None
                return self.delete_track(conn, room, owner, track, native=identity)

        @router.patch('/v1/social/rooms/{room}/music/playlist/{track}/review-request')
        async def review_track(room: str, track: str, request: Request):
            owner = actor(request, True)
            data = await body(request, ('consent',))
            with psycopg.connect(self.dsn) as conn:
                owner = transaction_actor(self.auth, request, conn, mutate=True)['id']
                identity = getattr(request.state, 'device_identity', None) if native_resource(request) else None
                return self.review_track(conn, room, owner, track, data, native=identity)

        @router.post('/v1/social/rooms/{room}/music/playlist/{track}/reports', status_code=202)
        async def report_track(room: str, track: str, request: Request):
            owner = actor(request, True)
            data = await body(request, ('reason',))
            with psycopg.connect(self.dsn) as conn:
                owner = transaction_actor(self.auth, request, conn, mutate=True)['id']
                identity = getattr(request.state, 'device_identity', None) if native_resource(request) else None
                return self.report_track(conn, room, owner, track, data, native=identity)

        @router.put('/v1/social/rooms/{room}/music')
        async def select(room: str, request: Request):
            owner = actor(request, True)
            data = await body(request, ('revision', 'playlistId', 'playlistRevision', 'trackId', 'rightsConfirmed'))
            with psycopg.connect(self.dsn) as conn:
                owner = transaction_actor(self.auth, request, conn, mutate=True)['id']
                identity = getattr(request.state, 'device_identity', None) if native_resource(request) else None
                return self.select(conn, room, owner, data, native=identity)

        @router.delete('/v1/social/rooms/{room}/music')
        async def stop(room: str, request: Request):
            owner = actor(request, True)
            data = await body(request, ('revision',))
            with psycopg.connect(self.dsn) as conn:
                owner = transaction_actor(self.auth, request, conn, mutate=True)['id']
                identity = getattr(request.state, 'device_identity', None) if native_resource(request) else None
                return self.stop(conn, room, owner, data, native=identity)

        @router.patch('/v1/social/rooms/{room}/music/review-request')
        async def review_request(room: str, request: Request):
            owner = actor(request, True)
            data = await body(request, ('revision', 'consent'))
            with psycopg.connect(self.dsn) as conn:
                owner = transaction_actor(self.auth, request, conn, mutate=True)['id']
                identity = getattr(request.state, 'device_identity', None) if native_resource(request) else None
                return self.review_request(conn, room, owner, data, native=identity)

        @router.post('/v1/social/rooms/{room}/music/reports', status_code=202)
        async def report(room: str, request: Request):
            owner = actor(request, True)
            data = await body(request, ('selectionId', 'reason'))
            with psycopg.connect(self.dsn) as conn:
                owner = transaction_actor(self.auth, request, conn, mutate=True)['id']
                identity = getattr(request.state, 'device_identity', None) if native_resource(request) else None
                return self.report_selection(conn, room, owner, data, native=identity)

        return router
