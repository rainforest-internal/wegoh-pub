"""Actual current-v1 HTTP examples; private PG and synthetic edge, never OEM evidence."""
import copy
import secrets
import unittest
from datetime import datetime,timezone
import test_team_auth as fixture
import test_native_functional_business as current
import test_team_rooms as rooms

class ConsumerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass();__import__('api_application')
    @classmethod
    def tearDownClass(cls):fixture.TeamTests.tearDownClass()
    def setUp(self):
        self.h=rooms.RoomTests('test_18_room_owner_member_roles_and_explicit_close');self.h.setUp()
        self.factory=current.FunctionalBusinessTests();self.factory.h=self.h;self.factory.certificates={}
    def expect(self,result,status):
        self.assertEqual(result[0],status,result[2]);return result[2]
    def test_vehicle_documented_examples_match_live_functional_boundary(self):
        owner=self.h.login();other=self.h.login('bob');credential=self.factory.connect(owner)
        pack=self.h.pack();self.assertEqual(self.h.publish(pack,owner)[0],201);self.assertEqual(self.h.approve(pack,owner)[0],200)
        room=self.h.new_room(owner,courseId=pack['id'],courseVersion=pack['version']);rid=room['id'];did=credential['deviceId']
        self.expect(self.h.call('/v1/social/rooms/'+rid+'/consents',dict(consents=rooms.choices(status=True,location=True)),'PATCH',session=owner),200)
        revision=self.factory.approve(owner,credential,['vehicle-location:report','vehicle-visits:report'])
        path='/v1/devices/'+did+'/vehicle-domain?roomId='+rid
        state=self.expect(self.h.call(path,session=owner),200)
        grant=dict(deviceId=did,revision=state['roomReporting']['revision'],joinedAt=state['roomReporting']['joinedAt'],devicePermissionRevision=revision,
            shareLocation=True,shareVisits=True,receiveLocation=False,receiveVisits=False,expiresInHours=1)
        state=self.expect(self.h.call('/v1/social/rooms/'+rid+'/device-reporting',grant,'PUT',session=owner),200)
        schema=self.expect(self.h.call('/openapi.json'),200);models=schema['components']['schemas']
        self.assertEqual(set(state),set(models['VehicleSnapshot']['properties']))
        self.assertEqual(state['authorizationVersion'],1);self.assertEqual(state['authority'],'native-functional')
        self.assertEqual(state['functionalRevision'],revision)
        for kind in ('location','visits'):
            template='/v1/native/rooms/{room}/reports/'+kind
            op=schema['paths'][template]['post'];media=op['requestBody']['content']['application/json']
            model=models[media['schema']['$ref'].rsplit('/',1)[1]]
            body=copy.deepcopy(media['example']);body.update(eventId=secrets.token_hex(16),functionalRevision=revision,
                devicePermissionRevision=revision,roomRevision=state['roomReporting']['revision'],capturedAt=datetime.now(timezone.utc).isoformat())
            if kind=='visits':body.update(courseId=pack['id'],courseVersion=pack['version'],checkpoint=1)
            self.assertEqual(set(body),set(model['required']));self.assertFalse(model['additionalProperties'])
            self.assertEqual(op['security'],[{'NativeMTLS':[],'DeviceBearer':[]}])
            endpoint=template.replace('{room}',rid)
            missing={k:v for k,v in body.items()if k!='functionalRevision'}
            self.expect(self.factory.native(credential,endpoint,missing,'POST'),400)
            self.expect(self.factory.native(credential,endpoint,dict(body,functionalRevision=revision+1),'POST'),409)
            actual=self.expect(self.factory.native(credential,endpoint,body,'POST'),200)
            self.assertEqual(set(actual),set(models['VehicleReceipt']['required']));self.assertEqual(actual['status'],'accepted')
        before=self.expect(self.h.call(path,session=owner),200)
        for method,template,payload in [('PUT','/v1/devices/{device}/reporting-permissions',dict(revision=revision,purposes=dict(location=True,visits=False),expiresInHours=1)),
                                        ('DELETE','/v1/devices/{device}/reporting-permissions/{purpose}',None)]:
            endpoint=template.replace('{device}',did).replace('{purpose}','location');op=schema['paths'][template][method.lower()]
            self.assertTrue(op['deprecated']);self.assertFalse(op['x-wegoh-executable'])
            self.assertFalse(any(code.startswith('2')for code in op['responses']))
            result=self.expect(self.h.call(endpoint,payload,method,session=owner),409)
            self.assertEqual(result,op['responses']['409']['content']['application/json']['example'])
            self.expect(self.h.call(endpoint,payload,method,session=owner,csrf=False),403)
            self.expect(self.h.call(endpoint,payload,method,session=other,who='bob'),404)
        after=self.expect(self.h.call(path,session=owner),200)
        self.assertEqual(after['reporting'],before['reporting']);self.assertEqual(after['functionalRevision'],before['functionalRevision'])
        self.assertEqual(after['latestLocation'],before['latestLocation']);self.assertEqual(after['latestVisit'],before['latestVisit'])

    def test_native_business_actual_read_models_preserve_explicit_purpose(self):
        owner=self.h.login();credential=self.factory.connect(owner)
        schema=self.expect(self.h.call('/openapi.json'),200);models=schema['components']['schemas']
        inbox=self.expect(self.factory.native(credential,'/v1/device/command-inbox'),200)
        self.assertEqual(set(inbox),{'requests','supportedControlActions','serverNow'});self.assertEqual(inbox['requests'],[])
        settings=self.expect(self.factory.native(credential,'/v1/recommendations/settings'),200)
        self.assertEqual(set(settings),set(models['NativeRecommendationSettings']['required']))
        self.assertEqual(settings['learning']['settingsRevision'],settings['revision']);self.assertFalse(settings['aiUsed'])
        self.assertEqual(settings['algorithm'],'explicit-rules-v1')
        cautions=self.expect(self.factory.native(credential,'/v1/social/cautions'),200)
        self.assertEqual(cautions['items'],[]);self.assertIsNone(cautions['nextCursor'])
        for value in (inbox,cautions):self.assertIsNotNone(datetime.fromisoformat(value['serverNow']).utcoffset())
        self.h.set_command_receiver(credential,False,self.factory.certificates[credential['grantId']])
        self.expect(self.factory.native(credential,'/v1/device/command-inbox'),403)
        for path in ('/v1/recommendations/settings','/v1/social/cautions'):
            self.expect(self.factory.native(credential,path),200)

if __name__=='__main__':unittest.main()
