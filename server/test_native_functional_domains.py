"""Current Native domain QA: isolated synthetic PG/trusted-edge metadata, not live TLS/OEM."""
import copy
import hashlib
import json
import unittest
import os
import socket
import secrets
from datetime import datetime,timezone
import test_team_auth as auth_fixture
import test_native_functional_business as current_fixture

class NativeFunctionalDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_voice=os.environ.get("WEGOH_VOICE_ENABLED")
        os.environ["WEGOH_VOICE_ENABLED"]="1"
        auth_fixture.TeamTests.setUpClass()
        __import__('api_application')
    @classmethod
    def tearDownClass(cls):
        auth_fixture.TeamTests.tearDownClass()
        if cls.previous_voice is None:os.environ.pop("WEGOH_VOICE_ENABLED",None)
        else:os.environ["WEGOH_VOICE_ENABLED"]=cls.previous_voice
    def setUp(self):
        self.factory=current_fixture.FunctionalBusinessTests('test_native_friend_request_respond_scope_withdrawal_and_original_authority')
        self.factory.setUp()
        self.h=self.factory.h
    def expect(self,result,status,label):
        self.assertEqual(result[0],status,label+': actual HTTP '+str(result[0]))
        return result[2]
    def test_account_recommendations_use_selected_place_without_enabling_history(self):
        from team_recommendations import DEFAULTS
        owner=self.h.login()
        credential=self.factory.connect(owner)
        base=self.factory.state()
        revision=self.factory.approve(owner,credential,[])
        settings=self.expect(self.factory.native(credential,'/v1/recommendations/settings'),200,'Owner reads account preferences')
        body=dict(functionalRevision=revision,settingsRevision=settings['revision'],
            anchor=dict(kind='selected-place',place=dict(id='synthetic-selected',provider='map',name='Synthetic selected place',address='',latitude=37.5,longitude=127.0)),
            preferences=copy.deepcopy(DEFAULTS),dismissed=[])
        result=self.expect(self.factory.native(credential,'/v1/recommendations/query',body,'POST'),200,'Owner queries with a selected place')
        self.assertFalse(result['historyUsed'])
        self.assertEqual(result['anchor']['kind'],'selected-place')
        self.assertEqual(self.factory.state(),base,'Base authority remains unchanged')

    def room(self,owner,voice=False,who='alice'):
        body=dict(name='Synthetic Native domain room',courseId=None,courseVersion=None,expiresInHours=1)
        room=self.expect(self.h.call('/v1/social/rooms',body,'POST',session=owner,who=who),201,'Browser-owned synthetic room')
        flags={key:(voice if key=='voice' else key=='status')for key in ('status','location','visits','music','voice','control')}
        self.expect(self.h.call('/v1/social/rooms/'+room['id']+'/consents',dict(consents=flags),'PATCH',session=owner,who=who),200,'Explicit Browser room choices only')
        return room
    def receiver(self,credential,enabled):
        self.h.set_command_receiver(credential,enabled,self.factory.certificates[credential['grantId']])

    def test_commands_current_principal_explicit_purpose_and_target_reference(self):
        self.assertTrue(self.h.module.TEAM_AUTH.enabled)
        self.assertTrue(self.h.module.TEAM_DEVICE_COMMANDS.enabled)
        print('QA_FEATURE commands auth=true service=true',flush=True)
        owner=self.h.login();credential=self.factory.connect(owner);base=self.factory.state()
        self.receiver(credential,False)
        self.expect(self.factory.native(credential,'/v1/device/command-inbox'),403,'No receive purpose denies inbox')
        self.receiver(credential,True)
        inbox=self.expect(self.factory.native(credential,'/v1/device/command-inbox'),200,'Current Native receiver reads own inbox')
        self.assertEqual(inbox['requests'],[],'No room/device command permission may be inherited')
        path='/v1/devices/'+credential['deviceId']+'/command-access'
        self.expect(self.h.call(path,session=owner),200,'Owner config can resolve current Native target without legacy row')
        self.receiver(credential,False)
        self.expect(self.factory.native(credential,'/v1/device/command-inbox'),403,'Receive withdrawal denies inbox')
        self.receiver(credential,True)
        self.assertEqual(self.expect(self.factory.native(credential,'/v1/device/command-inbox'),200,'Reapproved global purpose has no old delivery')['requests'],[])
        self.assertEqual(self.factory.state(),base)
    def test_missions_current_principal_separate_grant_and_participation(self):
        self.assertTrue(self.h.module.TEAM_AUTH.enabled)
        self.assertTrue(self.h.module.TEAM_MISSIONS.enabled)
        print('QA_FEATURE missions auth=true service=true',flush=True)
        owner=self.h.login();credential=self.factory.connect(owner);room=self.room(owner);rid=room['id'];path='/v1/native/rooms/'+rid+'/missions'
        self.assertEqual(self.expect(self.factory.native(credential,path),200,'Member reads the filtered mission list')['missions'],[])
        report=path+'/'+'a'*32+'/progress'
        revision=self.factory.approve(owner,credential,[])
        body=dict(eventId='b'*32,checkpoint=1,participationRevision=1,functionalRevision=revision)
        self.expect(self.factory.native(credential,report,body,'POST'),403,'Reading missions does not grant reporting')
        body['functionalRevision']=self.factory.approve(owner,credential,['missions:progress'])
        self.expect(self.factory.native(credential,report,body,'POST'),404,'Unknown mission cannot become participation')
    def test_cautions_current_principal_reads_own_record(self):
        owner=self.h.login();credential=self.factory.connect(owner);base=self.factory.state();path='/v1/social/cautions'
        self.factory.approve(owner,credential,[])
        self.assertEqual(self.expect(self.factory.native(credential,path),200,'Owner starts with no cautions')['items'],[])
        body=dict(eventId=secrets.token_hex(16),kind='road-surface',observedAt=datetime.now(timezone.utc).isoformat(),placeSource=dict(kind='selected-place',place=dict(id='synthetic-public-place',provider='map',name='Synthetic explicit place',address='',latitude=37.5,longitude=127.0)),publicPlaceConfirmed=True,storageConsent=True,rightsConfirmed=True)
        item=self.expect(self.h.call(path,body,'POST',session=owner),201,'Explicit Browser original caution')
        self.expect(self.factory.native(credential,path+'/'+item['id']),200,'Native owner reads owned caution')
        self.assertEqual(self.factory.state(),base)
    def voice_status(self,credential,room,snapshot):
        from websockets.sync.client import connect
        from websockets.exceptions import InvalidStatus
        raw=socket.create_connection(('127.0.0.1',self.h.port),timeout=3)
        cert=self.factory.certificates[credential['grantId']]
        headers={'Authorization':'Bearer '+credential['accessToken'],'cf-cert-sha256':cert,'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'}
        headers.update({'X-WegoH-Functional-Revision':str(snapshot['functionalRevision']),
                        'X-WegoH-Room-Voice-Revision':str(snapshot['revision'])})
        try:
            with connect('ws://api.wegoh.invalid/v1/social/rooms/'+room+'/voice',sock=raw,additional_headers=headers,origin=None,open_timeout=3,close_timeout=1)as stream:
                return 101
        except InvalidStatus as error:return error.response.status_code
        finally:raw.close()
    def test_voice_requires_room_device_consent_before_opening_channel(self):
        owner=self.h.login()
        car=self.factory.connect(owner)
        room=self.room(owner,voice=True)['id']
        self.factory.approve(owner,car,['room-voice:receive','room-voice:transmit'])
        path='/v1/devices/'+car['deviceId']+'/rooms/'+room+'/voice-permissions'
        current=self.expect(self.h.call(path,session=owner),200,'Owner reads vehicle voice settings')
        self.assertEqual(self.voice_status(car,room,current),403,'Room membership alone cannot open the vehicle channel')
        update={k:v for k,v in current.items()if k not in ('deviceId','roomId','expiresAt')}
        update['permissions']=dict(receiveVoice=True,transmitVoice=False)
        approved=self.expect(self.h.call(path,update,'PUT',session=owner),200,'Owner enables listening for this vehicle and room')
        self.assertEqual(self.voice_status(car,room,approved),101,'Vehicle can open the approved channel')

    def test_populated_command_claim_ack_and_directional_withdrawal(self):
        import psycopg
        from test_team_device_commands import FixtureRegistry,ACTION
        service=self.h.module.TEAM_DEVICE_COMMANDS;previous=service.registry;service.registry=FixtureRegistry();self.addCleanup(lambda:setattr(service,'registry',previous))
        a,e,b=self.h.login(),self.h.login('eve'),self.h.login('bob')
        receiver=self.factory.connect(a)
        sender=receiver
        other=self.factory.connect(b,'bob')
        base=self.factory.state()
        ra=rb=self.factory.approve(a,receiver,['device-commands:request'])
        room=self.room(a)
        path='/v1/social/rooms/'+room['id']
        d='/v1/devices/'+receiver['deviceId']+'/command-access'
        m=path+'/device-command-access'
        g=path+'/device-command-grants/'+receiver['deviceId']+'/'+a['user']['id']
        q=path+'/device-requests'
        self.expect(self.h.call(d,session=e,who='eve'),404,'Other owner cannot read target access')
        def allow(owner=a,credential=receiver,target_room=room,who='alice'):
            target='/v1/devices/'+credential['deviceId']+'/command-access'
            participant='/v1/social/rooms/'+target_room['id']+'/device-command-access'
            target_grant='/v1/social/rooms/'+target_room['id']+'/device-command-grants/'+credential['deviceId']+'/'+owner['user']['id']
            options=dict(session=owner,who=who)
            old=self.expect(self.h.call(target,**options),200,'Current target owner read')
            access=self.expect(self.h.call(target,dict(revision=old['revision'],consent=True,expiresInHours=1,actions=[ACTION]),'PUT',**options),200,'Explicit receive device access')
            member=self.expect(self.h.call(participant,**options),200,'Requester participation read')
            member=self.expect(self.h.call(participant,dict(revision=member['revision'],joinedAt=member['currentJoinedAt'],consent=True,expiresInHours=1,actions=[ACTION]),'PUT',**options),200,'Explicit requester room participation')
            snapshot=self.expect(self.h.call(participant,**options),200,'Owner room context read')
            old=next((x for x in snapshot['grants'] if x['deviceId']==credential['deviceId'] and x['requesterId']==owner['user']['id']),{'revision':0})
            return self.expect(self.h.call(target_grant,dict(revision=old['revision'],deviceRevision=access['revision'],participationRevision=member['revision'],ownerJoinedAt=snapshot['currentJoinedAt'],requesterJoinedAt=member['joinedAt'],consent=True,expiresInHours=1,actions=[ACTION]),'PUT',**options),200,'Explicit target-to-requester grant')
        grant=allow()
        def create():
            body=dict(functionalRevision=rb,eventId=secrets.token_hex(16),targetDeviceId=receiver['deviceId'],grantRevision=grant['revision'],capabilityId=ACTION['id'],capabilityRevision=1,arguments={},expiresInSeconds=60)
            self.expect(self.factory.native(sender,q,dict(body,functionalRevision=rb+1),'POST'),409,'Stale FR rejected before command write')
            return self.expect(self.factory.native(sender,q,body,'POST'),201,'Current Native requester queued synthetic no-effect action')
        item=create();identifier=item['id'];self.assertFalse(item['physicalExecutionVerified'])
        inbox=self.expect(self.factory.native(receiver,'/v1/device/command-inbox'),200,'Populated receiver inbox');self.assertEqual([x['id']for x in inbox['requests']],[identifier])
        claim='/v1/device/requests/'+identifier+'/claim';claim_body=dict(functionalRevision=ra,claimId=secrets.token_hex(16))
        self.expect(self.h.native(claim,claim_body,'POST',token=receiver['accessToken'],certificate=self.factory.certificates[other['grantId']]),401,'Other key cannot claim')
        lease=self.expect(self.factory.native(receiver,claim,claim_body,'POST'),200,'Native target claims exact request');self.assertEqual(lease['stage'],'delivered');self.assertTrue(lease['mayHaveExecuted']);self.assertFalse(lease['physicalExecutionVerified'])
        self.assertEqual(self.expect(self.factory.native(receiver,claim,claim_body,'POST'),200,'Same claim receipt')['leaseId'],lease['leaseId'])
        ack='/v1/device/requests/'+identifier+'/ack';ack_body=dict(functionalRevision=ra,ackId=secrets.token_hex(16),leaseId=lease['leaseId'],stage='received',evidence={})
        received=self.expect(self.factory.native(receiver,ack,ack_body,'POST'),200,'Synthetic received ACK only');self.assertEqual(received['stage'],'received');self.assertFalse(received['physicalExecutionVerified'])
        self.assertEqual(self.expect(self.factory.native(receiver,ack,ack_body,'POST'),200,'Exact ACK replay')['stage'],'received');self.expect(self.factory.native(receiver,ack,dict(ack_body,stage='unknown'),'POST'),409,'Different ACK under same event rejected')
        queued=create();self.receiver(receiver,False)
        with psycopg.connect(self.h.dsn)as conn:
            first=service.restore('request',identifier,conn.execute('SELECT protected FROM team_device_commands WHERE request_id=%s',(identifier,)).fetchone()[0]);second=service.restore('request',queued['id'],conn.execute('SELECT protected FROM team_device_commands WHERE request_id=%s',(queued['id'],)).fetchone()[0])
            self.assertEqual(first['stage'],'unknown');self.assertIsNone(first['leaseHash']);self.assertEqual(second['stage'],'cancelled');self.assertIsNone(second['leaseHash'])
        self.receiver(receiver,True);self.assertEqual(self.expect(self.factory.native(receiver,'/v1/device/command-inbox'),200,'Receive reapproval does not restore delivery')['requests'],[])
        self.expect(self.factory.native(receiver,ack,dict(ack_body,functionalRevision=ra),'POST'),409,'Paused receiver cannot reuse an invalidated lease')
        grant=allow();queued=create();claimed=create();claimed_lease=self.expect(self.factory.native(receiver,'/v1/device/requests/'+claimed['id']+'/claim',dict(functionalRevision=ra,claimId=secrets.token_hex(16)),'POST'),200,'Claimed sender-origin operation')
        other_revision=self.factory.approve(b,other,['device-commands:request'],'bob')
        other_room=self.room(b,who='bob');other_grant=allow(b,other,other_room,'bob');other_requests='/v1/social/rooms/'+other_room['id']+'/device-requests'
        other_body=dict(functionalRevision=other_revision,eventId=secrets.token_hex(16),targetDeviceId=other['deviceId'],grantRevision=other_grant['revision'],capabilityId=ACTION['id'],capabilityRevision=1,arguments={},expiresInSeconds=60)
        other_item=self.expect(self.factory.native(other,other_requests,other_body,'POST'),201,'Independent account installation request')
        browser_body={k:v for k,v in other_body.items()if k!='functionalRevision'};browser_body.update(eventId=secrets.token_hex(16),targetDeviceId=receiver['deviceId'],grantRevision=grant['revision']);browser_item=self.expect(self.h.call(q,browser_body,'POST',session=a),201,'Independent explicit Browser request')
        with psycopg.connect(self.h.dsn)as conn:unchanged={i:conn.execute('SELECT protected FROM team_device_commands WHERE request_id=%s',(i,)).fetchone()[0]for i in(other_item['id'],browser_item['id'])}
        self.factory.approve(a,sender,[])
        for identifier,original in unchanged.items():
            with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT protected FROM team_device_commands WHERE request_id=%s',(identifier,)).fetchone()[0],original)
        inbox=self.expect(self.factory.native(other,'/v1/device/command-inbox'),200,'Other account receiver preserves independent request');self.assertEqual({x['id']for x in inbox['requests']},{other_item['id']})
        with psycopg.connect(self.h.dsn)as conn:
            queued_state=service.restore('request',queued['id'],conn.execute('SELECT protected FROM team_device_commands WHERE request_id=%s',(queued['id'],)).fetchone()[0]);claimed_state=service.restore('request',claimed['id'],conn.execute('SELECT protected FROM team_device_commands WHERE request_id=%s',(claimed['id'],)).fetchone()[0])
            self.assertEqual(queued_state['stage'],'cancelled');self.assertFalse(queued_state['mayHaveExecuted']);self.assertEqual(claimed_state['stage'],'unknown');self.assertTrue(claimed_state['mayHaveExecuted']);self.assertIsNone(claimed_state['leaseHash'])
        ra=rb=self.factory.approve(a,sender,['device-commands:request']);grant=allow()
        self.assertEqual(self.expect(self.factory.native(receiver,'/v1/device/command-inbox'),200,'Fresh receiver binding cannot resurrect old origins')['requests'],[])
        with psycopg.connect(self.h.dsn)as conn:
            self.assertEqual(conn.execute('SELECT protected FROM team_device_commands WHERE request_id=%s',(other_item['id'],)).fetchone()[0],unchanged[other_item['id']])
        self.expect(self.factory.native(receiver,'/v1/device/requests/'+claimed['id']+'/ack',dict(functionalRevision=ra,ackId=secrets.token_hex(16),leaseId=claimed_lease['leaseId'],stage='received',evidence={}), 'POST'),409,'Withdrawn claimed lease is unknown, never an undone physical operation')
        self.assertEqual(self.factory.state(),base,'Original base/key/grant/cipher authority preserved')

    def test_populated_mission_participation_device_grant_progress_and_reapproval(self):
        import psycopg
        from test_team_missions import MissionsTests
        setup=MissionsTests('test_01_exact_fields_owner_csrf_and_no_implicit_participation');setup.setUp();a,b,e,room,relative,mission=setup.prepare(start=True)
        self.h=setup.h;self.factory.h=self.h;ca,cb=self.factory.connect(a),self.factory.connect(b,'bob');base=self.factory.state();rid=room['id'];mid=mission['id'];web='/v1/social/rooms/'+rid+'/missions';native='/v1/native/rooms/'+rid+'/missions'
        purposes=['rooms:read','missions:read','missions:progress'];ra=self.factory.approve(a,ca,purposes);rb=self.factory.approve(b,cb,purposes,'bob')
        self.assertEqual(self.expect(self.factory.native(ca,native),200,'Active mission is not an implicit device grant')['missions'],[])
        path=web+'/'+mid+'/devices/'+ca['deviceId'];device_list=web+'/'+mid+'/devices'
        def current():return self.expect(self.h.call(web,session=a),200,'Current owner mission')['missions'][0]
        def completed(value):return next(x['completedCheckpoints']for x in value['participants']if x['accountId']==a['user']['id'])
        person=current()['participation'];body=dict(functionalRevision=ra,eventId=secrets.token_hex(16),checkpoint=1,participationRevision=person['revision'])
        self.expect(self.factory.native(ca,native+'/'+mid+'/progress',body,'POST'),403,'Explicit device mission grant required')
        def grant():
            own=self.expect(self.h.call(device_list,session=a),200,'Current credential-free device choices');entry=next(x for x in own['devices']if x['deviceId']==ca['deviceId']);payload=dict(revision=entry['revision'],consent=True,expiresInHours=1,participationRevision=current()['participation']['revision'])
            self.expect(self.h.call(path,payload,'PUT',session=a,csrf=False),403,'Phone CSRF remains required')
            other_person=self.expect(self.h.call(web,session=b,who='bob'),200,'Other participant own revision')['missions'][0]['participation']
            self.expect(self.h.call(path,dict(payload,participationRevision=other_person['revision']),'PUT',session=b,who='bob'),404,'Other owner cannot grant device')
            return self.expect(self.h.call(path,payload,'PUT',session=a),200,'Separate current owner device mission consent')
        grant();self.assertEqual([x['id']for x in self.expect(self.factory.native(ca,native),200,'Granted Native mission')['missions']],[mid]);self.assertEqual(self.expect(self.factory.native(cb,native),200,'Other participant device has no inherited grant')['missions'],[])
        self.expect(self.factory.native(cb,native+'/'+mid+'/progress',dict(body,functionalRevision=rb),'POST'),403,'Other participant device lacks separate grant')
        self.expect(self.factory.native(ca,native+'/'+mid+'/progress',dict(body,functionalRevision=ra+1),'POST'),409,'Stale functional revision cannot write progress')
        self.expect(self.h.native(native+'/'+mid+'/progress',body,'POST',token=ca['accessToken'],certificate=self.factory.certificates[cb['grantId']]),401,'Other key cannot report')
        first=self.expect(self.factory.native(ca,native+'/'+mid+'/progress',body,'POST'),200,'Explicit checkpoint report');self.assertEqual(completed(first),1);self.assertFalse(first['physicalArrivalVerified']);self.assertEqual(first['confirmationSource'],'user-confirmed')
        self.assertEqual(completed(self.expect(self.factory.native(ca,native+'/'+mid+'/progress',body,'POST'),200,'Same event idempotent')),1)
        self.expect(self.factory.native(ca,native+'/'+mid+'/progress',dict(body,checkpoint=2),'POST'),409,'Different event payload rejected')
        self.factory.approve(a,ca,['rooms:read','missions:read']);self.expect(self.factory.native(ca,native+'/'+mid+'/progress',body,'POST'),403,'Progress-purpose withdrawal denies reporting')
        ra=self.factory.approve(a,ca,purposes);self.assertEqual(self.expect(self.factory.native(ca,native),200,'Global reapproval does not restore device mission grant')['missions'],[])
        self.expect(self.factory.native(ca,native+'/'+mid+'/progress',dict(body,functionalRevision=ra,eventId=secrets.token_hex(16),checkpoint=2,participationRevision=current()['participation']['revision']),'POST'),403,'Old room grant cannot revive')
        grant();person=current()['participation'];second=self.expect(self.factory.native(ca,native+'/'+mid+'/progress',dict(functionalRevision=ra,eventId=secrets.token_hex(16),checkpoint=2,participationRevision=person['revision']),'POST'),200,'Fresh owner consent permits next report');self.assertEqual(completed(second),2);self.assertFalse(second['physicalArrivalVerified'])
        self.assertEqual(self.factory.state(),base,'Base key/grant/epoch/absolute expiry/cipher preserved')
        with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*) FROM team_mission_events WHERE mission_id=%s AND account_id=%s',(mid,a['user']['id'])).fetchone()[0],2)

    def test_recommendation_learning_query_feedback_location_and_withdrawal(self):
        import psycopg
        from team_recommendations import DEFAULTS
        a,b=self.h.login(),self.h.login('bob');ca,cb=self.factory.connect(a),self.factory.connect(b,'bob');base=self.factory.state();ra=self.factory.approve(a,ca,['recommendations:use']);rb=self.factory.approve(b,cb,['recommendations:use'],'bob')
        path='/v1/recommendations';settings=self.expect(self.h.call(path+'/settings',session=a),200,'Browser settings has original seven fields');self.assertEqual(len(settings),7)
        configured=self.expect(self.h.call(path+'/settings',dict(revision=settings['revision'],preferences=copy.deepcopy(DEFAULTS),permissions=dict(useHistory=False,useFeedback=True)),'PUT',session=a),200,'Separate account feedback use consent')
        native=self.expect(self.factory.native(ca,path+'/settings'),200,'Native coherent settings and learning read');self.assertEqual(set(native)-set(configured),{'learning'});self.assertFalse(native['learning']['enabled']);self.assertEqual(native['learning']['settingsRevision'],native['revision'])
        self.assertEqual(set(native['learning']),{'enabled','learningRevision','settingsRevision','modelVersion','status','eligibleSamples'})
        self.expect(self.factory.native(ca,path+'/learning',dict(functionalRevision=ra,revision=0,recommendationRevision=native['revision'],consent=True),'PUT'),404,'Account learning approval has no Native route')
        with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*) FROM team_recommendation_learning').fetchone()[0],0,'Denied Native request must not create learning consent')
        learning=self.expect(self.h.call(path+'/learning',session=a),200,'Browser current learning state')
        enabled=self.expect(self.h.call(path+'/learning',dict(revision=learning['learningRevision'],recommendationRevision=native['revision'],consent=True),'PUT',session=a),200,'Explicit Browser learning consent')
        native=self.expect(self.factory.native(ca,path+'/settings'),200,'Native gets actual learning generation');self.assertTrue(native['learning']['enabled']);self.assertEqual(native['learning']['learningRevision'],enabled['learningRevision']);self.assertEqual(native['revision'],native['learning']['settingsRevision'])
        pack=self.h.pack();self.expect(self.h.publish(pack,a),201,'Synthetic owned course');self.expect(self.h.approve(pack,a),200,'Actual current approved course')
        query=dict(functionalRevision=ra,settingsRevision=native['revision'],anchor=dict(kind='selected-place',place=dict(id='synthetic-explicit-place',provider='map',name='Synthetic selected place',address='',latitude=37.5,longitude=127.0)),preferences=copy.deepcopy(DEFAULTS),dismissed=[],learningRevision=native['learning']['learningRevision'])
        self.expect(self.factory.native(ca,path+'/query',dict(query,functionalRevision=ra+1),'POST'),409,'Stale functional revision cannot process query')
        response=self.expect(self.factory.native(ca,path+'/query',query,'POST'),200,'Explicit learning-mode query; not enough samples is not trained AI');self.assertFalse(response['aiUsed']);self.assertEqual(response['anchor']['kind'],'selected-place')
        feedback=dict(functionalRevision=ra,revision=native['revision'],kind='course',id=pack['id'],version=pack['version'],response='like',learningRevision=native['learning']['learningRevision'])
        self.expect(self.factory.native(cb,path+'/feedback',dict(feedback,functionalRevision=rb),'POST'),409,'Other account cannot borrow the owner settings generation')
        learned=self.expect(self.factory.native(ca,path+'/feedback',feedback,'POST'),200,'Explicit current learning feedback');self.assertGreater(learned['learningRevision'],feedback['learningRevision'])
        def saved():
            with psycopg.connect(self.h.dsn)as conn:return {n:conn.execute('SELECT row_to_json(t)::text FROM '+n+' t ORDER BY row_to_json(t)::text').fetchall()for n in('team_recommendations','team_recommendation_learning')}
        original=saved();native=self.expect(self.factory.native(ca,path+'/settings'),200,'Eligible sample read under real row locks');self.assertEqual(native['learning']['eligibleSamples'],1);self.assertEqual(native['revision'],native['learning']['settingsRevision']);self.assertEqual(saved(),original,'Coherent GET performs no business DML')
        point=dict(kind='device-location',consent=True,position=dict(latitude=37.5,longitude=127.0,accuracyMeters=12,capturedAt=datetime.now(timezone.utc).isoformat()))
        device_query=dict(query,settingsRevision=native['revision'],learningRevision=native['learning']['learningRevision'],anchor=point)
        self.expect(self.factory.native(ca,path+'/query',dict(device_query,anchor=dict(point,consent=False)),'POST'),400,'Per-query location consent required')
        self.expect(self.factory.native(ca,path+'/query',dict(device_query,anchor=dict(point,kind='browser-location')),'POST'),400,'Native cannot claim Browser location provenance')
        response=self.expect(self.factory.native(ca,path+'/query',device_query,'POST'),200,'Explicit reported device location only');self.assertEqual(response['anchor']['kind'],'device-reported');self.assertFalse(response['historyUsed']);self.assertTrue(response['unsupported']['roadRouting']);self.assertEqual(saved(),original,'Location query does not persist anchor or train implicitly')
        self.expect(self.h.call(path+'/learning',method='DELETE',session=a),200,'Browser explicit learning withdrawal');current=self.expect(self.factory.native(ca,path+'/settings'),200,'Current learning tombstone view');self.assertFalse(current['learning']['enabled']);self.assertEqual(current['learning']['eligibleSamples'],0)
        self.expect(self.factory.native(ca,path+'/query',dict(device_query,settingsRevision=current['revision']),'POST'),409,'Old learning generation rejected after account withdrawal')
        before=saved()
        denied=self.factory.native(ca,path+'/query',dict(device_query,functionalRevision=self.factory.approve(a,ca,[]),settingsRevision=current['revision']),'POST')
        self.expect(denied,409,'Account access cannot restore withdrawn learning consent')
        self.assertEqual(saved(),before,'Denied query preserves settings and learning tombstones')
        self.assertEqual(self.factory.state(),base,'Base authority/expiry/cipher unchanged')

    def test_caution_native_cursor_recipient_review_and_withdrawal(self):
        import psycopg
        from urllib.parse import quote
        from starlette.websockets import WebSocket
        from native_functional_query import native_query_allowed
        a,b=self.h.login(),self.h.login('bob');ca,cb=self.factory.connect(a),self.factory.connect(b,'bob');base=self.factory.state();self.factory.approve(a,ca,['cautions:read']);self.factory.approve(b,cb,['cautions:read'],'bob');path='/v1/social/cautions'
        def body():return dict(eventId=secrets.token_hex(16),kind='road-surface',observedAt=datetime.now(timezone.utc).isoformat(),placeSource=dict(kind='selected-place',place=dict(id='synthetic-public-place',provider='map',name='Synthetic explicit public place',address='',latitude=37.5,longitude=127.0)),publicPlaceConfirmed=True,storageConsent=True,rightsConfirmed=True)
        first_body=body();first=self.expect(self.h.call(path,first_body,'POST',session=a),201,'Explicit Browser caution original');item=first['id'];service=self.h.module.TEAM_CAUTIONS
        # Seed only extra pagination records via the same real domain validator,
        # not an API rate-limit override or an HTTP creation-success claim.
        identifiers={item}
        with psycopg.connect(self.h.dsn)as conn:
            for _ in range(50):status,created=service.create(conn,a['user']['id'],body());self.assertEqual(status,201);identifiers.add(created['id'])
            originals={i:conn.execute('SELECT protected FROM team_cautions WHERE caution_id=%s',(i,)).fetchone()[0]for i in identifiers}
        page=self.expect(self.factory.native(ca,path),200,'Native owned first page');self.assertEqual(len(page['items']),50);self.assertTrue(page['nextCursor']);cursor=page['nextCursor'];tail=self.expect(self.factory.native(ca,path+'?cursor='+quote(cursor,safe='')),200,'Exact Native cursor reads last record');self.assertEqual(len(tail['items']),1);self.assertIsNone(tail['nextCursor']);self.assertEqual({x['id']for x in page['items']+tail['items']},identifiers)
        for suffix in ('?cursor='+cursor+'&cursor='+cursor,'?other=x','?eventId='+first_body['eventId'],'?access_token=synthetic','?cursor=not-valid'):
            denied=self.expect(self.factory.native(ca,path+suffix),400,'Unknown/duplicate/credential/bad Native selector rejected at current request boundary');print('SYNTHETIC_CAUTION_QUERY_DENIAL_KEYS',sorted(denied),flush=True);self.assertEqual(denied,{'detail':'INVALID_REQUEST'})
        self.assertEqual(self.expect(self.factory.native(cb,path),200,'Other owner list has no private records')['items'],[]);self.expect(self.factory.native(cb,path+'/'+item),404,'Other owner cannot read private caution')
        self.expect(self.h.call('/v1/social/friends/requests',dict(targetId=b['user']['id']),'POST',session=a),201,'Friend request');self.expect(self.h.call('/v1/social/friends/requests/'+a['user']['id']+'/respond',dict(accept=True),'POST',session=b,who='bob'),200,'Friend acceptance')
        review=self.expect(self.h.call(path+'/'+item+'/review-request',dict(revision=1,consent=True),'PATCH',session=a),200,'Explicit exact caution review request')['review']
        self.expect(self.h.call('/v1/moderation/content/caution/'+item,dict(checksum=review['checksum'],decision='approved',reviewer='Synthetic admin',reviewNote='Synthetic selected public place and observation only'),'POST',session=a),200,'Synthetic reviewed projection')
        shares=self.expect(self.h.call(path+'/'+item+'/shares',session=a),200,'Current owner share revision');share=path+'/'+item+'/shares/'+b['user']['id'];permission=dict(revision=shares['revision'],permissionRevision=shares['permissionRevision'],consent=True,expiresInHours=1,rightsConfirmed=True)
        self.expect(self.factory.native(ca,share,dict(permission,functionalRevision=1),'PUT'),404,'Native caution read does not grant Browser share mutation')
        self.expect(self.h.call(share,permission,'PUT',session=a),200,'Explicit owner-to-recipient current share')
        shared=self.expect(self.factory.native(cb,path+'/'+item),200,'Current Native recipient sees reviewed projection');self.assertFalse(shared['own']);self.assertIsNone(shared['permissionRevision']);self.assertNotIn('placeSource',shared);self.assertFalse(shared['source']['physicalMeasurementVerified']);self.assertFalse(shared['currentRoadConditionVerified'])
        self.expect(self.h.call(share,method='DELETE',session=a),200,'Explicit share withdrawal');self.expect(self.factory.native(cb,path+'/'+item),404,'Recipient immediately denied after share withdrawal')
        self.factory.approve(b,cb,[],'bob')
        self.expect(self.factory.native(cb,path+'/'+item),404,'Account read access cannot restore a withdrawn share')
        async def receive():return {'type':'websocket.disconnect'}
        async def send(message):pass
        for query,allowed in ((b'',True),(b'cursor='+cursor.encode(),False),(b'token=synthetic',False)):
            socket=WebSocket(dict(type='websocket',scheme='wss',path='/v1/events',root_path='',query_string=query,headers=[],server=('api.wegoh.invalid',443),client=('127.0.0.1',1234)),receive,send);self.assertEqual(native_query_allowed(socket),allowed)
        self.expect(self.factory.native(ca,path+'/'+item),200,'Owner retains access to the original')
        with psycopg.connect(self.h.dsn)as conn:
            for i,raw in originals.items():self.assertEqual(conn.execute('SELECT protected FROM team_cautions WHERE caution_id=%s',(i,)).fetchone()[0],raw)
        self.assertEqual(self.factory.state(),base,'Base authority and original expiry/cipher preserved')

if __name__=='__main__':unittest.main()

