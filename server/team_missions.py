"""Explicit cooperative checkpoints; no race, location inference, or invented score.

Membership and purpose are checked in the same transaction as each mutation.
Checkpoint confirmations are user reports, not evidence of physical arrival.
"""
from course_publication import COURSE_AVAILABLE, available
import json
import hashlib
from pathlib import Path
import re
import secrets
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from private_records import VisitCipher, PrivateRecordError
from team_friends import blocked
from team_rooms import PREFERENCES
from team_trip_context import resolve_trip_context
from team_auth import hashed
from studio import validate_pack
from native_functional_identity import request_actor,transaction_actor,business_json,resolve_current_device
from native_functional_policy import FunctionalError
from native_principal import is_native_principal

ID = re.compile(r"[a-f0-9]{32}")
STATES = ("enrolling", "active", "completed", "cancelled")


def fail(status=404, detail="Mission unavailable"):
    raise HTTPException(status, detail)


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        fail()
    return value


def integer(value, minimum=1, maximum=2147483647):
    if type(value) is not int or not minimum <= value <= maximum:
        fail(400, "Invalid mission number")
    return value


def safety_status():
    # No verified supplier contract is installed. A browser/device number must
    # never become a manufacturer score merely by passing format validation.
    return dict(state="unavailable", value=None, source=None, observedAt=None,
                verifiedMeasurementKinds=[], computedByWegoH=False)


def historical_access(conn, room, account):
    row = conn.execute('SELECT r.trip_id,r.owner_id,m.joined_at FROM team_rooms r '
        'JOIN team_room_members m USING(room_id) WHERE r.room_id=%s AND m.account_id=%s',
        (identifier(room), account)).fetchone()
    if not row or row[0] is None:
        fail()
    return dict(tripId=row[0], ownerId=row[1], expiresAt=None), row[2].isoformat()


def trip_room(auth, conn, trip, account, *, withdraw=False):
    if withdraw:
        row = conn.execute('SELECT room_id FROM team_rooms WHERE trip_id=%s', (identifier(trip),)).fetchone()
        if not row:
            fail()
        historical_access(conn, row[0], account)
        return row[0]
    return resolve_trip_context(auth, conn, trip, account)['roomId']


