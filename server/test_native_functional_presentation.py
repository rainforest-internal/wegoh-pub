import hashlib
import http.client
import json
import unittest

import psycopg
from private_records import VisitCipher
from native_functional_policy import WIRE, FunctionalError, validate_snapshot
from native_functional_presentation import HEADER, LEGACY_SHA256
import test_team_auth as fixture


LEGACY_PURPOSES = frozenset(('cautions:read', 'device-commands:receive', 'device-commands:request',
    'friends:manage', 'friends:read', 'history:read', 'history:write', 'missions:progress', 'missions:read',
    'recommendations:use', 'room-music:control', 'room-music:read', 'room-voice:receive', 'room-voice:transmit',
    'rooms:interact', 'rooms:read', 'vehicle-location:report', 'vehicle-reports:read', 'vehicle-visits:report'))
FIELDS = {'authorizationVersion', 'deviceId', 'grantId', 'revision', 'expiresAt', 'approvedPurposes',
          'functionalDisclosureVersion', 'functionalDisclosureSha256'}


class NativeFunctionalPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TeamTests.setUpClass()
        cls.addClassCleanup(fixture.TeamTests.tearDownClass)

    def setUp(self):
        self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp()
        self.owner=self.h.login()
        _,_,self.device=self.h.pair(self.owner)
        self.owner_path='/v1/devices/'+self.device['deviceId']+'/functional-permissions'
        self.current=self.h.call(self.owner_path,session=self.owner)[2]
        self.path='/v1/device/functional-permissions'

    def native(self, versions=(), *, path=None, method='GET', data=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.h.port,timeout=5)
        connection.putrequest(method,path or self.path,skip_host=True)
        for key,value in {'Host':'api.wegoh.invalid','Content-Type':'application/json',
                'Authorization':'Bearer '+self.device['accessToken'],
                'cf-cert-sha256':self.h._native_fingerprint,'cf-cert-presented':'true',
                'cf-cert-verified':'true','cf-cert-revoked':'false'}.items():
            connection.putheader(key,value)
        for version in versions:
            connection.putheader(HEADER,version)
        payload=json.dumps(data).encode() if data is not None else None
        if payload is not None:connection.putheader('Content-Length',str(len(payload)))
        connection.endheaders(payload)
        response=connection.getresponse();result=response.status,dict(response.getheaders()),json.loads(response.read())
        connection.close();return result

    def old_decoder(self, value):
        self.assertEqual(set(value),FIELDS)
        self.assertEqual(value['authorizationVersion'],1)
        self.assertEqual(value['deviceId'],self.device['deviceId'])
        self.assertEqual(value['grantId'],self.device['grantId'])
        self.assertIs(type(value['revision']),int)
        self.assertGreater(value['expiresAt'],0)
        self.assertLessEqual(value['expiresAt'],self.device['grantExpiresAt'])
        self.assertEqual(value['functionalDisclosureVersion'],2)
        self.assertEqual(value['functionalDisclosureSha256'],LEGACY_SHA256)
        self.assertEqual(value['approvedPurposes'],sorted(set(value['approvedPurposes'])))
        self.assertTrue(set(value['approvedPurposes'])<=LEGACY_PURPOSES)
        self.assertNotIn('driving-score:report',value['approvedPurposes'])

    def authority(self):
        with psycopg.connect(self.h.dsn) as conn:
            records=[(table,conn.execute('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY row_to_json(t)::text').fetchall())
                for table in ('native_v2_grants','native_v2_credentials','native_functional_authorizations')]
        return hashlib.sha256(json.dumps(records).encode()).hexdigest()

    def approve(self, enabled):
        current=self.h.call(self.owner_path,session=self.owner)[2]
        data={key:value for key,value in current.items() if key not in ('deviceId','expiresAt')}
        purposes=set(data['approvedPurposes'])
        if enabled:purposes.add('driving-score:report')
        else:purposes.discard('driving-score:report')
        data['approvedPurposes']=sorted(purposes)
        status,_,result=self.h.call(self.owner_path,data,'PUT',session=self.owner)
        self.assertEqual(status,200,result);return result

    def test_legacy_two_and_three_stay_frozen_and_internal_snapshot_is_five(self):
        before=self.authority()
        for versions in ((),('2',)):
            status,headers,result=self.native(versions)
            self.assertEqual(status,200,result)
            self.assertEqual(headers['cache-control'],'private, no-store')
            self.old_decoder(result)
        status,_,previous=self.native(('3',))
        self.assertEqual(status,200,previous)
        self.assertEqual(previous['functionalDisclosureVersion'],3)
        self.assertEqual(set(previous),FIELDS)
        self.assertEqual(previous['functionalDisclosureSha256'],'74e93e6fb3b374e627b572fe0a49de390fd276074a004f00a9ffac470964fe92')
        status,_,current=self.native(('5',))
        self.assertEqual(status,200,current)
        validate_snapshot({key:value for key,value in current.items() if key!='approvedDisclosureVersion'})
        self.assertEqual(current,dict(self.current,approvedDisclosureVersion=5))
        self.assertEqual(current['functionalDisclosureVersion'],5)
        with self.assertRaises(FunctionalError):validate_snapshot(self.native()[2])
        with self.assertRaises(FunctionalError):validate_snapshot(previous)
        self.assertEqual(self.authority(),before)
        service=fixture.TeamTests.module.TEAM_AUTH.functional_access
        self.assertEqual(service.owned_get(self.owner['user']['id'],self.device['deviceId'])['functionalDisclosureVersion'],5)

    def test_v4_presentation_stays_frozen_and_does_not_claim_a_new_approval(self):
        self.approve(True)
        before = self.authority()
        value = self.native(('4',))[2]
        old = next(row for row in WIRE['previousDisclosures'] if row['version'] == 4)
        self.assertEqual(value['functionalDisclosureVersion'], 4)
        self.assertEqual(value['functionalDisclosureSha256'], old['sha256'])
        self.assertIsNone(value['approvedDisclosureVersion'])
        self.assertEqual(self.authority(), before)

    def test_explicit_new_grant_is_hidden_from_legacy_without_modifying_authority_then_revokes(self):
        self.assertNotIn('driving-score:report',self.native(('3',))[2]['approvedPurposes'])
        approved=self.approve(True)
        before=self.authority()
        legacy=self.native()[2];self.old_decoder(legacy)
        current=self.native(('5',))[2]
        self.assertEqual(current,dict(approved,approvedDisclosureVersion=5))
        self.assertIn('driving-score:report',current['approvedPurposes'])
        self.assertEqual((legacy['revision'],legacy['expiresAt']),(current['revision'],current['expiresAt']))
        self.assertEqual(set(current['approvedPurposes'])-set(legacy['approvedPurposes']),{'driving-score:report'})
        self.assertEqual(self.authority(),before)
        removed=self.approve(False)
        self.assertGreater(removed['revision'],approved['revision'])
        self.assertNotIn('driving-score:report',self.native(('3',))[2]['approvedPurposes'])
        self.old_decoder(self.native()[2])

    def test_unknown_duplicate_and_noncanonical_profiles_fail_without_authority_mutation(self):
        before=self.authority()
        for versions in (('1',),('6',),('03',),('',),('2,3',),('3','3'),('2','3'),('5','5')):
            with self.subTest(versions=versions):
                status,_,value=self.native(versions)
                self.assertEqual((status,value),(400,dict(authorizationVersion=1,error='INVALID_FUNCTIONAL_PRESENTATION')))
        self.assertEqual(self.authority(),before)

    def test_command_receiver_has_no_nested_snapshot_in_either_profile(self):
        path='/v1/device/command-receiver'
        for versions in ((),('3',),('5',)):
            status,_,receiver=self.native(versions,path=path)
            self.assertEqual(status,200,receiver)
            self.assertEqual(set(receiver),{'deviceId','grantId','revision','enabled'})
        update={key:receiver[key] for key in ('grantId','revision')};update['enabled']=False
        status,_,changed=self.native((),path=path,method='PUT',data=update)
        self.assertEqual(status,200,changed)
        self.assertEqual(set(changed),{'deviceId','grantId','revision','enabled'})
        self.assertFalse(changed['enabled'])
        self.old_decoder(self.native()[2])
        validate_snapshot({key:value for key,value in self.native(('5',))[2].items() if key!='approvedDisclosureVersion'})

    def test_current_presentation_exposes_original_approval_without_read_or_delete_upgrade(self):
        approved=self.approve(True)
        grant=self.device['grantId']
        frozen=next(row for row in WIRE['previousDisclosures'] if row['version']==3)
        with psycopg.connect(self.h.dsn) as conn:
            raw=conn.execute('SELECT protected FROM native_functional_authorizations WHERE grant_id=%s',(grant,)).fetchone()[0]
            payload=VisitCipher().restore('native-functional',grant,raw)
            payload.update(functionalDisclosureVersion=3,functionalDisclosureSha256=frozen['sha256'])
            conn.execute('UPDATE native_functional_authorizations SET protected=%s WHERE grant_id=%s',
                (VisitCipher().protect('native-functional',grant,payload),grant))
        before=self.authority()
        self.assertEqual(self.native(('5',))[2]['approvedDisclosureVersion'],3)
        self.assertEqual(self.authority(),before)
        self.assertEqual(self.h.call(self.owner_path+'/driving-score:report',method='DELETE',session=self.owner)[0],200)
        self.assertEqual(self.native(('5',))[2]['approvedDisclosureVersion'],3)
        again=self.approve(True)
        self.assertGreater(again['revision'],approved['revision'])
        self.assertEqual(self.native(('5',))[2]['approvedDisclosureVersion'],5)
