"""암호화된 여행과 차량의 여행 조회·초대 응답."""
import os
from pathlib import Path
import re
import secrets
import unicodedata

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from native_access_codec import CodecError, decode_json
from private_records import PrivateRecordError, VisitCipher
from iphone_push_invitations import enqueue_invitation
from team_data import changed
from team_device_commands import iso
from team_friends import ACCOUNT, blocked, linked, pair_ids, read_pair, issue_link, resolve_link, has_vehicle
from native_access import native_resource
from native_functional_identity import request_actor, transaction_actor, business_json
from team_rooms import TeamRooms
from team_trip_places import TeamTripPlaces
from course_publication import COURSE_AVAILABLE
from team_trip_context import (LIVE_STATES, CLOSED_STATES, trip_state, linked_room,
    check_members, resolve_trip_context, create_internal_room, activate_member, bump_revision)

IDENT = re.compile(r'[a-f0-9]{32}')
PACK = re.compile(r'[a-z0-9][a-z0-9_-]{0,79}')
MAX_VOICE_REVISION = 2147483647


def failure(status=404, detail='Trip unavailable'):
    raise HTTPException(status, detail)


def trip_text(value, field, minimum, maximum, *, multiline=False):
    if (not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum
            or any(unicodedata.category(char) in ('Cc', 'Cs') and not (multiline and char == '\n') for char in value)):
        failure(400, 'Invalid ' + field)
    return value.strip()


def trip_fields(data):
    return dict(title=trip_text(data['title'], 'trip title', 1, 40),
        description=trip_text(data['description'], 'trip description', 0, 300, multiline=True))


def car_fields(data):
    name = trip_text(data['name'], 'car name', 1, 20)
    if type(data['seats']) is not int or not 1 <= data['seats'] <= 8:
        failure(400, 'Invalid seats')
    return dict(name=name, seats=data['seats'])


def permissions(value):
    return (isinstance(value, dict) and set(value) == {'invite', 'edit'}
        and all(type(flag) is bool for flag in value.values()))


def location_choice(data):
    enabled = data.get('locationConsent', False)
    if type(enabled) is not bool:
        failure(400, 'Invalid location consent')
    return enabled


def voice_counter_key(trip, account):
    return 'trip-voice:' + trip + ':' + account


def advance_voice_revision(conn, trip, account, *, enabling=False):
    row = conn.execute("INSERT INTO team_resource_versions(account_id,resource,revision) VALUES(%s,'rooms',1) "
        "ON CONFLICT(account_id,resource) DO UPDATE SET revision=team_resource_versions.revision+1 "
        "WHERE team_resource_versions.revision<%s RETURNING revision",
        (voice_counter_key(trip, account), MAX_VOICE_REVISION - 1)).fetchone()
    if row:
        return row[0] + 1
    if enabling:
        failure(409, 'TRIP_VOICE_REVISION_EXHAUSTED')
    return MAX_VOICE_REVISION


def valid_remote_actions(value):
    return (isinstance(value, list) and bool(value)
        and all(isinstance(item, dict) and set(item) == {'id', 'revision'}
            and isinstance(item['id'], str) and 1 <= len(item['id']) <= 80
            and type(item['revision']) is int and item['revision'] >= 1 for item in value)
        and len({(item['id'], item['revision']) for item in value}) == len(value))

def public_remote_actions(value, options):
    return [{key: item[key] for key in ('id', 'revision', 'label')} for item in options
        if dict(id=item['id'], revision=item['revision']) in value]