class TeamMissions:
    def __init__(self, auth, rooms, content):
        self.auth, self.rooms, self.dsn, self.enabled = auth, rooms, auth.dsn, auth.enabled
        self.content = Path(content)

    @staticmethod
    def protect(kind, owner, key, value):
        return VisitCipher().protect("team-mission-" + kind + ":" + owner, key, value)

    @staticmethod
    def restore(kind, owner, key, raw):
        return VisitCipher().restore("team-mission-" + kind + ":" + owner, key, raw)

    def member(self, conn, room, account):
        row = conn.execute("SELECT protected,joined_at FROM team_room_members WHERE room_id=%s "
                           "AND account_id=%s AND left_at IS NULL", (room, account)).fetchone()
        if not row or not self.rooms.person(account):
            return None
        self.rooms.member_payload(account, room, row[0])
        return row[1].isoformat()

    def course(self, conn, value, *, required=True):
        row = conn.execute("SELECT p.checksum,p.stop_count FROM pack_versions p LEFT JOIN pack_reviews r USING(checksum) "
                           f"WHERE p.pack_id=%s AND p.version=%s AND {COURSE_AVAILABLE} FOR SHARE OF p",
                           (value['courseId'], value['courseVersion'])).fetchone()
        if row and not available(conn, row[0], lock=True):
            row = None
        if not row:
            if required:
                fail(409, "Available room course required")
            return None
        return dict(id=value['courseId'], version=value['courseVersion'], checksum=row[0], checkpointCount=row[1])

    def creation_course(self, conn, access, actor):
        if not access.get('tripId') or access['courseId'] is not None:
            return self.course(conn, access, required=False)
        from team_trips import TeamTrips
        trips = getattr(self.auth, 'trip_service', None) or TeamTrips(self.auth)
        for course in trips.courses(conn, access['tripId'], actor, can_edit=False):
            return self.course(conn, dict(courseId=course['packId'], courseVersion=course['version']), required=False)
        return None

    def checkpoints(self, conn, course):
        # Resolve the exact available immutable course; ordinal placeholders do
        # not tell a participant which real place they are confirming.
        try:
            current = self.course(conn, dict(courseId=course['id'], courseVersion=course['version']))
        except HTTPException as error:
            if error.status_code == 409:
                return []
            raise
        if current != course:
            return []
        if not isinstance(course['checksum'],str) or not re.fullmatch('[a-f0-9]{64}',course['checksum']):
            fail(503, "Mission course unavailable")
        path = self.content / course['checksum']
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
                fail(503, "Mission course unavailable")
            with path.open('rb') as source:
                raw = source.read(262145)
            if len(raw) > 262144 or hashlib.sha256(raw).hexdigest() != course['checksum']:
                fail(503, "Approved mission course integrity changed")
            pack = validate_pack(json.loads(raw))
            if (pack['id'] != course['id'] or pack['version'] != course['version']
                    or len(pack['stops']) != course['checkpointCount']):
                fail(503, "Mission course identity changed")
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            fail(503, "Mission course unavailable")
        return [dict(ordinal=index + 1, label=stop['name']) for index, stop in enumerate(pack['stops'])]

    def row(self, conn, room, mission, actor, *, trip_context=False):
        identifier(mission)
        access = self.rooms.access(conn, room, actor, trip_context=trip_context)
        row = conn.execute("SELECT owner_id,protected,state,revision,created_at,completed_at "
                           "FROM team_missions WHERE mission_id=%s AND room_id=%s FOR UPDATE",
                           (mission, room)).fetchone()
        if not row:
            fail()
        value = self.record(row[0], mission, row[1], row[2])
        return access, row, value

    def record(self, owner, mission, raw, state):
        value = self.restore('record', owner, mission, raw)
        if (state not in STATES or not isinstance(value, dict)
                or set(value) != {'course', 'preference', 'roster'}
                or value['preference'] not in PREFERENCES
                or not isinstance(value['course'], dict)
                or set(value['course']) != {'id', 'version', 'checksum', 'checkpointCount'}
                or type(value['course']['checkpointCount']) is not int
                or not 1 <= value['course']['checkpointCount'] <= 3
                or not isinstance(value['roster'], dict) or len(value['roster']) > 20
                or any(not isinstance(a, str) or not isinstance(nonce, str) or not ID.fullmatch(nonce)
                       for a, nonce in value['roster'].items())):
            raise PrivateRecordError("Mission record integrity failed")
        return value

    def participants(self, conn, room, mission):
        result = {}
        for account, raw, revision in conn.execute("SELECT account_id,protected,revision FROM team_mission_members "
                                                 "WHERE mission_id=%s ORDER BY account_id", (mission,)):
            value = self.restore('member', account, mission, raw)
            if (not isinstance(value, dict) or set(value) != {'consent', 'nonce', 'roomJoinedAt', 'completed'}
                    or type(value['consent']) is not bool or not isinstance(value['nonce'], str) or not ID.fullmatch(value['nonce'])
                    or type(value['completed']) is not int or not 0 <= value['completed'] <= 3):
                raise PrivateRecordError("Mission participation integrity failed")
            eligible = value['consent'] and self.member(conn, room, account) == value['roomJoinedAt']
            result[account] = dict(value, eligible=eligible, revision=revision)
        return result

    def current_state(self, conn, row, value, people):
        state = row[2]
        if state == 'cancelled':
            return state
        try:
            current = self.course(conn, dict(courseId=value['course']['id'], courseVersion=value['course']['version']))
        except HTTPException as error:
            if error.status_code != 409:
                raise
            return 'course-unavailable'
        if current != value['course']:
            return 'course-unavailable'
        if state not in ('active', 'completed'):
            return state
        roster = value['roster']
        valid = len(roster) >= 2 and all(account in people and people[account]['eligible']
                and people[account]['nonce'] == nonce for account, nonce in roster.items())
        accounts = sorted(roster)
        if valid:
            valid = not any(blocked(conn, a, b) for i, a in enumerate(accounts) for b in accounts[i + 1:])
        return state if valid else ('result-withdrawn' if state == 'completed' else 'interrupted')

    def save_record(self, conn, mission, owner, value, state):
        conn.execute("UPDATE team_missions SET protected=%s,state=%s,revision=revision+1,updated_at=now(), "
                     "completed_at=CASE WHEN %s='completed' THEN COALESCE(completed_at,now()) ELSE completed_at END "
                     "WHERE mission_id=%s", (self.protect('record', owner, mission, value), state, state, mission))

    def snapshot(self, conn, room, mission, actor, *, trip_context=False):
        access, row, value = self.row(conn, room, mission, actor, trip_context=trip_context)
        people = self.participants(conn, room, mission)
        state = self.current_state(conn, row, value, people)
        visible = []
        if state not in ('result-withdrawn', 'course-unavailable'):
            for account, person in people.items():
                who = self.rooms.person(account)
                if person['eligible'] and who and (account == actor or not blocked(conn, actor, account)):
                    visible.append(dict(accountId=account, name=who['name'],
                                        completedCheckpoints=person['completed'], revision=person['revision']))
        own = people.get(actor)
        result = dict(id=mission, roomId=room, ownerId=row[0], revision=row[3], state=state,
                    title='함께 경로 완주하기', course=value['course'],
                    routePreference=dict(value=value['preference'], appliedToNavigation=False),
                    checkpoints=self.checkpoints(conn, value['course']),
                    participants=visible,
                    participation=dict(consent=bool(own and own['eligible']),
                                       revision=own['revision'] if own else 0,
                                       nextCheckpoint=(own['completed'] + 1 if own and own['eligible']
                                           and own['completed'] < value['course']['checkpointCount'] else None)),
                    confirmationSource='user-confirmed', physicalArrivalVerified=False,
                    safety=safety_status(), createdAt=row[4], completedAt=row[5] if state == 'completed' else None,
                    expiresAt=access['expiresAt'], serverNow=datetime.now(timezone.utc),
                    nativeReportingPurpose='mission-progress')
        if trip_context:
            result.pop('roomId')
            result.pop('expiresAt')
            result.update(tripId=access['tripId'], contractVersion=1)
        return result

    def own_participant(self, conn, room, mission, actor):
        value = self.participants(conn, room, mission).get(actor)
        if not value or not value['eligible']:
            fail(403, "Explicit mission participation required")
        return value

    def create(self, conn, room, actor, preference, *, trip_context=False):
        self.rooms.graph_lock(conn)
        access = self.rooms.access(conn, room, actor, trip_context=trip_context)
        if access['ownerId'] != actor:
            fail(403, "Only the room owner may create a mission")
        if preference not in PREFERENCES:
            fail(400, "Invalid route preference")
        if preference != access['preference']:
            fail(409, "Save the room route preference first")
        if conn.execute("SELECT count(*) FROM team_missions WHERE room_id=%s", (room,)).fetchone()[0] >= 50:
            fail(409, "Room mission limit reached")
        course = self.creation_course(conn, access, actor)
        if course is None:
            fail(409, "Available room course required")
        mission = secrets.token_hex(16)
        value = dict(course=course, preference=preference, roster={})
        conn.execute("INSERT INTO team_missions(mission_id,room_id,owner_id,protected) VALUES(%s,%s,%s,%s)",
                     (mission, room, actor, self.protect('record', actor, mission, value)))
        self.rooms.notify(conn, room)
        return self.snapshot(conn, room, mission, actor, trip_context=trip_context)

    def participate(self, conn, room, mission, actor, consent, expected=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        if trip_context and consent is False:
            historical_access(conn, room, actor)
            return self.withdraw_participation(conn, room, mission, actor)
        access, row, value = self.row(conn, room, mission, actor, trip_context=trip_context)
        current = self.participants(conn, room, mission).get(actor)
        if consent and integer(expected, 0) != (current['revision'] if current else 0):
            fail(409, "Mission participation changed")
        if consent and self.current_state(conn, row, value, self.participants(conn, room, mission)) != 'enrolling':
            fail(409, "Mission participation is closed")
        if consent and current and current['eligible']:
            return self.snapshot(conn, room, mission, actor, trip_context=trip_context)
        payload = dict(consent=consent, nonce=secrets.token_hex(16),
                       roomJoinedAt=self.member(conn, room, actor), completed=0)
        conn.execute("INSERT INTO team_mission_members(mission_id,account_id,protected) VALUES(%s,%s,%s) "
                     "ON CONFLICT(mission_id,account_id) DO UPDATE SET protected=excluded.protected, "
                     "revision=team_mission_members.revision+1,updated_at=now()",
                     (mission, actor, self.protect('member', actor, mission, payload)))
        # Rejoining never revives an earlier device-report purpose.
        conn.execute("DELETE FROM team_mission_device_grants WHERE mission_id=%s AND account_id=%s", (mission, actor))
        self.save_record(conn, mission, row[0], value, row[2])
        self.rooms.notify(conn, room)
        return self.snapshot(conn, room, mission, actor, trip_context=trip_context)

    def start(self, conn, room, mission, actor, revision, *, trip_context=False):
        self.rooms.graph_lock(conn)
        access, row, value = self.row(conn, room, mission, actor, trip_context=trip_context)
        if access.get('tripId') and access['state'] != 'active':
            fail(409, 'TRIP_STATE_CONFLICT')
        if actor != row[0]:
            fail(403, "Only the mission owner may start")
        if self.current_state(conn, row, value, self.participants(conn, room, mission)) != 'enrolling' or row[3] != revision:
            fail(409, "Mission changed")
        people = self.participants(conn, room, mission)
        roster = {account: person['nonce'] for account, person in people.items() if person['eligible']}
        if not 2 <= len(roster) <= 20 or actor not in roster:
            fail(409, "At least two consenting participants required")
        if any(blocked(conn, a, b) for a in roster for b in roster if a < b):
            fail(409, "Mission participants unavailable")
        value['roster'] = roster
        self.save_record(conn, mission, actor, value, 'active')
        self.rooms.notify(conn, room)
        return self.snapshot(conn, room, mission, actor, trip_context=trip_context)

    def progress(self, conn, room, mission, actor, data, device=None, *, trip_context=False):
        self.rooms.graph_lock(conn)
        access, row, value = self.row(conn, room, mission, actor, trip_context=trip_context)
        if access.get('tripId') and access['state'] != 'active':
            fail(409, 'TRIP_STATE_CONFLICT')
        people = self.participants(conn, room, mission)
        person = self.own_participant(conn, room, mission, actor)
        event = identifier(data['eventId'])
        checkpoint = integer(data['checkpoint'], 1, value['course']['checkpointCount'])
        integer(data['participationRevision'])
        if device:
            self.authorize_device(conn, room, mission, actor, device, person)
        previous = conn.execute("SELECT protected FROM team_mission_events WHERE mission_id=%s AND account_id=%s "
                                "AND event_id=%s", (mission, actor, event)).fetchone()
        payload = dict(checkpoint=checkpoint, nonce=person['nonce'], source='user-confirmed')
        if previous:
            if self.restore('event', actor, mission + ':' + event, previous[0]) != payload:
                fail(409, "Mission event already used")
            return self.snapshot(conn, room, mission, actor, trip_context=trip_context)
        if self.current_state(conn, row, value, people) != 'active' or value['roster'].get(actor) != person['nonce']:
            fail(409, "Mission is not active")
        if data['participationRevision'] != person['revision'] or checkpoint != person['completed'] + 1:
            fail(409, "Refresh mission progress")
        member = {key: person[key] for key in ('consent', 'nonce', 'roomJoinedAt', 'completed')}
        member['completed'] = checkpoint
        conn.execute("INSERT INTO team_mission_events(mission_id,account_id,event_id,protected) VALUES(%s,%s,%s,%s)",
                     (mission, actor, event, self.protect('event', actor, mission + ':' + event, payload)))
        conn.execute("UPDATE team_mission_members SET protected=%s,revision=revision+1,updated_at=now() "
                     "WHERE mission_id=%s AND account_id=%s", (self.protect('member', actor, mission, member), mission, actor))
        people[actor]['completed'] = checkpoint
        complete = all(people[account]['completed'] == value['course']['checkpointCount'] for account in value['roster'])
        self.save_record(conn, mission, row[0], value, 'completed' if complete else 'active')
        self.rooms.notify(conn, room)
        return self.snapshot(conn, room, mission, actor, trip_context=trip_context)

    def authorize_device(self, conn, room, mission, actor, device, participant):
        credential=device;device=credential['id']
        try:reference=resolve_current_device(self.auth,conn,actor,device,required=frozenset({'rooms:read','missions:read'}))
        except FunctionalError as error:fail(error.status,error.code)
        if reference.grant_id!=credential['grantId']:fail(401,'Device grant changed')
        row=conn.execute('SELECT protected,expires_at FROM team_mission_device_grants WHERE mission_id=%s AND account_id=%s AND device_id=%s FOR SHARE',(mission,actor,device)).fetchone()
        if not row or row[1]<=datetime.now(timezone.utc):fail(403,'Explicit device mission reporting required')
        grant=self.restore('device-grant',actor,mission+':'+device,row[0])
        if (not grant['consent']or grant['nonce']!=participant['nonce']or grant['roomJoinedAt']!=participant['roomJoinedAt']
            or grant.get('nativeGrantId')!=reference.grant_id or grant['permissionRevision']!=reference.functional_revision):
            fail(403,'Explicit device mission reporting required')

    def grant(self, conn, room, mission, actor, device, data, *, trip_context=False):
        self.rooms.graph_lock(conn)
        if trip_context and data['consent'] is False:
            historical_access(conn, room, actor)
            identifier(device)
            if not conn.execute('SELECT 1 FROM team_missions WHERE mission_id=%s AND room_id=%s', (identifier(mission), room)).fetchone():
                fail()
            row = conn.execute('SELECT g.revision FROM team_mission_device_grants g JOIN team_missions m USING(mission_id) '
                'WHERE g.mission_id=%s AND m.room_id=%s AND g.account_id=%s AND g.device_id=%s FOR UPDATE OF g',
                (identifier(mission), room, actor, device)).fetchone()
            conn.execute('DELETE FROM team_mission_device_grants WHERE mission_id IN '
                '(SELECT mission_id FROM team_missions WHERE mission_id=%s AND room_id=%s) AND account_id=%s AND device_id=%s',
                (mission, room, actor, device))
            self.rooms.notify(conn, room)
            return dict(deviceId=device, purpose='mission-progress', consent=False,
                        revision=row[0] if row else 0, expiresAt=None)
        access, row, value = self.row(conn, room, mission, actor, trip_context=trip_context)
        if type(data['consent']) is not bool:
            fail(400, "Explicit device mission purpose required")
        integer(data['participationRevision'], 0)
        participant = self.participants(conn, room, mission).get(actor)
        if data['consent']:
            participant = self.own_participant(conn, room, mission, actor)
            if data['participationRevision'] != participant['revision']:
                fail(409, "Mission participation changed")
        identifier(device)
        try:reference=resolve_current_device(self.auth,conn,actor,device,required=frozenset({'rooms:read','missions:read','missions:progress'})if data['consent']else frozenset())
        except FunctionalError as error:fail(error.status,error.code)
        permissions=dict(rooms='rooms:read'in reference.approved_purposes);permission_revision=reference.functional_revision;device_expiry=reference.expires_at
        current = conn.execute("SELECT revision FROM team_mission_device_grants WHERE mission_id=%s AND account_id=%s "
                               "AND device_id=%s FOR UPDATE", (mission, actor, device)).fetchone()
        revision = current[0] if current else 0
        if integer(data['revision'], 0) != revision and data['consent'] is not False:
            fail(409, "Device mission purpose changed")
        if type(data['consent']) is not bool:
            fail(400, "Explicit device mission purpose required")
        hours = integer(data['expiresInHours'], 1, 24)
        if not participant:
            # Never-enrolled has no membership FK or saved grant. A requested
            # false remains false without creating a new purpose/participant.
            return dict(deviceId=device, purpose='mission-progress', consent=False, revision=0, expiresAt=None)
        if data['consent'] and (not permissions['rooms'] or self.current_state(conn, row, value,
                                  self.participants(conn, room, mission)) not in ('enrolling', 'active')):
            fail(409, "Device rooms read purpose and active mission required")
        expiry = min(limit for limit in (access['expiresAt'], device_expiry, datetime.now(timezone.utc) + timedelta(hours=hours)) if limit is not None)
        payload = dict(consent=data['consent'], nonce=participant['nonce'], roomJoinedAt=participant['roomJoinedAt'],
                       permissionRevision=permission_revision,nativeGrantId=reference.grant_id)
        conn.execute("INSERT INTO team_mission_device_grants(mission_id,account_id,device_id,protected,expires_at) "
                     "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(mission_id,account_id,device_id) DO UPDATE SET "
                     "protected=excluded.protected,expires_at=excluded.expires_at,revision=team_mission_device_grants.revision+1",
                     (mission, actor, device, self.protect('device-grant', actor, mission + ':' + device, payload), expiry))
        self.rooms.notify(conn, room)
        return dict(deviceId=device, purpose='mission-progress', consent=data['consent'], revision=revision + 1, expiresAt=expiry)

    def trip_router(self):
        return self.router(trip_context=True)

    def withdraw_participation(self, conn, room, mission, account):
        row = conn.execute('SELECT owner_id FROM team_missions WHERE mission_id=%s AND room_id=%s FOR UPDATE',
            (identifier(mission), room)).fetchone()
        if not row:
            fail()
        person = self.participants(conn, room, mission).get(account)
        revision = person['revision'] if person else 0
        if person and person['consent']:
            value = {key: person[key] for key in ('consent', 'nonce', 'roomJoinedAt', 'completed')}
            value.update(consent=False, nonce=secrets.token_hex(16))
            conn.execute('UPDATE team_mission_members SET protected=%s,revision=revision+1,updated_at=now() '
                'WHERE mission_id=%s AND account_id=%s',
                (self.protect('member', account, mission, value), mission, account))
            conn.execute('UPDATE team_missions SET revision=revision+1,updated_at=now() WHERE mission_id=%s', (mission,))
            revision += 1
        conn.execute('DELETE FROM team_mission_device_grants WHERE mission_id=%s AND account_id=%s', (mission, account))
        self.rooms.notify(conn, room)
        return dict(id=mission, consent=False, revision=revision)

    def withdraw_trip_context(self, conn, trip, room, account=None):
        if not conn.execute('SELECT 1 FROM team_rooms WHERE room_id=%s AND trip_id=%s', (room, trip)).fetchone():
            fail()
        rows = conn.execute('SELECT mission_id,owner_id,protected,state FROM team_missions '
            'WHERE room_id=%s ORDER BY mission_id FOR UPDATE', (room,)).fetchall()
        for mission, owner, raw, state in rows:
            if account is not None:
                self.withdraw_participation(conn, room, mission, account)
                continue
            if state == 'enrolling':
                conn.execute("UPDATE team_missions SET state='cancelled',revision=revision+1,updated_at=now() "
                    'WHERE mission_id=%s', (mission,))
            elif state == 'active':
                value = self.record(owner, mission, raw, state)
                people = self.participants(conn, room, mission)
                changed = False
                for member, nonce in value['roster'].items():
                    if member in people and nonce == people[member]['nonce']:
                        value['roster'][member] = secrets.token_hex(16)
                        changed = True
                if changed:
                    self.save_record(conn, mission, owner, value, state)
        if account is None:
            conn.execute('DELETE FROM team_mission_device_grants WHERE mission_id IN '
                '(SELECT mission_id FROM team_missions WHERE room_id=%s)', (room,))

    def on_trip_block(self, conn, trip, room, blocker, target):
        if not conn.execute('SELECT 1 FROM team_rooms WHERE room_id=%s AND trip_id=%s', (room, trip)).fetchone():
            fail()
        rows = conn.execute("SELECT mission_id,owner_id,protected,state FROM team_missions "
            "WHERE room_id=%s AND state IN ('active','completed') ORDER BY mission_id FOR UPDATE", (room,)).fetchall()
        for mission, owner, raw, state in rows:
            value = self.record(owner, mission, raw, state)
            if blocker not in value['roster'] or target not in value['roster']:
                continue
            people = self.participants(conn, room, mission)
            changed = False
            for account in (blocker, target):
                if account in people and value['roster'][account] == people[account]['nonce']:
                    value['roster'][account] = secrets.token_hex(16)
                    changed = True
            if changed:
                self.save_record(conn, mission, owner, value, state)
            conn.execute('DELETE FROM team_mission_device_grants WHERE mission_id=%s AND account_id=ANY(%s)',
                (mission, [blocker, target]))

    def trip_result_reader(self, conn, trip, room, account):
        self.rooms.graph_lock(conn)
        access, _ = historical_access(conn, room, account)
        if access['tripId'] != trip:
            fail()
        rows = conn.execute('SELECT mission_id,owner_id,protected,state,revision,created_at,completed_at '
            'FROM team_missions WHERE room_id=%s ORDER BY created_at DESC,mission_id LIMIT 50', (room,)).fetchall()
        result = []
        for mission, owner, raw, state, revision, created, completed in rows:
            value = self.record(owner, mission, raw, state)
            row = (owner, raw, state, revision, created, completed)
            people = self.participants(conn, room, mission)
            state = self.current_state(conn, row, value, people)
            visible = []
            if state == 'completed':
                for member in value['roster']:
                    person = people[member]
                    who = self.rooms.person(member)
                    if who and (member == account or not blocked(conn, account, member)):
                        visible.append(dict(accountId=member, name=who['name'], completedCheckpoints=person['completed']))
            result.append(dict(id=mission, state=state, course=value['course'], participants=visible,
                completedAt=completed if state == 'completed' else None,
                confirmationSource='user-confirmed', physicalArrivalVerified=False, safety=safety_status()))
        return dict(missions=result)

    def router(self, *, trip_context=False):
        router = APIRouter()
        if not self.enabled:
            return router

        web_root = '/v1/social/'+('trips' if trip_context else 'rooms')+'/{room}/missions'
        native_root = '/v1/native/'+('trips' if trip_context else 'rooms')+'/{room}/missions'

        def scope(conn, room, who, *, withdraw=False):
            self.rooms.graph_lock(conn)
            return trip_room(self.auth, conn, room, who, withdraw=withdraw) if trip_context else room

        async def body(request, fields):
            raw = bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 4096:
                    fail(413, "Mission request too large")
            try:
                value = business_json(request,raw,maximum=4096)
            except (ValueError, UnicodeError):
                fail(400, "Invalid mission JSON")
            if not isinstance(value, dict) or set(value) != set(fields):
                fail(400, "Invalid mission fields")
            return value

        def actor(request, mutate=False, native=False):
            actual=is_native_principal(getattr(request.state,'device_identity',None))
            if actual!=native:fail()
            return request_actor(self.auth,request,mutate=mutate)

        def credential(request, who):
            return dict(id=who['deviceId'],grantId=who['grantId'])

        def list_current(room, who, device=None, request=None):
            with psycopg.connect(self.dsn) as conn:
                self.rooms.graph_lock(conn)
                if request is None or transaction_actor(self.auth,request,conn)['id']!=who:fail(401,'Mission account changed')
                room = scope(conn, room, who)
                access = self.rooms.access(conn, room, who, trip_context=trip_context)
                ids = [item[0] for item in conn.execute("SELECT mission_id FROM team_missions WHERE room_id=%s "
                                                      "ORDER BY created_at DESC,mission_id LIMIT 50", (room,))]
                result = []
                for mission in ids:
                    if device:
                        person = self.participants(conn, room, mission).get(who)
                        if not person or not person['eligible']:
                            continue
                        try:
                            self.authorize_device(conn, room, mission, who, device, person)
                        except HTTPException as error:
                            if error.status_code not in (403, 404):
                                raise
                            continue
                    result.append(self.snapshot(conn, room, mission, who, trip_context=trip_context))
                value = dict(missions=result, preference=access['preference'], serverNow=datetime.now(timezone.utc))
                if trip_context and not device:
                    value['courseAvailable'] = (access['ownerId'] == who
                        and self.creation_course(conn, access, who) is not None)
                return value

        @router.get(web_root)
        def missions(room: str, request: Request):
            return list_current(room, actor(request)['id'],request=request)

        @router.get(native_root)
        def native_missions(room: str, request: Request):
            who = actor(request, native=True)
            return list_current(room, who['id'], credential(request, who),request=request)

        @router.post(web_root, status_code=201)
        async def create(room: str, request: Request):
            data = await body(request, ('preference',))
            who = actor(request, True)['id']
            self.auth.rate('mission-create:' + who, limit=20)
            with psycopg.connect(self.dsn) as conn:
                current=transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                if current['id']!=(who if isinstance(who,str)else who['id']):fail(401,'Mission account changed')
                room = scope(conn, room, who if isinstance(who, str) else who['id'])
                return self.create(conn, room, who, data['preference'], trip_context=trip_context)

        @router.put(web_root+'/{mission}/participation')
        async def participate(room: str, mission: str, request: Request):
            data = await body(request, ('consent', 'participationRevision'))
            who = actor(request, True)['id']
            if data['consent'] is not True:
                fail(400, "Explicit participation consent required")
            self.auth.rate('mission-participation:' + who, limit=30)
            with psycopg.connect(self.dsn) as conn:
                current=transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                if current['id']!=(who if isinstance(who,str)else who['id']):fail(401,'Mission account changed')
                room = scope(conn, room, who if isinstance(who, str) else who['id'])
                return self.participate(conn, room, mission, who, True, data['participationRevision'], trip_context=trip_context)

        @router.delete(web_root+'/{mission}/participation')
        def withdraw(room: str, mission: str, request: Request):
            who = actor(request, True)['id']
            with psycopg.connect(self.dsn) as conn:
                current=transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                if current['id']!=(who if isinstance(who,str)else who['id']):fail(401,'Mission account changed')
                room = scope(conn, room, who if isinstance(who, str) else who['id'], withdraw=True)
                return self.participate(conn, room, mission, who, False, trip_context=trip_context)

        @router.post(web_root+'/{mission}/start')
        async def start(room: str, mission: str, request: Request):
            data = await body(request, ('revision',))
            who = actor(request, True)['id']
            integer(data['revision'])
            with psycopg.connect(self.dsn) as conn:
                current=transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                if current['id']!=(who if isinstance(who,str)else who['id']):fail(401,'Mission account changed')
                room = scope(conn, room, who if isinstance(who, str) else who['id'])
                return self.start(conn, room, mission, who, data['revision'], trip_context=trip_context)

        @router.get(web_root+'/{mission}/devices')
        def devices(room: str, mission: str, request: Request):
            who = actor(request)['id']
            with psycopg.connect(self.dsn) as conn:
                current=transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                if current['id']!=(who if isinstance(who,str)else who['id']):fail(401,'Mission account changed')
                room = scope(conn, room, who if isinstance(who, str) else who['id'])
                self.rooms.graph_lock(conn)
                access, row, value = self.row(conn, room, mission, who, trip_context=trip_context)
                person = self.participants(conn, room, mission).get(who)
                result = []
                candidates=conn.execute("SELECT g.device_id FROM native_v2_grants g JOIN native_v2_installations i USING(installation_key_id) JOIN native_device_refs r ON r.device_id=g.device_id AND r.kind='native' WHERE g.account_id=%s AND g.state='TOKEN_ISSUED' AND g.expires_at>extract(epoch FROM now()) AND i.active_grant_id=g.grant_id AND i.revoked_at IS NULL ORDER BY g.device_id LIMIT 100",(who,)).fetchall()
                for(device,)in candidates:
                    try:reference=resolve_current_device(self.auth,conn,who,device)
                    except FunctionalError as error:fail(error.status,error.code)
                    permissions=dict(rooms='rooms:read'in reference.approved_purposes);permission_revision=reference.functional_revision
                    progress_enabled = 'missions:progress' in reference.approved_purposes
                    grant = conn.execute("SELECT protected,revision,expires_at FROM team_mission_device_grants "
                                         "WHERE mission_id=%s AND account_id=%s AND device_id=%s", (mission, who, device)).fetchone()
                    saved = self.restore('device-grant', who, mission + ':' + device, grant[0]) if grant else None
                    active = bool(saved and saved['consent'] and person and person['eligible']
                                  and saved['nonce'] == person['nonce']
                                  and saved['roomJoinedAt'] == person['roomJoinedAt']
                                  and saved.get('nativeGrantId')==reference.grant_id and saved['permissionRevision'] == permission_revision and permissions['rooms']
                                  and progress_enabled and grant[2] > datetime.now(timezone.utc))
                    result.append(dict(deviceId=device, name=reference.name, roomsRead=permissions['rooms'],
                                       progressEnabled=progress_enabled,
                                       consent=bool(saved and saved['consent']), active=active,
                                       revision=grant[1] if grant else 0, expiresAt=grant[2] if grant else None))
            return dict(purpose='mission-progress', devices=result, serverNow=datetime.now(timezone.utc))

        @router.post(web_root+'/{mission}/progress')
        @router.post(native_root+'/{mission}/progress')
        async def progress(room: str, mission: str, request: Request):
            native = request.url.path.startswith('/v1/native/')
            data = await body(request, ('eventId', 'checkpoint', 'participationRevision'))
            who = actor(request, not native, native)
            current_device = credential(request, who) if native else None
            self.auth.rate('mission-progress:' + who['id'], limit=60)
            with psycopg.connect(self.dsn) as conn:
                current=transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                if current['id']!=(who if isinstance(who,str)else who['id']):fail(401,'Mission account changed')
                room = scope(conn, room, who if isinstance(who, str) else who['id'])
                return self.progress(conn, room, mission, who['id'], data, current_device, trip_context=trip_context)

        @router.put(web_root+'/{mission}/devices/{device}')
        async def grant(room: str, mission: str, device: str, request: Request):
            data = await body(request, ('revision', 'consent', 'expiresInHours', 'participationRevision'))
            who = actor(request, True)['id']
            with psycopg.connect(self.dsn) as conn:
                current=transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                if current['id']!=(who if isinstance(who,str)else who['id']):fail(401,'Mission account changed')
                room = scope(conn, room, who if isinstance(who, str) else who['id'], withdraw=data['consent'] is False)
                return self.grant(conn, room, mission, who, device, data, trip_context=trip_context)

        @router.delete(web_root+'/{mission}')
        def cancel(room: str, mission: str, request: Request):
            who = actor(request, True)['id']
            with psycopg.connect(self.dsn) as conn:
                current=transaction_actor(self.auth,request,conn,mutate=request.method!='GET')
                if current['id']!=(who if isinstance(who,str)else who['id']):fail(401,'Mission account changed')
                room = scope(conn, room, who if isinstance(who, str) else who['id'])
                self.rooms.graph_lock(conn)
                access, row, value = self.row(conn, room, mission, who, trip_context=trip_context)
                if who != row[0]:
                    fail(403, "Only the mission owner may cancel")
                if row[2] == 'completed':
                    fail(409, "Completed mission cannot be cancelled")
                self.save_record(conn, mission, who, value, 'cancelled')
                self.rooms.notify(conn, room)
                return self.snapshot(conn, room, mission, who, trip_context=trip_context)

        return router
