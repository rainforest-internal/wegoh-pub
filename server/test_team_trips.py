"""Trip v6: isolated PostgreSQL/HTTP contracts and explicitly DB-free policy tests."""
import ast
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import psycopg
from fastapi import HTTPException, Request, Response
from private_records import VisitCipher, PrivateRecordError
from team_trips import TeamTrips, trip_text, car_fields, permissions
from team_friends import create_router, issue_link, resolve_link
import test_team_friends as friend_fixture


@contextmanager
def concurrent_active_trips():
    """Seed trips that ran side by side before the one-active-trip rule.

    The rule only blocks new starts and joins; such stored trips are kept as they are,
    so isolation between them is still checked against this state."""
    with patch.object(TeamTrips, 'active_trips', staticmethod(lambda conn, account, excluded: [])):
        yield


class TripTests(friend_fixture.FriendTests):
    def trip(self, path='', data=None, method='GET', *, session=None, who=None, **kwargs):
        who = who or (session['user']['displayName'] if session else 'alice')
        return self.friend('/trips' + path, data, method, session=session, who=who, **kwargs)

    def social(self, path, session, data=None, method='GET', **kwargs):
        return self.friend(path, data, method, session=session, who=session['user']['displayName'], **kwargs)

    def link_request(self, kind, token, session, *, action='preview', **kwargs):
        return self.social('/'+kind+'-links/'+(action.lstrip('/') or 'preview'),session,dict(token=token),'POST',**kwargs)

    def new_trip(self, session, title='우리 여행', members=()):
        status, headers, value = self.trip(data=dict(title=title, description='', memberIds=[m['user']['id'] for m in members]), method='POST', session=session)
        self.assertEqual(status, 201, value)
        self.assertEqual(set(value), {'id'})
        self.assertEqual(headers['cache-control'], 'private, no-store')
        return value['id']

    def close_trip(self, trip, session, action='cancel'):
        with psycopg.connect(self.dsn) as conn:
            revision = conn.execute('SELECT revision FROM team_trips WHERE trip_id=%s', (trip,)).fetchone()[0]
            return self.module.TEAM_TRIPS.transition(conn, trip, session['user']['id'], action, revision)

    def invite(self, trip, owner, target):
        return self.trip('/' + trip + '/members', dict(accountId=target['user']['id']), 'POST', session=owner)

    def respond(self, trip, session, accept=True):
        return self.trip('/' + trip + '/respond', dict(accept=accept), 'POST', session=session)

    def rights(self, trip, owner, target, *, invite=False, edit=False):
        return self.trip('/' + trip + '/members/' + target['user']['id'] + '/permissions', dict(invite=invite, edit=edit), 'PUT', session=owner)

    def join(self, trip, owner, target):
        token = self.trip('/' + trip + '/link', method='POST', session=owner)[2]['token']
        result = self.link_request('trip', token, target, action='/join')
        self.assertEqual(result[2], dict(tripId=trip))
        return token

    def new_car(self, trip, session, *, seats=2):
        result = self.trip('/' + trip + '/cars', dict(name='우리 차', seats=seats), 'POST', session=session)
        self.assertEqual(result[0], 201, result[2])
        return trip + '/cars/' + result[2]['id']

    def ride(self, car_path, session):
        return self.trip('/' + car_path + '/ride', method='PUT', session=session)

    def attach(self, trip, pack, session):
        return self.trip('/' + trip + '/courses', dict(packId=pack['id']), 'POST', session=session)

    def detach(self, trip, pack, session):
        return self.trip('/' + trip + '/courses/' + pack['id'], method='DELETE', session=session)

    def vehicle(self, session):
        who = session['user']['displayName']
        _, _, device = self.pair(session, who)
        self.assertEqual(self.call('/v1/devices/' + device['deviceId'] + '/vehicle-profile',
            dict(plateNumber='123가4567', name='', expectedRevision=0), 'PUT', session=session, who=who)[0], 200)
        return device

    def befriend(self, owner, target, who='bob'):
        self.assertEqual(self.request_friend(owner, target, owner['user']['displayName'])[0], 201)
        self.assertEqual(self.friend('/friends/requests/' + owner['user']['id'] + '/respond',
            dict(accept=True), 'POST', session=target, who=who)[0], 200)

    def revision(self, session):
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='friends'",
                (session['user']['id'],)).fetchone()
        return row[0] if row else 0

    def published_course(self, session, who='alice'):
        pack = self.pack()
        self.assertEqual(self.publish(pack, session, who)[0], 201)
        return pack

    def display_remote_actions(self, *ids):
        ids = ids or ('hvac.temperature', 'hvac.fan')
        return [{key: item[key] for key in ('id', 'revision', 'label')}
            for item in self.module.TEAM_FRIEND_CONTROLS.options() if item['id'] in ids]

    def remote_setup(self):
        a, b, e = self.sessions()
        self.befriend(a, b)
        device = self.vehicle(b)
        trip = self.new_trip(b, members=(a,))
        self.assertEqual(self.respond(trip, a)[0], 200)
        car_path = self.new_car(trip, b)
        self.assertEqual(self.ride(car_path, a)[0], 200)
        return a, b, e, car_path, device

    def set_remote_policy(self, car_path, owner, device=None, actions=('hvac.temperature',), enabled=True, **kwargs):
        data = dict(enabled=enabled, actions=list(actions), deviceId=device['deviceId'] if device else None)
        return self.trip('/' + car_path + '/remote-policy', data, 'PUT', session=owner, **kwargs)

    def seed_legacy_remote(self, car_path, requester):
        trip, _, car = car_path.partition('/cars/')
        identifier = secrets.token_hex(16)
        service = self.module.TEAM_TRIPS
        with psycopg.connect(self.dsn) as conn:
            owner = conn.execute('SELECT driver_id FROM team_trip_cars WHERE trip_id=%s AND car_id=%s', (trip, car)).fetchone()[0]
            created = conn.execute('SELECT clock_timestamp()').fetchone()[0].isoformat()
            value = dict(carId=car, requesterId=requester['user']['id'], ownerId=owner, createdAt=created,
                actions=[dict(id='hvac.temperature', revision=1)])
            conn.execute('INSERT INTO team_trip_remote_requests(trip_id,request_id,requester_id,driver_id,car_id,protected) VALUES(%s,%s,%s,%s,%s,%s)',
                (trip, identifier, requester['user']['id'], owner, car, service.protect('remote-request:' + identifier, trip, value)))
        return identifier

    def member_remote(self, car_path, session, owner=None, who=None):
        cars = self.trip('/' + car_path.split('/')[0], session=session, who=who)[2]['cars']
        return next(car['remote'] for car in cars if car['id'] == car_path.split('/')[-1])

    def transition_trip(self, trip, owner, action):
        revision = self.trip('/' + trip, session=owner)[2]['revision']
        status, _, result = self.trip('/' + trip + '/' + action, dict(revision=revision), 'POST', session=owner)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['state'], {'start': 'active', 'finish': 'completed'}[action])

    def test_44_only_selected_car_accepts_commands_during_the_approved_trip(self):
        rider, driver, outsider, car_path, chosen = self.remote_setup()
        chosen_certificate = self._native_fingerprint
        other = self.vehicle(outsider)
        other_certificate = self._native_fingerprint
        self._native_fingerprint = chosen_certificate
        chosen_id, other_id = chosen['deviceId'], other['deviceId']
        trip = car_path.split('/')[0]
        candidates_path = '/' + car_path + '/remote-devices'
        candidates = self.trip(candidates_path, session=driver)[2]['devices']
        self.assertEqual({d['id'] for d in candidates if d['receiveEnabled']}, {chosen_id})
        self.assertIn(self.trip(candidates_path, session=rider)[0], (403, 404))
        self.assertEqual(self.set_remote_policy(car_path, driver, chosen)[0], 200)
        driver_view = self.trip('/' + trip, session=driver)[2]
        self.assertEqual(driver_view['remoteRequests'], [])
        self.assertEqual(driver_view['cars'][0]['remotePolicy']['actions'], ['hvac.temperature'])
        rider_view = self.trip('/' + trip, session=rider)[2]
        self.assertNotIn('remoteGranted', rider_view['cars'][0]['passengers'][0])
        self.assertIsNone(self.member_remote(car_path, driver))
        self.assertEqual(self.member_remote(car_path, rider)['actions'], self.display_remote_actions('hvac.temperature'))

        generic_path = '/v1/vehicle-remotes'
        trip_path = '/v1/social/trips/' + trip + '/vehicle-remotes'
        def send(path, device_id=chosen_id, revision=1, **changes):
            data = dict(eventId=secrets.token_hex(16), grantRevision=revision, capabilityId='hvac.temperature',
                capabilityRevision=1, arguments=dict(seat='ROW_1_RIGHT', value=22))
            data.update(changes)
            return self.call(path + '/' + device_id + '/commands', data, 'POST', session=rider)

        self.assertEqual(self.call(trip_path, session=rider)[0], 409)
        self.assertIn(send(trip_path)[0], (403, 409))
        self.transition_trip(trip, driver, 'start')
        remotes = self.call(trip_path, session=rider)[2]['remotes']
        self.assertEqual([r['deviceId'] for r in remotes], [chosen_id])
        remote = remotes[0]
        self.assertEqual([action['id'] for action in remote['actions']], ['hvac.temperature'])
        revision = remote['grantRevision']
        self.assertEqual(self.call(generic_path, session=rider)[0], 404)
        self.assertIn(send(generic_path, revision=revision)[0], (404, 405))
        self.assertEqual(send(trip_path, other_id, revision)[0], 403)
        self.assertEqual(send(trip_path, revision=revision, capabilityId='hvac.fan',
            arguments=dict(seat='ROW_1_RIGHT', value=2))[0], 403)

        second_trip = self.new_trip(driver, members=(rider,))
        self.assertEqual(self.respond(second_trip, rider)[0], 200)
        second_car = self.new_car(second_trip, driver)
        self.assertEqual(self.ride(second_car, rider)[0], 200)
        with concurrent_active_trips():
            self.transition_trip(second_trip, driver, 'start')
        wrong_path = '/v1/social/trips/' + second_trip + '/vehicle-remotes'
        self.assertEqual(self.call(wrong_path, session=rider)[2]['remotes'], [])
        self.assertEqual(send(wrong_path, revision=revision)[0], 403)

        status, _, sent = send(trip_path, revision=revision)
        self.assertEqual(status, 201, sent)
        self.assertEqual(sent['tripId'], trip)
        inbox = '/v1/device/command-inbox'
        self.assertEqual([item['id'] for item in self.native(inbox, token=chosen['accessToken'])[2]['requests']], [sent['id']])
        self.assertEqual(self.native(inbox, token=other['accessToken'], certificate=other_certificate)[2]['requests'], [])
        claim_path = '/v1/device/requests/' + sent['id'] + '/claim'
        permission = self.native('/v1/device/functional-permissions', token=chosen['accessToken'])[2]
        claim = dict(claimId=secrets.token_hex(16), functionalRevision=permission['revision'])
        status, _, delivered = self.native(claim_path, claim, 'POST', token=chosen['accessToken'])
        self.assertEqual(status, 200, delivered)
        status, _, queued = send(trip_path, revision=revision)
        self.assertEqual(status, 201, queued)
        self.transition_trip(trip, driver, 'finish')

        self.assertEqual(self.call(trip_path, session=rider)[0], 409)
        self.assertIn(send(trip_path, revision=revision)[0], (403, 409))
        self.assertIn(send(generic_path, revision=revision)[0], (404, 405))
        self.assertEqual(send(wrong_path, revision=revision)[0], 403)
        self.assertEqual(self.native(inbox, token=chosen['accessToken'])[2]['requests'], [])
        self.assertIn(self.native(claim_path, claim, 'POST', token=chosen['accessToken'])[0], (403, 409))
        ack_path = '/v1/device/requests/' + sent['id'] + '/ack'
        ack = dict(ackId=secrets.token_hex(16), leaseId=delivered['leaseId'], stage='received', evidence={},
            functionalRevision=permission['revision'])
        self.assertIn(self.native(ack_path, ack, 'POST', token=chosen['accessToken'])[0], (403, 409))
        with psycopg.connect(self.dsn) as conn:
            commands = self.module.TEAM_FRIEND_CONTROLS.commands
            self.assertEqual(commands.load_request(conn, queued['id'])['stage'], 'cancelled')
            previous = commands.load_request(conn, delivered['id'])
            self.assertEqual(previous['stage'], 'unknown')
            self.assertIsNone(previous['leaseHash'])

    def test_45_remote_policy_retires_request_routes_and_preserves_owner_boundary(self):
        rider, driver, outsider, car, device = self.remote_setup()
        for method, suffix, data in [('POST', '/remote-requests', dict(actions=[])),
                ('POST', '/remote-requests/' + 'a'*32 + '/respond', dict(accept=True)),
                ('DELETE', '/remote-requests/' + 'a'*32, None), ('DELETE', '/remote-grants/' + rider['user']['id'], None)]:
            self.assertIn(self.trip('/' + car + suffix, data, method, session=driver)[0], (404, 405))
        self.assertEqual(self.set_remote_policy(car, rider, device)[0], 403)
        self.assertEqual(self.set_remote_policy(car, outsider, device)[0], 404)
        self.assertEqual(self.set_remote_policy(car, driver, device, csrf=False)[0], 403)
        self.assertEqual(self.set_remote_policy(car, driver, device)[0], 200)
        self.assertEqual(self.member_remote(car, rider)['actions'], self.display_remote_actions('hvac.temperature'))

    def test_46_remote_policy_receiver_and_pending_revocation(self):
        rider, driver, _, car, device = self.remote_setup()
        self.set_command_receiver(device, False)
        self.assertIn(self.set_remote_policy(car, driver, device)[0], (403, 404, 409))
        self.assertEqual(self.member_remote(car, rider)['status'], 'none')
        self.set_command_receiver(device, True)
        self.assertEqual(self.set_remote_policy(car, driver, device)[0], 200)
        self.assertEqual(self.member_remote(car, rider)['status'], 'granted')
        self.set_command_receiver(device, False)
        self.assertEqual(self.member_remote(car, rider)['status'], 'none')
        self.set_command_receiver(device, True)
        self.assertEqual(self.member_remote(car, rider)['status'], 'granted')
        trip = car.split('/')[0]
        self.transition_trip(trip, driver, 'start')
        path = '/' + trip + '/vehicle-remotes'
        remote = self.trip(path, session=rider)[2]['remotes'][0]
        body = dict(eventId=secrets.token_hex(16), grantRevision=remote['grantRevision'], capabilityId='hvac.temperature',
            capabilityRevision=1, arguments=dict(seat='ROW_1_RIGHT', value=22))
        status, _, queued = self.trip(path + '/' + device['deviceId'] + '/commands', body, 'POST', session=rider)
        self.assertEqual(status, 201, queued)
        self.assertEqual(self.set_remote_policy(car, driver, enabled=False, actions=[])[0], 200)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(self.module.TEAM_FRIEND_CONTROLS.commands.load_request(conn, queued['id'])['stage'], 'cancelled')
        self.assertEqual(self.trip(path, session=rider)[2]['remotes'], [])

    def test_49_policy_actions_validation_and_encrypted_replacement(self):
        rider, driver, _, car, device = self.remote_setup()
        path = '/' + car + '/remote-policy'
        for actions in (None, {}, 'hvac.temperature', [], ['hvac.temperature']*2, ['steering.heat'], ['hvac.defroster'], [dict(id='hvac.temperature', revision=1)], [None]):
            with self.subTest(actions=actions):
                self.assertEqual(self.trip(path, dict(enabled=True, actions=actions), 'PUT', session=driver)[0], 400)
        first = self.set_remote_policy(car, driver, device)
        self.assertEqual(first[0], 200, first[2])
        self.assertEqual(self.set_remote_policy(car, driver, device, actions=['hvac.fan'])[0], 200)
        self.assertEqual(self.member_remote(car, rider)['actions'], self.display_remote_actions('hvac.fan'))
        with psycopg.connect(self.dsn) as conn:
            raw = conn.execute('SELECT protected FROM team_trip_cars WHERE car_id=%s', (car.split('/')[-1],)).fetchone()[0]
            self.assertNotIn(b'hvac.fan', bytes(raw))
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_remote_requests').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_remote_grants').fetchone()[0], 0)

    def test_50_policy_options_removed_from_registry_are_not_authority(self):
        rider, driver, _, car, device = self.remote_setup()
        self.assertEqual(self.set_remote_policy(car, driver, device, actions=['hvac.temperature', 'hvac.fan'])[0], 200)
        controls = self.module.TEAM_FRIEND_CONTROLS
        options = controls.options()
        with patch.object(controls, 'options', return_value=[item for item in options if item['id'] == 'hvac.fan']):
            self.assertEqual(self.member_remote(car, rider)['actions'], self.display_remote_actions('hvac.fan'))
            self.assertEqual(self.set_remote_policy(car, driver, device, actions=['hvac.temperature'])[0], 400)
            self.assertEqual(self.set_remote_policy(car, driver, device, actions=['hvac.fan'])[0], 200)
        with patch.object(controls, 'options', return_value=[]):
            self.assertEqual(self.member_remote(car, rider)['status'], 'none')

    def test_52_policy_revision_change_replaces_prior_command_authority(self):
        rider, driver, outsider, car, device = self.remote_setup()
        foreign = self.vehicle(outsider)
        self.assertEqual(self.set_remote_policy(car, driver, foreign)[0], 404)
        self.assertEqual(self.set_remote_policy(car, driver, device)[0], 200)
        trip = car.split('/')[0]
        self.transition_trip(trip, driver, 'start')
        path = '/' + trip + '/vehicle-remotes'
        remote = self.trip(path, session=rider)[2]['remotes'][0]
        command = dict(eventId=secrets.token_hex(16), grantRevision=remote['grantRevision'], capabilityId='hvac.temperature',
            capabilityRevision=1, arguments=dict(seat='ROW_1_RIGHT', value=22))
        command_path = path + '/' + device['deviceId'] + '/commands'
        status, _, queued = self.trip(command_path, command, 'POST', session=rider)
        self.assertEqual(status, 201, queued)
        self.assertEqual(self.set_remote_policy(car, driver, device, actions=['hvac.temperature', 'hvac.fan'])[0], 200)
        self.assertEqual(self.trip(command_path, dict(command, eventId=secrets.token_hex(16)), 'POST', session=rider)[0], 409)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(self.module.TEAM_FRIEND_CONTROLS.commands.load_request(conn, queued['id'])['stage'], 'cancelled')

    def test_66_ten_courses_idempotence_order_and_reuse_capacity(self):
        a, _, _ = self.sessions()
        trip = self.new_trip(a)
        packs = [self.published_course(a) for _ in range(11)]
        for pack in packs[:10]:
            self.assertEqual(self.attach(trip, pack, a)[0], 201)
        self.assertEqual(self.attach(trip, packs[0], a)[0], 200)
        result = self.attach(trip, packs[10], a)
        self.assertEqual((result[0], result[2]), (409, dict(detail='Trip course limit')))
        self.assertEqual([course['packId'] for course in self.trip('/' + trip, session=a)[2]['courses']], [pack['id'] for pack in packs[:10]])
        self.assertEqual(self.detach(trip, packs[0], a)[0], 200)
        self.assertEqual(self.attach(trip, packs[10], a)[0], 201)

    def test_shared_course_priority_preserves_legacy_order_and_rejects_stale_edits(self):
        owner, member, outsider = self.sessions()
        self.befriend(owner, member)
        trip = self.new_trip(owner, members=(member,))
        self.assertEqual(self.respond(trip, member)[0], 200)
        path = '/' + trip
        priority_path = path + '/courses/priority'
        first, second, third = [self.published_course(owner) for _ in range(3)]
        first_id, second_id, third_id = (pack['id'] for pack in (first, second, third))
        for pack in (first, second):
            self.assertEqual(self.attach(trip, pack, owner)[0], 201)
        device = self.vehicle(owner)
        self.vehicle(member)
        custom_car = self.new_car(trip, owner).rsplit('/', 1)[1]
        default_car = self.new_car(trip, member).rsplit('/', 1)[1]
        items = [dict(type='course', courseId=pack['id'], ref=pack['stops'][0]['id']) for pack in (first, second)]
        route_path = path + '/cars/' + custom_car + '/route-order'
        self.assertEqual(self.trip(route_path, dict(items=items), 'PUT', session=owner)[0], 200)
        detail = self.trip(path, session=owner)[2]
        self.assertEqual([course['packId'] for course in detail['courses']], [first_id, second_id])
        request = dict(packIds=[second_id, first_id], revision=detail['revision'])
        self.assertEqual(self.native('/v1/social/trips' + priority_path, request, 'PUT', device['accessToken'])[0], 403)
        self.assertEqual(self.trip(priority_path, request, 'PUT', session=owner, csrf=False)[0], 403)
        self.assertEqual(self.trip(priority_path, request, 'PUT', session=outsider)[0], 404)
        self.assertEqual(self.trip(priority_path, request, 'PUT', session=member)[0], 403)
        self.assertEqual(self.trip(priority_path, dict(request, packIds=[first_id, first_id]), 'PUT', session=owner)[0], 400)
        status, _, saved = self.trip(priority_path, request, 'PUT', session=owner)
        self.assertEqual((status, saved), (200, dict(status='updated', revision=detail['revision'] + 1)))
        saved_cars = {car['id']: car for car in self.trip(path, session=owner)[2]['cars']}
        self.assertEqual(saved_cars[custom_car]['routeOrder'], items)
        self.assertEqual(saved_cars[custom_car]['routeRevision'], 1)
        self.assertIsNone(saved_cars[default_car]['routeOrder'])
        self.assertEqual(saved_cars[default_car]['routeRevision'], 1)
        self.assertEqual(self.trip(priority_path, request, 'PUT', session=owner)[0], 409)
        self.assertEqual(self.attach(trip, third, owner)[0], 201)
        for actor in (owner, member):
            loaded = self.trip(path, session=actor)[2]
            self.assertEqual([course['packId'] for course in loaded['courses']], [second_id, first_id, third_id])
        self.assertEqual(self.trip(priority_path, dict(request, revision=loaded['revision']), 'PUT', session=owner)[0], 409)
        self.assertEqual(self.trip(path + '/start', dict(revision=loaded['revision']), 'POST', session=owner)[0], 200)
        self.assertEqual(self.trip(priority_path, dict(packIds=[third_id, second_id, first_id],
            revision=loaded['revision'] + 1), 'PUT', session=owner)[0], 409)

    def test_v6_creation_privacy_permissions_and_invitation_lifecycle(self):
        a, b, e = self.sessions()
        bid = b['user']['id']
        self.befriend(a, b)
        trip = self.new_trip(a, '  주말 여행  ', (b,))
        path = '/' + trip
        self.assertEqual(self.trip(session=b)[2]['invitations'], [dict(tripId=trip, title='주말 여행', ownerName='alice')])
        self.assertEqual(self.trip(path, session=b)[2], dict(detail='Trip unavailable'))
        self.assertEqual(self.trip(path, session=e)[0], 404)
        owner = self.trip(path, session=a)[2]
        self.assertEqual(set(owner), {'id','title','description','isOwner','ownerId','myPermissions','members','link','cars','unassigned','remoteOptions','remoteRequests','courses','startDate','endDate','state','revision','rideInvites','locationConsent','routeContractVersion','startConflict'})
        self.assertEqual(owner['routeContractVersion'],1)
        self.assertEqual(owner['startConflict'], dict(activeTrips=[], busyMemberIds=[]))
        self.assertEqual(owner['myPermissions'], dict(invite=True, edit=True))
        self.assertEqual(owner['link'], dict(active=False, expiresAt=None))
        self.assertEqual(owner['members'][0]['id'], a['user']['id'])
        self.assertEqual(owner['members'][1]['state'], 'pending')
        self.assertEqual(self.rights(trip, a, b, invite=True)[2], dict(detail='Account unavailable'))
        self.assertEqual(self.invite(trip, a, b)[0], 200)
        self.assertEqual(self.respond(trip, b)[2], dict(status='accepted'))
        self.assertEqual(self.respond(trip, b)[0], 200)
        self.assertEqual(self.invite(trip, a, b)[2], dict(status='accepted'))
        self.assertEqual(self.trip(path, session=b)[2]['myPermissions'], dict(invite=False, edit=False))
        self.assertIsNone(self.trip(path, session=b)[2]['link'])
        self.assertTrue(all(item['permissions'] is None for item in self.trip(path, session=b)[2]['members']))
        self.assertEqual(self.trip(path, dict(title='수정', description=''), 'PATCH', session=b)[2], dict(detail='Trip edit permission required'))
        self.assertEqual(self.trip(path + '/link', method='POST', session=b)[2], dict(detail='Trip invite permission required'))
        self.assertEqual(self.rights(trip, b, a, invite=True)[0], 403)
        self.assertEqual(self.rights(trip, a, a, edit=True)[0], 404)
        self.assertEqual(self.rights(trip, a, b, edit=True)[2], dict(status='updated'))
        self.assertEqual(self.trip(path, dict(title='  바다  ', description='  첫날\n둘째날  '), 'PATCH', session=b)[2], dict(status='updated'))
        self.assertEqual(self.trip(path, session=a)[2]['description'], '첫날\n둘째날')
        self.assertEqual(self.trip(path + '/link', method='POST', session=b)[0], 403)
        self.befriend(b, e, 'eve')
        self.assertEqual(self.invite(trip, b, e)[0], 403)
        self.assertEqual(self.rights(trip, a, b, invite=True)[0], 200)
        self.assertEqual(self.invite(trip, b, e)[0], 201)
        self.assertEqual(len(self.trip(path, session=b)[2]['members']), 3)
        self.assertEqual(self.rights(trip, a, b)[0], 200)
        self.assertEqual(len(self.trip(path, session=b)[2]['members']), 2)
        self.assertEqual(self.respond(trip, e, False)[2], dict(status='declined'))
        self.assertEqual(self.invite(trip, a, e)[2], dict(detail='Account unavailable'))
        self.assertEqual(self.trip(path, method='DELETE', session=b)[2], dict(detail='Only the owner may manage the trip'))
        self.assertEqual(self.trip(path + '/members/' + a['user']['id'], method='DELETE', session=a)[2], dict(detail='Finish or cancel the trip instead'))
        before = self.revision(b)
        self.assertEqual(self.trip(path + '/members/' + bid, method='DELETE', session=b)[2], dict(status='removed'))
        self.assertGreater(self.revision(b), before)
        self.assertEqual(self.trip(path, session=b)[0], 404)
        self.assertEqual(self.trip(path, method='DELETE', session=a)[0], 409)
        self.close_trip(trip, a)
        self.assertEqual(self.trip(path, method='DELETE', session=a)[2], dict(status='deleted'))

    def start(self, trip, session, **extra):
        revision = self.trip('/' + trip, session=session)[2]['revision']
        return self.trip('/' + trip + '/start', dict(revision=revision, **extra), 'POST', session=session)

    def state(self, trip):
        with psycopg.connect(self.dsn) as conn:
            return conn.execute('SELECT state FROM team_trips WHERE trip_id=%s', (trip,)).fetchone()[0]

    def test_single_active_trip_per_person_owner_conflict_and_end_then_start(self):
        a, b, _ = self.sessions()
        self.befriend(a, b)
        first = self.new_trip(a, '첫 여행', (b,))
        self.assertEqual(self.respond(first, b)[0], 200)
        self.assertEqual(self.start(first, a)[0], 200)
        second = self.new_trip(a, '다음 여행', (b,))
        self.assertEqual(self.respond(second, b)[0], 200)
        detail = self.trip('/' + second, session=a)[2]
        # bob is busy only in alice's own active trip, so ending it frees him as well.
        self.assertEqual(detail['startConflict'], dict(activeTrips=[dict(tripId=first, title='첫 여행', isOwner=True)], busyMemberIds=[]))
        self.assertIsNone(self.trip('/' + second, session=b)[2]['startConflict'])
        self.assertIsNone(self.trip('/' + first, session=a)[2]['startConflict'])
        before = detail['revision']
        status, _, result = self.start(second, a)
        self.assertEqual((status, result), (409, dict(detail='TRIP_ALREADY_ACTIVE')))
        self.assertEqual((self.state(first), self.state(second)), ('active', 'planned'))
        self.assertEqual(self.trip('/' + second, session=a)[2]['revision'], before)
        for invalid in ('yes', 1, None):
            self.assertEqual(self.start(second, a, endActiveTrip=invalid)[0], 400)
        revision = self.trip('/' + first, session=a)[2]['revision']
        self.assertEqual(self.trip('/' + first + '/finish', dict(revision=revision, endActiveTrip=True), 'POST', session=a)[0], 400)
        status, _, result = self.start(second, a, endActiveTrip=True)
        self.assertEqual((status, result['state']), (200, 'active'), result)
        self.assertEqual((self.state(first), self.state(second)), ('completed', 'active'))
        with psycopg.connect(self.dsn) as conn:
            closed = conn.execute('SELECT closed_at IS NOT NULL FROM team_rooms WHERE trip_id=%s', (first,)).fetchone()[0]
        self.assertTrue(closed)
        self.assertEqual(self.trip('/' + second + '/start', dict(revision=before, endActiveTrip=True), 'POST', session=a)[2]['state'], 'active')

    def test_single_active_trip_member_conflicts_and_leaving_as_participant(self):
        a, b, e = self.sessions()
        self.befriend(a, b)
        self.befriend(e, b, 'bob')
        self.befriend(a, e, 'eve')
        others = self.new_trip(e, '이브 여행', (b,))
        self.assertEqual(self.respond(others, b)[0], 200)
        self.assertEqual(self.start(others, e)[0], 200)
        mine = self.new_trip(a, '앨리스 여행', (b,))
        self.assertEqual(self.respond(mine, b)[0], 200)
        detail = self.trip('/' + mine, session=a)[2]
        self.assertEqual(detail['startConflict'], dict(activeTrips=[], busyMemberIds=[b['user']['id']]))
        self.assertEqual(self.start(mine, a)[2], dict(detail='TRIP_MEMBER_ALREADY_ACTIVE'))
        self.assertEqual(self.start(mine, a, endActiveTrip=True)[2], dict(detail='TRIP_MEMBER_ALREADY_ACTIVE'))
        self.assertEqual(self.state(mine), 'planned')
        # A participant starting their own trip leaves the other active trip instead of finishing it.
        own = self.new_trip(b, '밥 여행')
        self.assertEqual(self.trip('/' + own, session=b)[2]['startConflict'],
            dict(activeTrips=[dict(tripId=others, title='이브 여행', isOwner=False)], busyMemberIds=[]))
        self.assertEqual(self.start(own, b)[2], dict(detail='TRIP_ALREADY_ACTIVE'))
        self.assertEqual(self.start(own, b, endActiveTrip=True)[0], 200)
        self.assertEqual((self.state(others), self.state(own)), ('active', 'active'))
        self.assertEqual(self.trip('/' + others, session=b)[0], 404)
        self.assertEqual([m['id'] for m in self.trip('/' + others, session=e)[2]['members']], [e['user']['id']])
        # Joining a running trip requires leaving the current one first; planned trips stay open.
        self.assertEqual(self.trip('/' + mine + '/members/' + b['user']['id'], method='DELETE', session=a)[0], 200)
        self.assertEqual(self.start(mine, a)[0], 200)
        self.assertEqual(self.invite(mine, a, b)[0], 201)
        self.assertEqual(self.respond(mine, b)[2], dict(detail='TRIP_ALREADY_ACTIVE'))
        token = self.trip('/' + mine + '/link', method='POST', session=a)[2]['token']
        self.assertEqual(self.link_request('trip', token, b, action='/join')[2], dict(detail='TRIP_ALREADY_ACTIVE'))
        planned = self.new_trip(a, '다음 계획', (b,))
        self.assertEqual(self.respond(planned, b)[2], dict(status='accepted'))
        self.assertEqual(self.trip('/' + planned, session=a)[2]['startConflict'],
            dict(activeTrips=[dict(tripId=mine, title='앨리스 여행', isOwner=True)], busyMemberIds=[b['user']['id']]))
        self.assertEqual(self.start(planned, a, endActiveTrip=True)[2], dict(detail='TRIP_MEMBER_ALREADY_ACTIVE'))
        self.assertEqual(self.state(mine), 'active')

    def test_v6_strict_fields_limits_and_browser_auth(self):
        a, b, _ = self.sessions()
        data = dict(title='여행', description='', memberIds=[])
        self.assertEqual(self.trip()[0], 401)
        for options in (dict(csrf=False), dict(origin='https://wrong.invalid')):
            self.assertEqual(self.trip(data=data, method='POST', session=a, **options)[0], 403)
        for changes in (dict(title=''), dict(title='x'*41), dict(title='x\n'), dict(description='x'*301),
                dict(description='x\t'), dict(description=None), dict(memberIds=None), dict(memberIds=[{}]),
                dict(memberIds=['team-'+'f'*40]*2), dict(memberIds=['team-'+'f'*40]*20), dict(extra=True)):
            with self.subTest(changes=changes):
                self.assertEqual(self.trip(data=dict(data, **changes), method='POST', session=a)[0], 400)
        self.assertEqual(self.trip(data=dict(data, memberIds=[b['user']['id']]), method='POST', session=a)[2], dict(detail='Account unavailable'))
        self.assertEqual(self.trip(data=dict(data, memberIds=[a['user']['id']]), method='POST', session=a)[0], 404)
        trip = self.new_trip(a, 'x'*40)
        self.assertEqual(self.trip('/' + trip, raw=b'{"title":"a","title":"b","description":""}', method='PATCH', session=a)[0], 400)
        self.assertEqual(self.trip('/' + trip, raw=b'x'*4097, method='PATCH', session=a)[0], 413)
        for _ in range(19):
            self.new_trip(a)
        self.assertEqual(self.trip(data=data, method='POST', session=a)[2], dict(detail='Trip limit reached'))
        self.assertEqual(self.trip('/' + trip, method='DELETE', data={'extra':True}, session=a)[0], 400)
        self.assertEqual(self.trip('/' + trip + '/respond', dict(accept=1), 'POST', session=a)[2], dict(detail='Choose a response'))
        self.assertEqual(self.rights(trip, a, b, invite=1)[2], dict(detail='Invalid permissions'))
        _, _, device = self.pair(a)
        self.assertEqual(self.native('/v1/social/trips', token=device['accessToken'])[0], 200)
        self.assertEqual(self.call('/v1/devices/' + device['deviceId'] + '/functional-permissions/rooms:read',
            method='DELETE', session=a)[0], 200)
        for path, method, expected in (('/trips','GET',200), ('/trip-links/preview','POST',403), ('/friend-link','POST',404), ('/friend-links/preview','POST',404)):
            self.assertEqual(self.native('/v1/social'+path, method=method, token=device['accessToken'])[0], expected)
        from team_auth import hashed
        with psycopg.connect(self.dsn) as conn:
            conn.execute('UPDATE team_rate_limits SET hits=60,bucket=%s WHERE scope_hash=%s',
                (int(time.time())//60, hashed('trip-mutate:'+a['user']['id'])))
        result=self.trip('/'+trip, dict(title='제한',description=''), 'PATCH',session=a)
        self.assertEqual(result[0],429)
        self.assertEqual(result[1]['retry-after'],'60')

    def test_v6_trip_link_hash_replace_revoke_expiry_pending_and_block(self):
        a, b, e = self.sessions()
        self.befriend(a, b)
        trip = self.new_trip(a, members=(b,))
        path = '/' + trip
        issued = self.trip(path + '/link', method='POST', session=a)
        self.assertEqual(issued[0], 201)
        token = issued[2]['token']
        preview = self.link_request('trip', token, b, action='preview')
        self.assertEqual(preview[2], dict(tripId=trip, title='우리 여행', description='', ownerName='alice', memberCount=1,
            expiresAt=issued[2]['expiresAt'], alreadyMember=False))
        with psycopg.connect(self.dsn) as conn:
            digest, owner, expires, now = conn.execute('SELECT token_sha256,created_by,expires_at,clock_timestamp() FROM team_trip_links WHERE trip_id=%s', (trip,)).fetchone()
            self.assertEqual(digest, hashlib.sha256(token.encode()).hexdigest())
            self.assertNotEqual(digest, token)
            self.assertEqual(owner, a['user']['id'])
            self.assertTrue(604790 < (expires-now).total_seconds() <= 604800)
        self.assertEqual(self.link_request('trip', token, b, action='/join')[2], dict(tripId=trip))
        self.assertEqual(self.link_request('trip', token, b, action='/join')[0], 200)
        self.assertTrue(self.link_request('trip', token, b, action='preview')[2]['alreadyMember'])
        self.assertEqual(self.trip(path, session=a)[2]['members'][1]['via'], 'link')
        self.assertEqual(self.link_request('trip', token, e, action='/join')[0], 200)
        self.assertEqual(self.social('/overview', e)[2]['friends'], [])
        new = self.trip(path + '/link', method='POST', session=a)[2]['token']
        self.assertNotEqual(token, new)
        self.assertEqual(self.link_request('trip', token, b, action='preview')[2], dict(detail='Link unavailable'))
        self.assertEqual(self.trip(path + '/link', method='DELETE', session=a)[2], dict(status='revoked'))
        self.assertEqual(self.link_request('trip', new, b, action='/join')[0], 404)
        token=self.trip(path+'/link',method='POST',session=a)[2]['token']
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE team_trip_links SET expires_at=clock_timestamp()-interval '1 second' WHERE trip_id=%s",(trip,))
        self.assertFalse(self.trip(path, session=a)[2]['link']['active'])
        for suffix, method in (('', 'GET'), ('/join', 'POST')):
            self.assertEqual(self.link_request('trip', token, b, action=suffix)[2], dict(detail='Link unavailable'))
        token=self.trip(path+'/link',method='POST',session=a)[2]['token']
        self.assertEqual(self.social('/blocks',a,dict(targetId=b['user']['id']),'POST')[0],201)
        self.assertEqual(self.link_request('trip', token, b, action='preview')[0],404)
        self.assertEqual(self.link_request('trip', token, b, action='/join')[0],404)
        self.assertEqual(self.trip(path,session=b)[0],404)
        self.assertEqual(self.link_request('trip', 'unknown', e, action='preview')[2], dict(detail='Link unavailable'))

    def test_v6_friend_links_and_trip_friend_requests_without_search(self):
        a, b, e = self.sessions()
        trip = self.new_trip(a)
        self.join(trip,a,b)
        path='/'+trip
        before=self.trip(path,session=b)[2]['members'][0]
        self.assertFalse(before['isFriend']);self.assertEqual(before['friendRequest'],'none')
        self.assertEqual(self.request_friend(b,a,'bob')[0],201)
        self.assertEqual(self.trip(path,session=b)[2]['members'][0]['friendRequest'],'sent')
        peer=next(m for m in self.trip(path,session=a)[2]['members'] if m['id']==b['user']['id'])
        self.assertEqual(peer['friendRequest'],'received')
        issued=self.social('/friend-link',a,method='POST')
        self.assertEqual(issued[0],201)
        token=issued[2]['token']
        self.assertEqual(self.link_request('friend', token, b, action='preview')[2],dict(ownerName='alice',expiresAt=issued[2]['expiresAt'],alreadyFriends=False))
        with psycopg.connect(self.dsn) as conn:
            digest,expires,now=conn.execute('SELECT token_sha256,expires_at,clock_timestamp() FROM team_friend_links WHERE account_id=%s',(a['user']['id'],)).fetchone()
            self.assertEqual(digest,hashlib.sha256(token.encode()).hexdigest())
            self.assertTrue(604790 < (expires-now).total_seconds() <= 604800)
        self.assertEqual(self.link_request('friend', token, a, action='/accept')[2],dict(detail='Link unavailable'))
        self.assertEqual(self.link_request('friend', token, b, action='/accept')[2],dict(status='accepted'))
        self.assertEqual(self.link_request('friend', token, b, action='/accept')[0],200)
        self.assertEqual(self.link_request('friend', token, e, action='/accept')[0],200)
        self.assertTrue(self.link_request('friend', token, b, action='preview')[2]['alreadyFriends'])
        peer=self.trip(path,session=b)[2]['members'][0]
        self.assertTrue(peer['isFriend']);self.assertEqual(peer['friendRequest'],'none')
        new=self.social('/friend-link',a,method='POST')[2]['token']
        self.assertEqual(self.link_request('friend', token, b, action='preview')[0],404)
        self.assertEqual(self.social('/friend-link',a,method='DELETE')[2],dict(status='revoked'))
        self.assertEqual(self.link_request('friend', new, b, action='preview')[0],404)
        token=self.social('/friend-link',a,method='POST')[2]['token']
        with psycopg.connect(self.dsn) as conn:
            conn.execute('UPDATE team_friend_links SET expires_at=clock_timestamp() WHERE account_id=%s',(a['user']['id'],))
        self.assertEqual(self.link_request('friend', token, b, action='preview')[0],404)
        token=self.social('/friend-link',a,method='POST')[2]['token']
        self.social('/blocks',b,dict(targetId=a['user']['id']),'POST')
        self.assertEqual(self.link_request('friend', token, b, action='preview')[0],404)
        self.assertEqual(self.link_request('friend', token, b, action='/accept')[0],404)
        self.assertEqual(self.trip(path,session=b)[0],404)
    def test_v6_cars_seats_movement_and_driver_creation(self):
        a,b,e=self.sessions()
        trip=self.new_trip(a)
        self.join(trip,a,b);self.join(trip,a,e)
        path='/'+trip
        self.assertEqual(self.trip(path+'/cars',dict(name='차',seats=2),'POST',session=a)[2],dict(detail='Vehicle owner required'))
        self.vehicle(a)
        car=self.new_car(trip,a,seats=1)
        self.assertEqual(self.trip(path+'/cars',dict(name='두번째',seats=2),'POST',session=a)[2],dict(detail='Already driving'))
        for seats in (0,9,True,'2',None):
            self.assertEqual(self.trip('/'+car,dict(name='차',seats=seats),'PATCH',session=a)[2],dict(detail='Invalid seats'))
        self.assertEqual(self.trip('/'+car,dict(name='x'*21,seats=2),'PATCH',session=a)[2],dict(detail='Invalid car name'))
        self.assertEqual(self.ride(car,a)[2],dict(detail='Already driving'))
        self.assertEqual(self.ride(car,b)[2],dict(status='riding'))
        self.assertEqual(self.ride(car,b)[0],200)
        self.assertEqual(self.ride(car,e)[2],dict(detail='Car is full'))
        self.assertEqual(self.trip('/'+car,dict(name='넓은 차',seats=2),'PATCH',session=b)[0],403)
        self.assertEqual(self.trip('/'+car,dict(name='넓은 차',seats=2),'PATCH',session=a)[2],dict(status='updated'))
        self.assertEqual(self.ride(car,e)[0],200)
        self.assertEqual(self.trip('/'+car,dict(name='작은 차',seats=1),'PATCH',session=a)[2],dict(detail='Seats taken'))
        self.vehicle(b)
        other=self.new_car(trip,b,seats=1)
        detail=self.trip(path,session=a)[2]
        self.assertEqual(len(detail['cars'][0]['passengers']),1)
        self.assertEqual(self.ride(other,e)[0],200)
        detail=self.trip(path,session=e)[2]
        self.assertEqual([c['id'] for c in detail['cars'] if c['iRide']],[other.split('/')[-1]])
        self.assertEqual(self.trip('/'+other,method='DELETE',session=e)[0],403)
        self.assertEqual(self.trip('/'+other,dict(name='방장 수정',seats=2),'PATCH',session=a)[0],403)
        self.assertEqual(self.trip('/'+other,method='DELETE',session=a)[2],dict(status='deleted'))
        self.assertEqual({p['id'] for p in self.trip(path,session=a)[2]['unassigned']},{b['user']['id'],e['user']['id']})
        self.assertEqual(self.ride(car,e)[0],200)
        self.assertEqual(self.trip(path+'/ride',method='DELETE',session=e)[2],dict(status='left'))
        self.assertEqual(self.trip('/'+car,method='DELETE',session=a)[0],200)
        self.assertEqual(len(self.trip(path,session=a)[2]['unassigned']),3)

    def test_v6_live_vehicle_classification(self):
        a,b,_=self.sessions()
        self.befriend(a,b)
        trip=self.new_trip(a)
        self.join(trip,a,b)
        _,_,device=self.pair(b,'bob')
        self.assertEqual(self.trip('/'+trip+'/cars',dict(name='차',seats=2),'POST',session=b)[2],dict(detail='Vehicle owner required'))
        self.assertEqual(self.call('/v1/devices/'+device['deviceId']+'/vehicle-profile',dict(plateNumber='123가4567',name='',expectedRevision=0),'PUT',session=b,who='bob')[0],200)
        car=self.new_car(trip,b)
        self.assertTrue(self.social('/overview',a)[2]['friends'][0]['hasVehicle'])
        self.assertEqual(self.ride(car,a)[0],200)
        for mutation in ('expiry','slot','revoke'):
            with self.subTest(mutation=mutation),psycopg.connect(self.dsn) as conn:
                key,grant,expiry=conn.execute('SELECT installation_key_id,grant_id,expires_at FROM native_v2_grants WHERE device_id=%s',(device['deviceId'],)).fetchone()
                if mutation=='expiry':conn.execute('UPDATE native_v2_grants SET expires_at=1 WHERE grant_id=%s',(grant,))
                elif mutation=='slot':conn.execute('UPDATE native_v2_installations SET active_grant_id=NULL WHERE installation_key_id=%s',(key,))
                else:conn.execute('UPDATE native_v2_installations SET revoked_at=1 WHERE installation_key_id=%s',(key,))
            detail=self.trip('/'+trip,session=a)[2]
            self.assertFalse(next(m for m in detail['members'] if m['id']==b['user']['id'])['hasVehicle'])
            self.assertFalse(self.social('/overview',a)[2]['friends'][0]['hasVehicle'])
            self.assertFalse(detail['cars'][0]['driverVehicleReady'])
            self.assertIsNone(detail['cars'][0]['remote'])
            self.assertNotIn('123가4567',json.dumps(detail,ensure_ascii=False))
            self.assertNotIn('plateNumber',json.dumps(detail))
            with psycopg.connect(self.dsn) as conn:
                conn.execute('UPDATE native_v2_grants SET expires_at=%s WHERE grant_id=%s',(expiry,grant))
                conn.execute('UPDATE native_v2_installations SET active_grant_id=%s,revoked_at=NULL WHERE installation_key_id=%s',(grant,key))

    def test_v6_capacity_pending_links_and_race(self):
        from account_handles import create_account
        a,b,e=self.sessions()
        self.befriend(a,b);self.befriend(a,e,'eve')
        trip=self.new_trip(a,members=(b,))
        with psycopg.connect(self.dsn) as conn:
            for _ in range(18):
                account='team-'+secrets.token_hex(20)
                create_account(conn,account,VisitCipher().protect('team-account:'+account,'identity',dict(email='synthetic@example.invalid')))
                self.module.TEAM_TRIPS.save_member(conn,trip,account)
        token=self.trip('/'+trip+'/link',method='POST',session=a)[2]['token']
        self.assertEqual(self.invite(trip,a,b)[0],200)
        self.assertEqual(self.invite(trip,a,e)[2],dict(detail='Trip is full'))
        self.assertEqual(self.link_request('trip', token, e, action='/join')[2],dict(detail='Trip is full'))
        self.assertEqual(self.link_request('trip', token, b, action='/join')[0],200)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_members WHERE trip_id=%s',(trip,)).fetchone()[0],20)
        trip=self.new_trip(a)
        token=self.trip('/'+trip+'/link',method='POST',session=a)[2]['token']
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls=[pool.submit(self.link_request,'trip',token,b,action='join') for _ in range(2)]
            self.assertEqual([c.result()[0] for c in calls],[200,200])
        self.join(trip,a,e)
        self.vehicle(a)
        car=self.new_car(trip,a,seats=1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls=[pool.submit(self.ride,car,p) for p in (b,e)]
            self.assertEqual(sorted(c.result()[0] for c in calls),[200,409])
        self.assertEqual(len(self.trip('/'+trip,session=a)[2]['cars'][0]['passengers']),1)

    def test_v6_remote_car_scope_friendship_and_cleanup(self):
        rider, driver, outsider, car, device = self.remote_setup()
        trip = car.split('/')[0]
        self.join(trip, driver, outsider)
        self.assertEqual(self.set_remote_policy(car, driver, device)[0], 200)
        self.ride(car, outsider)
        self.assertEqual(self.member_remote(car, outsider)['status'], 'none')
        self.assertEqual(self.member_remote(car, rider)['status'], 'granted')
        self.assertEqual(self.trip('/' + trip + '/ride', method='DELETE', session=rider)[0], 200)
        self.assertIsNone(self.member_remote(car, rider))
        self.ride(car, rider)
        self.assertEqual(self.member_remote(car, rider)['status'], 'granted')
        self.assertEqual(self.social('/friends/' + driver['user']['id'], rider, method='DELETE')[0], 200)
        self.assertEqual(self.trip('/' + trip, session=rider)[0], 200)
        self.assertEqual(self.member_remote(car, rider)['status'], 'none')
        self.assertEqual(self.trip('/' + trip, session=driver)[2]['remoteRequests'], [])

    def test_v6_block_visibility_owner_cleanup_and_friendship_preserved_membership(self):
        a,b,e=self.sessions()
        trip=self.new_trip(a)
        self.join(trip,a,b);self.join(trip,a,e)
        self.vehicle(b)
        car=self.new_car(trip,b)
        self.ride(car,e)
        self.assertEqual(self.social('/blocks',e,dict(targetId=b['user']['id']),'POST')[0],201)
        for viewer,hidden in ((b,e),(e,b)):
            detail=self.trip('/'+trip,session=viewer)[2]
            self.assertNotIn(hidden['user']['id'],json.dumps(detail))
        self.assertEqual(len(self.trip('/'+trip,session=a)[2]['members']),3)
        self.assertEqual(self.trip('/'+trip,session=e)[2]['cars'],[])
        self.assertEqual(self.social('/blocks',a,dict(targetId=b['user']['id']),'POST')[0],201)
        detail=self.trip('/'+trip,session=a)[2]
        self.assertEqual(detail['cars'],[])
        self.assertIn(e['user']['id'],[p['id'] for p in detail['unassigned']])
        self.assertEqual(self.trip('/'+trip,session=b)[0],404)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_riders WHERE trip_id=%s',(trip,)).fetchone()[0],0)

    def test_v6_courses_permissions_review_visibility_and_member_cleanup(self):
        a,b,e=self.sessions()
        trip=self.new_trip(a)
        self.join(trip,a,b);self.join(trip,a,e)
        pack=self.published_course(b,'bob')
        self.assertEqual(self.attach(trip,pack,b)[0],201)
        self.assertEqual(self.attach(trip,pack,a)[0],200)
        item=self.trip('/'+trip,session=a)[2]['courses'][0]
        self.assertEqual(item['title'],pack['title'])
        self.assertTrue(item['canRemove']);self.assertFalse(item['mine']);self.assertTrue(item['reviewed'])
        self.assertEqual(self.trip('/'+trip,session=b)[2]['courses'][0]['title'],pack['title'])
        self.assertEqual(self.detach(trip,pack,e)[0],403)
        self.approve(pack,a)
        self.assertTrue(self.trip('/'+trip,session=e)[2]['courses'][0]['reviewed'])
        pack['version']=2;pack['title']='새 비공개 제목'
        self.assertEqual(self.publish(pack,b,'bob')[0],201)
        self.assertEqual(self.trip('/'+trip,session=e)[2]['courses'][0]['title'],pack['title'])
        self.rights(trip,a,b)
        self.assertEqual(self.detach(trip,pack,b)[0],200)
        self.rights(trip,a,b,edit=True);self.attach(trip,pack,b)
        self.rights(trip,a,e,edit=True)
        self.assertEqual(self.detach(trip,pack,e)[0],200)
        self.attach(trip,pack,b)
        self.assertEqual(self.trip('/'+trip+'/members/'+b['user']['id'],method='DELETE',session=a)[0],200)
        self.assertEqual(self.trip('/'+trip,session=a)[2]['courses'],[])
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_courses WHERE trip_id=%s',(trip,)).fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM pack_versions WHERE pack_id=%s',(pack['id'],)).fetchone()[0],2)

    def test_public_approved_course_can_be_attached_without_exposing_later_drafts(self):
        owner, creator, member = self.sessions()
        trip = self.new_trip(owner)
        self.join(trip, owner, member)
        pack = self.published_course(creator, 'bob')
        self.assertEqual(self.attach(trip, pack, member)[0], 201)
        self.assertEqual(self.attach(trip, pack, owner)[0], 200)
        self.assertEqual(self.trip('/'+trip, session=owner)[2]['courses'][0]['title'], pack['title'])
        draft = dict(pack, version=2, title='비공개 다음 버전')
        self.assertEqual(self.publish(draft, creator, 'bob')[0], 201)
        self.assertEqual(self.call(f"/v1/packs/{pack['id']}/versions/2/reports", dict(reason='privacy'), 'POST', session=owner)[0], 202)
        shown = self.trip('/'+trip, session=owner)[2]['courses'][0]
        self.assertEqual((shown['version'], shown['title']), (1, pack['title']))
        self.assertTrue(shown['reviewed'])
        self.approve(draft, owner)
        self.assertEqual(self.trip('/'+trip, session=owner)[2]['courses'][0]['version'], 2)

    def test_planned_trip_waypoints_preserve_source_and_driver_route(self):
        owner, creator, member = self.sessions()
        trip = self.new_trip(owner)
        self.join(trip, owner, member)
        pack = self.published_course(creator, 'bob')
        self.assertEqual(self.attach(trip, pack, owner)[0], 201)
        device = self.vehicle(owner)
        car = self.new_car(trip, owner)
        place = dict(kind='pickup', name='모이는 곳', lat=37.51, lng=127.01)
        pickup = self.trip('/' + car + '/places', place, 'POST', session=owner)[2]['id']
        order = [dict(type='pickup', ref=pickup)] + [
            dict(type='course', courseId=pack['id'], ref=stop['id']) for stop in pack['stops']]
        route_path = '/' + car + '/route-order'
        self.assertEqual(self.trip(route_path, dict(items=order), 'PUT', session=owner)[0], 200)
        baseline = self.trip('/' + trip, session=owner)[2]
        original = baseline['courses'][0]['stops']
        revision = baseline['cars'][0]['routeRevision']
        path = '/' + trip + '/waypoints'
        request = dict(packId=pack['id'], name='전시관', lat=37.53, lng=127.03)
        self.assertEqual(self.trip(path, request, 'POST', session=member)[0], 403)
        self.assertEqual(self.trip(path, request, 'POST', session=creator)[0], 404)
        self.assertEqual(self.trip(path, dict(request, lat=True), 'POST', session=owner)[0], 400)
        status, headers, first = self.trip(path, request, 'POST', session=owner)
        self.assertEqual(status, 201, first)
        self.assertEqual(headers['cache-control'], 'private, no-store')
        duplicate = self.trip(path, request, 'POST', session=owner)
        self.assertEqual((duplicate[0], duplicate[2]), (200, first))
        result = self.trip(path, dict(request, name='전망대'), 'POST', session=owner)
        self.assertEqual(result[0], 201, result[2])
        second = result[2]
        projection = self.trip('/' + trip + '?section=route', session=owner)[2]
        expected_order = order[:-1] + [dict(type='course', courseId=pack['id'], ref=point['id'])
            for point in (first, second)] + order[-1:]
        self.assertEqual(projection['courses'][0]['stops'], original[:-1] + [first, second] + original[-1:])
        self.assertEqual(projection['cars'][0]['routeOrder'], expected_order)
        self.assertEqual(projection['cars'][0]['routeRevision'], revision + 2)
        self.assertEqual(self.trip(route_path, dict(items=order, routeRevision=revision), 'PUT', session=owner)[0], 409)
        source = self.call(f"/v1/packs/{pack['id']}/versions/1", session=owner)[2]
        self.assertEqual([stop['id'] for stop in source['stops']], [stop['id'] for stop in original])
        with psycopg.connect(self.dsn) as conn:
            raw, = conn.execute('SELECT waypoints FROM team_trip_courses WHERE trip_id=%s', (trip,)).fetchone()
            self.assertNotIn(request['name'].encode(), bytes(raw))
        native = self.native('/v1/native/trips/' + trip + '?section=route', token=device['accessToken'])
        self.assertEqual(native[0], 200, native[2])
        self.assertEqual(native[2]['cars'][0]['routeOrder'], expected_order)
        delete = path + '/' + pack['id'] + '/' + first['id']
        self.assertEqual(self.trip(delete, method='DELETE', session=owner)[0], 200)
        self.assertEqual(self.trip('/' + trip, session=owner)[2]['courses'][0]['waypoints'], [second])
        self.close_trip(trip, owner)
        self.assertEqual(self.trip(path, request, 'POST', session=owner)[0], 409)

    def test_waypoint_capacity_includes_future_cars(self):
        owner, creator, _ = self.sessions()
        trip = self.new_trip(owner)
        first, *others = [self.published_course(creator, 'bob') for _ in range(10)]
        self.assertEqual(self.attach(trip, first, owner)[0], 201)
        path = '/' + trip + '/waypoints'
        request = dict(packId=first['id'], name='전시관', lat=37.53, lng=127.03)
        status, _, waypoint = self.trip(path, request, 'POST', session=owner)
        self.assertEqual(status, 201, waypoint)
        for pack in others[:-1]:
            self.assertEqual(self.attach(trip, pack, owner)[0], 201)
        status, _, body = self.attach(trip, others[-1], owner)
        self.assertEqual((status, body), (409, dict(detail='Trip route limit reached')))
        delete = path + '/' + first['id'] + '/' + waypoint['id']
        self.assertEqual(self.trip(delete, method='DELETE', session=owner)[0], 200)
        self.assertEqual(self.attach(trip, others[-1], owner)[0], 201)
        status, _, body = self.trip(path, request, 'POST', session=owner)
        self.assertEqual((status, body), (409, dict(detail='Trip route limit reached')))
        detail = self.trip('/' + trip, session=owner)[2]
        self.assertEqual(len(detail['courses']), 10)
        self.assertTrue(all(not course['waypoints'] for course in detail['courses']))

    def test_trip_cipher_and_closed_trip_soft_delete(self):
        a,b,_,car,_=self.remote_setup()
        trip=car.split('/')[0]
        request=self.seed_legacy_remote(car,a)
        pack=self.published_course(b,'bob');self.attach(trip,pack,b)
        self.trip('/'+trip+'/link',method='POST',session=b)
        service=self.module.TEAM_TRIPS
        with psycopg.connect(self.dsn) as conn:
            raw=conn.execute('SELECT protected FROM team_trips WHERE trip_id=%s',(trip,)).fetchone()[0]
            self.assertEqual(service.restore('owner:'+b['user']['id'],trip,raw),dict(title='우리 여행',description=''))
            raw=conn.execute('SELECT protected FROM team_trip_cars WHERE trip_id=%s',(trip,)).fetchone()[0]
            self.assertNotIn('우리 차'.encode(),bytes(raw))
            self.assertNotIn(b'seats',bytes(raw))
            raw=conn.execute('SELECT protected FROM team_trip_members WHERE trip_id=%s AND account_id=%s',(trip,a['user']['id'])).fetchone()[0]
            for word in (b'accepted',b'permissions',b'invite',b'friend'):
                self.assertNotIn(word,bytes(raw))
            raw=conn.execute('SELECT protected FROM team_trip_remote_requests WHERE request_id=%s',(request,)).fetchone()[0]
            for secret in (a['user']['id'],b['user']['id'],'hvac.temperature',car.split('/')[-1]):
                self.assertNotIn(secret.encode(),bytes(raw))
            value=service.restore('remote-request:'+request,trip,raw)
            self.assertEqual(value['carId'],car.split('/')[-1])
        before=self.revision(a)
        self.assertEqual(self.trip('/'+trip,method='DELETE',session=b)[0],409)
        self.close_trip(trip, b)
        self.assertEqual(self.trip('/'+trip,method='DELETE',session=b)[0],200)
        self.assertGreater(self.revision(a),before)
        with psycopg.connect(self.dsn) as conn:
            for table in ('team_trip_links','team_trip_remote_requests'):
                self.assertEqual(conn.execute('SELECT count(*) FROM '+table+' WHERE trip_id=%s',(trip,)).fetchone()[0],0)
            for table in ('team_trip_members','team_trip_cars','team_trip_riders','team_trip_courses'):
                self.assertGreater(conn.execute('SELECT count(*) FROM '+table+' WHERE trip_id=%s',(trip,)).fetchone()[0],0)
            self.assertIsNotNone(conn.execute('SELECT deleted_at FROM team_trips WHERE trip_id=%s',(trip,)).fetchone()[0])
        self.assertEqual(self.trip(session=b)[2]['trips'], [])

    def test_v6_corrupted_payloads_fail_closed(self):
        a,b,_,car,_=self.remote_setup()
        trip=car.split('/')[0]
        self.seed_legacy_remote(car,a)
        self.attach(trip,self.published_course(b,'bob'),b)
        keys = dict(team_trips=('trip_id',), team_trip_members=('trip_id','account_id'),
            team_trip_cars=('trip_id','car_id'), team_trip_courses=('trip_id','pack_id'))
        for table, columns in keys.items():
            with self.subTest(table=table):
                with psycopg.connect(self.dsn) as conn:
                    rows=conn.execute('SELECT '+','.join(columns)+',protected FROM '+table+' WHERE trip_id=%s',(trip,)).fetchall()
                    conn.execute('UPDATE '+table+' SET protected=%s WHERE trip_id=%s',(b'invalid-ciphertext',trip))
                try:
                    self.assertEqual(self.trip('/'+trip,session=b)[0],503)
                    if table=='team_trip_members':
                        self.assertEqual(self.respond(trip,a)[0],503)
                finally:
                    with psycopg.connect(self.dsn) as conn:
                        for row in rows:
                            conn.execute('UPDATE '+table+' SET protected=%s WHERE '+
                                ' AND '.join(column+'=%s' for column in columns), (row[-1],*row[:-1]))

    def test_v61_link_transport_csrf_and_replaced_routes(self):
        a,b,_=self.sessions()
        trip=self.new_trip(a)
        trip_token=self.trip('/'+trip+'/link',method='POST',session=a)[2]['token']
        friend_token=self.social('/friend-link',a,method='POST')[2]['token']
        for kind,token,actions in (('trip',trip_token,('preview','join')),('friend',friend_token,('preview','accept'))):
            for action in actions:
                path='/'+kind+'-links/'+action
                for options in (dict(csrf=False),dict(origin='https://wrong.invalid')):
                    self.assertEqual(self.social(path,b,dict(token=token),'POST',**options)[0],403)
                for data in ({},dict(token=token,extra=True)):
                    self.assertEqual(self.social(path,b,data,'POST')[0],400)
                self.assertEqual(self.social(path,b,dict(token='invalid'),'POST')[2],dict(detail='Link unavailable'))
                result=self.social(path,b,dict(token=token),'POST')
                self.assertEqual(result[0],200,result[2])
                self.assertEqual(result[1]['cache-control'],'private, no-store')
        for path in ('/trip-links/'+trip_token,'/trip-links/'+trip_token+'/join','/friend-links/'+friend_token,'/friend-links/'+friend_token+'/accept'):
            self.assertEqual(self.social(path,b)[0],404)
            self.assertIn(self.social(path,b,{},'POST')[0],(404,405))

    def test_v61_relational_ids_override_ciphertext_and_cleanup(self):
        a,b,e,car,_=self.remote_setup()
        trip=car.split('/')[0]
        request=self.seed_legacy_remote(car,a)
        pack=self.published_course(b,'bob');self.attach(trip,pack,b)
        service=self.module.TEAM_TRIPS
        with psycopg.connect(self.dsn) as conn:
            value=service.remote_requests(conn,trip)[request]
            value.update(requesterId=e['user']['id'],ownerId=a['user']['id'],carId='f'*32)
            conn.execute('UPDATE team_trip_remote_requests SET protected=%s WHERE trip_id=%s AND request_id=%s',
                (service.protect('remote-request:'+request,trip,value),trip,request))
            conn.execute('UPDATE team_trip_courses SET protected=%s WHERE trip_id=%s AND pack_id=%s',
                (service.protect('course:'+pack['id'],trip,dict(packId=pack['id'],addedBy=e['user']['id'])),trip,pack['id']))
            value=service.remote_requests(conn,trip)[request]
            self.assertEqual((value['requesterId'],value['ownerId'],value['carId']),
                (a['user']['id'],b['user']['id'],car.split('/')[-1]))
            self.assertEqual(service.course_links(conn,trip)[pack['id']]['addedBy'],b['user']['id'])
        detail=self.trip('/'+trip,session=b)[2]
        self.assertEqual(detail['remoteRequests'],[])
        self.assertEqual(detail['courses'][0]['addedById'],b['user']['id'])
        self.assertEqual(self.trip('/'+trip+'/members/'+a['user']['id'],method='DELETE',session=a)[0],200)
        with psycopg.connect(self.dsn) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_remote_requests WHERE trip_id=%s',(trip,)).fetchone()[0],0)

    def test_v61_account_and_car_foreign_key_cascade(self):
        from account_handles import create_account
        a=self.login()
        trip=self.new_trip(a)
        service=self.module.TEAM_TRIPS
        driver,rider='team-'+secrets.token_hex(20),'team-'+secrets.token_hex(20)
        car,identifier=secrets.token_hex(16),secrets.token_hex(16)
        with psycopg.connect(self.dsn) as conn:
            for account in (driver,rider):
                create_account(conn,account,VisitCipher().protect('team-account:'+account,'identity',dict(email='synthetic@example.invalid')))
                service.save_member(conn,trip,account,'accepted')
            conn.execute('INSERT INTO team_trip_cars(trip_id,car_id,driver_id,protected) VALUES(%s,%s,%s,%s)',
                (trip,car,driver,service.protect('car:'+car+':driver:'+driver,trip,dict(name='차',seats=2))))
            conn.execute('INSERT INTO team_trip_riders(trip_id,account_id,car_id) VALUES(%s,%s,%s)',(trip,rider,car))
            conn.execute('INSERT INTO team_trip_courses(trip_id,pack_id,added_by,protected) VALUES(%s,%s,%s,%s)',
                (trip,'synthetic',rider,service.protect('course:synthetic',trip,dict(packId='synthetic',addedBy=rider))))
            request=dict(carId=car,requesterId=rider,ownerId=driver,createdAt=datetime.now(timezone.utc).isoformat(),actions=[dict(id='hvac.fan',revision=1)])
            conn.execute('INSERT INTO team_trip_remote_requests(trip_id,request_id,requester_id,driver_id,car_id,protected) VALUES(%s,%s,%s,%s,%s,%s)',
                (trip,identifier,rider,driver,car,service.protect('remote-request:'+identifier,trip,request)))
            issue_link(conn,rider);issue_link(conn,rider,trip=trip)
            with self.assertRaises(psycopg.errors.ForeignKeyViolation), conn.transaction():
                conn.execute('DELETE FROM team_accounts WHERE account_id=%s',(rider,))
            conn.execute('DELETE FROM team_room_members WHERE account_id=%s',(rider,))
            conn.execute('DELETE FROM team_accounts WHERE account_id=%s',(rider,))
            for table in ('team_trip_courses','team_trip_remote_requests','team_trip_riders','team_trip_links'):
                self.assertEqual(conn.execute('SELECT count(*) FROM '+table+' WHERE trip_id=%s',(trip,)).fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_friend_links WHERE account_id=%s',(rider,)).fetchone()[0],0)
            self.assertEqual(set(service.members(conn,trip)),{a['user']['id'],driver})
            request['requesterId']=a['user']['id']
            conn.execute('INSERT INTO team_trip_remote_requests(trip_id,request_id,requester_id,driver_id,car_id,protected) VALUES(%s,%s,%s,%s,%s,%s)',
                (trip,identifier,a['user']['id'],driver,car,service.protect('remote-request:'+identifier,trip,request)))
            conn.execute('DELETE FROM team_trip_cars WHERE trip_id=%s AND car_id=%s',(trip,car))
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_remote_requests WHERE trip_id=%s',(trip,)).fetchone()[0],0)
            conn.execute('UPDATE team_trips SET owner_id=%s WHERE trip_id=%s',(driver,trip))
            room=conn.execute('SELECT room_id FROM team_rooms WHERE trip_id=%s',(trip,)).fetchone()[0]
            with self.assertRaises(psycopg.errors.ForeignKeyViolation), conn.transaction():
                conn.execute('DELETE FROM team_accounts WHERE account_id=%s',(driver,))
            conn.execute('DELETE FROM team_room_members WHERE room_id=%s',(room,))
            conn.execute('DELETE FROM team_rooms WHERE room_id=%s',(room,))
            conn.execute('DELETE FROM team_accounts WHERE account_id=%s',(driver,))
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trips WHERE trip_id=%s',(trip,)).fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_members WHERE trip_id=%s',(trip,)).fetchone()[0],0)


