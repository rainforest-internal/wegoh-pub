"""Period-limited rooms, individual consent and selected-place requests.

No claim of external vehicle/market approval. No GPS,
voice, media, history persistence, navigation or vehicle command implementation.
"""
from course_publication import COURSE_AVAILABLE
import hashlib
import hmac
import json
import math
import re
import secrets

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from private_records import VisitCipher, PrivateRecordError
from team_data import changed
from team_friends import blocked, ACCOUNT

CONSENTS = ('status', 'location', 'visits', 'music', 'voice', 'control')
AVAILABLE_CONSENTS = ('status', 'location')
ROLES = ('member', 'dj', 'rest', 'food')
KINDS = ('restroom', 'smoking', 'nursing', 'drowsy', 'rest', 'hungry', 'cafe', 'ev_charge', 'fuel', 'arrived', 'join')
STOP_KINDS = frozenset(('restroom', 'smoking', 'nursing', 'drowsy', 'rest', 'hungry', 'cafe', 'ev_charge', 'fuel'))
PREFERENCES = ('balanced', 'country-roads', 'short-distance', 'short-time')
CODE = re.compile(r'[A-HJ-NP-Z2-9]{8}')


def failure(status=404, detail='Room unavailable'):
    raise HTTPException(status, detail)


def text(value, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum or any(ord(c) < 32 for c in value):
        failure(400, 'Invalid text')
    return value.strip()


def consents(value, supported=AVAILABLE_CONSENTS, previous=None):
    if not isinstance(value, dict) or set(value) != set(CONSENTS) or any(type(v) is not bool for v in value.values()):
        failure(400, 'Choose each sharing permission')
    if supported is not None and any(value[key]and not(previous or{}).get(key,False)for key in CONSENTS if key not in supported):
        failure(400, 'Sharing capability unavailable')
    return dict(value)


from native_access import read_actor, native_resource
from native_functional_identity import request_actor,transaction_actor,business_json

class TeamRooms:
    def __init__(self, auth):
        self.auth, self.dsn, self.enabled = auth, auth.dsn, auth.enabled

    def available_consents(self):
        voice=getattr(self.auth,'voice_service',None)
        music=getattr(self.auth,'room_music_service',None)
        return AVAILABLE_CONSENTS+(('music',)if music and music.enabled else())+(('voice',)if voice and voice.enabled else())

    @property
    def content(self):return getattr(self.auth,'content_service',None)
    def projection(self,conn,room,owner):
        link = conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s AND trip_id IS NOT NULL', (room,)).fetchone()
        if link:
            from team_trip_context import resolve_trip_context
            context = resolve_trip_context(self.auth, conn, link[0], owner)
            if context['ownerId'] != owner:failure()
            return dict(name=context['title'])
        row=conn.execute('SELECT r.protected FROM team_rooms r JOIN team_room_members m USING(room_id) WHERE r.room_id=%s AND r.owner_id=%s AND m.account_id=%s AND m.left_at IS NULL AND r.closed_at IS NULL AND r.expires_at>now()',(room,owner,owner)).fetchone()
        if not row:failure()
        return dict(name=self.restore('owner:'+owner,room,row[0])['name'])
    def place_projection(self,conn,key,owner):
        parts=key.split(':')
        if len(parts)!=2:failure()
        room,signal=parts
        link = conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s AND trip_id IS NOT NULL', (room,)).fetchone()
        if link:
            access = self.access(conn, room, owner, 'status', trip_context=True)
            row = conn.execute('SELECT s.protected FROM team_room_signals s JOIN team_room_members m '
                'ON m.room_id=s.room_id AND m.account_id=s.account_id WHERE s.room_id=%s AND s.signal_id=%s '
                'AND s.account_id=%s AND m.left_at IS NULL AND s.created_at>=m.joined_at', (room, signal, owner)).fetchone()
            if not row or not access['consents']['location']:failure()
            value = self.restore('signal:' + owner, signal, row[0])
            if not value.get('destination'):failure()
            return dict(name=value['destination']['name'])
        row=conn.execute('SELECT s.protected,m.protected FROM team_room_signals s JOIN team_rooms r USING(room_id) JOIN team_room_members m ON m.room_id=r.room_id AND m.account_id=s.account_id WHERE s.room_id=%s AND s.signal_id=%s AND s.account_id=%s AND m.left_at IS NULL AND r.closed_at IS NULL AND r.expires_at>now()',(room,signal,owner)).fetchone()
        if not row:failure()
        member=self.member_payload(owner,room,row[1]);value=self.restore('signal:'+owner,signal,row[0])
        if not member['consents']['status']or not member['consents']['location']or not value.get('destination'):failure()
        return dict(name=value['destination']['name'])
    def review_name(self,conn,room,owner,name,viewer):
        projection=dict(name=name)
        review=self.content.review(conn,'room',room,owner,projection)if self.content else dict(kind='room',key=room,state='private',checksum=None,requested=False)
        if viewer==owner:return name,review
        shared=self.content.shared(conn,'room',room,owner,projection)if self.person(owner,connection=conn)and self.content else None
        return(shared['name'],review)if shared else('여행방',dict(kind='room',key=room,state='private',checksum=None,requested=False))
    def withdraw_context(self,conn,room,account=None,*,music=True,voice=True,preserve_music=False):
        commands=getattr(self.auth,'device_command_service',None)
        if commands:commands.revoke_context(conn,room,account)
        vehicle=getattr(self.auth,'vehicle_service',None)
        if vehicle:vehicle.withdraw_room(conn,room,account)
        if voice:
            voice_access=getattr(self.auth,'room_voice_access',None)
            if voice_access:voice_access.withdraw_room_context(conn,room,account)
        service=getattr(self.auth,'room_music_service',None)
        if music:
            authority=getattr(self.auth,'room_music_access',None)
            if authority:authority.withdraw_room_context(conn,room,account)
            if service and not preserve_music:service.clear(conn,room,account)
        if not self.content:return
        if account is None:
            owner=conn.execute('SELECT owner_id,protected FROM team_rooms WHERE room_id=%s',(room,)).fetchone()
            if owner:
                name=self.restore('owner:'+owner[0],room,owner[1])['name'];self.content.request(conn,'room',room,owner[0],dict(name=name),False)
        query='SELECT signal_id,account_id,protected FROM team_room_signals WHERE room_id=%s';args=[room]
        if account is not None:query+=' AND account_id=%s';args.append(account)
        for signal,sender,raw in conn.execute(query,args):
            value=self.restore('signal:'+sender,signal,raw)
            if value.get('destination'):self.content.request(conn,'room-place',room+':'+signal,sender,dict(name=value['destination']['name']),False)
    @staticmethod
    def graph_lock(conn):
        # Future friend on-block integration must acquire this before pair/room
        # locks. Join and block are serialized without lock-order inversion.
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('social-membership',0))")

    @staticmethod
    def protect(domain, identifier, payload):
        return VisitCipher().protect('team-room-' + domain, identifier, payload)

    @staticmethod
    def restore(domain, identifier, payload):
        return VisitCipher().restore('team-room-' + domain, identifier, payload)

    def code_hash(self, code):
        return hmac.new(self.auth.secret, ('room-code-v1:' + code).encode(), hashlib.sha256).hexdigest()

    def person(self, account, *, connection=None):
        try:
            value = self.auth.current_account(account,connection=connection) if connection is not None else self.auth.current_account(account)
            return dict(id=value['id'], name=value['displayName'])
        except HTTPException:
            return None

    def member_payload(self, account, room, raw):
        value = self.restore('member:' + account, room, raw)
        if not isinstance(value, dict) or set(value) != {'role', 'consents'} or value['role'] not in ROLES:
            raise PrivateRecordError('Room membership integrity failed')
        consents(value['consents'],supported=None)
        return value

    def active_members(self, conn, room):
        result = {}
        link = conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s', (room,)).fetchone()
        accepted = None
        if link and link[0]:
            from team_trips import TeamTrips
            accepted = {account for account, value in TeamTrips(self.auth).members(conn, link[0]).items() if value['state'] == 'accepted'}
        for account, raw in conn.execute('SELECT account_id,protected FROM team_room_members '
                'WHERE room_id=%s AND left_at IS NULL ORDER BY joined_at,account_id', (room,)):
            if accepted is not None and account not in accepted:
                continue
            who = self.person(account,connection=conn)
            if who:
                result[account] = dict(who, **self.member_payload(account, room, raw))
        return result

    @staticmethod
    def course(conn, value):
        if value.get('courseId') is None:
            return None
        row = conn.execute("SELECT p.pack_id,p.version,p.title FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) "
            f"WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE}",
            (value['courseId'], value['courseVersion'])).fetchone()
        return dict(id=row[0], version=row[1], title=row[2]) if row else None

    def access(self, conn, room, account, permission=None, *, trip_context=False):
        if not isinstance(room,str) or not re.fullmatch(r'[a-f0-9]{32}',room): failure()
        link = conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s AND trip_id IS NOT NULL', (room,)).fetchone()
        if link:
            if not trip_context:
                from team_trips import TeamTrips
                TeamTrips(self.auth).access(conn, link[0], account)
                failure(409, 'TRIP_CLIENT_UPDATE_REQUIRED')
            from team_trip_context import resolve_trip_context
            context = resolve_trip_context(self.auth, conn, link[0], account)
            raw = conn.execute('SELECT protected FROM team_room_members WHERE room_id=%s AND account_id=%s AND left_at IS NULL', (room, account)).fetchone()
            if not raw:failure(409, 'TRIP_MEMBERSHIP_INCONSISTENT')
            member = self.member_payload(account, room, raw[0])
            if permission and not member['consents'][permission]:failure(403, 'Sharing permission required')
            raw_room = conn.execute('SELECT protected FROM team_rooms WHERE room_id=%s', (room,)).fetchone()[0]
            payload = self.restore('owner:' + context['ownerId'], room, raw_room)
            name, review = self.review_name(conn, room, context['ownerId'], context['title'], account)
            return dict(id=room, tripId=context['tripId'], ownerId=context['ownerId'], name=name, review=review,
                state=context['state'], revision=context['revision'], expiresAt=None,
                tripLocationConsent=context['members'][account].get('locationConsent') is True,
                serverNow=conn.execute('SELECT clock_timestamp()').fetchone()[0],
                courseId=payload['courseId'], courseVersion=payload['courseVersion'], preference=payload['preference'],
                course=self.course(conn, payload), role=member['role'], consents=member['consents'],
                availableConsentKeys=list(self.available_consents()))
        row = conn.execute('SELECT r.owner_id,r.protected,r.expires_at,m.protected '
            'FROM team_rooms r JOIN team_room_members m USING(room_id) WHERE r.room_id=%s '
            'AND m.account_id=%s AND m.left_at IS NULL AND r.closed_at IS NULL AND r.archived_at IS NULL AND r.expires_at>clock_timestamp()',
            (room, account)).fetchone()
        if not row:
            failure()
        member = self.member_payload(account, room, row[3])
        peers = self.active_members(conn, room)
        # Do not call the friend helper with self; that is invalid user input.
        if account != row[0] and any(blocked(conn, account, peer) for peer in peers if peer != account):
            failure()
        if permission and not member['consents'][permission]:
            failure(403, 'Sharing permission required')
        payload = self.restore('owner:' + row[0], room, row[1]);name,review=self.review_name(conn,room,row[0],payload['name'],account)
        server_now=conn.execute('SELECT clock_timestamp()').fetchone()[0]
        return dict(name=name,review=review,code=payload['code'],courseId=payload['courseId'],courseVersion=payload['courseVersion'],preference=payload['preference'],id=room, ownerId=row[0], expiresAt=row[2], serverNow=server_now,
                    expiresInSeconds=max(0,(row[2]-server_now).total_seconds()), course=self.course(conn,payload),
                    role=member['role'], consents=member['consents'],
                    availableConsentKeys=list(self.available_consents()))

    def notify(self, conn, room, extra=(), *, sections=None):
        accounts = {x[0] for x in conn.execute('SELECT account_id FROM team_room_members '
                    'WHERE room_id=%s AND left_at IS NULL', (room,))} | set(extra)
        link = conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s AND trip_id IS NOT NULL', (room,)).fetchone()
        if link:
            from team_event_versions import SECTIONS, trip_changed
            trip_changed(conn, link[0], SECTIONS if sections is None else sections)
            from team_trips import TeamTrips
            accepted = {account for account, member in TeamTrips(self.auth).members(conn, link[0]).items() if member['state'] == 'accepted'}
            accounts &= accepted | set(extra)
        for account in sorted(accounts):
            changed(conn, account, 'rooms', legacy_only=bool(link))
            if link:
                changed(conn, 'trip-account:' + account, 'rooms')

    def agreed_stop(self, conn, peers, signals):
        """Derive the current group stop from the same visible, consented votes."""
        if len(peers) < 2 or any(not member['consents']['status'] for member in peers.values()):
            return None
        # signals() orders by newest request first. A proposal counts as the
        # sender's agreement unless they explicitly vote to pass.
        for item in signals:
            if item['kind'] not in STOP_KINDS or not item['destination'] or item['votes']['pass']:
                continue
            agree = item['votes']['agree']
            if agree not in (len(peers) - 1, len(peers)):
                continue
            if agree == len(peers) - 1:
                sender, identifier = item['accountId'], item['id']
                vote = conn.execute('SELECT protected FROM team_room_votes WHERE signal_id=%s AND account_id=%s',
                                    (identifier, sender)).fetchone()
                if vote and self.restore('vote:' + sender, identifier, vote[0])['choice'] == 'agree':
                    continue
            return dict(signalId=item['id'], destination=item['destination'])
        return None

    def archive(self, conn, room):
        self.graph_lock(conn)
        row = conn.execute('UPDATE team_rooms SET archived_at=COALESCE(closed_at,expires_at), '
            'closed_at=COALESCE(closed_at,expires_at), expiry_notified_at=COALESCE(expiry_notified_at,now()), '
            'archived_music=(SELECT protected FROM team_room_music WHERE room_id=%s) '
            'WHERE room_id=%s AND trip_id IS NULL AND archived_at IS NULL AND (closed_at IS NOT NULL OR expires_at<=clock_timestamp()) '
            'RETURNING room_id', (room, room)).fetchone()
        if row:
            self.withdraw_context(conn, room, preserve_music=True)
            accounts = [x[0] for x in conn.execute('SELECT account_id FROM team_room_members WHERE room_id=%s', (room,))]
            self.notify(conn, room, extra=accounts)

    def notify_expired(self, conn):
        self.graph_lock(conn)
        rows = conn.execute('SELECT room_id FROM team_rooms WHERE trip_id IS NULL AND archived_at IS NULL '
            'AND (expires_at<=clock_timestamp() OR closed_at IS NOT NULL) '
            'ORDER BY room_id FOR UPDATE SKIP LOCKED LIMIT 100').fetchall()
        for (room,) in rows:
            self.archive(conn, room)

    def archive_access(self, conn, room, account):
        if not isinstance(room, str) or not re.fullmatch(r'[a-f0-9]{32}', room):
            failure()
        link = conn.execute('SELECT trip_id FROM team_rooms WHERE room_id=%s AND trip_id IS NOT NULL', (room,)).fetchone()
        if link:
            self.access(conn, room, account)
        row = conn.execute('SELECT r.owner_id,r.protected,r.expires_at,r.created_at,r.closed_at,r.archived_at '
            'FROM team_rooms r JOIN team_room_members m USING(room_id) WHERE r.room_id=%s AND m.account_id=%s '
            'AND (r.archived_at IS NOT NULL OR r.closed_at IS NOT NULL OR r.expires_at<=clock_timestamp())', (room, account)).fetchone()
        if not row:
            failure()
        peers = conn.execute('SELECT account_id FROM team_room_members WHERE room_id=%s', (room,)).fetchall()
        if any(blocked(conn, account, peer) for (peer,) in peers if peer != account):
            failure()
        self.archive(conn, room)
        payload = self.restore('owner:' + row[0], room, row[1])
        name, _ = self.review_name(conn, room, row[0], payload['name'], account)
        ended = row[5] or row[4] or row[2]
        return dict(id=room, name=name, ownerId=row[0], state='archived', readOnly=True,
            createdAt=row[3], expiresAt=row[2], archivedAt=ended,
            courseId=payload['courseId'], courseVersion=payload['courseVersion'],
            preference=payload['preference'], course=self.course(conn, payload), memberCount=len(peers))

    def archive_detail(self, conn, room, account):
        value = self.archive_access(conn, room, account)
        members = []
        for peer, raw, joined, left in conn.execute('SELECT account_id,protected,joined_at,left_at '
                'FROM team_room_members WHERE room_id=%s ORDER BY joined_at,account_id', (room,)):
            person = self.person(peer)
            if person:
                member = self.member_payload(peer, room, raw)
                members.append(dict(person, role=member['role'], joinedAt=joined, leftAt=left))
        music = None
        raw = conn.execute('SELECT archived_music FROM team_rooms WHERE room_id=%s', (room,)).fetchone()[0]
        if raw is not None:
            selection = VisitCipher().restore('team-room-music', room, raw)
            if selection['ownerId'] == account:
                music = {key:selection[key] for key in ('selectionId', 'ownerId', 'playlistId', 'playlistRevision', 'trackId')}
        active = conn.execute('SELECT left_at IS NULL FROM team_room_members WHERE room_id=%s AND account_id=%s', (room, account)).fetchone()[0]
        return dict(value, members=members, signals=self.signals(conn, room, account) if active else [], musicSelection=music)

    def list_rooms(self, conn, owner):
        self.notify_expired(conn)
        result = []
        for (room,) in conn.execute('SELECT r.room_id FROM team_rooms r JOIN team_room_members m USING(room_id) '
                'WHERE m.account_id=%s AND r.trip_id IS NULL AND m.left_at IS NULL AND r.closed_at IS NULL AND r.archived_at IS NULL AND r.expires_at>now() '
                'ORDER BY r.created_at DESC LIMIT 100', (owner,)):
            try:
                value = self.access(conn, room, owner)
            except HTTPException as error:
                if error.status_code == 404:
                    continue
                raise
            peers = self.active_members(conn, room)
            result.append(dict(id=room, name=value['name'], courseId=value['courseId'], courseVersion=value['courseVersion'],
                expiresAt=value['expiresAt'],review=value['review'], ownerId=value['ownerId'], active=True, memberCount=len(peers)))
        return result

    def on_block(self, conn, blocker, target):
        # Caller holds graph_lock before its pair lock; preserves room records.
        common = conn.execute('SELECT r.room_id,r.owner_id FROM team_rooms r '
            'JOIN team_room_members a USING(room_id) JOIN team_room_members b USING(room_id) '
            'WHERE a.account_id=%s AND b.account_id=%s AND a.left_at IS NULL AND b.left_at IS NULL '
            'AND r.trip_id IS NULL AND r.closed_at IS NULL AND r.expires_at>now() ORDER BY r.room_id', (blocker, target)).fetchall()
        for room, creator in common:
            conn.execute('SELECT room_id FROM team_rooms WHERE room_id=%s FOR UPDATE', (room,))
            removed = target if creator == blocker else blocker
            conn.execute('UPDATE team_room_members SET left_at=now() WHERE room_id=%s AND account_id=%s', (room, removed));self.withdraw_context(conn,room,removed)
            self.notify(conn, room, extra=(removed,))

    def signals(self, conn, room, viewer):
        peers = self.active_members(conn, room)
        result = []
        for identifier, sender, raw, created in conn.execute('SELECT signal_id,account_id,protected,created_at '
                'FROM team_room_signals WHERE room_id=%s ORDER BY created_at DESC,signal_id LIMIT 100', (room,)):
            who = peers.get(sender)
            if not who or not who['consents']['status'] or (sender != viewer and blocked(conn, viewer, sender)):
                continue
            value = self.restore('signal:' + sender, identifier, raw)
            # Current consent applies to old messages, not just future writes.
            if not who['consents']['location']:
                value['destination'] = None
            review=None
            if value.get('destination'):
                key=room+':'+identifier;projection=dict(name=value['destination']['name']);review=self.content.review(conn,'room-place',key,sender,projection)if self.content else dict(kind='room-place',key=key,state='private',checksum=None,requested=False)
                if sender!=viewer:
                    shared=self.content.shared(conn,'room-place',key,sender,projection)if self.content else None
                    value['destination']={k:value['destination'][k]for k in('name','latitude','longitude')};value['destination']['name']=shared['name']if shared else'선택한 장소'
                    if not shared:review=dict(kind='room-place',key=key,state='private',checksum=None,requested=False)
            counts, mine = {'agree': 0, 'pass': 0}, None
            for voter, vote in conn.execute('SELECT account_id,protected FROM team_room_votes WHERE signal_id=%s', (identifier,)):
                member = peers.get(voter)
                if not member or not member['consents']['status'] or (voter != viewer and blocked(conn, viewer, voter)):
                    continue
                choice = self.restore('vote:' + voter, identifier, vote)['choice']
                if choice not in counts:
                    raise PrivateRecordError('Room vote integrity failed')
                counts[choice] += 1
                if voter == viewer:
                    mine = choice
            destination={k:value['destination'][k]for k in('name','latitude','longitude')}if value.get('destination')else None
            result.append(dict(kind=value['kind'],destination=destination,review=review,id=identifier,accountId=sender,createdAt=created,votes=counts,myVote=mine))
        return result

    def router(self):
        router = APIRouter()
        if not self.enabled:
            return router

        def actor(request, mutate=False):
            return request_actor(self.auth,request,mutate=mutate)['id']

        async def body(request, required, optional=()):
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 16384:
                    failure(413, 'Request too large')
            try:
                value = business_json(request,raw,maximum=16384)
            except (ValueError, UnicodeError):
                failure(400, 'Invalid JSON')
            if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
                failure(400, 'Invalid room fields')
            return value

        @router.get('/v1/social/room-archives')
        def archives(request: Request, response: Response):
            if native_resource(request):
                failure()
            with psycopg.connect(self.dsn) as conn:
                owner = self.auth.browser(request, connection=conn)['id']
                self.graph_lock(conn)
                rows = conn.execute('SELECT r.room_id FROM team_rooms r JOIN team_room_members m USING(room_id) '
                    'WHERE m.account_id=%s AND r.trip_id IS NULL AND (r.archived_at IS NOT NULL OR r.closed_at IS NOT NULL OR r.expires_at<=clock_timestamp()) '
                    'ORDER BY COALESCE(r.archived_at,r.closed_at,r.expires_at) DESC,r.room_id DESC LIMIT 100', (owner,)).fetchall()
                result = []
                for (room,) in rows:
                    try:
                        result.append(self.archive_access(conn, room, owner))
                    except HTTPException as error:
                        if error.status_code != 404:
                            raise
            response.headers['Cache-Control'] = 'private, no-store'
            return dict(rooms=result)

        @router.get('/v1/social/room-archives/{room}')
        def archived_room(room: str, request: Request, response: Response):
            if native_resource(request):
                failure()
            with psycopg.connect(self.dsn) as conn:
                owner = self.auth.browser(request, connection=conn)['id']
                self.graph_lock(conn)
                result = self.archive_detail(conn, room, owner)
            response.headers['Cache-Control'] = 'private, no-store'
            return result

        def invite(conn, code):
            if not isinstance(code, str) or not CODE.fullmatch(code):
                failure()
            row = conn.execute('SELECT room_id,owner_id,protected,expires_at FROM team_rooms WHERE code_hash=%s AND trip_id IS NULL '
                'AND closed_at IS NULL AND archived_at IS NULL AND expires_at>clock_timestamp() FOR UPDATE', (self.code_hash(code),)).fetchone()
            if not row:
                failure()
            return row

        @router.get('/v1/social/invites/{code}')
        def invitation(code: str, request: Request):
            owner = actor(request)
            self.auth.rate('room-invite:' + owner, limit=20)
            with psycopg.connect(self.dsn) as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                row = invite(conn, code)
                if any(blocked(conn, owner, peer) for peer in self.active_members(conn, row[0]) if peer != owner):
                    failure()
                value = self.restore('owner:' + row[1], row[0], row[2]);name,review=self.review_name(conn,row[0],row[1],value['name'],owner)
                server_now=conn.execute('SELECT now()').fetchone()[0]
                return dict(id=row[0],code=code,name=name,review=review,expiresAt=row[3], serverNow=server_now,
                    expiresInSeconds=max(0,(row[3]-server_now).total_seconds()), courseId=value['courseId'],
                    courseVersion=value['courseVersion'], course=self.course(conn,value), consentKeys=list(CONSENTS), availableConsentKeys=list(self.available_consents()))

        @router.post('/v1/social/rooms', status_code=201)
        async def create(request: Request):
            owner = actor(request, True)
            data = await body(request, ('name', 'courseId', 'courseVersion', 'expiresInHours'), ('preference',))
            name = text(data['name'], 80)
            hours = data['expiresInHours'];preference = data.get('preference', 'balanced')
            if type(hours) is not int or not 1 <= hours <= 168 or preference not in PREFERENCES:
                failure(400, 'Choose an available expiry and preference')
            self.auth.rate('room-mutate:' + owner, limit=30)
            room, code = secrets.token_hex(16), ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
            with psycopg.connect(self.dsn) as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn)
                if conn.execute('SELECT count(*) FROM team_rooms WHERE owner_id=%s '
                    'AND closed_at IS NULL AND expires_at>now()', (owner,)).fetchone()[0] >= 10:
                    failure(409, 'Manage existing rooms first')
                if data['courseId'] is not None:
                    if not isinstance(data['courseId'], str) or type(data['courseVersion']) is not int:
                        failure(400, 'Choose an available course')
                    if not conn.execute("SELECT 1 FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) "
                        f"WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE}", (data['courseId'], data['courseVersion'])).fetchone():
                        failure(409, 'Course unavailable')
                elif data['courseVersion'] is not None:
                    failure(400, 'Course version requires a course')
                value = dict(name=name, code=code, courseId=data['courseId'], courseVersion=data['courseVersion'], preference=preference)
                conn.execute('INSERT INTO team_rooms(room_id,owner_id,code_hash,protected,expires_at) '
                    'VALUES(%s,%s,%s,%s,now()+make_interval(hours=>%s))',
                    (room, owner, self.code_hash(code), self.protect('owner:' + owner, room, value), hours))
                member = dict(role='member', consents={key:False for key in CONSENTS})
                conn.execute('INSERT INTO team_room_members(room_id,account_id,protected) VALUES(%s,%s,%s)',
                    (room, owner, self.protect('member:' + owner, room, member)))
                self.notify(conn, room)
            return dict(id=room, code=code)

        @router.post('/v1/social/rooms/join')
        async def join(request: Request):
            owner = actor(request, True)
            data = await body(request, ('code', 'consents'));choices = consents(data['consents'],self.available_consents())
            self.auth.rate('room-join:' + owner, limit=15)
            with psycopg.connect(self.dsn) as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn);row = invite(conn, data['code']);room = row[0]
                peers = self.active_members(conn, room)
                if any(blocked(conn, owner, peer) for peer in peers if peer != owner):
                    failure()
                if owner in peers:
                    # Repeat join does not silently rewrite saved role/consent.
                    return dict(id=room, status='joined', consents=peers[owner]['consents'])
                if len(peers) >= 10:
                    failure(409, 'Room is full')
                member = dict(role='member', consents=choices)
                conn.execute('INSERT INTO team_room_members(room_id,account_id,protected) VALUES(%s,%s,%s) '
                    'ON CONFLICT(room_id,account_id) DO UPDATE SET protected=excluded.protected,left_at=NULL,joined_at=now()',
                    (room, owner, self.protect('member:' + owner, room, member)))
                self.notify(conn, room)
            return dict(id=room, status='joined', consents=choices)

        @router.get('/v1/social/rooms/{room}')
        def detail(room: str, request: Request):
            owner = actor(request)
            with psycopg.connect(self.dsn) as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                native = native_resource(request)
                if not native:
                    self.graph_lock(conn)
                value = self.access(conn, room, owner)
                peers = self.active_members(conn, room)
                members = [dict(id=p['id'], name=p['name'], role=p['role']) for p in peers.values()
                    if p['id'] == owner or not blocked(conn, owner, p['id'])]
                if native:
                    value={k:v for k,v in value.items() if k not in ('code','consents','availableConsentKeys')}
                    allowed=getattr(request.state,'functional_snapshot',{}).get('approvedPurposes',frozenset())
                    value.update(nativeReadOnly=not {'rooms:read','rooms:interact'}<=allowed)
                signals = self.signals(conn, room, owner)
                if not native:
                    value['agreedStop'] = self.agreed_stop(conn, peers, signals)
                return dict(value, members=members, signals=signals)

        @router.patch('/v1/social/rooms/{room}/consents')
        async def sharing(room: str, request: Request):
            owner = actor(request, True)
            choices = consents((await body(request, ('consents',)))['consents'],supported=None)
            with psycopg.connect(self.dsn) as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn);value = self.access(conn, room, owner)
                consents(choices,self.available_consents(),previous=value['consents'])
                payload = dict(role=value['role'], consents=choices)
                conn.execute('UPDATE team_room_members SET protected=%s WHERE room_id=%s AND account_id=%s',
                    (self.protect('member:' + owner, room, payload), room, owner))
                if not choices['music']:
                    music=getattr(self.auth,'room_music_service',None)
                    if music:music.clear(conn,room,owner,browser_only=True)
                if not choices['status'] or not choices['location']:self.withdraw_context(conn,room,owner,music=False,voice=False)
                self.notify(conn, room)
            return dict(consents=choices)

        @router.patch('/v1/social/rooms/{room}/role')
        async def role(room: str, request: Request):
            owner = actor(request, True);data = await body(request, ('accountId', 'role'))
            if data['role'] not in ROLES:
                failure(400, 'Invalid role')
            with psycopg.connect(self.dsn) as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn);access = self.access(conn, room, owner)
                if access['ownerId'] != owner:
                    failure(403, 'Only the owner may assign roles')
                target = data['accountId']
                if not isinstance(target,str) or not ACCOUNT.fullmatch(target): failure(400, 'Invalid account')
                peers = self.active_members(conn, room)
                if target not in peers:
                    failure()
                music=getattr(self.auth,'room_music_service',None)
                if data['role']=='dj':
                    for other,peer in peers.items():
                        if other!=target and peer['role']=='dj':
                            authority=getattr(self.auth,'room_music_access',None)
                            if authority:authority.withdraw_room_context(conn,room,other,share_only=True)
                            if music:music.clear(conn,room,other)
                            conn.execute('UPDATE team_room_members SET protected=%s WHERE room_id=%s AND account_id=%s',
                                (self.protect('member:'+other,room,dict(role='member',consents=peer['consents'])),room,other))
                elif peers[target]['role']=='dj':
                    authority=getattr(self.auth,'room_music_access',None)
                    if authority:authority.withdraw_room_context(conn,room,target,share_only=True)
                    if music:music.clear(conn,room,target)
                payload = dict(role=data['role'], consents=peers[target]['consents'])
                conn.execute('UPDATE team_room_members SET protected=%s WHERE room_id=%s AND account_id=%s',
                    (self.protect('member:' + target, room, payload), room, target))
                self.notify(conn, room)
            return dict(status='updated')

        @router.post('/v1/social/rooms/{room}/leave')
        async def leave(room: str, request: Request):
            owner = actor(request, True)
            if native_resource(request):await body(request,())
            with psycopg.connect(self.dsn) as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn);value = self.access(conn, room, owner)
                if value['ownerId'] == owner:
                    conn.execute('UPDATE team_rooms SET closed_at=now() WHERE room_id=%s', (room,))
                    self.archive(conn, room)
                else:
                    conn.execute('UPDATE team_room_members SET left_at=now() WHERE room_id=%s AND account_id=%s', (room, owner))
                    self.withdraw_context(conn,room,owner)
                    self.notify(conn, room, extra=(owner,))
            return dict(status='closed' if value['ownerId'] == owner else 'left')

        @router.patch('/v1/social/rooms/{room}/review-request')
        async def request_room_review(room:str,request:Request):
            owner=actor(request,True);data=await body(request,('consent',))
            with psycopg.connect(self.dsn)as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn);value=self.access(conn,room,owner)
                if value['ownerId']!=owner:failure(403,'Only the owner may request review')
                result=self.content.request(conn,'room',room,owner,self.projection(conn,room,owner),data['consent'],expires_at=value['expiresAt'])
                self.notify(conn,room)
            return dict(review=result)

        @router.post('/v1/social/rooms/{room}/reports',status_code=202)
        async def report_room(room:str,request:Request):
            who=actor(request,True);data=await body(request,('reason',),('code',))
            self.auth.rate('content-report:'+who,limit=20)
            with psycopg.connect(self.dsn)as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn)
                try:value=self.access(conn,room,who);owner=value['ownerId']
                except HTTPException as error:
                    # An authenticated invite holder can report the name shown
                    # before joining. Code possession never grants other data.
                    if error.status_code!=404 or 'code'not in data:raise
                    invited=invite(conn,data['code'])
                    if invited[0]!=room or any(blocked(conn,who,peer)for peer in self.active_members(conn,room)if peer!=who):failure()
                    owner=invited[1]
                projection=self.projection(conn,room,owner)
                if who!=owner and not self.content.allowed(conn,'room',room,owner,projection):failure()
                result=self.content.report(conn,'room',room,owner,projection,who,data['reason'])
            return result

        @router.patch('/v1/social/rooms/{room}/signals/{identifier}/review-request')
        async def request_place_review(room:str,identifier:str,request:Request):
            owner=actor(request,True);data=await body(request,('consent',));key=room+':'+identifier
            if type(data['consent'])is not bool:failure(400,'Explicit review consent required')
            with psycopg.connect(self.dsn)as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn);value=self.access(conn,room,owner)
                row=conn.execute('SELECT protected FROM team_room_signals WHERE room_id=%s AND signal_id=%s AND account_id=%s',(room,identifier,owner)).fetchone()
                if not row:failure()
                signal=self.restore('signal:'+owner,identifier,row[0]);destination=signal.get('destination')
                if not destination:failure()
                projection=dict(name=destination['name'])
                if data['consent']:projection=self.place_projection(conn,key,owner)
                result=self.content.request(conn,'room-place',key,owner,projection,data['consent'],expires_at=value['expiresAt'])
            return dict(review=result)

        @router.post('/v1/social/rooms/{room}/signals/{identifier}/reports',status_code=202)
        async def report_place(room:str,identifier:str,request:Request):
            who=actor(request,True);data=await body(request,('reason',));key=room+':'+identifier
            self.auth.rate('content-report:'+who,limit=20)
            with psycopg.connect(self.dsn)as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn);self.access(conn,room,who)
                signal=next((item for item in self.signals(conn,room,who)if item['id']==identifier),None)
                if not signal or not signal['destination']:failure()
                owner=signal['accountId'];projection=self.place_projection(conn,key,owner)
                if who!=owner and not self.content.allowed(conn,'room-place',key,owner,projection):failure()
                result=self.content.report(conn,'room-place',key,owner,projection,who,data['reason'])
            return result

        @router.post('/v1/social/rooms/{room}/signals', status_code=201)
        async def signal(room: str, request: Request):
            owner = actor(request, True)
            data = await body(request, ('kind',), ('destination',))
            if data['kind'] not in KINDS:
                failure(400, 'Invalid status signal')
            place = data.get('destination')
            if place is not None:
                if not isinstance(place, dict) or set(place) != {'name', 'latitude', 'longitude'}:
                    failure(400, 'Choose a place')
                place = dict(place, name=text(place['name'], 80))
                for field, low, high in [('latitude', -90, 90), ('longitude', -180, 180)]:
                    if type(place[field]) not in (int, float) or not math.isfinite(place[field]) or not low <= place[field] <= high:
                        failure(400, 'Invalid place')
            self.auth.rate('room-signal:' + owner, limit=20)
            identifier = secrets.token_hex(16)
            with psycopg.connect(self.dsn) as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn)
                access = self.access(conn, room, owner, 'status')
                if place is not None and not access['consents']['location']:
                    failure(403, 'Place sharing permission required')
                if conn.execute('SELECT count(*) FROM team_room_signals WHERE room_id=%s', (room,)).fetchone()[0] >= 5000:
                    failure(409, 'Room request limit reached')
                payload = dict(kind=data['kind'], destination=place)
                conn.execute('INSERT INTO team_room_signals(signal_id,room_id,account_id,protected) VALUES(%s,%s,%s,%s)',
                    (identifier, room, owner, self.protect('signal:' + owner, identifier, payload)))
                self.notify(conn, room, sections=('signals',))
            return dict(id=identifier, status='sent')

        @router.post('/v1/social/rooms/{room}/signals/{identifier}/vote')
        async def vote(room: str, identifier: str, request: Request):
            owner = actor(request, True)
            data = await body(request, ('choice',))
            if data['choice'] not in ('agree', 'pass'):
                failure(400, 'Invalid vote')
            self.auth.rate('room-vote:' + owner, limit=30)
            with psycopg.connect(self.dsn) as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn)
                self.access(conn, room, owner, 'status')
                # Visibility is checked with current sender membership/consent.
                # Never allow voting through a guessed cross-room signal ID.
                item=next((item for item in self.signals(conn, room, owner) if item['id']==identifier),None)
                if item is None:
                    failure()
                if item['destination'] is None:
                    failure(409, 'Place proposal unavailable')
                payload = self.protect('vote:' + owner, identifier, dict(choice=data['choice']))
                conn.execute('INSERT INTO team_room_votes(signal_id,account_id,protected) VALUES(%s,%s,%s) '
                    'ON CONFLICT(signal_id,account_id) DO UPDATE SET protected=excluded.protected,updated_at=now()',
                    (identifier, owner, payload))
                self.notify(conn, room, sections=('signals',))
            return dict(status='saved', choice=data['choice'])

        @router.delete('/v1/social/rooms/{room}/signals/{identifier}/vote')
        async def withdraw_vote(room: str, identifier: str, request: Request):
            owner = actor(request, True)
            if native_resource(request):await body(request,())
            self.auth.rate('room-vote:' + owner, limit=30)
            with psycopg.connect(self.dsn) as conn:
                transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                self.graph_lock(conn)
                self.access(conn, room, owner)
                if not conn.execute('SELECT 1 FROM team_room_signals WHERE signal_id=%s AND room_id=%s', (identifier, room)).fetchone():
                    failure()
                conn.execute('DELETE FROM team_room_votes WHERE signal_id=%s AND account_id=%s', (identifier, owner))
                self.notify(conn, room, sections=('signals',))
            return dict(status='withdrawn')

        return router
