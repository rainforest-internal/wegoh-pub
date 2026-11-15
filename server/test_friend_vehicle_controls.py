"""Trip-scoped passenger remotes and retired friend-level permissions."""
import asyncio
import copy
import datetime as dt
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException, Request, Response
import psycopg

from native_functional_defaults import ACCOUNT_PURPOSES, INITIAL_PURPOSES
import test_climate_commands as fixtures


class FriendRemoteContractTests(unittest.TestCase):
    def setUp(self):
        from device_command_registry import ProductionCommandRegistry
        from team_device_commands import TeamDeviceCommands
        from friend_vehicle_controls import FriendVehicleControls

        self.commands = TeamDeviceCommands.__new__(TeamDeviceCommands)
        self.commands.registry = ProductionCommandRegistry()
        self.commands.auth = SimpleNamespace()
        self.commands.dsn = 'unused'
        self.commands.enabled = True
        self.controls = FriendVehicleControls(self.commands)
        self.commands.friend_controls = self.controls

    def test_passenger_remote_routes_require_a_trip(self):
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(self.commands.router())
        app.include_router(self.commands.trip_router())
        paths = {(method.upper(), path) for path, ops in app.openapi()['paths'].items() for method in ops}
        trip_root = '/v1/social/trips/{trip}/vehicle-remotes'
        self.assertIn(('GET', trip_root), paths)
        self.assertIn(('POST', trip_root + '/{device}/commands'), paths)
        standing_routes = {
            ('GET', '/v1/social/friends/{peer}/vehicle-controls'),
            ('PUT', '/v1/devices/{device}/friend-controls/{peer}'),
            ('DELETE', '/v1/devices/{device}/friend-controls/{peer}'),
            ('GET', '/v1/vehicle-remotes'),
            ('POST', '/v1/vehicle-remotes/{device}/commands'),
        }
        self.assertFalse(standing_routes & paths)

    def test_options_include_all_eleven_registered_actions(self):
        options = self.commands.display_actions()
        self.assertEqual(self.controls.options(), options)
        self.assertEqual(len(options), 11)
        future = dict(id='fixture.future', revision=2, label='Fixture', argumentKind='switch')
        with patch.object(self.commands, 'display_actions', return_value=options + [future]):
            self.assertIn(future, self.controls.options())

    def test_removed_actions_are_rejected_before_database_access(self):
        endpoint = next(route.endpoint for route in self.controls.trip_router().routes
                        if route.path.endswith('/vehicle-remotes/{device}/commands'))
        for action, arguments in [('steering.heat', {'value': 1}),
                                  ('hvac.defroster', {'window': 'FRONT_WINDSHIELD', 'value': True})]:
            with self.subTest(action=action):
                self.assertIsNone(self.commands.registry.lookup(action, 1))
                data = dict(eventId='removed-action-denied', grantRevision=1, capabilityId=action,
                            capabilityRevision=1, arguments=arguments)

                async def receive():
                    return dict(type='http.request', body=json.dumps(data).encode(), more_body=False)

                request = Request(dict(type='http', method='POST', path='/v1/social/trips/trip/vehicle-remotes/device/commands', headers=[]), receive)
                with patch('friend_vehicle_controls.psycopg.connect', side_effect=AssertionError('Unexpected DB access')):
                    with self.assertRaises(HTTPException) as denied:
                        asyncio.run(endpoint('a' * 32, 'b' * 32, request, Response()))
                self.assertEqual(denied.exception.status_code, 400)

    def test_queued_standing_remote_rejected_without_a_trip(self):
        legacy = dict(friendRemote=True, grantRevision=1, grantId='grant', functionalRevision=1)
        with self.assertRaises(HTTPException) as denied:
            self.controls.context(None, 'device', 'peer', 'owner', expected=legacy)
        self.assertEqual(denied.exception.status_code, 403)

    def test_queued_trip_command_rechecks_membership_and_explicit_action(self):
        trip = 'a' * 32
        membership = dict(tripId=trip, carId='car', requesterJoinedAt='first', ownerJoinedAt='first')
        allowed = dict(id='hvac.temperature', revision=1)
        grant = dict(carId='car', revision=2, grantId='install', actions=[allowed])
        device = SimpleNamespace(grant_id='install', functional_revision=3, expires_at=dt.datetime.now(dt.UTC))
        with patch.object(self.controls, 'trip_context', return_value=membership) as resolve, \
             patch.object(self.controls, 'friendship'), \
             patch.object(self.controls, 'trip_grant', return_value=('owner', grant)), \
             patch.object(self.controls, 'device', return_value=device):
            saved, _ = self.controls.context(None, 'device', 'peer', 'owner', action=allowed, trip=trip)
            self.controls.context(None, 'device', 'peer', 'owner', expected=saved, action=allowed)
            resolve.assert_called_with(None, trip, 'peer', 'owner', states=('active',))
            with self.assertRaises(HTTPException) as denied:
                self.controls.context(None, 'device', 'peer', 'owner', action=dict(id='hvac.fan', revision=1), trip=trip)
            self.assertEqual(denied.exception.status_code, 403)
            resolve.return_value = dict(membership, requesterJoinedAt='rejoined')
            with self.assertRaises(HTTPException) as stale:
                self.controls.context(None, 'device', 'peer', 'owner', expected=saved, action=allowed)
            self.assertEqual(stale.exception.status_code, 409)

    def test_trip_withdrawal_terminalizes_queued_and_delivered_commands_only_for_this_trip(self):
        trip, room = 'a' * 32, 'b' * 32
        base = dict(targetDeviceId='device', requesterId='peer', ownerId='owner')
        values = {
            'queued': dict(base, context=dict(tripId=trip), stage='queued', mayHaveExecuted=False, leaseHash=None),
            'delivered': dict(base, context=dict(tripId=trip), stage='delivered', mayHaveExecuted=True, leaseHash='lease'),
            'other-trip': dict(base, context=dict(tripId='c' * 32), stage='queued'),
        }
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = [(key, key) for key in values]
        self.commands.restore = Mock(side_effect=lambda kind, key, raw: copy.deepcopy(values[key]))
        self.commands.save_request = Mock()
        self.commands.invalidate_receiver = Mock()
        self.commands.notify = Mock()
        self.controls.withdraw_trip_context(conn, trip, room, account='peer')
        saved = {call.args[1]: call.args[2] for call in self.commands.save_request.call_args_list}
        self.assertEqual(set(saved), {'queued', 'delivered'})
        self.assertEqual(saved['queued']['stage'], 'cancelled')
        self.assertEqual(saved['delivered']['stage'], 'unknown')
        self.assertIsNone(saved['delivered']['leaseHash'])


