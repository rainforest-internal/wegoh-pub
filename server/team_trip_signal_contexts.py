import math
import re
import secrets

from fastapi import HTTPException
from iphone_push import enqueue_push
from private_records import PrivateRecordError, VisitCipher
from team_friends import blocked
from team_rooms import KINDS, STOP_KINDS, TeamRooms, text
from team_trip_context import resolve_trip_context

IDENT = re.compile(r'[a-f0-9]{32}')
GROUP_RULE = 'other-car-groups-v1'
GROUP_FIELDS = {'decisionRule', 'requesterCarId', 'requiredCarIds', 'groupRoster', 'groupResponses'}
TERMINAL_RESULTS = frozenset(('agreed', 'passed', 'completed', 'cancelled'))


def fail(status=404, detail='Trip item unavailable'):
    raise HTTPException(status, detail)


def place_value(value):
    if not isinstance(value, dict) or set(value) != {'name', 'latitude', 'longitude'}:
        fail(400, 'Choose a place')
    result = dict(value, name=text(value['name'], 80))
    for key, low, high in (('latitude', -90, 90), ('longitude', -180, 180)):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]) or not low <= value[key] <= high:
            fail(400, 'Invalid place')
    return result


def page_values(limit, cursor):
    if type(limit) is not int or not 1 <= limit <= 100:
        fail(400, 'Invalid page size')
    if cursor is None:
        return limit, 0
    if not isinstance(cursor, str) or not re.fullmatch(r'0|[1-9][0-9]{0,4}', cursor) or int(cursor) > 5000:
        fail(400, 'Invalid page cursor')
    return limit, int(cursor)


