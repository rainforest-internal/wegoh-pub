import secrets

from fastapi import HTTPException
from private_records import PrivateRecordError, VisitCipher
from team_friends import blocked
from team_trip_context import linked_room, resolve_trip_context, trip_state
from team_trip_signal_contexts import IDENT, fail, page_values, place_value


class TeamTripPlaces:
    def __init__(self, auth):
        self.auth = auth
        self.signals = auth.trip_signal_contexts

    @staticmethod
    def protect(trip, proposal, account, value):
        return VisitCipher().protect('trip-place:' + account, trip + ':' + proposal, value)

    @staticmethod
    def restore(trip, proposal, account, raw):
        value = VisitCipher().restore('trip-place:' + account, trip + ':' + proposal, raw)
        if (not isinstance(value, dict) or set(value) != {'category', 'place', 'state', 'sourceSignalId',
                'joinedAt', 'recommended', 'selectedBy'} or value['category'] not in ('food', 'rest')
                or value['state'] not in ('proposed', 'selected', 'withdrawn')
                or type(value['recommended']) is not bool or not isinstance(value['joinedAt'], str)
                or not isinstance(value['sourceSignalId'], str) or not IDENT.fullmatch(value['sourceSignalId'])):
            raise PrivateRecordError('Trip place integrity failed')
        try:
            place_value(value['place'])
        except HTTPException:
            raise PrivateRecordError('Trip place integrity failed') from None
        return value

    @classmethod
    def withdraw_for_location(cls, conn, trip, account):
        rows = conn.execute('SELECT proposal_id,protected FROM team_trip_place_proposals '
            'WHERE trip_id=%s AND account_id=%s ORDER BY proposal_id FOR UPDATE', (trip, account)).fetchall()
        changed = False
        for proposal, raw in rows:
            value = cls.restore(trip, proposal, account, raw)
            if value['state'] == 'withdrawn':
                continue
            value.update(state='withdrawn', selectedBy=None)
            conn.execute('UPDATE team_trip_place_proposals SET protected=%s,revision=revision+1 '
                'WHERE trip_id=%s AND proposal_id=%s', (cls.protect(trip, proposal, account, value), trip, proposal))
            changed = True
        return changed

    def row(self, conn, trip, proposal):
        if not isinstance(proposal, str) or not IDENT.fullmatch(proposal):
            fail()
        row = conn.execute('SELECT account_id,protected,revision,created_at FROM team_trip_place_proposals '
            'WHERE trip_id=%s AND proposal_id=%s FOR UPDATE', (trip, proposal)).fetchone()
        if not row:
            fail()
        account, raw, revision, created = row
        return account, self.restore(trip, proposal, account, raw), revision, created

    def dto(self, conn, context, proposal, account, row, members):
        owner, value, revision, created = row
        member = members.get(owner)
        if (value['state'] == 'withdrawn' or not member or member['joinedAt'] != value['joinedAt']
                or not member['consents']['location'] or owner != account and blocked(conn, owner, account)):
            fail()
        signal = value['sourceSignalId']
        source = self.signals.visible(conn, context, signal, account, members)
        public = self.signals.dto(conn, context, signal, account, source, members)
        selected = value['selectedBy']
        if selected and (selected not in members or selected != account and blocked(conn, selected, account)):
            selected = None
        return dict(id=proposal, accountId=owner, category=value['category'], place=public['destination'],
            state=value['state'], recommended=value['recommended'], selectedBy=selected,
            sourceSignalId=signal, revision=revision, createdAt=created)

    def create(self, conn, trip, account, category, place=None, source_signal=None):
        if not isinstance(category, str) or category not in ('food', 'rest'):
            fail(400, 'Invalid place category')
        if (place is None) == (source_signal is None):
            fail(400, 'Choose a place or a source signal')
        if place is not None:
            place = place_value(place)
        context = resolve_trip_context(self.auth, conn, trip, account)
        members = self.signals.members(conn, trip, context['roomId'])
        member = members[account]
        if member['role'] != category:
            fail(403, 'Place role required')
        if not member['consents']['location'] or not member['consents']['status']:
            fail(403, 'Sharing permission required')
        if conn.execute('SELECT count(*) FROM team_trip_place_proposals WHERE trip_id=%s', (trip,)).fetchone()[0] >= 5000:
            fail(409, 'Trip place limit reached')
        author = account
        if source_signal is not None:
            source = self.signals.visible(conn, context, source_signal, account, members)
            author, place = source[0], source[1].get('destination')
            if place is None:
                fail(409, 'Place proposal unavailable')
        else:
            source_signal = self.signals.create(conn, trip, account, 'rest', place, preparation=True)['id']
        proposal = secrets.token_hex(16)
        value = dict(category=category, place=place, state='proposed', sourceSignalId=source_signal,
            joinedAt=members[author]['joinedAt'], recommended=True, selectedBy=None)
        conn.execute('INSERT INTO team_trip_place_proposals(trip_id,proposal_id,account_id,protected) VALUES(%s,%s,%s,%s)',
            (trip, proposal, author, self.protect(trip, proposal, author, value)))
        self.signals.rooms.notify(conn, context['roomId'], sections=('route',))
        return self.dto(conn, context, proposal, account, self.row(conn, trip, proposal), members)

    def update(self, conn, trip, account, proposal, data):
        if type(data.get('revision')) is not int or not 1 <= data['revision'] <= 2147483647:
            fail(400, 'Invalid place revision')
        changes = set(data) - {'revision'}
        if not changes or changes - {'place', 'recommended', 'state'}:
            fail(400, 'Invalid place fields')
        context = resolve_trip_context(self.auth, conn, trip, account)
        members = self.signals.members(conn, trip, context['roomId'])
        owner, value, revision, _ = row = self.row(conn, trip, proposal)
        if not (changes == {'state'} and data['state'] == 'withdrawn' and owner == account):
            self.dto(conn, context, proposal, account, row, members)
        if revision != data['revision']:
            fail(409, 'TRIP_PLACE_REVISION_CONFLICT')
        if 'state' in changes:
            state = data['state']
            if not isinstance(state, str) or state not in ('proposed', 'selected', 'withdrawn'):
                fail(400, 'Invalid place state')
            if state == 'withdrawn':
                if owner != account:
                    fail(403, 'Only the author may withdraw a place')
            else:
                resolve_trip_context(self.auth, conn, trip, account, permission='edit')
            value.update(state=state, selectedBy=account if state == 'selected' else None)
        if changes & {'place', 'recommended'}:
            if members[account]['role'] != value['category']:
                fail(403, 'Place role required')
            if not members[account]['consents']['status'] or not members[account]['consents']['location']:
                fail(403, 'Sharing permission required')
        if 'recommended' in changes:
            if type(data['recommended']) is not bool:
                fail(400, 'Invalid recommendation')
            value['recommended'] = data['recommended']
        if 'place' in changes:
            if owner != account:
                fail(403, 'Only the author may edit a place')
            if value['state'] == 'selected':
                fail(409, 'Unselect the place before editing it')
            value['place'] = place_value(data['place'])
            value['sourceSignalId'] = self.signals.create(conn, trip, account, 'rest', value['place'], preparation=True)['id']
        conn.execute('UPDATE team_trip_place_proposals SET protected=%s,revision=revision+1 WHERE trip_id=%s AND proposal_id=%s',
            (self.protect(trip, proposal, owner, value), trip, proposal))
        if value['state'] == 'withdrawn':
            saved = self.signals.row(conn, context, value['sourceSignalId'])[3]
            saved.update(withdrawn=True, state='reconfirm', votes={}, agreedAtClose=False)
            self.signals.save(conn, trip, value['sourceSignalId'], saved)
        self.signals.rooms.notify(conn, context['roomId'], sections=('route',))
        return dict(status='withdrawn' if value['state'] == 'withdrawn' else 'updated', revision=revision + 1)

    def list(self, conn, trip, account, limit=50, cursor=None):
        limit, offset = page_values(limit, cursor)
        context = resolve_trip_context(self.auth, conn, trip, account)
        members = self.signals.members(conn, trip, context['roomId'])
        rows = conn.execute('SELECT proposal_id FROM team_trip_place_proposals WHERE trip_id=%s '
            'ORDER BY created_at DESC,proposal_id LIMIT %s OFFSET %s', (trip, limit + 1, offset)).fetchall()
        items = []
        for (proposal,) in rows[:limit]:
            try:
                item = self.dto(conn, context, proposal, account, self.row(conn, trip, proposal), members)
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                continue
            items.append(item)
        return dict(places=items, nextCursor=str(offset + limit) if len(rows) > limit else None)

    def result_reader(self, conn, trip, account):
        state = trip_state(conn, trip)
        if state['state'] != 'completed':
            fail(409, 'TRIP_STATE_CONFLICT')
        room, owner = linked_room(conn, trip)
        if not self.signals.rooms.person(account) or account != owner and blocked(conn, account, owner):
            fail()
        if not conn.execute('SELECT 1 FROM team_room_members WHERE room_id=%s AND account_id=%s', (room, account)).fetchone():
            fail()
        context = dict(tripId=trip, roomId=room, **state)
        members = self.signals.members(conn, trip, room)
        items = []
        for (proposal,) in conn.execute('SELECT proposal_id FROM team_trip_place_proposals WHERE trip_id=%s '
                'ORDER BY created_at,proposal_id LIMIT 5000', (trip,)).fetchall():
            row = self.row(conn, trip, proposal)
            if row[1]['state'] != 'selected':
                continue
            try:
                item = self.dto(conn, context, proposal, account, row, members)
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                continue
            items.append(dict(item, kind='selected'))
        for (signal,) in conn.execute('SELECT signal_id FROM team_trip_signal_contexts WHERE trip_id=%s ORDER BY signal_id LIMIT 5000', (trip,)).fetchall():
            try:
                row = self.signals.visible(conn, context, signal, account, members)
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                continue
            saved = row[3]
            roster = saved['roster']
            if (not saved['agreedAtClose'] or roster != self.signals.roster(members)
                    or any(blocked(conn, a, b) for a in roster for b in roster if a < b)):
                continue
            public = self.signals.dto(conn, context, signal, account, row, members)
            items.append(dict(id=signal, kind='agreed', accountId=public['accountId'], place=public['destination']))
        return dict(places=items)