class FriendRemoteTests(fixtures.ClimateHttpTests):
 def setup_remote(self):
  from device_command_registry import ProductionCommandRegistry
  self.service.registry=ProductionCommandRegistry()
  self.prepare(False)
  self.peer=self.b['user']['id']

 def start_trip(self):
  from test_team_trips import TripTests
  harness=TripTests()
  self.assertEqual(self.web('/v1/devices/'+self.did+'/vehicle-profile',
      dict(plateNumber='123가4567',name='',expectedRevision=0),'PUT',session=self.a)[0],200)
  self.trip_id=harness.new_trip(self.a,members=(self.b,))
  self.assertEqual(harness.respond(self.trip_id,self.b)[0],200)
  self.car_path=harness.new_car(self.trip_id,self.a)
  self.assertEqual(harness.ride(self.car_path,self.b)[0],200)
  harness.transition_trip(self.trip_id,self.a,'start')
  self.trip_remotes='/v1/social/trips/'+self.trip_id+'/vehicle-remotes'

 def enable(self,actions=None):
  from test_team_trips import TripTests
  harness=TripTests()
  if actions is None:
   actions=[dict(id='hvac.temperature',revision=1)]
  policy=dict(enabled=True,actions=[action['id']for action in actions],deviceId=self.did)
  status,_,value=self.web('/v1/social/trips/'+self.car_path+'/remote-policy',policy,'PUT',session=self.a)
  self.assertEqual(status,200,value)
  status,_,value=self.web(self.trip_remotes,who='bob',session=self.b)
  self.assertEqual(status,200,value)
  self.assertEqual([remote['deviceId'] for remote in value['remotes']],[self.did])
  self.grant_revision=value['remotes'][0]['grantRevision']

 def send(self,event_id='friend-control-0001',**changes):
  data=dict(eventId=event_id,grantRevision=self.grant_revision,capabilityId='hvac.temperature',
            capabilityRevision=1,arguments=dict(seat='ROW_1_RIGHT',value=22.5))
  data.update(changes)
  return self.web(self.trip_remotes+'/'+self.did+'/commands',data,'POST',who='bob',session=self.b)

 def test_policy_defaults_owner_boundary_and_closed_input(self):
  self.setup_remote();self.start_trip()
  path='/v1/social/trips/'+self.car_path+'/remote-policy'
  self.assertEqual(self.web(path,session=self.a)[2],dict(remotePolicy=dict(enabled=False,actions=[],deviceId=None)))
  value=dict(enabled=True,actions=['hvac.temperature'])
  self.assertEqual(self.web(path,value,'PUT',who='bob',session=self.b)[0],403)
  for invalid in (dict(value,actions=['steering.heat']),dict(value,actions=['hvac.temperature']*2),
                  dict(value,enabled=1),dict(value,extra=True),dict(value,actions=[])):
   self.assertEqual(self.web(path,invalid,'PUT',session=self.a)[0],400)
  status,_,saved=self.web(path,value,'PUT',session=self.a)
  self.assertEqual(status,200,saved)
  self.assertEqual(saved['remotePolicy'],dict(value,deviceId=self.did))
  self.assertEqual(self.web(path,who='bob',session=self.b)[2],saved)
  with psycopg.connect(self.dsn)as conn:
   self.assertEqual(conn.execute('SELECT count(*) FROM team_trip_remote_grants').fetchone()[0],0)
   raw=bytes(conn.execute('SELECT protected FROM team_trip_cars WHERE car_id=%s',(self.car_path.split('/')[-1],)).fetchone()[0])
   self.assertNotIn(b'hvac.temperature',raw)

 def test_policy_action_removal_leave_and_end_cancel_pending_commands(self):
  from test_team_trips import TripTests
  for termination in ('action','leave','finish'):
   with self.subTest(termination=termination):
    self.setup_remote();self.start_trip();self.enable()
    status,_,queued=self.send('policy-cancel-'+termination)
    self.assertEqual(status,201,queued)
    if termination=='action':
     body=dict(enabled=True,actions=['hvac.fan'],deviceId=self.did)
     self.assertEqual(self.web('/v1/social/trips/'+self.car_path+'/remote-policy',body,'PUT',session=self.a)[0],200)
    elif termination=='leave':
     self.assertEqual(self.web('/v1/social/trips/'+self.trip_id+'/ride',method='DELETE',who='bob',session=self.b)[0],200)
    else:TripTests().transition_trip(self.trip_id,self.a,'finish')
    with psycopg.connect(self.dsn)as conn:
     self.assertEqual(self.service.load_request(conn,queued['id'])['stage'],'cancelled')
    self.assertIn(self.send('policy-after-'+termination)[0],(403,404,409))
    self.assertIn(self.claim(queued['id'])[0],(403,404,409))
    self.h.setUp()

 def test_policy_action_order_does_not_invalidate_queued_command(self):
  self.setup_remote();self.start_trip()
  self.enable([dict(id=action,revision=1)for action in ('hvac.temperature','hvac.fan')])
  status,_,queued=self.send('policy-order-command-001')
  self.assertEqual(status,201,queued)
  policy=dict(enabled=True,actions=['hvac.fan','hvac.temperature'],deviceId=self.did)
  path='/v1/social/trips/'+self.car_path+'/remote-policy'
  self.assertEqual(self.web(path,policy,'PUT',session=self.a)[0],200)
  current=self.web(self.trip_remotes,who='bob',session=self.b)[2]['remotes'][0]
  self.assertEqual(current['grantRevision'],self.grant_revision)
  self.assertEqual(self.claim(queued['id'])[0],200)

 def test_legacy_trip_grant_is_preserved_but_not_execution_authority(self):
  self.setup_remote();self.start_trip()
  trip=self.trip_id;car=self.car_path.split('/')[-1];owner=self.a['user']['id']
  key=':'.join((trip,car,owner,self.peer,self.did))
  grant=dict(grantId=self.token['grantId'],actions=[dict(id='hvac.temperature',revision=1)],revision=1)
  raw=self.service.protect('trip-remote-grant',key,grant)
  with psycopg.connect(self.dsn)as conn:
   conn.execute('INSERT INTO team_trip_remote_grants(trip_id,car_id,driver_id,requester_id,device_id,protected) VALUES(%s,%s,%s,%s,%s,%s)',
       (trip,car,owner,self.peer,self.did,raw))
  self.assertEqual(self.web(self.trip_remotes,who='bob',session=self.b)[2]['remotes'],[])
  self.grant_revision=1
  self.assertEqual(self.send('legacy-trip-policy-deny')[0],403)
  with psycopg.connect(self.dsn)as conn:
   stored=conn.execute('SELECT protected FROM team_trip_remote_grants WHERE trip_id=%s AND requester_id=%s',(trip,self.peer)).fetchone()[0]
   self.assertEqual(bytes(stored),bytes(raw))

 def test_preexisting_standing_grant_cannot_dispatch_or_complete_commands(self):
  self.setup_remote()
  self.start_trip()
  self.enable()
  status,_,leased=self.send()
  self.assertEqual(status,201,leased)
  status,claim=self.claim(leased['id'])
  self.assertEqual(status,200,claim)
  status,_,queued=self.send('other-legacy-command')
  self.assertEqual(status,201,queued)
  old_context=dict(friendRemote=True,grantRevision=1,grantId=self.token['grantId'],
                   functionalRevision=self.functional_revision)
  prior_grant=dict(consent=True,actions=[dict(id='hvac.temperature',revision=1)],revision=1,
                   expiresAt=None,nativeBinding=dict(grantId=self.token['grantId'],functionalRevision=self.functional_revision))
  raw=self.service.protect('friend-grant',self.did+':'+self.peer,prior_grant)
  with psycopg.connect(self.dsn)as conn:
   conn.execute('INSERT INTO friend_vehicle_controls(device_id,requester_id,owner_id,protected) VALUES(%s,%s,%s,%s)',
                (self.did,self.peer,self.a['user']['id'],raw))
   for command in (queued,leased):
    value=self.service.load_request(conn,command['id'])
    value['context']=old_context
    self.service.save_request(conn,command['id'],value)

  self.assertEqual(self.native('/v1/device/command-inbox')[1]['requests'],[])
  self.assertIn(self.claim(queued['id'])[0],(403,404,409))
  self.assertIn(self.ack(leased['id'],claim['leaseId'],'received')[0],(403,404,409))
  with psycopg.connect(self.dsn)as conn:
   self.assertEqual(bytes(conn.execute('SELECT protected FROM friend_vehicle_controls WHERE device_id=%s AND requester_id=%s',
                                       (self.did,self.peer)).fetchone()[0]),bytes(raw))
   self.assertIsNone(self.service.load_request(conn,leased['id'])['lastAcknowledgedStage'])

 def test_standing_remote_endpoints_unavailable_to_owner_and_recipient(self):
  self.setup_remote()
  path='/v1/devices/'+self.did+'/friend-controls/'+self.peer
  control=dict(revision=0,consent=True,actions=[dict(id='hvac.temperature',revision=1)],expiresInHours=None)
  command=dict(eventId='retired-route-command',grantRevision=1,capabilityId='hvac.temperature',capabilityRevision=1,
               arguments=dict(seat='ROW_1_RIGHT',value=22.5))
  for url,method,payload in (('/v1/social/friends/'+self.peer+'/vehicle-controls','GET',None),(path,'PUT',control),
                             (path,'DELETE',None),('/v1/vehicle-remotes','GET',None),
                             ('/v1/vehicle-remotes/'+self.did+'/commands','POST',command)):
   with self.subTest(method=method,url=url):
    self.assertIn(self.web(url,payload,method,session=self.a)[0],(404,405))
    self.assertIn(self.web(url,payload,method,who='bob',session=self.b)[0],(404,405))
  self.functional_revision=self.factory.approve(self.a,self.token,['device-commands:receive','friends:read','friends:manage'])
  self.assertIn(self.native(path,control,'PUT')[0],(404,405))
  self.assertIn(self.native('/v1/social/friends/'+self.peer+'/vehicle-controls')[0],(404,405))

 def test_trip_command_idempotency_withdrawal_and_receiver_invalidation(self):
  self.setup_remote();self.start_trip();self.enable()
  status,_,first=self.send()
  self.assertEqual(status,201,first)
  self.assertEqual(self.send()[2]['id'],first['id'])
  self.assertEqual(self.send(arguments=dict(seat='ROW_1_RIGHT',value=23))[0],409)
  self.assertEqual(self.send('friend-control-0002',capabilityId='hvac.fan',arguments=dict(seat='ROW_1_RIGHT',value=2))[0],403)
  with self.tls.websocket(self.token['accessToken'])as ws:
   self.assertEqual(json.loads(ws.recv(timeout=3))['type'],'snapshot')
   revoke='/v1/social/trips/'+self.car_path+'/remote-policy'
   self.assertEqual(self.web(revoke,dict(enabled=False,actions=[],deviceId=None),'PUT',session=self.a)[0],200)
   self.assertIn('devices',json.loads(ws.recv(timeout=3))['resources'])
  self.assertEqual(self.web(self.trip_remotes,who='bob',session=self.b)[2]['remotes'],[])
  self.assertIn(self.claim(first['id'])[0],(403,404,409))

 def test_current_policy_requires_current_friendship(self):
  self.setup_remote();self.start_trip();self.enable()
  self.assertEqual(self.h.friend('/friends/'+self.peer,method='DELETE',session=self.a)[0],200)
  self.assertEqual(self.web(self.trip_remotes,who='bob',session=self.b)[2]['remotes'],[])
  self.assertIn(self.send()[0],(403,404,409))
  self.assertEqual(self.h.request_friend(self.a,self.b)[0],201)
  self.assertEqual(self.h.friend('/friends/requests/'+self.a['user']['id']+'/respond',dict(accept=True),'POST',who='bob',session=self.b)[0],200)
  self.assertEqual(len(self.web(self.trip_remotes,who='bob',session=self.b)[2]['remotes']),1)

 def test_initial_receive_default_does_not_restore_explicit_withdrawal(self):
  self.setup_remote()
  with psycopg.connect(self.dsn)as conn:conn.execute('DELETE FROM native_functional_authorizations WHERE grant_id=%s',(self.token['grantId'],))
  status,value=self.native('/v1/device/functional-permissions');self.assertEqual(status,200,value);self.assertEqual(value['approvedPurposes'],sorted(ACCOUNT_PURPOSES.union(INITIAL_PURPOSES)))
  receiver='/v1/device/command-receiver'
  status,current=self.native(receiver);self.assertEqual(status,200,current);self.assertTrue(current['enabled'])
  body=dict(grantId=current['grantId'],revision=current['revision'],enabled=False)
  status,updated=self.tls.native(receiver,body,'PUT',token=self.token['accessToken'])
  self.assertEqual(status,200,updated);self.assertFalse(updated['enabled'])
  self.factory.approve(self.a,self.token,[])
  status,value=self.native('/v1/device/functional-permissions');self.assertEqual(status,200,value);self.assertEqual(value['approvedPurposes'],sorted(ACCOUNT_PURPOSES))
 def test_stored_v1_explicit_off_is_read_without_reapproval_or_rewrite(self):
  self.setup_remote();self.factory.approve(self.a,self.token,[])
  from native_functional_policy import WIRE
  from private_records import VisitCipher
  old=WIRE['previousDisclosures'][0]
  payload=dict(approvedPurposes=[],functionalDisclosureVersion=old['version'],functionalDisclosureSha256=old['sha256'])
  protected=VisitCipher().protect('native-functional',self.token['grantId'],payload)
  with psycopg.connect(self.dsn)as conn:conn.execute('UPDATE native_functional_authorizations SET protected=%s WHERE grant_id=%s',(protected,self.token['grantId']))
  status,value=self.native('/v1/device/functional-permissions');self.assertEqual(status,200,value);self.assertEqual(value['approvedPurposes'],sorted(ACCOUNT_PURPOSES));self.assertEqual(value['functionalDisclosureVersion'],2)
  with psycopg.connect(self.dsn)as conn:self.assertEqual(bytes(conn.execute('SELECT protected FROM native_functional_authorizations WHERE grant_id=%s',(self.token['grantId'],)).fetchone()[0]),bytes(protected))
 def test_native_social_invalidation_tracks_only_allowed_resource(self):
  self.setup_remote();eve=self.h.login('eve')
  self.functional_revision=self.factory.approve(self.a,self.token,['friends:read'])
  with self.tls.websocket(self.token['accessToken'])as ws:
   self.assertEqual(json.loads(ws.recv(timeout=3))['type'],'snapshot')
   self.assertEqual(self.h.request_friend(self.a,eve)[0],201)
   event=json.loads(ws.recv(timeout=3));self.assertIn('devices',event['resources']);self.assertNotIn(eve['user']['id'],json.dumps(event))
  self.functional_revision=self.factory.approve(self.a,self.token,[])
  with self.tls.websocket(self.token['accessToken'])as ws:
   self.assertEqual(json.loads(ws.recv(timeout=3))['type'],'snapshot')
   self.assertEqual(self.h.friend('/friends/'+eve['user']['id'],method='DELETE',session=self.a)[0],200)
   with self.assertRaises(TimeoutError):ws.recv(timeout=.8)
 def test_friend_remote_api_documentation(self):
  from team_api_docs import build_schema
  import sys
  from pathlib import Path
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
  from check_api_documentation import check
  schema=build_schema(self.h.module.app,self.h.module.TEAM_AUTH)
  remote={p:v for p,v in schema['paths'].items()if any(part in p for part in ('friend-controls','vehicle-remotes','vehicle-controls','remote-devices','remote-policy'))}
  self.assertEqual({p for p in remote if p.startswith('/v1/iphone/')},{'/v1/iphone/trips/{id}/cars/{carId}/remote-policy','/v1/iphone/trips/{trip}/vehicle-remotes','/v1/iphone/trips/{trip}/vehicle-remotes/{device}/commands'})
  schema['paths']={p:v for p,v in remote.items()if not p.startswith('/v1/iphone/')}
  paths=schema['paths']
  self.assertEqual(len(paths),4,paths.keys())
  self.assertTrue(all(path.startswith('/v1/social/trips/') for path in paths))
  self.assertIn('get',paths['/v1/social/trips/{trip}/vehicle-remotes'])
  self.assertIn('post',paths['/v1/social/trips/{trip}/vehicle-remotes/{device}/commands'])
  count=sum(len(methods)for methods in paths.values())
  schema['x-wegoh-documentation-coverage']=dict(operations=count,genericCatalogOperations=count,authorizationOverlayOperations=0,iphoneOperations=0)
  self.assertEqual(check(schema)['operations'],count)
 def test_new_value_supersedes_only_queued_same_property_and_seat(self):
  self.setup_remote();self.start_trip();self.enable()
  first=self.send()[2]
  other=self.send('friend-control-other',arguments=dict(seat='ROW_2_LEFT',value=21))[2]
  latest=self.send('friend-control-newest',arguments=dict(seat='ROW_1_RIGHT',value=24))[2]
  inbox=self.native('/v1/device/command-inbox')[1]['requests'];ids={r['id']for r in inbox}
  self.assertNotIn(first['id'],ids);self.assertIn(other['id'],ids);self.assertIn(latest['id'],ids)
  with psycopg.connect(self.dsn)as conn:self.assertEqual(self.service.load_request(conn,first['id'])['stage'],'cancelled')

 def test_trip_request_status_matches_passenger_and_receiver(self):
  self.setup_remote();self.start_trip();self.enable()
  inbox='/v1/device/command-inbox'
  with self.tls.websocket(self.token['accessToken'],subprotocols=['wegoh.events.v1']) as events:
   initial=json.loads(events.recv(timeout=3));self.assertEqual(initial['type'],'snapshot')
   self.assertIn('commands',initial['versions'])
   code,_,receipt=self.send();self.assertEqual(code,201,receipt)
   identifier=receipt['id']
   changed=json.loads(events.recv(timeout=3));self.assertEqual(changed['type'],'invalidate')
   self.assertEqual(set(changed['versions']),{'commands'})

  def status(stage):
   mobile=self.web(self.trip_remotes,who='bob',session=self.b)[2]['remotes'][0]['requests']
   code,payload=self.native(inbox+'?view=status');self.assertEqual(code,200,payload)
   receiver=payload['requests']
   for rows in (mobile,receiver):
    self.assertEqual([(row['id'],row['stage']) for row in rows],[(identifier,stage)])
    self.assertFalse(rows[0]['physicalExecutionVerified'])
    self.assertNotIn('leaseId',rows[0]);self.assertNotIn('arguments',rows[0])

  status('queued')
  code,claim=self.claim(identifier);self.assertEqual(code,200,claim)
  status('delivered')
  lease=claim['leaseId'];ack_id='synthetic-status-ack'
  self.assertEqual(self.ack(identifier,lease,'received',ack_id=ack_id)[0],200)
  status('received')
  self.assertEqual(self.ack(identifier,lease,'received',ack_id=ack_id)[0],200)
  proof=dict(kind='pleos-vehicle-setter-v1',requestId=identifier,property='TARGET_CELSIUS',seat='ROW_1_RIGHT',value=22.5)
  code,response=self.ack(identifier,lease,'sdk-accepted',evidence=proof);self.assertEqual(code,200,response)
  status('sdk-accepted')
  proof.update(kind='pleos-vehicle-getter-v1',receivedAtElapsedMillis=1,capturedAtMillis=None)
  code,response=self.ack(identifier,lease,'state-confirmed',evidence=proof);self.assertEqual(code,200,response)
  with self.tls.websocket(self.token['accessToken'],subprotocols=['wegoh.events.v1']) as events:
   resumed=json.loads(events.recv(timeout=3))
   self.assertEqual((resumed['type'],resumed['seq']),('snapshot',0))
   self.assertNotEqual(resumed['versions']['commands'],changed['versions']['commands'])
   status('state-confirmed')
  self.assertEqual(self.native(inbox)[1]['requests'],[])
  self.assertEqual(self.native(inbox+'?view=status&view=active')[0],400)
  self.assertEqual(self.send()[2]['stage'],'state-confirmed')
  status('state-confirmed')
  self.assertEqual(self.web(self.trip_remotes,session=self.a)[2]['remotes'],[])
  revoke='/v1/social/trips/'+self.car_path+'/remote-policy'
  self.assertEqual(self.web(revoke,dict(enabled=False,actions=[]),'PUT',session=self.a)[0],200)
  self.assertEqual(self.web(self.trip_remotes,who='bob',session=self.b)[2]['remotes'],[])
  self.assertEqual(self.native(inbox+'?view=status')[1]['requests'],[])
 def test_all_eleven_friend_actions_round_trip(self):
  from test_device_command_registry import CONTRACTS
  self.setup_remote();self.start_trip()
  self.enable([dict(id=row[0],revision=1)for row in CONTRACTS])
  for index,(identifier,_,_,prop,arguments)in enumerate(CONTRACTS):
   with self.subTest(action=identifier):
    status,_,value=self.send('friend-action-'+str(index).zfill(4),capabilityId=identifier,arguments=arguments)
    self.assertEqual(status,201,value)
    status,claim=self.claim(value['id']);self.assertEqual(status,200,claim)
    lease=claim['leaseId'];self.assertEqual(self.ack(value['id'],lease,'received')[0],200)
    proof=dict(kind='pleos-vehicle-setter-v1',requestId=value['id'],property=prop,**arguments)
    self.assertEqual(self.ack(value['id'],lease,'sdk-accepted',evidence=proof)[0],200)
    proof.update(kind='pleos-vehicle-getter-v1',receivedAtElapsedMillis=1,capturedAtMillis=None)
    self.assertEqual(self.ack(value['id'],lease,'state-confirmed',evidence=proof)[0],200)

 def test_driver_seat_and_window_requests_are_rejected(self):
  from test_device_command_registry import CONTRACTS
  self.setup_remote();self.start_trip()
  self.enable([dict(id=row[0],revision=1)for row in CONTRACTS])
  for index,(identifier,_,_,_,arguments)in enumerate(CONTRACTS):
   key='seat'if 'seat'in arguments else'window'if 'window'in arguments else None
   if key is None:continue
   with self.subTest(action=identifier):
    status,_,value=self.send('friend-driver-'+str(index).zfill(4),capabilityId=identifier,arguments=dict(arguments,**{key:'ROW_1_LEFT'}))
    self.assertEqual(status,400,value)
  self.assertEqual(self.native('/v1/device/command-inbox')[1]['requests'],[])

 def test_window_and_global_commands_supersede_only_same_action_and_area(self):
  self.setup_remote();self.start_trip()
  self.enable([dict(id=i,revision=1)for i in ('window.position','light.cabin')])
  def send(event,action,arguments):
   status,_,value=self.send(event,capabilityId=action,arguments=arguments);self.assertEqual(status,201,value);return value['id']
  first=send('window-command-0001','window.position',dict(window='ROW_2_LEFT',value=10))
  other=send('window-command-0002','window.position',dict(window='ROW_1_RIGHT',value=10))
  newest=send('window-command-0003','window.position',dict(window='ROW_2_LEFT',value=20))
  light=send('global-command-0001','light.cabin',dict(value=True))
  latest=send('global-command-0002','light.cabin',dict(value=False))
  ids={r['id']for r in self.native('/v1/device/command-inbox')[1]['requests']}
  self.assertEqual(ids,{other,newest,latest})
  with psycopg.connect(self.dsn)as conn:
   for identifier in (first,light):self.assertEqual(self.service.load_request(conn,identifier)['stage'],'cancelled')

def load_tests(loader,tests,pattern):
 return unittest.TestSuite([loader.loadTestsFromTestCase(FriendRemoteContractTests),
                            *(FriendRemoteTests(name)for name in vars(FriendRemoteTests)if name.startswith('test_'))])