class TeamTripSignalContexts:
    def __init__(self, auth):
        self.auth = auth
        self.rooms = getattr(auth, 'room_service', None) or TeamRooms(auth)

    @staticmethod
    def protect(trip, signal, value):
        return VisitCipher().protect('trip-signal-context', trip + ':' + signal, value)

    @staticmethod
    def restore(trip, signal, raw):
        value = VisitCipher().restore('trip-signal-context', trip + ':' + signal, raw)
        required = {'authorJoinedAt', 'tripRevision', 'roster', 'votes', 'state', 'withdrawn', 'agreedAtClose'}
        if (not isinstance(value, dict) or not required <= value.keys()
                or value.keys() - required - {'handRaise', 'resolution', 'directAction', 'candidateDetails'} - GROUP_FIELDS
                or value['state'] not in ('valid', 'reconfirm', 'closed')
                or type(value['tripRevision']) is not int or value['tripRevision'] < 1
                or type(value['withdrawn']) is not bool or type(value['agreedAtClose']) is not bool
                or 'handRaise' in value and type(value['handRaise']) is not bool
                or 'directAction' in value and value['directAction'] is not True
                or value.get('resolution', 'pending') not in ('pending', 'agreed', 'passed', 'completed', 'cancelled')
                or not isinstance(value['roster'], dict) or not isinstance(value['votes'], dict)):
            raise PrivateRecordError('Trip signal context integrity failed')
        if 'candidateDetails' in value:
            from trip_candidate_receipts import details
            try:
                details(value['candidateDetails'])
            except ValueError:
                raise PrivateRecordError('Trip candidate details integrity failed') from None
        for member in value['roster'].values():
            if (not isinstance(member, dict) or set(member) != {'joinedAt', 'status', 'location'}
                    or not isinstance(member['joinedAt'], str) or type(member['status']) is not bool
                    or type(member['location']) is not bool):
                raise PrivateRecordError('Trip signal roster integrity failed')
        for voter, vote in value['votes'].items():
            if (voter not in value['roster'] or not isinstance(vote, dict)
                    or set(vote) != {'choice', 'joinedAt', 'revision'} or vote['choice'] not in ('agree', 'pass')
                    or vote['joinedAt'] != value['roster'][voter]['joinedAt'] or vote['revision'] != value['tripRevision']):
                raise PrivateRecordError('Trip vote context integrity failed')
        if value.keys() & GROUP_FIELDS:
            if not GROUP_FIELDS <= value.keys() or value['decisionRule'] != GROUP_RULE:
                raise PrivateRecordError('Trip group context integrity failed')
            groups, responses = value['groupRoster'], value['groupResponses']
            requester, required_cars = value['requesterCarId'], value['requiredCarIds']
            if (not isinstance(groups, dict) or not groups or not isinstance(responses, dict)
                    or any(not isinstance(car, str) for car in groups)
                    or not isinstance(requester, str) or requester not in groups
                    or not isinstance(required_cars, list) or any(not isinstance(car, str) for car in required_cars)
                    or required_cars != sorted(set(groups) - {requester})
                    or not set(responses) <= set(required_cars)):
                raise PrivateRecordError('Trip group context integrity failed')
            assigned = set()
            for car, group in groups.items():
                if (not isinstance(car, str) or not IDENT.fullmatch(car) or not isinstance(group, dict)
                        or set(group) != {'driverId', 'name', 'members'}
                        or not isinstance(group['name'], str) or not 1 <= len(group['name']) <= 20
                        or not isinstance(group['driverId'], str) or not isinstance(group['members'], dict)
                        or group['driverId'] not in group['members']):
                    raise PrivateRecordError('Trip group roster integrity failed')
                for account, joined in group['members'].items():
                    if account in assigned or account not in value['roster'] or joined != value['roster'][account]['joinedAt']:
                        raise PrivateRecordError('Trip group membership integrity failed')
                    assigned.add(account)
            for car, response in responses.items():
                if (not isinstance(response, dict) or not {'accountId', 'choice', 'joinedAt', 'revision'} <= set(response)
                        or set(response) - {'accountId', 'choice', 'joinedAt', 'revision', 'source'}
                        or 'source' in response and response['source'] not in ('native', 'iphone', 'web')
                        or response['choice'] not in ('agree', 'pass')
                        or not isinstance(response['accountId'], str) or type(response['revision']) is not int
                        or response['accountId'] not in groups[car]['members']
                        or response['joinedAt'] != groups[car]['members'][response['accountId']]
                        or response['revision'] != value['tripRevision']):
                    raise PrivateRecordError('Trip group response integrity failed')
        return value

    def save(self, conn, trip, signal, value):
        conn.execute('UPDATE team_trip_signal_contexts SET protected=%s,revision=revision+1 '
            'WHERE trip_id=%s AND signal_id=%s', (self.protect(trip, signal, value), trip, signal))

    def members(self, conn, trip, room):
        from team_trips import TeamTrips
        accepted = (getattr(self.auth, 'trip_service', None) or TeamTrips(self.auth)).members(conn, trip)
        result = {}
        for peer, raw, joined in conn.execute('SELECT account_id,protected,joined_at FROM team_room_members '
                'WHERE room_id=%s AND left_at IS NULL', (room,)):
            if accepted.get(peer, {}).get('state') != 'accepted' or not self.rooms.person(peer):
                continue
            result[peer] = dict(self.rooms.member_payload(peer, room, raw), joinedAt=joined.isoformat())
        return result

    @staticmethod
    def roster(members):
        return {peer: dict(joinedAt=member['joinedAt'], status=member['consents']['status'],
            location=member['consents']['location']) for peer, member in members.items()}

    @staticmethod
    def author_live(sender, value, saved, members):
        member = members.get(sender)
        return bool(member and not saved['withdrawn'] and member['joinedAt'] == saved['authorJoinedAt']
            and (saved.get('directAction') is True or saved.get('decisionRule') == GROUP_RULE or member['consents']['status']
                 and (not value.get('destination') or member['consents']['location'])))

    def groups(self, conn, context, members):
        trips = self.auth.trip_service
        riders = trips.riders(conn, context['tripId'])
        return {car: dict(driverId=value['driverId'], name=value['name'], members={
            peer: member['joinedAt'] for peer, member in members.items()
            if peer == value['driverId'] or riders.get(peer) == car})
            for car, value in trips.cars(conn, context['tripId']).items() if value['driverId'] in members}

    @staticmethod
    def member_group(groups, account):
        return next((car for car, group in groups.items() if account in group['members']), None)

    @staticmethod
    def group_counts(saved):
        responses = saved['groupResponses']
        return dict(agree=sum(value['choice'] == 'agree' for value in responses.values()),
                    **{'pass': sum(value['choice'] == 'pass' for value in responses.values())},
                    total=len(saved['requiredCarIds']))

    def apply_group_route(self, conn, context, signal, value, saved):
        from team_trip_plan import TeamTripPlan
        TeamTripPlan(self.auth.trip_service).apply_agreed_signal(
            conn, context, signal, value['destination'], sorted(saved['groupRoster']))

    @staticmethod
    def direct_terminal(saved):
        return (saved.get('directAction') is True or saved.get('decisionRule') == GROUP_RULE) and saved.get('resolution') in TERMINAL_RESULTS

    def agreed(self, conn, sender, value, saved, members):
        if self.direct_terminal(saved):
            return bool(saved['resolution'] == 'agreed' and value['kind'] in STOP_KINDS
                        and value.get('destination') and self.author_live(sender, value, saved, members))
        roster = self.roster(members)
        if (saved['state'] != 'valid' or saved['roster'] != roster
                or not self.author_live(sender, value, saved, members)
                or value['kind'] not in STOP_KINDS or not value.get('destination')):
            return False
        if saved.get('handRaise') is True:
            return saved.get('resolution') == 'agreed'
        if (len(roster) < 2 or any(not item['status'] for item in roster.values())
                or any(blocked(conn, a, b) for a in roster for b in roster if a < b)):
            return False
        return all(saved['votes'].get(peer, {}).get('choice', 'agree' if peer == sender else None) == 'agree'
            for peer in roster)

    def row(self, conn, context, signal):
        if not isinstance(signal, str) or not IDENT.fullmatch(signal):
            fail()
        row = conn.execute('SELECT s.account_id,s.protected,s.created_at,c.protected,c.revision '
            'FROM team_room_signals s JOIN team_trip_signal_contexts c USING(signal_id) '
            'WHERE c.trip_id=%s AND s.room_id=%s AND s.signal_id=%s',
            (context['tripId'], context['roomId'], signal)).fetchone()
        if not row:
            fail()
        sender, raw, created, protected, revision = row
        value = self.rooms.restore('signal:' + sender, signal, raw)
        return sender, value, created, self.restore(context['tripId'], signal, protected), revision

    def visible(self, conn, context, signal, viewer, members=None):
        sender, value, created, saved, revision = self.row(conn, context, signal)
        members = members if members is not None else self.members(conn, context['tripId'], context['roomId'])
        if not self.author_live(sender, value, saved, members) or sender != viewer and blocked(conn, sender, viewer):
            fail()
        return sender, value, created, saved, revision

    def driver_votes(self, conn, context, sender, saved, members, viewer=None):
        drivers = {car['driverId'] for car in self.auth.trip_service.cars(conn, context['tripId']).values()
                   if car['driverId'] in members}
        if viewer is not None:
            drivers = {driver for driver in drivers if driver == viewer or not blocked(conn, viewer, driver)}
        valid = (saved['state'] == 'valid' and saved['tripRevision'] == context['revision']
                 and saved['roster'] == self.roster(members))
        counts = dict(agree=0, **{'pass': 0}, total=len(drivers))
        if valid:
            for driver in drivers:
                choice = saved['votes'].get(driver, {}).get('choice', 'agree' if driver == sender else None)
                if choice is not None:
                    counts[choice] += 1
        return counts

    def resolution(self, conn, context, row, members):
        sender, value, _, saved, _ = row
        if self.direct_terminal(saved):
            return saved['resolution'] if self.author_live(sender, value, saved, members) else 'reconfirm'
        if (saved['state'] != 'valid' or saved['tripRevision'] != context['revision']
                or saved['roster'] != self.roster(members) or not self.author_live(sender, value, saved, members)):
            return 'reconfirm'
        if saved.get('decisionRule') == GROUP_RULE and saved['groupRoster'] != self.groups(conn, context, members):
            return 'reconfirm'
        result = saved.get('resolution', 'pending')
        if result != 'pending' or not value.get('destination') or saved.get('handRaise') is False:
            return result
        if saved.get('decisionRule') == GROUP_RULE:
            votes = self.group_counts(saved)
            if votes['agree'] + votes['pass'] < votes['total']:
                return 'pending'
            return 'passed' if votes['pass'] else 'agreed'
        votes = self.driver_votes(conn, context, sender, saved, members)
        if votes['agree'] > votes['total'] / 2:
            return 'agreed'
        if votes['pass'] > votes['total'] / 2:
            return 'passed'
        return 'pending'

    def current(self, conn, context, members):
        legacy_places = None
        for signal, sender, raw, created, protected, revision in conn.execute(
                'SELECT c.signal_id,s.account_id,s.protected,s.created_at,c.protected,c.revision '
                'FROM team_trip_signal_contexts c JOIN team_room_signals s USING(signal_id) '
                'WHERE c.trip_id=%s AND s.room_id=%s ORDER BY s.created_at DESC,s.signal_id DESC',
                (context['tripId'], context['roomId'])).fetchall():
            value = self.rooms.restore('signal:' + sender, signal, raw)
            saved = self.restore(context['tripId'], signal, protected)
            if value['kind'] not in STOP_KINDS or saved.get('handRaise') is False:
                continue
            if 'handRaise' not in saved:
                if legacy_places is None:
                    places = self.auth.trip_places_service
                    legacy_places = {places.restore(context['tripId'], proposal, owner, payload)['sourceSignalId']
                        for proposal, owner, payload in conn.execute(
                            'SELECT proposal_id,account_id,protected FROM team_trip_place_proposals WHERE trip_id=%s',
                            (context['tripId'],))}
                if signal in legacy_places:
                    continue
            row = sender, value, created, saved, revision
            if self.resolution(conn, context, row, members) == 'pending':
                return signal, row
            return None
        return None

    def is_hand_raise(self, conn, trip, signal, value, saved):
        if value['kind'] not in STOP_KINDS:
            return False
        if 'handRaise' in saved:
            return saved['handRaise']
        places = self.auth.trip_places_service
        for proposal, owner, payload in conn.execute(
                'SELECT proposal_id,account_id,protected FROM team_trip_place_proposals WHERE trip_id=%s', (trip,)):
            if places.restore(trip, proposal, owner, payload)['sourceSignalId'] == signal:
                return False
        return True

    def dto(self, conn, context, signal, viewer, row, members, current=None):
        sender, value, created, saved, revision = row
        destination = value.get('destination')
        if destination:
            destination = dict(destination)
        valid = self.direct_terminal(saved) or (saved['state'] == 'valid' and saved['tripRevision'] == context['revision'] and saved['roster'] == self.roster(members))
        votes, mine = {'agree': 0, 'pass': 0}, None
        for peer, vote in saved['votes'].items() if valid else ():
            if peer != viewer and blocked(conn, peer, viewer):
                continue
            votes[vote['choice']] += 1
            if peer == viewer:
                mine = vote['choice']
        result = dict(id=signal, accountId=sender, kind=value['kind'], destination=destination, createdAt=created,
            revision=revision, contextState='valid' if valid else 'reconfirm', votes=votes,
            myVote=mine, agreed=valid and self.agreed(conn, sender, value, saved, members),
            inProgress=bool(current and current[0] == signal),
            resolution=self.resolution(conn, context, row, members),
            driverVotes=self.driver_votes(conn, context, sender, saved, members, viewer),
            candidateDetails=saved.get('candidateDetails'))
        if saved.get('decisionRule') == GROUP_RULE:
            mine = self.member_group(saved['groupRoster'], viewer)
            choice = saved['groupResponses'].get(mine, {}).get('choice')
            visible = {car for car, group in saved['groupRoster'].items()
                       if group['driverId'] == viewer or not blocked(conn, viewer, group['driverId'])}
            result.update(decisionRule=GROUP_RULE,
                groupVotes=self.group_counts(saved), myGroupChoice=choice,
                canRespond=bool(result['inProgress'] and result['resolution'] == 'pending'
                    and mine in saved['requiredCarIds'] and mine not in saved['groupResponses']),
                groupResponses=[dict(carId=car, carName=saved['groupRoster'][car]['name'],
                    choice=saved['groupResponses'].get(car, {}).get('choice'),
                    **self.response_author(conn, saved['groupResponses'].get(car), viewer))
                    for car in saved['requiredCarIds'] if car in visible])
            if saved['requesterCarId'] in visible:
                result['requesterCarId'] = saved['requesterCarId']
        return result

    def response_author(self, conn, response, viewer):
        account = response.get('accountId') if response else None
        person = self.rooms.person(account) if account and (account == viewer or not blocked(conn, viewer, account)) else None
        return dict(responderAccountId=account if person else None, responderName=person['name'] if person else None,
                    responseSource=response.get('source') if person else None)

    def create(self, conn, trip, account, kind, destination=None, *, preparation=False, candidate_receipt=None):
        if not isinstance(kind, str) or kind not in KINDS:
            fail(400, 'Invalid status signal')
        destination = place_value(destination) if destination is not None else None
        context = resolve_trip_context(self.auth, conn, trip, account, states=('planned', 'active') if preparation else ('active',))
        candidate_details = None
        if candidate_receipt is not None:
            from trip_candidate_receipts import verify
            now = conn.execute('SELECT extract(epoch FROM clock_timestamp())').fetchone()[0]
            candidate_details = verify(candidate_receipt, trip, account, context['revision'], kind, destination, float(now))
        members = self.members(conn, trip, context['roomId'])
        member = members[account]
        hand_raise = not preparation and kind in STOP_KINDS
        if hand_raise:
            from team_trip_route_segments import TeamTripRouteSegments
            TeamTripRouteSegments(self.auth.trip_service).check_shared(conn, trip, account)
        group_rule = hand_raise and destination is not None
        if not hand_raise and (not member['consents']['status'] or destination and not member['consents']['location']):
            fail(403, 'Sharing permission required')
        groups = self.groups(conn, context, members) if group_rule else None
        requester_car = self.member_group(groups, account) if groups is not None else None
        current = self.current(conn, context, members) if hand_raise else None
        if current:
            sender, value = current[1][:2]
            if sender == account and value == dict(kind=kind, destination=destination):
                return dict(id=current[0], status='sent')
            fail(409, 'TRIP_SIGNAL_IN_PROGRESS')
        if group_rule and requester_car is None:
            fail(409, 'TRIP_SIGNAL_CAR_REQUIRED')
        if group_rule and any(not any(peer == account or not blocked(conn, account, peer)
                for peer in group['members']) for car, group in groups.items() if car != requester_car):
            fail(409, 'TRIP_SIGNAL_GROUP_UNREACHABLE')
        if conn.execute('SELECT count(*) FROM team_room_signals WHERE room_id=%s', (context['roomId'],)).fetchone()[0] >= 5000:
            fail(409, 'Trip signal limit reached')
        signal = secrets.token_hex(16)
        value = dict(kind=kind, destination=destination)
        saved = dict(authorJoinedAt=member['joinedAt'], tripRevision=context['revision'], roster=self.roster(members),
            votes={}, state='valid', withdrawn=False, agreedAtClose=False, handRaise=hand_raise, resolution='pending')
        if candidate_details is not None:
            saved['candidateDetails'] = candidate_details
        if group_rule:
            saved.update(decisionRule=GROUP_RULE, requesterCarId=requester_car,
                requiredCarIds=sorted(set(groups) - {requester_car}), groupRoster=groups, groupResponses={})
        if hand_raise:
            saved['directAction'] = True
            saved['resolution'] = self.resolution(conn, context, (account, value, None, saved, 1), members)
        conn.execute('INSERT INTO team_room_signals(signal_id,room_id,account_id,protected) VALUES(%s,%s,%s,%s)',
            (signal, context['roomId'], account, self.rooms.protect('signal:' + account, signal, value)))
        conn.execute('INSERT INTO team_trip_signal_contexts(signal_id,trip_id,protected) VALUES(%s,%s,%s)',
            (signal, trip, self.protect(trip, signal, saved)))
        if group_rule and saved['resolution'] == 'agreed':
            self.apply_group_route(conn, context, signal, value, saved)
        if hand_raise and saved['resolution'] == 'pending':
            recipients = members
            if group_rule:
                recipients = [peer for car in saved['requiredCarIds'] for peer in groups[car]['members']]
            recipients = [peer for peer in recipients if peer != account and not blocked(conn, account, peer)]
            enqueue_push(conn, kind='hand_raise', actor=account, recipients=recipients, resource_id=signal, trip_id=trip)
        self.rooms.notify(conn, context['roomId'], sections=('signals', 'route') if saved.get('resolution') == 'agreed' else ('signals',))
        return dict(id=signal, status='sent')

    def list(self, conn, trip, account, limit=50, cursor=None):
        limit, offset = page_values(limit, cursor)
        context = resolve_trip_context(self.auth, conn, trip, account)
        members = self.members(conn, trip, context['roomId'])
        current = self.current(conn, context, members)
        rows = conn.execute('SELECT c.signal_id FROM team_trip_signal_contexts c JOIN team_room_signals s USING(signal_id) '
            'WHERE c.trip_id=%s AND s.room_id=%s ORDER BY s.created_at DESC,s.signal_id LIMIT %s OFFSET %s',
            (trip, context['roomId'], limit + 1, offset)).fetchall()
        items = []
        for (signal,) in rows[:limit]:
            try:
                row = self.visible(conn, context, signal, account, members)
            except HTTPException as error:
                if error.status_code != 404:
                    raise
                continue
            items.append(self.dto(conn, context, signal, account, row, members, current))
        return dict(signals=items, nextCursor=str(offset + limit) if len(rows) > limit else None,
                    hasActiveSignal=current is not None)

    def vote(self, conn, trip, account, signal, choice=None, *, source=None):
        if source is not None and source not in ('native', 'iphone', 'web'):
            fail(400, 'Invalid hand-raise response source')
        if choice is not None and (not isinstance(choice, str) or choice not in ('agree', 'pass')):
            fail(400, 'Invalid vote')
        context = resolve_trip_context(self.auth, conn, trip, account, states=('active',))
        members = self.members(conn, trip, context['roomId'])
        sender, value, _, saved, _ = self.visible(conn, context, signal, account, members)
        if saved.get('decisionRule') == GROUP_RULE:
            return self.group_vote(conn, context, signal, account, choice, sender, value, saved, members, source=source)
        if not members[account]['consents']['status']:
            fail(403, 'Sharing permission required')
        current = self.current(conn, context, members)
        hand_raise = self.is_hand_raise(conn, trip, signal, value, saved)
        if hand_raise:
            if current is None or current[0] != signal:
                fail(409, 'TRIP_SIGNAL_NOT_ACTIVE')
            drivers = {car['driverId'] for car in self.auth.trip_service.cars(conn, trip).values()}
            if account not in drivers:
                fail(403, 'Only current drivers may answer a hand raise')
        if choice is not None and (not value.get('destination') or saved['state'] != 'valid'
                or saved['tripRevision'] != context['revision'] or saved['roster'] != self.roster(members)):
            fail(409, 'TRIP_SIGNAL_RECONFIRM_REQUIRED')
        previous_choice = saved['votes'].get(account, {}).get('choice')
        if choice is None:
            saved['votes'].pop(account, None)
            conn.execute('DELETE FROM team_room_votes WHERE signal_id=%s AND account_id=%s', (signal, account))
        else:
            saved['votes'][account] = dict(choice=choice, joinedAt=members[account]['joinedAt'], revision=context['revision'])
            conn.execute('INSERT INTO team_room_votes(signal_id,account_id,protected) VALUES(%s,%s,%s) '
                'ON CONFLICT(signal_id,account_id) DO UPDATE SET protected=excluded.protected,updated_at=clock_timestamp()',
                (signal, account, self.rooms.protect('vote:' + account, signal, dict(choice=choice))))
        if hand_raise:
            saved['resolution'] = self.resolution(conn, context, (sender, value, None, saved, 0), members)
        self.save(conn, trip, signal, saved)
        if hand_raise and account != sender and choice is not None and choice != previous_choice:
            enqueue_push(conn, kind='hand_raise_reaction', actor=account, recipients=[sender], resource_id=signal, trip_id=trip)
        self.rooms.notify(conn, context['roomId'], sections=('signals', 'route') if saved.get('resolution') == 'agreed' else ('signals',))
        return dict(status='withdrawn' if choice is None else 'saved', choice=choice)

    def group_vote(self, conn, context, signal, account, choice, sender, value, saved, members, *, source=None):
        if choice is None:
            fail(409, 'TRIP_SIGNAL_GROUP_RESPONSE_FINAL')
        if self.resolution(conn, context, (sender, value, None, saved, 0), members) == 'reconfirm':
            fail(409, 'TRIP_SIGNAL_RECONFIRM_REQUIRED')
        car = self.member_group(saved['groupRoster'], account)
        if (car not in saved['requiredCarIds']
                or self.member_group(self.groups(conn, context, members), account) != car
                or saved['groupRoster'][car]['members'].get(account) != members[account]['joinedAt']):
            fail(403, 'TRIP_SIGNAL_OTHER_GROUP_REQUIRED')
        previous = saved['groupResponses'].get(car)
        if previous:
            return dict(status='saved', already=True, choice=previous['choice'],
                responderAccountId=self.response_author(conn, previous, account)['responderAccountId'])
        current = self.current(conn, context, members)
        if current is None or current[0] != signal:
            fail(409, 'TRIP_SIGNAL_NOT_ACTIVE')
        saved['groupResponses'][car] = dict(accountId=account, choice=choice,
            joinedAt=members[account]['joinedAt'], revision=context['revision'])
        if source is not None:
            saved['groupResponses'][car]['source'] = source
        saved['votes'][account] = dict(choice=choice, joinedAt=members[account]['joinedAt'], revision=context['revision'])
        conn.execute('INSERT INTO team_room_votes(signal_id,account_id,protected) VALUES(%s,%s,%s) '
            'ON CONFLICT(signal_id,account_id) DO UPDATE SET protected=excluded.protected,updated_at=clock_timestamp()',
            (signal, account, self.rooms.protect('vote:' + account, signal, dict(choice=choice))))
        saved['resolution'] = self.resolution(conn, context, (sender, value, None, saved, 0), members)
        self.save(conn, context['tripId'], signal, saved)
        if saved['resolution'] == 'agreed':
            self.apply_group_route(conn, context, signal, value, saved)
        enqueue_push(conn, kind='hand_raise_reaction', actor=account, recipients=[sender], resource_id=signal,
                     trip_id=context['tripId'])
        self.rooms.notify(conn, context['roomId'], sections=('signals', 'route') if saved.get('resolution') == 'agreed' else ('signals',))
        return dict(status='saved', choice=choice)

    def finish(self, conn, trip, account, signal, result):
        if not isinstance(result, str) or result not in ('completed', 'cancelled'):
            fail(400, 'Invalid hand-raise result')
        context = resolve_trip_context(self.auth, conn, trip, account, states=('active',))
        members = self.members(conn, trip, context['roomId'])
        row = self.visible(conn, context, signal, account, members)
        sender, value, _, saved, revision = row
        if sender != account:
            fail(403, 'Only the requester may finish a hand raise')
        if saved.get('resolution') == result:
            return dict(status=result, revision=revision)
        current = self.current(conn, context, members)
        if current is None or current[0] != signal:
            fail(409, 'TRIP_SIGNAL_NOT_ACTIVE')
        if result == 'completed' and value.get('destination'):
            fail(409, 'Drivers must decide on the selected place')
        saved['resolution'] = result
        self.save(conn, trip, signal, saved)
        self.rooms.notify(conn, context['roomId'], sections=('signals', 'route') if saved.get('resolution') == 'agreed' else ('signals',))
        return dict(status=result, revision=revision + 1)

    def invalidate_trip_context(self, conn, trip):
        row = conn.execute('SELECT room_id FROM team_rooms WHERE trip_id=%s', (trip,)).fetchone()
        if not row:
            return
        room = row[0]
        from team_event_versions import trip_changed
        trip_changed(conn, trip, ('signals',))
        members = self.members(conn, trip, room)
        for signal, sender, raw, protected in conn.execute('SELECT c.signal_id,s.account_id,s.protected,c.protected '
                'FROM team_trip_signal_contexts c JOIN team_room_signals s USING(signal_id) '
                'WHERE c.trip_id=%s AND s.room_id=%s', (trip, room)).fetchall():
            saved = self.restore(trip, signal, protected)
            value = self.rooms.restore('signal:' + sender, signal, raw)
            saved['withdrawn'] = not self.author_live(sender, value, saved, members)
            if saved['state'] != 'closed' and not self.direct_terminal(saved):
                saved.update(state='reconfirm', votes={}, agreedAtClose=False)
                if saved.get('decisionRule') == GROUP_RULE:
                    saved['groupResponses'] = {}
            self.save(conn, trip, signal, saved)

    def on_trip_block(self, conn, trip, room, blocker, target):
        self.invalidate_trip_context(conn, trip)
        for signal, raw in conn.execute('SELECT signal_id,protected FROM team_trip_signal_contexts WHERE trip_id=%s', (trip,)).fetchall():
            saved = self.restore(trip, signal, raw)
            if saved['agreedAtClose']:
                saved['agreedAtClose'] = False
                self.save(conn, trip, signal, saved)

    def withdraw_trip_context(self, conn, trip, room, account=None):
        if account is not None:
            self.invalidate_trip_context(conn, trip)
            return
        members = self.members(conn, trip, room)
        for signal, sender, raw, protected in conn.execute('SELECT c.signal_id,s.account_id,s.protected,c.protected '
                'FROM team_trip_signal_contexts c JOIN team_room_signals s USING(signal_id) '
                'WHERE c.trip_id=%s AND s.room_id=%s', (trip, room)).fetchall():
            saved = self.restore(trip, signal, protected)
            if saved['state'] == 'closed':
                continue
            value = self.rooms.restore('signal:' + sender, signal, raw)
            saved.update(agreedAtClose=self.agreed(conn, sender, value, saved, members), state='closed')
            self.save(conn, trip, signal, saved)
