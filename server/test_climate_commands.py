"""Exact HVAC contracts and existing owner/friend/lease authorization."""
import unittest
from device_command_registry import ProductionCommandRegistry
import test_team_device_commands as commands

class ClimateContractTests(unittest.TestCase):
 def test_arguments_and_fixed_registry(self):
  registry=ProductionCommandRegistry()
  self.assertEqual(len(registry.describe()),11)
  temp=registry.lookup('hvac.temperature',1);fan=registry.lookup('hvac.fan',1)
  for value in [True,None,float('nan'),float('inf'),-1,51,10**400]:
   self.assertFalse(temp.validate_arguments(dict(seat='ROW_1_RIGHT',value=value)))
  for value in [True,1.5,'2',-1,101]:self.assertFalse(fan.validate_arguments(dict(seat='ROW_1_RIGHT',value=value)))
  self.assertTrue(temp.validate_arguments(dict(seat='ROW_1_RIGHT',value=22.5)))
  self.assertTrue(fan.validate_arguments(dict(seat='ROW_2_LEFT',value=2)))
  self.assertFalse(temp.validate_arguments(dict(seat='ANY',value=22)))
  self.assertFalse(temp.validate_arguments(dict(seat='ROW_1_RIGHT',value=22,extra=1)))
  self.assertIsNotNone(registry.lookup('hvac.power',1));self.assertIsNone(registry.lookup('hvac.temperature',True))
 def test_only_permission_changes_invalidate_device_authority(self):
  from team_device_commands import TeamDeviceCommands
  from unittest.mock import patch
  service=TeamDeviceCommands.__new__(TeamDeviceCommands)
  with patch('team_device_commands.changed')as changed:
   service.notify_progress(None,'owner','peer','owner');self.assertEqual({v.args for v in changed.call_args_list},{(None,'owner','devices'),(None,'peer','devices')});self.assertEqual(changed.call_count,2)
   changed.reset_mock();service.notify(None,'owner');self.assertEqual([v.args[2]for v in changed.call_args_list],['devices','rooms'])
   changed.reset_mock();service.invalidate_receiver(None,'device');self.assertEqual(changed.call_args.args,(None,'command-device:device','devices'))
 def test_ack_binds_exact_arguments(self):
  action=ProductionCommandRegistry().lookup('hvac.temperature',1)
  context=dict(requestId='request',arguments=dict(seat='ROW_1_RIGHT',value=22))
  proof=dict(kind='pleos-vehicle-setter-v1',requestId='request',seat='ROW_1_RIGHT',property='TARGET_CELSIUS',value=22)
  self.assertTrue(action.validate_ack('sdk-accepted',proof,context))
  self.assertFalse(action.validate_ack('sdk-accepted',dict(proof,value=23),context))
  self.assertFalse(action.validate_ack('sdk-accepted',dict(proof,seat='ROW_1_LEFT'),context))
  read=dict(proof,kind='pleos-vehicle-getter-v1',receivedAtElapsedMillis=1,capturedAtMillis=None)
  self.assertTrue(action.validate_ack('state-confirmed',read,context))
  self.assertFalse(action.validate_ack('state-confirmed',proof,context))

class ClimateHttpTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):commands.CommandTests.setUpClass.__func__(cls)
 @classmethod
 def tearDownClass(cls):commands.CommandTests.tearDownClass.__func__(cls)
 setUp=commands.CommandTests.setUp
 tearDown=commands.CommandTests.tearDown
 web=commands.CommandTests.web
 native=commands.CommandTests.native
 prepare=commands.CommandTests.prepare
 allow=commands.CommandTests.allow
 claim=commands.CommandTests.claim
 ack=commands.CommandTests.ack

 def test_climate_schema_matches_typed_arguments(self):
  from scripts.check_api_documentation import check
  from team_api_docs import build_schema
  schema=build_schema(self.h.module.app,self.h.module.TEAM_AUTH)
  schema['paths']={p:v for p,v in schema['paths'].items()if any(x in p for x in ('command-access','device-command','device-requests','command-inbox','/device/requests/'))}
  count=sum(len(v)for v in schema['paths'].values())
  schema['x-wegoh-documentation-coverage']=dict(operations=count,genericCatalogOperations=count,authorizationOverlayOperations=0,iphoneOperations=0)
  self.assertGreater(check(schema)['operations'],0)

 def test_climate_owner_grant_and_exact_ack(self):
  self.service.registry=ProductionCommandRegistry()
  action=dict(id='hvac.temperature',revision=1)
  self.prepare(True,actions=[action])
  options=self.web(self.d,session=self.a)[2]['supportedControlActions']
  self.assertEqual({v['argumentKind']for v in options},{'hvac-celsius','hvac-fan','seat-switch','seat-level','window-position','switch'})
  body=dict(eventId='climate-request-0001',targetDeviceId=self.did,grantRevision=self.saved_grant['revision'],
   capabilityId=action['id'],capabilityRevision=1,arguments=dict(seat='ROW_1_RIGHT',value=22),expiresInSeconds=60)
  status,_,value=self.web(self.q,body,'POST',session=self.a)
  self.assertEqual(status,201,value)
  denied=dict(body,eventId='climate-request-0002',capabilityId='hvac.fan',arguments=dict(seat='ROW_1_RIGHT',value=2))
  self.assertEqual(self.web(self.q,denied,'POST',session=self.a)[0],403)
  import psycopg
  def stamp():
   with psycopg.connect(self.dsn)as conn:
    row=conn.execute("SELECT revision FROM team_resource_versions WHERE account_id=%s AND resource='devices'",('command-device:'+self.did,)).fetchone()
    return row[0]if row else 0
  before=stamp()
  identifier=value['id'];status,claim=self.claim(identifier);self.assertEqual(status,200,claim)
  lease=claim['leaseId'];self.assertEqual(self.ack(identifier,lease,'received')[0],200)
  evidence=dict(kind='pleos-vehicle-setter-v1',requestId=identifier,seat='ROW_1_RIGHT',property='TARGET_CELSIUS',value=23)
  self.assertEqual(self.ack(identifier,lease,'sdk-accepted',evidence=evidence)[0],400)
  evidence['value']=22;self.assertEqual(self.ack(identifier,lease,'sdk-accepted',evidence=evidence)[0],200)
  evidence.update(kind='pleos-vehicle-getter-v1',receivedAtElapsedMillis=1,capturedAtMillis=None)
  self.assertEqual(self.ack(identifier,lease,'state-confirmed',evidence=evidence)[0],200)
  self.assertEqual(stamp(),before)
  self.assertEqual(self.web(self.g,method='DELETE',session=self.a)[0],200)
  self.assertGreater(stamp(),before)

 def test_receiver_socket_observes_only_its_cancelled_lease(self):
  import json,psycopg
  self.service.registry=ProductionCommandRegistry()
  action=dict(id='hvac.temperature',revision=1);self.prepare(True,[action])
  with self.tls.websocket(self.token['accessToken'])as ws:
   snapshot=json.loads(ws.recv(timeout=3));self.assertEqual(snapshot['type'],'snapshot');self.assertIn('devices',snapshot['resources'])
   with psycopg.connect(self.dsn)as conn:self.service.invalidate_receiver(conn,'f'*32)
   with self.assertRaises(TimeoutError):ws.recv(timeout=1)
   body=dict(eventId='climate-socket-0001',targetDeviceId=self.did,grantRevision=self.saved_grant['revision'],capabilityId=action['id'],capabilityRevision=1,arguments=dict(seat='ROW_1_RIGHT',value=22),expiresInSeconds=60)
   status,_,value=self.web(self.q,body,'POST',session=self.a);self.assertEqual(status,201)
   status,claim=self.claim(value['id']);self.assertEqual(status,200)
   self.assertEqual(self.web(self.q+'/'+value['id'],method='DELETE',session=self.a)[0],200)
   event=json.loads(ws.recv(timeout=3));self.assertEqual(event['type'],'invalidate');self.assertIn('devices',event['resources'])
   self.assertNotIn(self.did,json.dumps(event));self.assertNotIn(claim['leaseId'],json.dumps(event))

 def test_owner_can_request_all_eleven_registered_actions(self):
  from test_device_command_registry import CONTRACTS
  self.service.registry=ProductionCommandRegistry();self.prepare(False)
  actions=self.service.registry.describe()
  status,_,access=self.web(self.d,dict(revision=0,consent=True,expiresInHours=1,actions=actions),'PUT',session=self.a)
  self.assertEqual(status,200,access)
  self.assertEqual(len(access['actions']),11)
  _,_,member=self.web(self.m,session=self.a)
  joined=member['currentJoinedAt']
  status,_,member=self.web(self.m,dict(revision=member['revision'],joinedAt=joined,consent=True,expiresInHours=1,actions=actions),'PUT',session=self.a)
  self.assertEqual(status,200,member)
  path='/v1/social/rooms/'+self.rid+'/device-command-grants/'+self.did+'/'+self.a['user']['id']
  status,_,grant=self.web(path,dict(revision=0,deviceRevision=access['revision'],participationRevision=member['revision'],ownerJoinedAt=joined,requesterJoinedAt=joined,consent=True,expiresInHours=1,actions=actions),'PUT',session=self.a)
  self.assertEqual(status,200,grant)
  for index,(identifier,_,_,prop,arguments)in enumerate(CONTRACTS):
   with self.subTest(action=identifier):
    data=dict(eventId='owner-action-'+str(index).zfill(4),targetDeviceId=self.did,grantRevision=grant['revision'],capabilityId=identifier,capabilityRevision=1,arguments=arguments,expiresInSeconds=60)
    status,_,value=self.web(self.q,data,'POST',session=self.a);self.assertEqual(status,201,value)
    status,claim=self.claim(value['id']);self.assertEqual(status,200,claim)
    lease=claim['leaseId'];self.assertEqual(self.ack(value['id'],lease,'received')[0],200)
    proof=dict(kind='pleos-vehicle-setter-v1',requestId=value['id'],property=prop,**arguments)
    self.assertEqual(self.ack(value['id'],lease,'sdk-accepted',evidence=proof)[0],200)
    proof.update(kind='pleos-vehicle-getter-v1',receivedAtElapsedMillis=1,capturedAtMillis=None)
    self.assertEqual(self.ack(value['id'],lease,'state-confirmed',evidence=proof)[0],200)
  for index,(identifier,_,_,_,arguments)in enumerate(CONTRACTS):
   key='seat'if 'seat'in arguments else'window'if 'window'in arguments else None
   if key is None:continue
   with self.subTest(driver=identifier):
    data=dict(eventId='owner-driver-'+str(index).zfill(4),targetDeviceId=self.did,grantRevision=grant['revision'],capabilityId=identifier,
     capabilityRevision=1,arguments=dict(arguments,**{key:'ROW_1_LEFT'}),expiresInSeconds=60)
    self.assertEqual(self.web(self.q,data,'POST',session=self.a)[0],400)

 def test_legacy_room_friend_cannot_use_owner_grant(self):
  self.service.registry=ProductionCommandRegistry()
  self.prepare(True, actions=self.service.registry.describe())
  room_permissions=self.web(self.m,who='bob',session=self.b)[2]
  self.assertEqual(room_permissions['receivedGrants'],[])
  body=dict(eventId='room-friend-action-01', targetDeviceId=self.did, grantRevision=self.saved_grant['revision'],
   capabilityId='hvac.temperature', capabilityRevision=1, arguments=dict(seat='ROW_1_RIGHT',value=22), expiresInSeconds=60)
  self.assertEqual(self.web(self.q,body,'POST',who='bob',session=self.b)[0],403)
  self.assertEqual(self.native('/v1/device/command-inbox')[1]['requests'],[])
