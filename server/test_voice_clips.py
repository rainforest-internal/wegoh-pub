"""Whole-message voice contracts with bounded RAM and disposable HTTP accounts."""
import base64
import os
import secrets
import time
import unittest
from unittest.mock import patch

import psycopg
from fastapi import HTTPException
from team_voice_clips import VoiceClipMemory
import test_iphone_trips as fixture


class VoiceClipMemoryTests(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.memory = VoiceClipMemory(clock=lambda: self.now[0], ttl=90, max_bytes=1280, max_count=3, trip_limit=2)
        self.source = dict(account='alice', stamp=('joined', 1), kind='iphone', tokenHash='synthetic')

    def add(self, client=None, pcm=None, trip='trip'):
        return self.memory.publish(trip, 'room', self.source, {'alice': ('joined', 1), 'bob': ('joined', 1)},
                                   client or secrets.token_hex(16), pcm or bytes(640))

    def test_cursor_initial_reset_order_and_expiry(self):
        initial, clips = self.memory.feed('trip', None)
        self.assertEqual(clips, [])
        first = self.add(); second = self.add()
        cursor, clips = self.memory.feed('trip', initial)
        self.assertEqual([clip.id for clip in clips], [first.id, second.id])
        self.assertEqual(self.memory.feed('trip', '0'*32+':0'), (cursor, []))
        self.now[0] = 90
        self.assertEqual(self.memory.feed('trip', initial), (cursor, []))
        with self.assertRaises(HTTPException): self.memory.get(first.id)

    def test_dedup_conflict_keeps_original_authority(self):
        key = secrets.token_hex(16)
        first = self.add(key)
        self.assertIs(self.add(key), first)
        with self.assertRaises(HTTPException) as error: self.add(key, b'1'*640)
        self.assertEqual(error.exception.status_code, 409)
        self.source['stamp'] = ('rejoined', 2)
        self.assertIs(self.add(key), first)
        self.assertEqual(self.memory.get(first.id).source["stamp"], ("joined", 1))

    def test_idle_timer_removes_audio_without_another_request(self):
        memory = VoiceClipMemory(ttl=0.02)
        memory.publish("trip", "room", self.source, {}, "a"*32, bytes(640))
        time.sleep(0.1)
        self.assertEqual(list(memory.clips), [])
        self.assertEqual(list(memory.receipts), [])
        self.assertIsNone(memory.timer)
        memory.publish("trip", "room", self.source, {}, "b"*32, bytes(640))
        memory.clear()
        self.assertEqual(list(memory.clips), [])
        self.assertEqual(list(memory.receipts), [])
        self.assertIsNone(memory.timer)

    def test_evicted_audio_retries_keep_ack_and_conflict_until_ttl(self):
        key = 'a'*32
        first = self.add(key)
        self.add(); self.add()
        self.assertNotIn(first.id,self.memory.clips)
        sequence = self.memory.sequence
        self.assertIs(self.add(key),first)
        self.assertEqual(self.memory.sequence,sequence)
        self.assertNotIn(first.id,self.memory.clips)
        with self.assertRaises(HTTPException) as error:self.add(key,b'1'*640)
        self.assertEqual(error.exception.status_code,409)
        self.now[0] = 90
        self.assertNotEqual(self.add(key).id,first.id)

    def test_every_message_retains_its_tuple_key_before_and_after_eviction(self):
        memory = VoiceClipMemory(trip_limit=3)
        keys = ['a'*32,'b'*32,'c'*32]
        receipts = [memory.publish('trip','room',self.source,{},key,bytes(640)) for key in keys]
        self.assertEqual(set(memory.receipts),{('trip','alice',key) for key in keys})
        for key,receipt in zip(keys,receipts):
            self.assertIs(memory.publish('trip','room',self.source,{},key,bytes(640)),receipt)
        self.assertEqual(memory.sequence,3)
        memory.publish('trip','room',self.source,{},'d'*32,bytes(640))
        self.assertNotIn(receipts[0].id,memory.clips)
        memory.withdraw('trip')
        for key,receipt in zip(keys,receipts):
            self.assertIs(memory.publish('trip','room',self.source,{},key,bytes(640)),receipt)
            with self.assertRaises(HTTPException) as error:
                memory.publish('trip','room',self.source,{},key,b'1'*640)
            self.assertEqual(error.exception.status_code,409)
        self.assertEqual(memory.sequence,4)
        self.assertEqual(list(memory.clips),[])
        memory.clear()

    def test_dedup_capacity_refuses_new_keys_without_evicting_live_receipts(self):
        memory = VoiceClipMemory(clock=lambda:self.now[0],max_count=1,max_receipts=2)
        first = memory.publish('trip','room',self.source,{},'a'*32,bytes(640))
        memory.publish('trip','room',self.source,{},'b'*32,bytes(640))
        with self.assertRaises(HTTPException) as error:
            memory.publish('trip','room',self.source,{},'c'*32,bytes(640))
        self.assertEqual((error.exception.status_code,error.exception.detail),(429,'VOICE_CLIP_CAPACITY'))
        self.assertEqual(len(memory.receipts),2)
        self.assertEqual(memory.publish('trip','room',self.source,{},'a'*32,bytes(640)).metadata(),first.metadata())
        self.now[0] = 90
        memory.publish('trip','room',self.source,{},'c'*32,bytes(640))
        self.assertEqual(len(memory.receipts),1)
        memory.clear()

    def test_global_count_and_per_trip_limits_are_independent(self):
        memory = VoiceClipMemory(max_count=3, trip_limit=2)
        for index in range(3):
            memory.publish("trip", "room", self.source, {}, str(index)*32, bytes(640))
        self.assertEqual(len(memory.clips),2)
        for index in range(3,6):
            memory.publish(str(index), "room", self.source, {}, str(index)*32, bytes(640))
        self.assertEqual(len(memory.clips),3)
        self.assertEqual([value.trip for value in memory.clips.values()],["3","4","5"])
        memory.clear()

    def test_memory_and_count_bound_drop_oldest_without_sequence_reuse(self):
        first = self.add(); second = self.add(); third = self.add()
        self.assertEqual(sum(len(clip.pcm) for clip in self.memory.clips.values()), 1280)
        self.assertEqual(list(self.memory.clips), [second.id, third.id])
        with self.assertRaises(HTTPException): self.memory.get(first.id)
        self.memory.withdraw('trip', 'alice')
        self.assertEqual(self.memory.feed('trip', self.memory.boot+':0')[1], [])
        self.assertEqual(self.add().sequence, 4)


class IPhoneVoiceClipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        enabled = patch.dict(os.environ, {'WEGOH_VOICE_ENABLED': '1'})
        enabled.start(); cls.addClassCleanup(enabled.stop)
        fixture.IPhoneTripTests.setUpClass.__func__(cls)

    def setUp(self):
        self.h = fixture.IPhoneTripTests(); self.h.setUp()
        self.addCleanup(self.h.phone.doCleanups)
        self.h.befriend(self.h.bob)
        self.trip = self.h.create(); self.h.join(self.trip, self.h.bob)
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute("UPDATE team_trips SET state='active',started_at=now() WHERE trip_id=%s", (self.trip,))
        self.service = fixture.fixture.fixture.TeamTests.module.TEAM_VOICE_CLIPS
        self.service.memory.clear()
        self.service.memory = VoiceClipMemory()
        self.base = '/' + self.trip + '/voice-clips'
        self.pcm = base64.b64encode(bytes(6400)).decode('ascii')

    def call(self, suffix='', data=None, method='GET', session=None, **kwargs):
        return self.h.call(self.base + suffix, data, method, session=session, **kwargs)

    def upload(self, session=None, key=None):
        return self.call(data=dict(clientMessageId=key or secrets.token_hex(16), pcmBase64=self.pcm), method='POST', session=session)

    def test_complete_upload_feed_download_order_and_dedup(self):
        cursor = self.h.checked(self.call(session=self.h.bob))['cursor']
        key = secrets.token_hex(16)
        clip = self.h.checked(self.upload(key=key))
        self.assertEqual(clip['durationMs'], 200)
        self.assertEqual(clip, self.h.checked(self.upload(key=key)))
        other_key = secrets.token_hex(16)
        other = self.h.checked(self.upload(key=other_key))
        self.assertEqual(self.h.checked(self.upload(key=key)),clip)
        self.assertEqual(self.h.checked(self.upload(key=other_key)),other)
        self.assertEqual(self.service.memory.sequence,2)
        feed = self.h.checked(self.call('?cursor=' + cursor, session=self.h.bob))
        self.assertEqual(feed['clips'], [clip, other])
        own = self.h.checked(self.call('?cursor=' + cursor))
        self.assertEqual(own['clips'], [])
        downloaded = self.h.checked(self.call('/' + clip['id'], session=self.h.bob))
        self.assertEqual(downloaded, dict(clip, pcmBase64=self.pcm))
        self.assertEqual(self.call('/' + clip['id'])[0], 404)
        self.assertEqual(self.call('?cursor=' + feed['cursor'], session=self.h.bob)[2]['clips'], [])

    def test_strict_lengths_fields_cursors_and_hosts(self):
        for payload in (
            dict(clientMessageId='a'*32, pcmBase64=base64.b64encode(bytes(639)).decode()),
            dict(clientMessageId='a'*32, pcmBase64=base64.b64encode(bytes(480640)).decode()),
            dict(clientMessageId='a'*32, pcmBase64='not-base64'),
            dict(clientMessageId='bad', pcmBase64=self.pcm),
            dict(clientMessageId='a'*32, pcmBase64=self.pcm, extra=True)):
            self.assertEqual(self.call(data=payload, method='POST')[0], 400)
        self.assertEqual(self.call('?cursor=wrong')[0], 400)
        self.assertEqual(self.call('?cursor='+'a'*32+':0&cursor='+'a'*32+':0')[0], 400)
        self.assertEqual(self.call('?token=not-allowed')[0], 400)
        self.assertEqual(self.call(session=self.h.eve)[0], 404)
        self.assertEqual(self.h.phone.api.call('/v1/iphone/trips' + self.base, who=None, host='web.wegoh.invalid')[0], 404)

    def test_mute_participation_and_source_session_revocation(self):
        cursor = self.h.checked(self.call(session=self.h.bob))['cursor']
        clip = self.h.checked(self.upload())
        path = '/' + self.trip + '/voice/filters/' + self.h.a
        self.h.checked(self.h.call(path, dict(muted=True), 'PUT', session=self.h.bob))
        self.assertEqual(self.call('?cursor='+cursor, session=self.h.bob)[2]['clips'], [])
        self.assertEqual(self.call('/'+clip['id'], session=self.h.bob)[0], 404)
        self.h.checked(self.h.call(path, dict(muted=False), 'PUT', session=self.h.bob))
        self.assertEqual(self.call('/'+clip['id'], session=self.h.bob)[0], 200)
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET revoked_at=%s WHERE account_id=%s', (int(time.time()), self.h.a))
        self.assertEqual(self.call('/'+clip['id'], session=self.h.bob)[0], 404)
        self.assertEqual(self.call('?cursor='+cursor, session=self.h.bob)[2]['clips'], [])

    def test_reports_require_download_and_suspend_speaker(self):
        clip = self.h.checked(self.upload())
        path = '/' + self.trip + '/voice/reports'
        payload = dict(speakerId=self.h.a, leaseId=clip['id'], reason='other')
        self.assertEqual(self.h.call(path, payload, 'POST', session=self.h.bob)[0], 404)
        self.h.checked(self.call('/'+clip['id'], session=self.h.bob))
        result = self.h.checked(self.h.call(path, payload, 'POST', session=self.h.bob), 202)
        self.assertFalse(result['audioRetained'])
        self.assertEqual(self.upload()[0], 403)
        self.assertEqual(self.call('/'+clip['id'], session=self.h.bob)[0], 404)

    def test_ttl_and_receiver_voice_epoch_hide_old_audio(self):
        clip = self.h.checked(self.upload())
        path = '/' + self.trip + '/voice-participation'
        state = self.h.checked(self.h.call(path, session=self.h.bob))
        off = self.h.checked(self.h.call(path, dict(participating=False, revision=state['revision'], memberJoinedAt=state['memberJoinedAt']), 'PATCH', session=self.h.bob))
        self.assertEqual(self.call('/'+clip['id'], session=self.h.bob)[0], 403)
        self.h.checked(self.h.call(path, dict(participating=True, revision=off['revision'], memberJoinedAt=off['memberJoinedAt']), 'PATCH', session=self.h.bob))
        self.assertEqual(self.call('/'+clip['id'], session=self.h.bob)[0], 404)
        fresh = self.h.checked(self.upload())
        self.service.memory.clock = lambda: time.monotonic()+91
        self.assertEqual(self.call('/'+fresh['id'], session=self.h.bob)[0], 404)

    def test_native_phone_roundtrip_direction_and_revocation(self):
        from test_native_functional_business import FunctionalBusinessTests
        factory = FunctionalBusinessTests()
        factory.h = self.h.phone.api
        factory.certificates = {}
        browser = factory.h.login()
        car = factory.connect(browser)
        purposes = ['rooms:read', 'rooms:interact', 'room-voice:receive', 'room-voice:transmit']
        revision = factory.approve(browser, car, purposes)
        path = '/v1/social/trips' + self.base
        cursor = self.h.checked(self.call(session=self.h.bob))['cursor']
        payload = dict(clientMessageId=secrets.token_hex(16), pcmBase64=self.pcm, functionalRevision=revision)
        clip = self.h.checked(factory.native(car, path, payload, 'POST'))
        self.assertEqual(self.call('?cursor='+cursor, session=self.h.bob)[2]['clips'], [clip])
        self.assertEqual(self.call('/'+clip['id'], session=self.h.bob)[0], 200)
        self.assertEqual(self.h.checked(factory.native(car, '/v1/social/trips/'+self.trip+'/voice/filters')), dict(mutedSpeakerIds=[]))
        native_cursor = self.h.checked(factory.native(car, path))['cursor']
        bob_clip = self.h.checked(self.upload(session=self.h.bob))
        self.assertEqual(self.h.checked(factory.native(car, path+'?cursor='+native_cursor))['clips'], [bob_clip])
        self.assertEqual(self.h.checked(factory.native(car, path+'/'+bob_clip['id']))['pcmBase64'], self.pcm)
        self.assertEqual(factory.native(car, path, {k:v for k,v in payload.items() if k!='functionalRevision'}, 'POST')[0], 400)
        factory.approve(browser, car, ['rooms:read', 'rooms:interact', 'room-voice:receive'])
        self.assertEqual(self.call('/'+clip['id'], session=self.h.bob)[0], 404)
        self.assertEqual(factory.native(car, path, payload, 'POST')[0], 409)

    def test_native_full_clip_fits_only_with_literal_base64_slashes(self):
        from test_native_functional_business import FunctionalBusinessTests
        factory = FunctionalBusinessTests()
        factory.h = self.h.phone.api
        factory.certificates = {}
        browser = factory.h.login()
        car = factory.connect(browser)
        revision = factory.approve(browser, car, ['rooms:read', 'rooms:interact', 'room-voice:receive', 'room-voice:transmit'])
        path = '/v1/social/trips' + self.base
        cursor = self.h.checked(self.call(session=self.h.bob))['cursor']
        pcm = base64.b64encode(bytes([0xff]) * 480000).decode('ascii')  # 15 s, Base64 '/' only

        def send(text):
            return factory.h.call(path, None, 'POST', who=None, host='api.wegoh.invalid', origin=None,
                                  bearer=car['accessToken'], certificate=factory.certificates[car['grantId']],
                                  raw=text.encode('utf-8'))
        # Byte layout of the vehicle client's canonical body: sorted keys, no spaces, literal '/'.
        compact = '{"clientMessageId":"%s","functionalRevision":%d,"pcmBase64":"%s"}' % (
            secrets.token_hex(16), revision, pcm)
        clip = self.h.checked(send(compact))
        self.assertEqual(clip['durationMs'], 15000)
        self.assertEqual(self.call('?cursor=' + cursor, session=self.h.bob)[2]['clips'], [clip])
        self.assertEqual(self.h.checked(self.call('/' + clip['id'], session=self.h.bob))['pcmBase64'], pcm)
        # Android org.json writes each '/' as "\/": the same clip no longer fits the body limit.
        escaped = '{"clientMessageId":"%s","functionalRevision":%d,"pcmBase64":"%s"}' % (
            secrets.token_hex(16), revision, pcm.replace('/', '\\/'))
        self.assertEqual(send(escaped)[0], 413)

    def test_fanout_to_two_five_and_ten_distinct_authorized_recipients(self):
        api = self.h.phone.api
        original = api.members_rows
        api.write_members(original + [dict(email='qa'+str(index)+'@example.invalid', name='qa'+str(index), role='creator') for index in range(9)])
        self.addCleanup(api.write_members, original)
        old_clip = self.h.checked(self.upload())
        members = [self.h.bob]
        for index in range(9):
            guest = self.h.phone.login(who='qa'+str(index))
            self.h.befriend(guest)
            self.h.join(self.trip, guest)
            self.assertEqual(self.call('/'+old_clip['id'], session=guest)[0], 404)
            members.append(guest)
        for count in (2, 5, 10):
            with self.subTest(recipients=count):
                receivers = members[:count]
                cursors = [self.h.checked(self.call(session=member))['cursor'] for member in receivers]
                clip = self.h.checked(self.upload())
                for member, cursor in zip(receivers, cursors):
                    self.assertEqual(self.h.checked(self.call('?cursor='+cursor, session=member))['clips'], [clip])
                    self.assertEqual(self.h.checked(self.call('/'+clip['id'], session=member))['pcmBase64'], self.pcm)
                self.assertEqual(len(self.service.memory.get(clip['id']).delivered), count)

    def test_finished_trip_purges_audio(self):
        self.h.checked(self.upload())
        current = self.h.detail(self.trip)
        self.h.checked(self.h.call('/'+self.trip+'/finish',dict(revision=current['revision']),'POST'))
        self.assertEqual(list(self.service.memory.clips),[])
        self.assertEqual(self.call(session=self.h.bob)[0],409)

    def test_source_leave_and_rejoin_cannot_revive_audio(self):
        clip = self.h.checked(self.upload(session=self.h.bob))
        self.h.checked(self.h.call('/'+self.trip+'/members/'+self.h.b, {}, 'DELETE',session=self.h.bob))
        self.assertEqual(self.call('/'+clip['id'])[0],404)
        self.assertEqual(list(self.service.memory.clips),[])
        self.h.join(self.trip,self.h.bob)
        self.assertEqual(self.call('/'+clip['id'])[0],404)


    def test_http_evicted_retry_deduplicates_and_revoked_session_cannot_get_ack(self):
        self.service.memory.trip_limit = 1
        key = secrets.token_hex(16)
        first = self.h.checked(self.upload(key=key))
        self.h.checked(self.upload())
        self.assertEqual(self.call('/'+first['id'],session=self.h.bob)[0],404)
        self.assertEqual(self.h.checked(self.upload(key=key)),first)
        self.assertEqual(self.service.memory.sequence,2)
        with psycopg.connect(self.h.phone.api.dsn) as conn:
            conn.execute('UPDATE iphone_sessions SET revoked_at=%s WHERE account_id=%s',(int(time.time()),self.h.a))
        self.assertEqual(self.upload(key=key)[0],401)

    def test_maximum_clip_json_and_blocked_context(self):
        payload = dict(clientMessageId=secrets.token_hex(16), pcmBase64=base64.b64encode(bytes(480000)).decode())
        clip = self.h.checked(self.call(data=payload, method='POST'))
        self.assertEqual(clip['durationMs'], 15000)
        self.assertEqual(len(self.h.checked(self.call('/'+clip['id'], session=self.h.bob))['pcmBase64']),640000)
        self.h.checked(self.h.phone.iphone('/v1/iphone/blocks',dict(targetId=self.h.b), 'POST', token=self.h.alice['accessToken']),201)
        self.assertEqual(self.call('/'+clip['id'],session=self.h.bob)[0],404)
        self.assertEqual(self.call(session=self.h.bob)[0],404)


class VoiceClipDocumentationTests(unittest.TestCase):
    def test_native_clip_body_cursor_and_filter_scopes(self):
        from types import SimpleNamespace
        import api_doc_native_domains as documentation
        from api_doc_voice import CLIP, OPS
        from team_api_docs import BODY
        rules = [rule for rule in documentation.WIRE['nativeRoutes'] if '/voice-clips' in rule['path'] or rule['path'].endswith('/voice/filters')]
        self.assertEqual(len(rules),4)
        self.assertEqual(set(CLIP['required']),{'id','speakerId','sequence','durationMs'})
        schema = dict(paths={})
        for index, rule in enumerate(rules):
            schema['paths'].setdefault(rule['path'],{})[rule['method'].lower()] = dict(description='',operationId='clip'+str(index), responses={}, requestBody={'content':{'application/json':{}}})
            self.assertIn((rule['method'].lower(),rule['path']),OPS)
        for method,path in [('put','/v1/devices/{device}/reporting-permissions'),('delete','/v1/devices/{device}/reporting-permissions/{purpose}')]:
            schema['paths'][path] = {method:dict(description='',responses={})}
        auth = SimpleNamespace(public_origin='https://web.wegoh.invalid',native_origin='https://api.wegoh.invalid')
        with patch.object(documentation,'WIRE',dict(documentation.WIRE,nativeRoutes=rules)):
            result = documentation.apply_native_domain_documentation(schema,auth)
        path = '/v1/social/trips/{trip}/voice-clips'
        operation = result['paths'][path]['post']
        self.assertEqual(operation['security'],[{'NativeMTLS':[],'DeviceBearer':[]}])
        body = result['components']['schemas'][operation['requestBody']['content']['application/json']['schema']['$ref'].split('/')[-1]]
        self.assertEqual(set(body['required']),{'clientMessageId','pcmBase64','functionalRevision'})
        self.assertEqual(body['properties']['pcmBase64']['maxLength'],640000)
        self.assertIn(('post',path),BODY)
        self.assertEqual(result['paths'][path]['get']['parameters'][0]['name'],'cursor')
        self.assertEqual(result['paths'][path]['get']['x-wegoh-native-functional-purposes']['all'],['rooms:read'])
