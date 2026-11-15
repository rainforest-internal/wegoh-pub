import argparse
import os
import secrets
from types import SimpleNamespace

import psycopg
from fastapi import HTTPException
from private_records import PrivateRecordError
from team_friends import blocked
from team_rooms import TeamRooms, CODE, PREFERENCES
from team_trips import TeamTrips, trip_fields
from team_trip_context import (trip_state, linked_room, check_members,
    create_internal_room, activate_member)


class TripRoomMigration:
    def __init__(self, auth):
        self.auth = auth
        self.trips = TeamTrips(auth)
        self.rooms = TeamRooms(auth)

    @staticmethod
    def account(conn, account):
        if not conn.execute("SELECT 1 FROM team_accounts WHERE account_id=%s AND account_status='active'", (account,)).fetchone():
            raise PrivateRecordError('Migration account unavailable')

    def room_payload(self, owner, room, raw):
        payload = self.rooms.restore('owner:' + owner, room, raw)
        if (not isinstance(payload, dict) or set(payload) != {'name', 'code', 'courseId', 'courseVersion', 'preference'}
                or not isinstance(payload['name'], str) or not 1 <= len(payload['name'].strip()) <= 80
                or any(ord(c) < 32 for c in payload['name'])
                or payload['preference'] not in PREFERENCES
                or (payload['code'] is not None and (not isinstance(payload['code'], str) or not CODE.fullmatch(payload['code'])))
                or (payload['courseId'] is None and payload['courseVersion'] is not None)
                or (payload['courseId'] is not None and (not isinstance(payload['courseId'], str) or type(payload['courseVersion']) is not int))):
            raise PrivateRecordError('Migration room integrity failed')
        return payload

    def validate_trip(self, conn, trip):
        state = trip_state(conn, trip)
        owner, _ = self.trips.load(conn, trip)
        self.account(conn, owner)
        room, room_owner = linked_room(conn, trip)
        if owner != room_owner:
            raise PrivateRecordError('Migration owner mismatch')
        members = self.trips.members(conn, trip)
        if members.get(owner, {}).get('state') != 'accepted':
            raise PrivateRecordError('Migration owner membership missing')
        if len(members) > 20:
            raise PrivateRecordError('Migration member limit exceeded')
        check_members(conn, trip, room, members)
        for account, value in members.items():
            self.account(conn, account)
            if account != owner and blocked(conn, owner, account):
                raise PrivateRecordError('Migration owner membership blocked')
        row = conn.execute('SELECT code_hash,expires_at,closed_at,archived_at,protected FROM team_rooms WHERE room_id=%s', (room,)).fetchone()
        self.room_payload(room_owner, room, row[4])
        if row[0] is not None or row[1] is not None:
            raise PrivateRecordError('Migration room context invalid')
        closed = state['state'] in ('completed', 'cancelled')
        if closed != (row[2] is not None and row[3] is not None):
            raise PrivateRecordError('Migration lifecycle mismatch')
        djs = 0
        for account, raw, left in conn.execute('SELECT account_id,protected,left_at FROM team_room_members WHERE room_id=%s', (room,)):
            member = self.rooms.member_payload(account, room, raw)
            djs += left is None and member['role'] == 'dj'
        if djs > 1:
            raise PrivateRecordError('Migration DJ membership invalid')
        return room

    def migrate_trip(self, conn, trip):
        trip_state(conn, trip)
        if conn.execute('SELECT 1 FROM team_rooms WHERE trip_id=%s', (trip,)).fetchone():
            self.validate_trip(conn, trip)
            return False
        owner, payload = self.trips.load(conn, trip)
        self.account(conn, owner)
        members = self.trips.members(conn, trip)
        if members.get(owner, {}).get('state') != 'accepted':
            raise PrivateRecordError('Migration owner membership missing')
        if len(members) > 20:
            raise PrivateRecordError('Migration member limit exceeded')
        room = create_internal_room(conn, trip, owner, payload['title'])
        for account, value in members.items():
            self.account(conn, account)
            if account != owner and blocked(conn, owner, account):
                raise PrivateRecordError('Migration owner membership blocked')
            if value['state'] == 'accepted':
                activate_member(conn, room, account)
        self.validate_trip(conn, trip)
        return True

    def migrate_room(self, conn, room):
        self.rooms.graph_lock(conn)
        row = conn.execute('SELECT trip_id,owner_id,protected,created_at,expires_at,closed_at,archived_at '
            'FROM team_rooms WHERE room_id=%s FOR UPDATE', (room,)).fetchone()
        if not row:
            raise PrivateRecordError('Migration room missing')
        if row[0]:
            self.validate_trip(conn, row[0])
            return False
        _, owner, raw, created, expires, closed, archived = row
        self.account(conn, owner)
        payload = self.room_payload(owner, room, raw)
        members = conn.execute('SELECT account_id,protected,joined_at,left_at FROM team_room_members '
            'WHERE room_id=%s ORDER BY account_id', (room,)).fetchall()
        active = []
        for account, protected, joined, left in members:
            self.rooms.member_payload(account, room, protected)
            if left is None:
                self.account(conn, account)
                if account != owner and blocked(conn, owner, account):
                    raise PrivateRecordError('Migration owner membership blocked')
                active.append(account)
        if owner not in active or len(active) > 20:
            raise PrivateRecordError('Migration room membership invalid')
        now = conn.execute('SELECT clock_timestamp()').fetchone()[0]
        ended = archived or closed or (expires if expires <= now else None)
        if ended is not None and ended < created:
            raise PrivateRecordError('Migration room dates invalid')
        trip = secrets.token_hex(16)
        value = trip_fields(dict(title=payload['name'][:40].strip(), description=''))
        conn.execute('INSERT INTO team_trips(trip_id,owner_id,protected,created_at,state,started_at,ended_at,source_kind) '
            'VALUES(%s,%s,%s,%s,%s,%s,%s,\'legacy_room\')',
            (trip, owner, self.trips.protect('owner:' + owner, trip, value), created,
                'completed' if ended else 'active', created, ended))
        for account in active:
            member = dict(state='accepted', via='link', permissions=dict(invite=account == owner, edit=account == owner))
            conn.execute('INSERT INTO team_trip_members(trip_id,account_id,protected) VALUES(%s,%s,%s)',
                (trip, account, self.trips.protect('member:' + account, trip, member)))
        conn.execute('UPDATE team_rooms SET trip_id=%s,code_hash=NULL,expires_at=NULL,'
            'closed_at=COALESCE(closed_at,%s),archived_at=COALESCE(archived_at,%s),'
            'archived_music=CASE WHEN %s THEN COALESCE(archived_music,(SELECT protected FROM team_room_music WHERE room_id=%s)) '
            'ELSE archived_music END WHERE room_id=%s', (trip, ended, ended, ended is not None, room, room))
        self.validate_trip(conn, trip)
        return True

    def verify(self, conn):
        self.rooms.graph_lock(conn)
        failures = 0
        trips = conn.execute('SELECT trip_id FROM team_trips ORDER BY trip_id').fetchall()
        for trip, in trips:
            try:
                with conn.transaction():
                    self.validate_trip(conn, trip)
            except (HTTPException, PrivateRecordError):
                failures += 1
        remaining = conn.execute('SELECT count(*) FROM team_rooms WHERE trip_id IS NULL').fetchone()[0]
        return dict(trips=len(trips), invalidTrips=failures, unlinkedRooms=remaining)

    def run(self):
        report = dict(succeeded=0, skipped=0, failed=0)
        with psycopg.connect(self.auth.dsn) as conn:
            work = [('trip', row[0]) for row in conn.execute('SELECT trip_id FROM team_trips ORDER BY trip_id')]
            work += [('room', row[0]) for row in conn.execute('SELECT room_id FROM team_rooms WHERE trip_id IS NULL ORDER BY room_id')]
        for kind, identifier in work:
            try:
                with psycopg.connect(self.auth.dsn) as conn:
                    changed = (self.migrate_trip if kind == 'trip' else self.migrate_room)(conn, identifier)
                report['succeeded' if changed else 'skipped'] += 1
            except (HTTPException, PrivateRecordError, psycopg.Error):
                report['failed'] += 1
        with psycopg.connect(self.auth.dsn) as conn:
            report.update(self.verify(conn))
        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    auth = SimpleNamespace(dsn=os.environ['WEGOH_DATABASE_DSN'], enabled=True)
    migration = TripRoomMigration(auth)
    if args.apply:
        report = migration.run()
    else:
        with psycopg.connect(auth.dsn) as conn:
            report = dict(succeeded=0, skipped=0, failed=0, **migration.verify(conn))
    print('trip-room.migration: finished ({succeeded} succeeded, {failed} failed) '
        'skipped={skipped} invalid_trips={invalidTrips} unlinked_rooms={unlinkedRooms}'.format(**report))
    return int(bool(report['failed'] or report['invalidTrips'] or report['unlinkedRooms']))


if __name__ == '__main__':
    raise SystemExit(main())