class TripPolicyTests(unittest.TestCase):
    def setUp(self):
        self.account = 'team-' + 'a'*40
        self.auth = SimpleNamespace(dsn='not-a-database', enabled=True,
            browser=MagicMock(return_value=dict(id=self.account)), rate=MagicMock())
        self.service = TeamTrips(self.auth)

    def test_course_queries_allow_unreviewed_versions_and_reject_actual_post_publication_restrictions(self):
        import sqlite3
        from course_publication import COURSE_AVAILABLE
        source = ast.parse(Path(__file__).with_name('team_trips.py').read_text())
        def query(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.JoinedStr):
                values = []
                for value in node.values:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        values.append(value.value)
                    elif (isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name)
                          and value.value.id == 'COURSE_AVAILABLE'):
                        values.append(COURSE_AVAILABLE)
                    else:
                        return ''
                return ''.join(values)
            return ''
        queries = [query(node.args[0]) for node in ast.walk(source)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'execute' and node.args]
        attach = next(sql for sql in queries if sql.startswith('SELECT 1 FROM pack_versions p'))
        visible = next(sql for sql in queries if sql.startswith('SELECT p.version,p.title,p.stop_count FROM'))
        with sqlite3.connect(':memory:') as conn:
            conn.execute('CREATE TABLE pack_versions(pack_id TEXT,creator_id TEXT,checksum TEXT,version INT,title TEXT,stop_count INT)')
            conn.execute('CREATE TABLE pack_reviews(checksum TEXT,state TEXT)')
            conn.execute('CREATE TABLE content_reports(checksum TEXT)')
            conn.execute('CREATE TABLE pack_review_events(checksum TEXT,state TEXT)')
            conn.executemany('INSERT INTO pack_versions VALUES(?,?,?,?,?,?)', [
                ('private','other','private',1,'비공개',1),('public','other','approved',1,'공개',1),
                ('public','other','draft',2,'다음 비공개',1),('mine','me','mine',1,'내 초안',1)])
            conn.executemany('INSERT INTO pack_reviews VALUES(?,?)', [('approved','approved'),('draft','quarantined'),('private','quarantined')])
            run = lambda sql, pack: conn.execute(sql.replace('%s','?'), (pack,)).fetchone()
            self.assertIsNotNone(run(attach, 'private'))
            self.assertIsNotNone(run(attach, 'public'))
            self.assertIsNotNone(run(attach, 'mine'))
            self.assertEqual(run(visible, 'public')[:2], (2, '다음 비공개'))
            conn.execute("INSERT INTO content_reports VALUES('private')")
            self.assertIsNone(run(attach, 'private'))
            conn.execute("UPDATE pack_reviews SET state='quarantined' WHERE checksum='approved'")
            conn.executemany('INSERT INTO content_reports VALUES(?)', [('approved',), ('draft',)])
            self.assertIsNone(run(attach, 'public'))
            self.assertIsNone(run(visible, 'public'))

    def test_text_and_seat_boundaries(self):
        self.assertEqual(trip_text('  여행  ', 'trip title', 1, 40), '여행')
        self.assertEqual(trip_text('\n 설명\n다음 \n', 'trip description', 0, 300, multiline=True), '설명\n다음')
        for text in ('', ' '*3, 'x'*41, '\n여행', '여행\x7f', '\ud800', 1, None):
            with self.subTest(text=repr(text)), self.assertRaises(HTTPException) as error:
                trip_text(text, 'trip title', 1, 40)
            self.assertEqual((error.exception.status_code,error.exception.detail),(400,'Invalid trip title'))
        for seats in (1,8):
            self.assertEqual(car_fields(dict(name=' 차 ',seats=seats)),dict(name='차',seats=seats))
        for seats in (False,True,0,9,1.0,'1',None):
            with self.subTest(seats=seats), self.assertRaises(HTTPException):
                car_fields(dict(name='차',seats=seats))
        self.assertTrue(permissions(dict(invite=True,edit=False)))
        for value in ({},dict(invite=1,edit=False),dict(invite=True,edit=False,extra=True)):
            self.assertFalse(permissions(value))

    def test_every_v6_write_rejects_unknown_fields_before_database(self):
        routes = [route for route in self.service.router().routes if not route.path.startswith(('/v1/native/', '/v1/iphone/'))] + [route for route in create_router(self.auth).routes if '/friend-link' in route.path]
        checked = 0
        for route in routes:
            if route.methods == {'GET'}:
                continue
            async def receive():
                return dict(type='http.request', body=b'{"unexpected":true}', more_body=False)
            request=Request(dict(type='http',method=next(iter(route.methods)),path=route.path,headers=[]),receive)
            arguments={name: ('A'*43 if name=='token' else self.account if name=='accountId' else 'a'*32) for name in route.param_convertors}
            with self.subTest(route=route.path), patch('psycopg.connect',side_effect=AssertionError('No database allowed')):
                with self.assertRaises(HTTPException) as error:
                    asyncio.run(route.endpoint(**arguments,request=request,response=Response()))
                self.assertEqual(error.exception.status_code,400)
            checked += 1
        self.assertEqual(checked,27)
        self.assertTrue(self.auth.browser.call_args.kwargs['mutate'])
        self.assertTrue(self.auth.rate.called)

    def test_exact_routes_match_authored_docs(self):
        from api_doc_trips import OPS, BODY, NO_BODY
        from api_doc_catalog import OPERATIONS
        routes=[route for route in self.service.router().routes if not route.path.startswith(('/v1/native/', '/v1/iphone/'))]+[route for route in create_router(self.auth).routes if '/friend-link' in route.path]
        actual={(method.lower(),route.path) for route in routes for method in route.methods}
        self.assertEqual(actual,set(OPS))
        self.assertEqual(len(actual),31)
        self.assertLessEqual(set(BODY),actual)
        self.assertLessEqual(NO_BODY,actual)
        self.assertLessEqual(actual,set(OPERATIONS))
        self.assertFalse(any('/groups' in path or path.endswith(('/start','/end','/invitable-groups')) for _,path in actual))
        for body in BODY.values():
            for shape in body.get('oneOf', [body]):
                self.assertFalse(shape['additionalProperties'])

    def test_tokens_hash_only_and_invalid_token_rejected_before_database(self):
        conn=MagicMock()
        now=datetime.now(timezone.utc)
        conn.execute.return_value.fetchone.return_value=(now,)
        for trip in (None,'a'*32):
            with self.subTest(trip=trip),patch('team_friends.secrets.token_urlsafe',return_value='A'*43) as generate:
                value=issue_link(conn,self.account,trip=trip)
                generate.assert_called_once_with(32)
                sql,args=conn.execute.call_args.args
                self.assertIn("interval '7 days'",sql)
                self.assertIn(hashlib.sha256(('A'*43).encode()).hexdigest(),args)
                self.assertNotIn('A'*43,args)
                self.assertEqual(value['token'],'A'*43)
        for token in ('a',None,[], 'a'*44, '!'*43):
            conn.reset_mock()
            with self.subTest(token=token),self.assertRaises(HTTPException) as error:
                resolve_link(conn,token)
            self.assertEqual(error.exception.detail,'Link unavailable')
            conn.execute.assert_not_called()
        conn.execute.return_value.fetchone.return_value=None
        with self.assertRaises(HTTPException):resolve_link(conn,'B'*43,trip=True)
        self.assertIn('expires_at>clock_timestamp()',conn.execute.call_args.args[0])

    def test_schema_replaces_v5_without_drop_and_only_encrypted_payloads(self):
        schema=(Path(__file__).parent/'schema.sql').read_text()
        self.assertNotRegex(schema,r'(?im)^\s*DROP\b')
        for name in ('team_groups','team_group_members','team_group_remote_requests','team_trip_groups','anchor_group_id'):
            self.assertNotIn(name,schema)
        for name in ('team_trips','team_trip_members','team_trip_links','team_friend_links','team_trip_cars','team_trip_riders','team_trip_courses','team_trip_remote_requests'):
            self.assertIn('CREATE TABLE IF NOT EXISTS '+name+' (',schema)
        self.assertIn('UNIQUE(trip_id,driver_id)',schema)
        self.assertIn('FOREIGN KEY(trip_id,car_id) REFERENCES team_trip_cars(trip_id,car_id) ON DELETE CASCADE',schema)
        trip_schema=schema[schema.index('CREATE TABLE IF NOT EXISTS team_trips ('):schema.index('CREATE TABLE IF NOT EXISTS team_rooms (')]
        self.assertNotRegex(trip_schema,r'(?m)^\s+(title|name|description|seats|actions|token)\s')

    def test_integrity_rejects_invalid_encrypted_shapes(self):
        conn=MagicMock()
        conn.execute.return_value.__iter__.return_value=iter([(self.account,b'cipher')])
        with patch.object(self.service,'restore',return_value=dict(state='accepted',via='link',permissions=dict(invite=1,edit=False))):
            with self.assertRaises(PrivateRecordError):self.service.members(conn,'a'*32)
        conn.execute.return_value.__iter__.return_value=iter([('b'*32,self.account,self.account,'c'*32,b'cipher')])
        with patch.object(self.service,'restore',return_value=dict(requesterId=self.account,ownerId=self.account,createdAt='now',carId='c'*32,actions=[])):
            with self.assertRaises(PrivateRecordError):self.service.remote_requests(conn,'a'*32)


if __name__ == '__main__':
    unittest.main(verbosity=2)