class TeamTrips:
    def __init__(self, auth):
        self.auth, self.dsn, self.enabled = auth, auth.dsn, auth.enabled
        self.content = Path(os.environ.get("WEGOH_CONTENT_DIR", "/srv/wegoh/content"))

    @staticmethod
    def protect(domain, identifier, payload):
        return VisitCipher().protect('team-trip-' + domain, identifier, payload)

    @staticmethod
    def restore(domain, identifier, payload):
        return VisitCipher().restore('team-trip-' + domain, identifier, payload)

    def person(self, account, *, connection=None):
        try:
            person = (self.auth.current_account(account, connection=connection) if connection is not None
                      else self.auth.current_account(account))
            return dict(id=account, name=person['displayName'])
        except HTTPException:
            return None

    @staticmethod
    def category(conn, account):
        return 'vehicle' if has_vehicle(conn, account) else 'passenger'

    @staticmethod
    def lock_pair(conn, account, target):
        TeamRooms.graph_lock(conn)
        a, b = pair_ids(account, target)
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('friends:' + a + ':' + b,))

    def remote_status(self, conn, trip, account, owner, options, device):
        controls = self.auth.device_command_service.friend_controls
        if device and controls.commands.enabled:
            try:
                controls.context(conn, device, account, owner, trip=trip, states=LIVE_STATES)
                _, grant = controls.trip_grant(conn, trip, device, account)
                return dict(status='granted', requestId=None, actions=public_remote_actions(grant['actions'], options))
            except HTTPException as error:
                if error.status_code not in (401, 403, 404, 409, 410):
                    raise
        return dict(status='none', requestId=None, actions=[])

    def load(self, conn, trip):
        if not isinstance(trip, str) or not IDENT.fullmatch(trip):
            failure()
        row = conn.execute('SELECT owner_id,protected FROM team_trips WHERE trip_id=%s', (trip,)).fetchone()
        if not row:
            failure()
        owner, raw = row
        value = self.restore('owner:' + owner, trip, raw)
        if not isinstance(value, dict) or set(value) != {'title', 'description'}:
            raise PrivateRecordError('Trip integrity failed')
        try:
            if trip_fields(value) != value:
                raise PrivateRecordError('Trip integrity failed')
        except HTTPException:
            raise PrivateRecordError('Trip integrity failed') from None
        return owner, value

    @staticmethod
    def dates(conn, trip):
        start, end = conn.execute('SELECT start_date,end_date FROM team_trips WHERE trip_id=%s', (trip,)).fetchone()
        return dict(startDate=start.isoformat() if start else None, endDate=end.isoformat() if end else None)

    def members(self, conn, trip):
        result = {}
        for account, raw in conn.execute('SELECT account_id,protected FROM team_trip_members WHERE trip_id=%s ORDER BY account_id', (trip,)):
            value = self.member_payload(trip, account, raw)
            result[account] = {key: item for key, item in value.items()
                               if key not in ('phoneLocation', 'vehicleLocation', 'musicPlayback')}
        return result

    def member_payload(self, trip, account, raw):
        value = self.restore('member:' + account, trip, raw)
        required = {'state', 'via', 'permissions'}
        if (not isinstance(value, dict) or not required <= value.keys()
                or value.keys() - required - {'locationConsent', 'locationShareId', 'phoneLocation', 'vehicleLocation',
                                              'musicPlayback'}
                or value['state'] not in ('pending', 'accepted') or value['via'] not in ('friend', 'link')
                or not permissions(value['permissions']) or type(value.get('locationConsent', False)) is not bool):
            raise PrivateRecordError('Trip membership integrity failed')
        enabled = value.get('locationConsent', False)
        if enabled and (value['state'] != 'accepted' or not isinstance(value.get('locationShareId'), str)
                        or not IDENT.fullmatch(value['locationShareId'])):
            raise PrivateRecordError('Trip location sharing integrity failed')
        if not enabled and any(key in value for key in ('locationShareId', 'phoneLocation', 'vehicleLocation')):
            raise PrivateRecordError('Trip location sharing integrity failed')
        playback = value.get('musicPlayback')
        if playback is not None and (value['state'] != 'accepted' or not isinstance(playback, dict)
                or set(playback) != {'itemId', 'startedAt'} or not isinstance(playback['itemId'], str)
                or not IDENT.fullmatch(playback['itemId']) or not isinstance(playback['startedAt'], str)
                or not 1 <= len(playback['startedAt']) <= 40):
            raise PrivateRecordError('Trip music playback integrity failed')
        return value

    def save_member(self, conn, trip, account, state='pending', via='friend', rights=None, *, location_consent=False):
        current = trip_state(conn, trip)['state']
        if current not in LIVE_STATES:
            failure(409, 'TRIP_STATE_CONFLICT')
        members = self.members(conn, trip)
        room, _ = linked_room(conn, trip)
        check_members(conn, trip, room, members)
        previous = members.get(account)
        if previous and previous['state'] == 'accepted' and state != 'accepted':
            failure(409, 'TRIP_MEMBERSHIP_CONFLICT')
        if account not in members and len(members) >= 20:
            failure(409, 'Trip is full')
        if (state == 'accepted' and not (previous and previous['state'] == 'accepted')
                and current == 'active' and self.active_trips(conn, account, trip)):
            failure(409, 'TRIP_ALREADY_ACTIVE')
        if previous and previous['state'] == 'accepted':
            raw, = conn.execute('SELECT protected FROM team_trip_members WHERE trip_id=%s AND account_id=%s',
                                (trip, account)).fetchone()
            value = self.member_payload(trip, account, raw)
        else:
            value = {}
            if state == 'accepted':
                exhausted = conn.execute("SELECT 1 FROM team_resource_versions WHERE account_id=%s "
                    "AND resource='rooms' AND revision>=%s", (voice_counter_key(trip, account), MAX_VOICE_REVISION - 1)).fetchone()
                activate_member(conn, room, account, location_consent=location_consent, voice_enabled=not exhausted)
                value['locationConsent'] = location_consent
                if location_consent:
                    value['locationShareId'] = secrets.token_hex(16)
        value.update(state=state, via=via, permissions=rights or dict(invite=False, edit=False))
        protected = self.protect('member:' + account, trip, value)
        conn.execute('INSERT INTO team_trip_members(trip_id,account_id,protected) VALUES(%s,%s,%s) '
            'ON CONFLICT(trip_id,account_id) DO UPDATE SET protected=excluded.protected',
            (trip, account, protected))
        return protected

    def location_sharing(self, conn, trip, account, *, enabled=None):
        context = resolve_trip_context(self.auth, conn, trip, account)
        member = context['members'][account]
        previous = member.get('locationConsent', False)
        share_id = member.get('locationShareId')
        revision = context['revision']
        if enabled is not None and enabled != previous:
            share_id = secrets.token_hex(16) if enabled else None
            member['locationConsent'] = enabled
            if enabled:
                member['locationShareId'] = share_id
            else:
                member.pop('locationShareId', None)
            # members() excludes latest fixes, so a new sharing period starts empty.
            conn.execute('UPDATE team_trip_members SET protected=%s WHERE trip_id=%s AND account_id=%s',
                         (self.protect('member:' + account, trip, member), trip, account))
            room = context['roomId']
            raw, = conn.execute('SELECT protected FROM team_room_members WHERE room_id=%s AND account_id=%s',
                                (room, account)).fetchone()
            rooms = TeamRooms(self.auth)
            membership = rooms.member_payload(account, room, raw)
            location_changed = membership['consents']['location'] != enabled
            membership['consents']['location'] = enabled
            conn.execute('UPDATE team_room_members SET protected=%s WHERE room_id=%s AND account_id=%s',
                         (rooms.protect('member:' + account, room, membership), room, account))
            vehicle = getattr(self.auth, 'vehicle_service', None)
            if vehicle:
                vehicle.reset_trip_location_reports(conn, room, account)
            places_withdrawn = location_changed and TeamTripPlaces.withdraw_for_location(conn, trip, account)
            sections = ('location', 'route') if places_withdrawn else ('location',)
            self.notify(conn, trip, sections=sections, invalidate=False)
            revision = trip_state(conn, trip)['revision']
            previous = enabled
        return dict(locationConsent=previous, locationShareId=share_id, revision=revision)

    def require_member(self, conn, account, owner, members, *, pending=False):
        if (members.get(account, {}).get('state') != ('pending' if pending else 'accepted')
                or not self.person(owner, connection=conn) or not self.person(account, connection=conn)
                or (owner != account and blocked(conn, owner, account))):
            failure()

    def access(self, conn, trip, account, *, permission=None, pending=False, mutable=False):
        owner, value = self.load(conn, trip)
        members = self.members(conn, trip)
        self.require_member(conn, account, owner, members, pending=pending)
        if permission and account != owner:
            if permission == 'owner':
                failure(403, 'Only the owner may manage the trip')
            if not members[account]['permissions'][permission]:
                failure(403, 'Trip ' + permission + ' permission required')
        if mutable:
            if trip_state(conn, trip)['state'] not in LIVE_STATES:
                failure(409, 'TRIP_STATE_CONFLICT')
            room, room_owner = linked_room(conn, trip)
            if room_owner != owner:
                raise PrivateRecordError('Trip owner integrity failed')
            check_members(conn, trip, room, members)
        return owner, value, members

    def rights(self, account, owner, members):
        return dict(invite=True, edit=True) if account == owner else members[account]['permissions']

    def notify(self, conn, trip, extra=(), *, trip_accounts=None, bump=True, invalidate=True, sections=None):
        from team_event_versions import SECTIONS, trip_changed
        trip_changed(conn, trip, SECTIONS if sections is None else sections)
        if bump:
            bump_revision(conn, trip)
        hook = getattr(getattr(self.auth, 'trip_signal_contexts', None), 'invalidate_trip_context', None)
        if hook and invalidate:
            hook(conn, trip)
        accounts = {row[0] for row in conn.execute('SELECT account_id FROM team_trip_members WHERE trip_id=%s', (trip,))}
        accounts |= set(extra)
        trip_accounts = accounts if trip_accounts is None else accounts & set(trip_accounts)
        for account in sorted(accounts):
            changed(conn, account, 'friends', legacy_only=True)
            if sections is None:
                from team_event_versions import bump as event_bump
                event_bump(conn, 'event-account:' + account, 'rooms')
            if account in trip_accounts:
                changed(conn, 'trip-account:' + account, 'rooms')

    def common_trips(self, conn, a, b):
        return [row[0] for row in conn.execute('SELECT a.trip_id FROM team_trip_members a '
            'JOIN team_trip_members b USING(trip_id) WHERE a.account_id=%s AND b.account_id=%s ORDER BY a.trip_id', (a, b))]

    def friendship_changed(self, conn, a, b, accepted):
        for trip in self.common_trips(conn, a, b):
            if not accepted:
                for identifier, value in self.remote_requests(conn, trip).items():
                    if {value['requesterId'], value['ownerId']} == {a, b}:
                        self.delete_remote_request(conn, trip, identifier)
            self.notify(conn, trip, trip_accounts=(), bump=False, invalidate=False)

    def on_block(self, conn, blocker, target):
        for trip in self.common_trips(conn, blocker, target):
            trip_state(conn, trip)
            owner, _ = self.load(conn, trip)
            if owner in (blocker, target):
                self.remove_member(conn, trip, target if owner == blocker else blocker)
            else:
                room, _ = linked_room(conn, trip)
                voice = getattr(self.auth, 'room_voice_access', None)
                if voice:
                    for account in (blocker, target):
                        voice.withdraw_room_context(conn, room, account)
                for name in ('mission_service', 'voice_service', 'trip_signal_contexts'):
                    service = getattr(self.auth, name, None)
                    hook = getattr(service, 'on_trip_block', None)
                    if hook:
                        hook(conn, trip, room, blocker, target)
            self.notify(conn, trip, (blocker, target),
                trip_accounts=None if owner in (blocker, target) else (blocker, target))

    def remove_member(self, conn, trip, account):
        trip_state(conn, trip)
        from team_trip_route_segments import TeamTripRouteSegments, route_contract_version
        segmented = route_contract_version(conn, trip) == 2
        room, _ = linked_room(conn, trip)
        members = self.members(conn, trip)
        check_members(conn, trip, room, members)
        accepted = members.get(account, {}).get('state') == 'accepted'
        if accepted:
            conn.execute('UPDATE team_room_members SET left_at=clock_timestamp() '
                'WHERE room_id=%s AND account_id=%s AND left_at IS NULL', (room, account))
            advance_voice_revision(conn, trip, account)
        for identifier, value in self.remote_requests(conn, trip).items():
            if account in (value['requesterId'], value['ownerId']):
                self.delete_remote_request(conn, trip, identifier)
        for pack, value in (self.course_links(conn, trip).items() if not segmented else []):
            if value['addedBy'] == account:
                conn.execute('DELETE FROM team_trip_courses WHERE trip_id=%s AND pack_id=%s', (trip, pack))
                from team_trip_plan import TeamTripPlan
                TeamTripPlan(self).courses_changed(conn, trip)
        for car, value in self.cars(conn, trip).items():
            if value['driverId'] == account:
                self.remove_car(conn, trip, car, defer_reconcile=segmented)
        self.leave_car(conn, trip, account)
        conn.execute('DELETE FROM team_trip_members WHERE trip_id=%s AND account_id=%s', (trip, account))
        if accepted:
            self.withdraw_context(conn, trip, room, account)
        if segmented:
            TeamTripRouteSegments(self).reconcile(conn, trip)

    def withdraw_context(self, conn, trip, room, account=None):
        rooms = getattr(self.auth, 'room_service', None) or TeamRooms(self.auth)
        rooms.withdraw_context(conn, room, account, preserve_music=account is None)
        for name in ('vehicle_service', 'device_command_service', 'room_music_service',
                'room_music_access', 'room_voice_access', 'voice_service', 'mission_service',
                'trip_signal_contexts'):
            hook = getattr(getattr(self.auth, name, None), 'withdraw_trip_context', None)
            if hook:
                hook(conn, trip, room, account=account)

    @staticmethod
    def active_trips(conn, account, excluded):
        """Other active trips the account currently takes part in, newest start first."""
        return [row[0] for row in conn.execute("SELECT t.trip_id FROM team_trips t JOIN team_rooms r USING(trip_id) "
            "JOIN team_room_members rm ON rm.room_id=r.room_id AND rm.left_at IS NULL "
            "WHERE rm.account_id=%s AND t.state='active' AND t.deleted_at IS NULL AND t.trip_id<>%s "
            "ORDER BY t.started_at DESC, t.trip_id", (account, excluded))]

    def start_conflict(self, conn, trip, account, memberships):
        """Who keeps this trip from starting: the starter's own active trips and busy accepted members.

        Members who are only busy in a trip the starter owns are not counted, because ending
        the starter's active trip before the start completes that trip for them as well."""
        own = self.active_trips(conn, account, trip)
        owners = {other: self.load(conn, other)[0] for other in own}
        ending = {other for other, owner in owners.items() if owner == account}
        busy = sorted(peer for peer, member in memberships.items()
            if peer != account and member['state'] == 'accepted'
            and set(self.active_trips(conn, peer, trip)) - ending)
        return own, owners, busy

    def end_active_trips(self, conn, account, own, owners):
        for other in own:
            if owners[other] == account:
                self.close_active_trip(conn, other)
            else:
                self.remove_member(conn, other, account)
                self.notify(conn, other, (account,))

    def transition(self, conn, trip, account, action, revision, route_contract_version=None, *, end_active_trip=False):
        if type(revision) is not int or not 1 <= revision <= 2147483647:
            failure(400, 'Invalid trip revision')
        if type(end_active_trip) is not bool or (end_active_trip and action != 'start'):
            failure(400, 'Invalid trip transition')
        transitions = {'start': ('planned', 'active'), 'finish': ('active', 'completed'),
            'cancel': ('planned', 'cancelled')}
        if not isinstance(action, str) or action not in transitions:
            failure(400, 'Invalid trip transition')
        if route_contract_version is not None and (action != 'start' or type(route_contract_version) is not int or route_contract_version != 2):
            failure(400, 'TRIP_ROUTE_CONTRACT_INVALID')
        context = resolve_trip_context(self.auth, conn, trip, account, states=None, permission='owner')
        source, target = transitions[action]
        state_revision = conn.execute('SELECT state_revision FROM team_trips WHERE trip_id=%s', (trip,)).fetchone()[0]
        if context['state'] == target and (revision == context['revision'] or
                revision == state_revision - 1 and context['revision'] == state_revision):
            return {key: context[key] for key in ('tripId', 'state', 'revision', 'startedAt', 'endedAt')}
        if context['state'] != source or revision != context['revision']:
            failure(409, 'TRIP_STATE_CONFLICT')
        if action == 'start':
            own, owners, busy = self.start_conflict(conn, trip, account, context['members'])
            if own and not end_active_trip:
                failure(409, 'TRIP_ALREADY_ACTIVE')
            if busy:
                failure(409, 'TRIP_MEMBER_ALREADY_ACTIVE')
            self.end_active_trips(conn, account, own, owners)
        if action == 'start' and route_contract_version == 2:
            from team_trip_route_segments import TeamTripRouteSegments
            TeamTripRouteSegments(self).prepare(conn, trip, context['ownerId'])
        timestamp = 'started_at' if action == 'start' else 'ended_at'
        conn.execute('UPDATE team_trips SET state=%s,' + timestamp + '=clock_timestamp(),state_revision=revision+1,revision=revision+1 '
            'WHERE trip_id=%s', (target, trip))
        context.update(trip_state(conn, trip))
        self.close_context(conn, context, target)
        self.notify(conn, trip, bump=False)
        return {key: context[key] for key in ('tripId', 'state', 'revision', 'startedAt', 'endedAt')}

    def close_context(self, conn, context, target):
        trip = context['tripId']
        if target in CLOSED_STATES:
            room = context['roomId']
            conn.execute('UPDATE team_rooms SET closed_at=%s,archived_at=%s, '
                'archived_music=(SELECT protected FROM team_room_music WHERE room_id=%s) WHERE room_id=%s',
                (context['endedAt'], context['endedAt'], room, room))
            conn.execute('DELETE FROM team_trip_links WHERE trip_id=%s', (trip,))
            conn.execute('DELETE FROM team_trip_remote_requests WHERE trip_id=%s', (trip,))
            self.withdraw_context(conn, trip, room)
            if target == 'completed':
                hook = getattr(getattr(self.auth, 'trip_results_service', None), 'finish_trip', None)
                if hook:
                    hook(conn, context)

    def close_active_trip(self, conn, trip):
        owner = self.load(conn, trip)[0]
        context = resolve_trip_context(self.auth, conn, trip, owner, states=None)
        if context['state'] != 'active':
            return
        conn.execute("UPDATE team_trips SET state='completed',ended_at=clock_timestamp(),state_revision=revision+1,revision=revision+1 WHERE trip_id=%s", (trip,))
        context.update(trip_state(conn, trip))
        self.close_context(conn, context, 'completed')
        self.notify(conn, trip, bump=False)

    def set_role(self, conn, trip, account, target, role, revision):
        from team_rooms import ROLES
        if (role not in ROLES or type(revision) is not int or not 1 <= revision <= 2147483647
                or not isinstance(target, str) or not ACCOUNT.fullmatch(target)):
            failure(400, 'Invalid trip role')
        context = resolve_trip_context(self.auth, conn, trip, account, permission='owner')
        if context['revision'] != revision:
            failure(409, 'TRIP_REVISION_CONFLICT')
        if context['members'].get(target, {}).get('state') != 'accepted':
            failure()
        rooms = TeamRooms(self.auth)
        peers = rooms.active_members(conn, context['roomId'])
        if target not in peers:
            failure()
        for peer, member in peers.items():
            selected = role if peer == target else 'member' if role == 'dj' and member['role'] == 'dj' else member['role']
            if selected == member['role']:
                continue
            if member['role'] == 'dj':
                authority = getattr(self.auth, 'room_music_access', None)
                if authority:
                    authority.withdraw_room_context(conn, context['roomId'], peer, share_only=True)
                music = getattr(self.auth, 'room_music_service', None)
                if music:
                    music.clear(conn, context['roomId'], peer)
            conn.execute('UPDATE team_room_members SET protected=%s WHERE room_id=%s AND account_id=%s',
                (rooms.protect('member:' + peer, context['roomId'], dict(role=selected, consents=member['consents'])), context['roomId'], peer))
        self.notify(conn, trip)
        return dict(status='updated', revision=trip_state(conn, trip)['revision'])

    def set_sharing(self, conn, trip, account, choices):
        from team_rooms import consents
        state = trip_state(conn, trip)
        room, _ = linked_room(conn, trip)
        raw = conn.execute('SELECT protected,left_at FROM team_room_members WHERE room_id=%s AND account_id=%s', (room, account)).fetchone()
        if not raw or not self.person(account):
            failure()
        rooms = TeamRooms(self.auth)
        member = rooms.member_payload(account, room, raw[0])
        revocation_only = raw[1] is not None or state['state'] in CLOSED_STATES
        location_enabled = False
        if not revocation_only:
            context = resolve_trip_context(self.auth, conn, trip, account)
            location_enabled = context['members'][account].get('locationConsent', False)
        if isinstance(choices, dict):
            choices = {**{key: member['consents'][key] for key in ('location', 'voice')}, **choices}
        choices = consents(choices, rooms.available_consents(), previous=member['consents'])
        if location_enabled and not choices['location']:
            self.location_sharing(conn, trip, account, enabled=False)
            member['consents']['location'] = False
            location_enabled = False
        if revocation_only and any(choices[key] and not member['consents'][key] for key in choices):
            failure(409, 'TRIP_STATE_CONFLICT')
        if choices != member['consents']:
            conn.execute('UPDATE team_room_members SET protected=%s WHERE room_id=%s AND account_id=%s',
                (rooms.protect('member:' + account, room, dict(role=member['role'], consents=choices)), room, account))
            revoked = {key for key in choices if member['consents'][key] and not choices[key]}
            if choices['location'] != member['consents']['location']:
                TeamTripPlaces.withdraw_for_location(conn, trip, account)
            if revoked & {'status', 'visits', 'control'}:
                rooms.withdraw_context(conn, room, account, music=False, voice=False)
            elif 'location' in revoked:
                vehicle = getattr(self.auth, 'vehicle_service', None)
                if vehicle:
                    vehicle.reset_trip_location_reports(conn, room, account)
            if 'music' in revoked:
                authority = getattr(self.auth, 'room_music_access', None)
                if authority:
                    authority.withdraw_room_context(conn, room, account)
                music = getattr(self.auth, 'room_music_service', None)
                if music:
                    music.withdraw_saved_tracks(conn, room, account)
                    music.clear(conn, room, account)
            if choices['voice'] != member['consents']['voice']:
                self.voice_participation_changed(conn, trip, room, account, choices['voice'])
            self.notify(conn, trip)
        return dict(consents=dict(choices, location=location_enabled), revision=trip_state(conn, trip)['revision'])

    def voice_participation_changed(self, conn, trip, room, account, enabled):
        revision = advance_voice_revision(conn, trip, account, enabling=enabled)
        if not enabled:
            authority = getattr(self.auth, 'room_voice_access', None)
            if authority:
                authority.withdraw_room_context(conn, room, account)
            elif voice := getattr(self.auth, 'voice_service', None):
                voice.invalidate_context(room, accounts={account})
        return revision

    def voice_membership(self, conn, trip, room, account):
        row = conn.execute("SELECT m.protected,m.joined_at,1+LEAST(%s,COALESCE(v.revision,0)) FROM team_room_members m "
            "LEFT JOIN team_resource_versions v ON v.account_id=%s AND v.resource='rooms' "
            "WHERE m.room_id=%s AND m.account_id=%s AND m.left_at IS NULL",
            (MAX_VOICE_REVISION - 1, voice_counter_key(trip, account), room, account)).fetchone()
        if not row:
            failure()
        member = TeamRooms(self.auth).member_payload(account, room, row[0])
        return member, dict(tripId=trip, participating=member['consents']['voice'],
                            memberJoinedAt=row[1].isoformat(), revision=row[2])

    def voice_participation(self, conn, trip, account, change=None):
        context = resolve_trip_context(self.auth, conn, trip, account, states=('active',))
        if any(peer != account and membership['state'] == 'accepted' and blocked(conn, account, peer)
               for peer, membership in context['members'].items()):
            failure()
        rooms = TeamRooms(self.auth)
        if 'voice' not in rooms.available_consents():
            failure(403, 'TRIP_VOICE_UNAVAILABLE')
        room = context['roomId']
        member, result = self.voice_membership(conn, trip, room, account)
        if change is None:
            return result
        if (type(change['participating']) is not bool or type(change['revision']) is not int
                or not 1 <= change['revision'] <= MAX_VOICE_REVISION
                or not isinstance(change['memberJoinedAt'], str) or not 1 <= len(change['memberJoinedAt']) <= 64):
            failure(400, 'Invalid voice participation')
        if change['memberJoinedAt'] != result['memberJoinedAt'] or change['revision'] != result['revision']:
            failure(409, 'TRIP_VOICE_PARTICIPATION_CHANGED')
        enabled = change['participating']
        if result['participating'] != enabled:
            member['consents']['voice'] = enabled
            conn.execute('UPDATE team_room_members SET protected=%s WHERE room_id=%s AND account_id=%s',
                         (rooms.protect('member:' + account, room, member), room, account))
            revision = self.voice_participation_changed(conn, trip, room, account, enabled)
            rooms.notify(conn, room, sections=('voice',))
            result.update(participating=enabled, revision=revision)
        return result

    def car_payload(self, trip, car, driver, raw):
        value = self.restore('car:' + car + ':driver:' + driver, trip, raw)
        try:
            if (not isinstance(value, dict) or not {'name', 'seats'} <= value.keys()
                    or value.keys() - {'name', 'seats', 'routeNext', 'routeRevision', 'routeSignals', 'remotePolicy', 'remotePolicyRevision', 'remotePolicyGrantId'}
                    or car_fields({key: value[key] for key in ('name', 'seats')}) != {key: value[key] for key in ('name', 'seats')}
                    or type(value.get('routeRevision', 0)) is not int or not 0 <= value.get('routeRevision', 0) <= 2147483647):
                raise PrivateRecordError('Trip car integrity failed')
            from team_trip_remote_policy import saved_policy
            saved_policy(value)
            from team_trip_plan import TeamTripPlan
            from team_trip_signal_contexts import place_value
            if value.get('routeNext') is not None:
                TeamTripPlan.order_fields([value['routeNext']])
            places = value.get('routeSignals', {})
            if not isinstance(places, dict) or len(places) > 50:
                raise PrivateRecordError('Trip car integrity failed')
            for signal, place in places.items():
                if (not isinstance(signal, str) or not IDENT.fullmatch(signal) or not isinstance(place, dict)
                        or set(place) != {'name', 'lat', 'lng'}):
                    raise PrivateRecordError('Trip car integrity failed')
                place_value(dict(name=place['name'], latitude=place['lat'], longitude=place['lng']))
        except (HTTPException, KeyError, TypeError):
            raise PrivateRecordError('Trip car integrity failed') from None
        return value

    def cars(self, conn, trip):
        result = {}
        for car, driver, raw, ordinal in conn.execute('SELECT car_id,driver_id,protected,ordinal FROM team_trip_cars WHERE trip_id=%s ORDER BY ordinal,car_id', (trip,)):
            value = self.car_payload(trip, car, driver, raw)
            from team_trip_remote_policy import saved_policy
            result[car] = dict(name=value['name'], seats=value['seats'], driverId=driver, ordinal=ordinal, remotePolicy=saved_policy(value))
        return result

    def car(self, conn, trip, car, account):
        value = self.cars(conn, trip).get(car)
        if not value or (value['driverId'] != account and blocked(conn, account, value['driverId'])):
            failure(404, 'Car unavailable')
        return value

    @staticmethod
    def riders(conn, trip):
        return dict(conn.execute('SELECT account_id,car_id FROM team_trip_riders WHERE trip_id=%s ORDER BY account_id', (trip,)))

    def remove_car(self, conn, trip, car, *, defer_reconcile=False):
        self.auth.device_command_service.friend_controls.withdraw_trip_grants(conn, trip=trip, car=car)
        for identifier, value in self.remote_requests(conn, trip).items():
            if value['carId'] == car:
                self.delete_remote_request(conn, trip, identifier)
        conn.execute('DELETE FROM team_trip_cars WHERE trip_id=%s AND car_id=%s', (trip, car))
        from team_trip_route_segments import TeamTripRouteSegments
        TeamTripRouteSegments(self).withdraw_car(conn, trip, car, defer_reconcile=defer_reconcile)

    def leave_car(self, conn, trip, account):
        self.auth.device_command_service.friend_controls.withdraw_trip_grants(conn, trip=trip, peer=account)
        for identifier, value in self.remote_requests(conn, trip).items():
            if value['requesterId'] == account:
                self.delete_remote_request(conn, trip, identifier)
        conn.execute('DELETE FROM team_trip_riders WHERE trip_id=%s AND account_id=%s', (trip, account))

    def assign_ride(self, conn, trip, car_id, account):
        self.access(conn, trip, account, mutable=True)
        car = self.car(conn, trip, car_id, account)
        if any(item['driverId'] == account for item in self.cars(conn, trip).values()):
            failure(409, 'Already driving')
        riders = self.riders(conn, trip)
        if riders.get(account) == car_id:
            return False
        if sum(riding == car_id for riding in riders.values()) >= car['seats']:
            failure(409, 'Car is full')
        self.leave_car(conn, trip, account)
        conn.execute('INSERT INTO team_trip_riders(trip_id,account_id,car_id) VALUES(%s,%s,%s)', (trip, account, car_id))
        return True

    def remote_requests(self, conn, trip):
        result = {}
        for identifier, requester, driver, car, raw in conn.execute('SELECT request_id,requester_id,driver_id,car_id,protected FROM team_trip_remote_requests WHERE trip_id=%s ORDER BY request_id', (trip,)):
            value = self.restore('remote-request:' + identifier, trip, raw)
            if isinstance(value, dict):
                value.update(requesterId=requester, ownerId=driver, carId=car)
            if (not isinstance(value, dict) or set(value) != {'carId', 'requesterId', 'ownerId', 'createdAt', 'actions'}
                    or not isinstance(value['carId'], str) or not IDENT.fullmatch(value['carId'])
                    or any(not isinstance(value[key], str) or not ACCOUNT.fullmatch(value[key]) for key in ('requesterId', 'ownerId'))
                    or value['requesterId'] == value['ownerId'] or not isinstance(value['createdAt'], str)
                    or not valid_remote_actions(value['actions'])):
                raise PrivateRecordError('Trip remote request integrity failed')
            result[identifier] = value
        return result

    @staticmethod
    def delete_remote_request(conn, trip, identifier):
        conn.execute('DELETE FROM team_trip_remote_requests WHERE trip_id=%s AND request_id=%s', (trip, identifier))

    def remote_pair(self, conn, trip, car, requester, driver):
        self.lock_pair(conn, requester, driver)
        if self.riders(conn, trip).get(requester) != car or not self.person(requester) or not self.person(driver):
            failure(404, 'Remote request unavailable')
        if not linked(conn, requester, driver):
            failure(409, 'Friends only')

    def course_links(self, conn, trip):
        result = {}
        for pack, adder, raw in conn.execute('SELECT pack_id,added_by,protected FROM team_trip_courses '
                'WHERE trip_id=%s ORDER BY priority NULLS LAST,created_at,pack_id', (trip,)):
            value = self.restore('course:' + pack, trip, raw)
            if isinstance(value, dict):
                value['addedBy'] = adder
            if (not isinstance(value, dict) or set(value) != {'packId', 'addedBy'} or value['packId'] != pack
                    or not PACK.fullmatch(pack) or not isinstance(value['addedBy'], str)
                    or not ACCOUNT.fullmatch(value['addedBy'])):
                raise PrivateRecordError('Trip course integrity failed')
            result[pack] = value
        return result

    def courses(self, conn, trip, account, can_edit):
        from team_trip_plan import TeamTripPlan
        plan = TeamTripPlan(self)
        from team_trip_route_segments import TeamTripRouteSegments
        frozen = TeamTripRouteSegments(self).frozen_courses(conn, trip, account, can_edit)
        result = [] if frozen is None else frozen
        for pack, link in (self.course_links(conn, trip).items() if frozen is None else []):
            adder = link['addedBy']
            if adder != account and blocked(conn, adder, account):
                continue
            person = self.person(adder)
            row = conn.execute('SELECT p.version,p.title,p.stop_count FROM pack_versions p '
                f'WHERE p.pack_id=%s AND {COURSE_AVAILABLE} '
                'ORDER BY p.version DESC LIMIT 1', (pack,)).fetchone()
            if not person or not row:
                continue
            version, title, stop_count = row
            mine = adder == account
            stops = plan.read_stops(conn, pack, version)
            published_ids = {stop['id'] for stop in stops}
            waypoints = [point for point in plan.course_waypoints(conn, trip, pack) if point['id'] not in published_ids] if stops else []
            result.append(dict(packId=pack, version=version, title=title,
                stopCount=stop_count + len(waypoints), addedById=adder, addedByName=person['name'], mine=mine,
                canRemove=mine or can_edit, reviewed=True,
                stops=stops[:-1] + waypoints + stops[-1:], waypoints=waypoints,
                completedCarIds=[car for car, driver in conn.execute('SELECT x.car_id,c.driver_id '
                    'FROM team_trip_car_course_completions x JOIN team_trip_cars c USING(trip_id,car_id) '
                    'WHERE x.trip_id=%s AND x.pack_id=%s ORDER BY x.car_id', (trip, pack))
                    if self.person(driver) and (driver == account or not blocked(conn, driver, account))]))
        from team_trip_driving_scores import TeamTripDrivingScores
        scores = TeamTripDrivingScores(self)
        for course in result:
            course['drivingScores'] = scores.for_course(conn, trip, account, course['packId'], course['version'])
        return result

    def set_course_priority(self, conn, trip, account, pack_ids, revision):
        if (not isinstance(pack_ids, list) or not 2 <= len(pack_ids) <= 10
                or any(not isinstance(pack, str) or not PACK.fullmatch(pack) for pack in pack_ids)
                or len(set(pack_ids)) != len(pack_ids) or type(revision) is not int
                or not 1 <= revision <= 2147483647):
            failure(400, 'Invalid trip course priority')
        self.access(conn, trip, account, permission='edit', mutable=True)
        state = trip_state(conn, trip)
        if state['state'] != 'planned' or revision != state['revision']:
            failure(409, 'TRIP_REVISION_CONFLICT')
        visible = [course['packId'] for course in self.courses(conn, trip, account, True)]
        if set(visible) != set(pack_ids):
            failure(409, 'TRIP_REVISION_CONFLICT')
        if visible != pack_ids:
            # Keep courses hidden from this editor in their original slots.
            sequence = iter(pack_ids)
            visible_set = set(visible)
            ordered = (next(sequence) if pack in visible_set else pack for pack in self.course_links(conn, trip))
            for priority, pack in enumerate(ordered, 1):
                conn.execute('UPDATE team_trip_courses SET priority=%s WHERE trip_id=%s AND pack_id=%s',
                    (priority, trip, pack))
            from team_trip_plan import TeamTripPlan
            TeamTripPlan(self).course_priority_changed(conn, trip)
            self.notify(conn, trip, sections=('route',))
        return dict(status='updated', revision=trip_state(conn, trip)['revision'])

    def readiness(self, conn, trip, memberships, cars, riders):
        # Departure readiness is the per-person part of the preparation checklist: accepted, in a car,
        # and either a driver with a connected vehicle or a passenger with both pickup and drop chosen.
        placed = {}
        for peer, car, kind in conn.execute('SELECT account_id,car_id,kind FROM team_trip_car_place_selections '
                'WHERE trip_id=%s', (trip,)):
            placed.setdefault((peer, car), set()).add(kind)
        drivers = {item['driverId'] for item in cars.values()}
        result = {}
        for peer, membership in memberships.items():
            if membership['state'] != 'accepted':
                result[peer] = 'invited'
            elif peer in drivers:
                result[peer] = 'ready' if self.category(conn, peer) == 'vehicle' else 'needsVehicle'
            elif peer not in riders:
                result[peer] = 'needsCar'
            else:
                result[peer] = 'ready' if placed.get((peer, riders[peer])) == {'pickup', 'drop'} else 'needsPlaces'
        return result

    def detail(self, conn, trip, account, *, native=False):
        from team_trip_plan import TeamTripPlan
        plan = TeamTripPlan(self)
        owner, value, memberships = self.access(conn, trip, account)
        rights = self.rights(account, owner, memberships)
        cars, riders = self.cars(conn, trip), self.riders(conn, trip)
        options = self.auth.device_command_service.friend_controls.options()
        visible = {peer: self.person(peer) for peer in memberships if peer == account or not blocked(conn, peer, account)}
        visible = {peer: person for peer, person in visible.items() if person}
        room, _ = linked_room(conn, trip)
        roles = TeamRooms(self.auth).active_members(conn, room)
        readiness = self.readiness(conn, trip, memberships, cars, riders)
        members = []
        for peer, membership in memberships.items():
            if peer not in visible or (membership['state'] == 'pending' and not rights['invite']):
                continue
            pair = read_pair(conn, *pair_ids(account, peer))[0] if peer != account else dict(state='none', requestedBy=None)
            friend_request = ('sent' if pair['requestedBy'] == account else 'received') if pair['state'] == 'pending' else 'none'
            car_id = next((car for car, item in cars.items() if item['driverId'] == peer), riders.get(peer))
            if car_id and cars[car_id]['driverId'] not in visible:
                car_id = None
            members.append(dict(visible[peer], state=membership['state'], via=membership['via'],
                isOwner=peer == owner, isMe=peer == account, isFriend=pair['state'] == 'accepted', friendRequest=friend_request,
                hasVehicle=self.category(conn, peer) == 'vehicle', carId=car_id, readiness=readiness[peer],
                role=roles.get(peer, {}).get('role', 'member'),
                permissions=self.rights(peer, owner, memberships) if account == owner else None))
        members.sort(key=lambda member: (not member['isOwner'], member['id']))
        result = []
        for car, item in cars.items():
            driver = item['driverId']
            if driver not in visible:
                continue
            ready = self.category(conn, driver) == 'vehicle'
            riding = riders.get(account) == car
            remote = self.remote_status(conn, trip, account, driver, options, item['remotePolicy']['deviceId']) if riding and driver != account and ready else None
            passengers = []
            for peer, assigned_car in riders.items():
                if assigned_car != car or peer not in visible:
                    continue
                passenger = dict(visible[peer], isMe=peer == account)
                passengers.append(passenger)
            shown = dict(item)
            if account != driver and not riding:
                shown['remotePolicy'] = None
            result.append(dict(id=car, **shown, driverName=visible[driver]['name'], isMine=driver == account,
                iRide=riding, driverVehicleReady=ready, remote=remote,
                places=plan.places(conn, trip, car, account, owner),
                routeOrder=plan.route_order(conn, trip, car, account, owner),
                passengers=passengers))
            if account in (owner, driver) or riding:
                route_state = plan.route_state(conn, trip, car)[1]
                result[-1]['routeRevision'] = route_state.get('routeRevision', 0)
                result[-1].update(plan.project_next(conn, trip, car, account, route_state))
        link = None
        if rights['invite']:
            row = conn.execute('SELECT expires_at FROM team_trip_links WHERE trip_id=%s AND expires_at>clock_timestamp()', (trip,)).fetchone()
            link = dict(active=bool(row), expiresAt=iso(row[0]) if row else None)
        assigned = set(riders) | {item['driverId'] for item in cars.values()}
        unassigned = [person for peer, person in visible.items() if memberships[peer]['state'] == 'accepted' and peer not in assigned]
        state = trip_state(conn, trip)
        from team_trip_route_segments import TeamTripRouteSegments, route_contract_version
        route_segments = TeamTripRouteSegments(self)
        for car in result:
            car['routePlan'] = route_segments.project(conn, trip, car['id'], account)
            car['routeStatus'] = route_segments.status(conn, trip, car['id'], account)
            if route_contract_version(conn, trip) == 2 and not (car['isMine'] or car['iRide']):
                car.pop('routeRevision', None)
                car.pop('routeNext', None)
        start_conflict = None
        if state['state'] == 'planned' and account == owner:
            own, owners, busy = self.start_conflict(conn, trip, account, memberships)
            start_conflict = dict(activeTrips=[dict(tripId=other, title=self.load(conn, other)[1]['title'],
                isOwner=owners[other] == account) for other in own], busyMemberIds=[peer for peer in busy if peer in visible])
        return dict(id=trip, **value, **self.dates(conn, trip), routeContractVersion=route_contract_version(conn, trip), state=state['state'], revision=state['revision'], isOwner=account == owner, ownerId=owner, myPermissions=rights,
            startConflict=start_conflict,
            locationConsent=state['state'] in LIVE_STATES and memberships[account].get('locationConsent', False),
            members=members, link=link, cars=result, unassigned=unassigned, remoteOptions=options,
            rideInvites=plan.invites(conn, trip, account), remoteRequests=[], courses=self.courses(conn, trip, account, rights['edit']))

    def link(self, conn, token, account):
        trip, owner, expires = resolve_link(conn, token, trip=True)
        if not self.person(owner) or (account != owner and blocked(conn, account, owner)):
            failure(404, 'Link unavailable')
        _, value = self.load(conn, trip)
        if trip_state(conn, trip)['state'] not in LIVE_STATES:
            failure(409, 'TRIP_STATE_CONFLICT')
        return trip, owner, expires, value, self.members(conn, trip)

    def check_invitee(self, conn, account, target, owner):
        if (not isinstance(target, str) or not ACCOUNT.fullmatch(target) or target == account
                or not self.person(target) or not linked(conn, account, target)
                or (target != owner and blocked(conn, owner, target))):
            failure(404, 'Account unavailable')

    def router(self):
        router = APIRouter()
        if not self.enabled:
            return router

        def iphone(request):
            return request.url.path.startswith('/v1/iphone/')

        def iphone_actor(request, *, connection=None, mutate=False):
            if request.url.query:
                failure(400, 'IPHONE_INVALID_REQUEST')
            return self.auth.iphone_sessions.authenticate(request, 'trips:manage' if mutate else 'trips:read',
                connection=connection, lock=mutate and connection is not None)

        def actor(request, response, *, mutate=False, native=False):
            response.headers['Cache-Control'] = 'private, no-store'
            if native_resource(request) and not native:
                failure(403, '차량에서 사용할 수 없는 경로입니다.')
            account = (iphone_actor(request, mutate=mutate) if iphone(request) else
                request_actor(self.auth, request, mutate=mutate) if native
                else self.auth.browser(request, mutate=mutate))['id']
            if iphone(request):
                request.state.iphone_trip_account_id = account
            if mutate:
                self.auth.rate('trip-mutate:' + account, limit=60)
            return account

        def transaction(request, conn, *, mutate=False, native=False):
            TeamRooms.graph_lock(conn)
            if iphone(request):
                current = iphone_actor(request, connection=conn, mutate=mutate)
                if current['id'] != request.state.iphone_trip_account_id:
                    failure(401, 'AUTHENTICATION_CHANGED')
            elif native:
                transaction_actor(self.auth, request, conn, mutate=mutate)
            else:
                self.auth.browser(request, mutate=mutate, connection=conn)

        async def body(request, fields=(), *, optional=False, optional_fields=()):
            raw = bytearray()
            if iphone(request):
                from iphone_sessions import body as iphone_body
                raw.extend(await iphone_body(request, 'application/json', maximum_bytes=4096))
            else:
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 4096:
                        failure(413, 'Request too large')
            if optional and not raw and not iphone(request):
                return {}
            try:
                value = (business_json(request, raw, maximum=4096) if native_resource(request)
                    else decode_json(bytes(raw), maximum_bytes=4096))
            except CodecError:
                failure(400, 'Invalid JSON')
            if (not isinstance(value, dict) or not set(fields) <= set(value)
                    or set(value) - set(fields) - set(optional_fields)):
                failure(400, 'Invalid trip fields')
            return value

        @router.get('/v1/iphone/trips', include_in_schema=False)
        @router.get('/v1/social/trips')
        def trips(request: Request, response: Response):
            account = actor(request, response, native=True)
            trips, invitations = [], []
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, native=True)
                for trip, in conn.execute('SELECT t.trip_id FROM team_trips t JOIN team_trip_members m USING(trip_id) '
                        'WHERE m.account_id=%s AND t.deleted_at IS NULL '
                        'ORDER BY t.created_at DESC,t.trip_id', (account,)):
                    owner, value = self.load(conn, trip)
                    person = self.person(owner)
                    if not person or (account != owner and blocked(conn, account, owner)):
                        continue
                    members = self.members(conn, trip)
                    state = trip_state(conn, trip)['state']
                    if members[account]['state'] == 'pending':
                        if state in LIVE_STATES:
                            invitations.append(dict(tripId=trip, title=value['title'], ownerName=person['name']))
                    else:
                        visible = {peer for peer in members if peer == account or not blocked(conn, peer, account)}
                        route_preview = [dict(name=stop['name'], courseId=course['packId'], ref=stop['id'])
                            for course in self.courses(conn, trip, account, False) for stop in course['stops']][:4]
                        trips.append(dict(id=trip, title=value['title'], state=state, **self.dates(conn, trip), isOwner=account == owner, ownerName=person['name'],
                            memberCount=sum(members[peer]['state'] == 'accepted' for peer in visible),
                            carCount=sum(car['driverId'] in visible for car in self.cars(conn, trip).values()),
                            routePreview=route_preview))
            return dict(trips=trips, invitations=invitations)

        @router.post('/v1/iphone/trips', status_code=201, include_in_schema=False)
        @router.post('/v1/social/trips', status_code=201)
        async def create(request: Request, response: Response):
            account = actor(request, response, mutate=True)
            data = await body(request, ('title', 'description', 'memberIds'), optional_fields=('startDate', 'endDate', 'locationConsent'))
            enabled = location_choice(data)
            from team_trip_plan import trip_dates
            dates = trip_dates(data)
            value, targets = trip_fields(data), data['memberIds']
            if (not isinstance(targets, list) or len(targets) > 19
                    or any(not isinstance(target, str) for target in targets) or len(set(targets)) != len(targets)):
                failure(400, 'Invalid member IDs')
            trip = secrets.token_hex(16)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True)
                for target in targets:
                    self.check_invitee(conn, account, target, account)
                if conn.execute("SELECT count(*) FROM team_trips WHERE owner_id=%s AND state IN ('planned','active')", (account,)).fetchone()[0] >= 20:
                    failure(409, 'Trip limit reached')
                conn.execute('INSERT INTO team_trips(trip_id,owner_id,protected,start_date,end_date) VALUES(%s,%s,%s,%s,%s)',
                    (trip, account, self.protect('owner:' + account, trip, value), dates['startDate'], dates['endDate']))
                create_internal_room(conn, trip, account, value['title'])
                self.save_member(conn, trip, account, 'accepted', rights=dict(invite=True, edit=True), location_consent=enabled)
                for target in targets:
                    membership = self.save_member(conn, trip, target)
                    enqueue_invitation(conn, trip, account, target, membership)
                self.notify(conn, trip, bump=False)
            return dict(id=trip)

        @router.get('/v1/iphone/trips/{id}', include_in_schema=False)
        @router.get('/v1/social/trips/{id}')
        def detail(id: str, request: Request, response: Response):
            account = actor(request, response, native=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, native=True)
                if request.query_params:
                    if list(request.query_params.multi_items()) != [('section', 'route')]:
                        failure(400, 'Invalid trip section')
                    from team_trip_routes import route_projection
                    return route_projection(self, conn, id, account)
                return self.detail(conn, id, account, native=native_resource(request))

        @router.get('/v1/social/trips/{id}/chat')
        def chat(id: str, request: Request, response: Response):
            from team_trip_chat import history

            account = actor(request, response)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn)
                return history(self, conn, id, account)

        @router.post('/v1/social/trips/{id}/chat', status_code=201)
        async def send_chat(id: str, request: Request, response: Response):
            from team_trip_chat import send

            account = actor(request, response, mutate=True)
            data = await body(request, ('id', 'text'))
            message = data['id']
            if not isinstance(message, str) or not IDENT.fullmatch(message):
                failure(400, 'Invalid trip message ID')
            text = trip_text(data['text'], 'message', 1, 400, multiline=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True)
                return send(self, conn, id, account, message, text)

        @router.patch('/v1/iphone/trips/{id}', include_in_schema=False)
        @router.patch('/v1/social/trips/{id}')
        @router.patch('/v1/native/trips/{id}')
        async def edit(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            data = await body(request, optional_fields=('title', 'description', 'startDate', 'endDate'))
            if (not data or ('title' in data) != ('description' in data)
                    or 'title' not in data and set(data) != {'startDate', 'endDate'}):
                failure(400, 'Invalid trip fields')
            value = trip_fields(data) if 'title' in data else None
            from team_trip_plan import trip_dates
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                owner, _, _ = self.access(conn, id, account, permission='edit', mutable=True)
                dates = trip_dates(data, self.dates(conn, id))
                conn.execute('UPDATE team_trips SET start_date=%s,end_date=%s WHERE trip_id=%s',
                    (dates['startDate'], dates['endDate'], id))
                if value is not None:
                    conn.execute('UPDATE team_trips SET protected=%s WHERE trip_id=%s',
                        (self.protect('owner:' + owner, id, value), id))
                    room, room_owner = linked_room(conn, id)
                    raw = conn.execute('SELECT protected FROM team_rooms WHERE room_id=%s', (room,)).fetchone()[0]
                    payload = TeamRooms.restore('owner:' + room_owner, room, raw)
                    if trip_state(conn, id)['sourceKind'] != 'legacy_room':
                        payload.update(name=value['title'], code=None)
                        conn.execute('UPDATE team_rooms SET protected=%s WHERE room_id=%s',
                            (TeamRooms.protect('owner:' + room_owner, room, payload), room))
                self.notify(conn, id)
            return dict(status='updated')

        @router.delete('/v1/iphone/trips/{id}', include_in_schema=False)
        @router.delete('/v1/social/trips/{id}')
        async def delete(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True)
            await body(request, optional=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True)
                self.access(conn, id, account, permission='owner')
                state = trip_state(conn, id)
                if state['state'] not in CLOSED_STATES:
                    failure(409, 'Close the trip before deleting it')
                if state['deletedAt'] is None:
                    conn.execute('UPDATE team_trips SET deleted_at=clock_timestamp() WHERE trip_id=%s', (id,))
                    conn.execute('DELETE FROM team_trip_messages WHERE trip_id=%s', (id,))
                    self.notify(conn, id)
            return dict(status='deleted')

        @router.post('/v1/iphone/trips/{id}/members', status_code=201, include_in_schema=False)
        @router.post('/v1/social/trips/{id}/members', status_code=201)
        @router.post('/v1/native/trips/{id}/members', status_code=201)
        async def invite(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            target = (await body(request, ('accountId',)))['accountId']
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                owner, _, members = self.access(conn, id, account, permission='invite', mutable=True)
                self.check_invitee(conn, account, target, owner)
                if target in members:
                    response.status_code = 200
                    return dict(status=members[target]['state'])
                if len(members) >= 20:
                    failure(409, 'Trip is full')
                membership = self.save_member(conn, id, target)
                enqueue_invitation(conn, id, account, target, membership)
                self.notify(conn, id)
            return dict(status='pending')

        @router.post('/v1/iphone/trips/{id}/respond', include_in_schema=False)
        @router.post('/v1/social/trips/{id}/respond')
        async def respond(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=True)
            data = await body(request, ('accept',), optional_fields=('locationConsent',))
            accept = data['accept']
            enabled = location_choice(data)
            if type(accept) is not bool:
                failure(400, 'Choose a response')
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=True)
                owner, _ = self.load(conn, id)
                members = self.members(conn, id)
                if accept and members.get(account, {}).get('state') == 'accepted':
                    resolve_trip_context(self.auth, conn, id, account)
                    return dict(status='accepted')
                self.access(conn, id, account, pending=True, mutable=True)
                if accept:
                    self.save_member(conn, id, account, 'accepted', members[account]['via'], members[account]['permissions'], location_consent=enabled)
                else:
                    self.remove_member(conn, id, account)
                self.notify(conn, id, (account,))
            return dict(status='accepted' if accept else 'declined')

        @router.delete('/v1/iphone/trips/{id}/members/{accountId}', include_in_schema=False)
        @router.delete('/v1/social/trips/{id}/members/{accountId}')
        @router.delete('/v1/native/trips/{id}/members/{accountId}')
        async def remove_member(id: str, accountId: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            await body(request, optional=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                owner, _, members = self.access(conn, id, account, mutable=True)
                if accountId not in members or (accountId != account and blocked(conn, account, accountId)):
                    failure(404, 'Account unavailable')
                if account not in (owner, accountId):
                    failure(403, 'Only the owner may remove another member')
                if accountId == owner:
                    failure(409, 'Finish or cancel the trip instead')
                self.remove_member(conn, id, accountId)
                self.notify(conn, id, (accountId,))
            return dict(status='removed')

        @router.put('/v1/social/trips/{id}/members/{accountId}/permissions')
        async def set_permissions(id: str, accountId: str, request: Request, response: Response):
            account = actor(request, response, mutate=True)
            rights = await body(request, ('invite', 'edit'))
            if not permissions(rights):
                failure(400, 'Invalid permissions')
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True)
                owner, _, members = self.access(conn, id, account, permission='owner', mutable=True)
                if accountId == owner or members.get(accountId, {}).get('state') != 'accepted':
                    failure(404, 'Account unavailable')
                self.save_member(conn, id, accountId, 'accepted', members[accountId]['via'], rights)
                self.notify(conn, id)
            return dict(status='updated')

        @router.post('/v1/social/trips/{id}/link', status_code=201)
        @router.post('/v1/native/trips/{id}/link', status_code=201)
        async def create_link(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            await body(request, optional=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                self.access(conn, id, account, permission='invite', mutable=True)
                value = issue_link(conn, account, trip=id)
                self.notify(conn, id)
            return value

        @router.delete('/v1/social/trips/{id}/link')
        @router.delete('/v1/native/trips/{id}/link')
        async def revoke_link(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            await body(request, optional=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                self.access(conn, id, account, permission='invite', mutable=True)
                conn.execute('DELETE FROM team_trip_links WHERE trip_id=%s', (id,))
                self.notify(conn, id)
            return dict(status='revoked')

        @router.post('/v1/social/trip-links/preview')
        async def preview_link(request: Request, response: Response):
            account = actor(request, response, mutate=True)
            token = (await body(request, ('token',)))['token']
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True)
                trip, owner, expires, value, members = self.link(conn, token, account)
                return dict(tripId=trip, **value, ownerName=self.person(owner)['name'], expiresAt=iso(expires),
                    memberCount=sum(item['state'] == 'accepted' and (peer == account or not blocked(conn, peer, account))
                        for peer, item in members.items()), alreadyMember=members.get(account, {}).get('state') == 'accepted')

        @router.post('/v1/social/trip-links/join')
        async def join_link(request: Request, response: Response):
            account = actor(request, response, mutate=True)
            data = await body(request, ('token',), optional_fields=('locationConsent',))
            token, enabled = data['token'], location_choice(data)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True)
                trip, _, _, _, members = self.link(conn, token, account)
                if members.get(account, {}).get('state') != 'accepted':
                    if account not in members and len(members) >= 20:
                        failure(409, 'Trip is full')
                    self.save_member(conn, trip, account, 'accepted', 'link', location_consent=enabled)
                    self.notify(conn, trip)
                else:
                    resolve_trip_context(self.auth, conn, trip, account)
            return dict(tripId=trip)

        @router.post('/v1/iphone/trips/{id}/cars', status_code=201, include_in_schema=False)
        @router.post('/v1/social/trips/{id}/cars', status_code=201)
        @router.post('/v1/native/trips/{id}/cars', status_code=201)
        async def create_car(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            data = await body(request, ('name', 'seats'), optional_fields=('remotePolicy',))
            value = car_fields(data)
            if 'remotePolicy' in data and request.url.path.startswith('/v1/native/'):
                failure(403, 'Remote policy is managed in the iPhone app')
            car = secrets.token_hex(16)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                self.access(conn, id, account, mutable=True)
                if self.category(conn, account) != 'vehicle':
                    failure(409, 'Vehicle owner required')
                from team_trip_route_segments import TeamTripRouteSegments
                TeamTripRouteSegments(self).lock_active(conn, id, 'TRIP_ROUTE_ROSTER_LOCKED')
                if any(item['driverId'] == account for item in self.cars(conn, id).values()):
                    failure(409, 'Already driving')
                if 'remotePolicy' in data:
                    from team_trip_remote_policy import resolve_policy
                    policy = resolve_policy(self, conn, account, data['remotePolicy'])
                    binding = self.auth.device_command_service.friend_controls.device(conn, account, policy['deviceId'], True).grant_id if policy['enabled'] else None
                    value.update(remotePolicy=policy, remotePolicyRevision=1, remotePolicyGrantId=binding)
                self.leave_car(conn, id, account)
                ordinal = conn.execute('UPDATE team_trips SET next_car_ordinal=next_car_ordinal+1 '
                    'WHERE trip_id=%s RETURNING next_car_ordinal-1', (id,)).fetchone()[0]
                conn.execute('INSERT INTO team_trip_cars(trip_id,car_id,driver_id,protected,ordinal) VALUES(%s,%s,%s,%s,%s)',
                    (id, car, account, self.protect('car:' + car + ':driver:' + account, id, value), ordinal))
                self.notify(conn, id)
            return dict(id=car)

        @router.patch('/v1/iphone/trips/{id}/cars/{carId}', include_in_schema=False)
        @router.patch('/v1/social/trips/{id}/cars/{carId}')
        @router.patch('/v1/native/trips/{id}/cars/{carId}')
        async def edit_car(id: str, carId: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            value = car_fields(await body(request, ('name', 'seats')))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                self.access(conn, id, account, mutable=True)
                car = self.car(conn, id, carId, account)
                if car['driverId'] != account:
                    failure(403, 'Only the driver may manage the car')
                if value['seats'] < sum(riding == carId for riding in self.riders(conn, id).values()):
                    failure(409, 'Seats taken')
                from team_trip_plan import TeamTripPlan
                saved = TeamTripPlan(self).route_state(conn, id, carId)[1]
                value = dict(saved, **value)
                conn.execute('UPDATE team_trip_cars SET protected=%s WHERE trip_id=%s AND car_id=%s',
                    (self.protect('car:' + carId + ':driver:' + account, id, value), id, carId))
                self.notify(conn, id)
            return dict(status='updated')

        @router.delete('/v1/iphone/trips/{id}/cars/{carId}', include_in_schema=False)
        @router.delete('/v1/social/trips/{id}/cars/{carId}')
        @router.delete('/v1/native/trips/{id}/cars/{carId}')
        async def delete_car(id: str, carId: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            await body(request, optional=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                owner, _, _ = self.access(conn, id, account, mutable=True)
                car = self.car(conn, id, carId, account)
                if account not in (owner, car['driverId']):
                    failure(403, 'Only the driver or owner may delete the car')
                self.remove_car(conn, id, carId)
                self.notify(conn, id)
            return dict(status='deleted')

        @router.put('/v1/iphone/trips/{id}/cars/{carId}/ride', include_in_schema=False)
        @router.put('/v1/social/trips/{id}/cars/{carId}/ride')
        @router.put('/v1/native/trips/{id}/cars/{carId}/ride')
        async def ride(id: str, carId: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            await body(request, optional=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                if self.assign_ride(conn, id, carId, account):
                    self.notify(conn, id)
            return dict(status='riding')

        @router.delete('/v1/iphone/trips/{id}/ride', include_in_schema=False)
        @router.delete('/v1/social/trips/{id}/ride')
        @router.delete('/v1/native/trips/{id}/ride')
        async def leave_ride(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            await body(request, optional=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                self.access(conn, id, account, mutable=True)
                self.leave_car(conn, id, account)
                self.notify(conn, id)
            return dict(status='left')

        @router.post('/v1/iphone/trips/{id}/courses', status_code=201, include_in_schema=False)
        @router.post('/v1/social/trips/{id}/courses', status_code=201)
        @router.post('/v1/native/trips/{id}/courses', status_code=201)
        async def attach_course(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            pack = (await body(request, ('packId',)))['packId']
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                self.access(conn, id, account, mutable=True)
                from team_trip_route_segments import TeamTripRouteSegments
                TeamTripRouteSegments(self).lock_active(conn, id)
                if (not isinstance(pack, str) or not PACK.fullmatch(pack)
                        or not conn.execute('SELECT 1 FROM pack_versions p '
                            f'WHERE p.pack_id=%s AND {COURSE_AVAILABLE} LIMIT 1', (pack,)).fetchone()):
                    failure(404, 'Course unavailable')
                links = self.course_links(conn, id)
                if pack in links:
                    response.status_code = 200
                    return dict(status='added')
                if len(links) >= 10:
                    failure(409, 'Trip course limit')
                conn.execute('INSERT INTO team_trip_courses(trip_id,pack_id,added_by,protected) VALUES(%s,%s,%s,%s)',
                    (id, pack, account, self.protect('course:' + pack, id, dict(packId=pack, addedBy=account))))
                from team_trip_plan import TeamTripPlan
                plan = TeamTripPlan(self)
                plan.check_waypoint_capacity(conn, id)
                plan.courses_changed(conn, id)
                self.notify(conn, id)
            return dict(status='added')

        @router.delete('/v1/iphone/trips/{id}/courses/{packId}', include_in_schema=False)
        @router.delete('/v1/social/trips/{id}/courses/{packId}')
        @router.delete('/v1/native/trips/{id}/courses/{packId}')
        async def remove_course(id: str, packId: str, request: Request, response: Response):
            account = actor(request, response, mutate=True, native=request.url.path.startswith('/v1/native/'))
            await body(request, (), optional=True)
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True, native=request.url.path.startswith('/v1/native/'))
                owner, _, members = self.access(conn, id, account, mutable=True)
                from team_trip_route_segments import TeamTripRouteSegments
                TeamTripRouteSegments(self).lock_active(conn, id)
                link = self.course_links(conn, id).get(packId)
                if not link:
                    failure(404, 'Course unavailable')
                if account != link['addedBy'] and not self.rights(account, owner, members)['edit']:
                    failure(403, 'Trip edit permission required')
                conn.execute('DELETE FROM team_trip_courses WHERE trip_id=%s AND pack_id=%s', (id, packId))
                from team_trip_plan import TeamTripPlan
                TeamTripPlan(self).courses_changed(conn, id)
                self.notify(conn, id)
            return dict(status='removed')

        @router.put('/v1/social/trips/{id}/courses/priority')
        @router.put('/v1/iphone/trips/{id}/courses/priority', include_in_schema=False)
        async def prioritize_courses(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True)
            fields = await body(request, ('packIds', 'revision'))
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True)
                if request.url.path.startswith('/v1/iphone/'):
                    self.access(conn, id, account, permission='owner', mutable=True)
                return self.set_course_priority(conn, id, account, fields['packIds'], fields['revision'])

        @router.post('/v1/social/trips/{id}/waypoints', status_code=201)
        async def add_waypoint(id: str, request: Request, response: Response):
            account = actor(request, response, mutate=True)
            fields = await body(request, ('packId', 'name', 'lat', 'lng'))
            pack = fields.pop('packId')
            from team_trip_plan import TeamTripPlan
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True)
                point, created = TeamTripPlan(self).edit_waypoints(conn, id, account, pack, place=fields)
                if not created:
                    response.status_code = 200
                return point

        @router.delete('/v1/social/trips/{id}/waypoints/{packId}/{waypointId}')
        async def delete_waypoint(id: str, packId: str, waypointId: str, request: Request, response: Response):
            account = actor(request, response, mutate=True)
            await body(request, optional=True)
            from team_trip_plan import TeamTripPlan
            with psycopg.connect(self.dsn) as conn:
                transaction(request, conn, mutate=True)
                TeamTripPlan(self).edit_waypoints(conn, id, account, packId, remove=waypointId)
                return dict(status='removed')

        from team_trip_remote_policy import install as install_remote_policy
        install_remote_policy(router, self, actor, transaction, body)
        return router
