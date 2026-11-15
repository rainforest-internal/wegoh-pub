import unittest

import psycopg
from private_records import VisitCipher
import test_iphone_session as fixture


class IPhoneFunctionalPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.addClassCleanup(fixture.IphoneSessionTests.doClassCleanups)
        fixture.IphoneSessionTests.setUpClass()

    def setUp(self):
        self.phone=fixture.IphoneSessionTests();self.phone.setUp()
        self.owner=self.phone.login();self.other=self.phone.login(who='bob')
        web=self.phone.api.login()
        _,_,self.vehicle=self.phone.api.pair(web)
        self.path='/v1/iphone/vehicles/'+self.vehicle['deviceId']+'/functional-permissions'

    def call(self, body=None, method='GET', *, owner=None, **kwargs):
        return self.phone.iphone(self.path,body,method,token=(owner or self.owner)['accessToken'],**kwargs)

    def get(self):
        status,headers,value=self.call()
        self.assertEqual(status,200,value)
        self.assertEqual(self.phone.header(headers,'cache-control'),'private, no-store')
        return value

    def body(self, envelope):
        return {k:v for k,v in envelope['authorization'].items() if k not in ('deviceId','expiresAt')}

    def test_explicit_consent_retains_readonly_and_does_not_autogrant(self):
        value=self.get()
        self.assertEqual(set(value),{'authorization','disclosure','readOnlyPurposes','approvedDisclosureVersion'})
        self.assertEqual(value['approvedDisclosureVersion'],5)
        self.assertEqual(value['disclosure']['version'],5)
        self.assertEqual(value['authorization']['functionalDisclosureSha256'],value['disclosure']['sha256'])
        option=next(row for row in value['disclosure']['purposes'] if row['id']=='driving-score:report')
        self.assertFalse(option['default'])
        self.assertNotIn('driving-score:report',value['authorization']['approvedPurposes'])
        self.assertIn('device-commands:receive',value['readOnlyPurposes'])
        request=self.body(value)
        request['approvedPurposes']=sorted(request['approvedPurposes']+['driving-score:report'])
        status,_,saved=self.call(request,'PUT')
        self.assertEqual(status,200,saved)
        self.assertIn('driving-score:report',saved['authorization']['approvedPurposes'])
        self.assertGreater(saved['authorization']['revision'],request['revision'])
        self.assertEqual(self.call(request,'PUT')[0],409)
        request=self.body(saved);request['approvedPurposes'].remove('driving-score:report')
        self.assertEqual(self.call(request,'PUT')[0],200)
        self.assertNotIn('driving-score:report',self.get()['authorization']['approvedPurposes'])

    def test_owner_scope_query_closed_body_and_vehicle_only_receiver(self):
        self.assertEqual(self.call(owner=self.other)[0],404)
        request=self.body(self.get())
        self.assertEqual(self.call(dict(request,deviceId=self.vehicle['deviceId']),'PUT')[0],400)
        self.assertEqual(self.call(dict(request,functionalDisclosureVersion=2),'PUT')[0],409)
        request['approvedPurposes']=[p for p in request['approvedPurposes'] if p!='device-commands:receive']
        self.assertEqual(self.call(request,'PUT')[0],403)
        self.assertEqual(self.phone.iphone(self.path+'?token=x',token=self.owner['accessToken'])[0],400)
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute("UPDATE iphone_sessions SET scopes=ARRAY['account:read'] WHERE account_id=%s",(self.owner['user']['id'],))
        self.assertEqual(self.call()[0],403)
        self.assertEqual(self.call(self.body(dict(authorization=request)),'PUT')[0],403)

    def test_old_disclosure_read_compatibility_never_expands_new_purpose(self):
        device=self.vehicle
        old=dict(approvedPurposes=['rooms:read'],functionalDisclosureVersion=2,
                 functionalDisclosureSha256='ec92f07e28aa015408006bd5430f9d9b440870238fabc9393c176c263d4e6657')
        raw=VisitCipher().protect('native-functional',device['grantId'],old)
        self.get()
        with psycopg.connect(self.phone.api.dsn) as conn:
            conn.execute('UPDATE native_functional_authorizations SET protected=%s WHERE grant_id=%s',(raw,device['grantId']))
        current=self.get()
        self.assertEqual(current['authorization']['functionalDisclosureVersion'],5)
        self.assertNotIn('driving-score:report',current['authorization']['approvedPurposes'])
