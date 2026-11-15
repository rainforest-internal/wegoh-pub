"""Current native music metadata/link/DJ guard; no fetching, audio, production or CF."""
import unittest,json,hashlib
import psycopg
import test_team_auth as fixture

class NativeMusicTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.TeamTests.setUpClass()
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def setUp(self):self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp();self.certs={}
 def connect(self,s,who='alice'):
  _,_,c=self.h.pair(s,who);self.certs[c['grantId']]=self.h._native_fingerprint;return c
 def native(self,c,path,body=None,method='GET',certificate=None):return self.h.native(path,body,method,token=c['accessToken'],certificate=certificate or self.certs[c['grantId']])
 def approve(self,s,c,purposes,who='alice'):
  path='/v1/devices/'+c['deviceId']+'/functional-permissions';code,_,old=self.h.call(path,session=s,who=who);self.assertEqual(code,200,old)
  body={k:v for k,v in old.items()if k not in('deviceId','expiresAt')};body['approvedPurposes']=self.h.web_purposes(old,purposes)
  code,_,value=self.h.call(path,body,'PUT',session=s,who=who);self.assertEqual(code,200,value);return value['revision']
 def room_approve(self,session,c,room,receive=True,share=False,who='alice'):
  path='/v1/devices/'+c['deviceId']+'/rooms/'+room+'/music-permissions';code,_,old=self.h.call(path,session=session,who=who);self.assertEqual(code,200,old)
  body={k:v for k,v in old.items()if k not in('deviceId','roomId','expiresAt')};body['permissions']=dict(receiveMusic=receive,shareMusic=share)
  code,_,value=self.h.call(path,body,'PUT',session=session,who=who);self.assertEqual(code,200,value);return value
 def base(self):
  with psycopg.connect(self.h.dsn)as conn:return {n:conn.execute('SELECT row_to_json(t)::text FROM '+n+' t ORDER BY row_to_json(t)::text').fetchall()for n in ['native_v2_grants','native_v2_credentials','native_v2_installations','native_v2_approvals','native_v2_certificates','native_v2_operations']}
 def test_native_dj_current_purpose_room_consent_rights_review_and_withdrawal(self):
  a,b,e=self.h.login(),self.h.login('bob'),self.h.login('eve');ca,cb=self.connect(a),self.connect(b,'bob');base=self.base()
  self.assertEqual(self.h.call('/v1/social/friends/requests',dict(targetId=b['user']['id']),'POST',session=a)[0],201)
  self.assertEqual(self.h.call('/v1/social/friends/requests/'+a['user']['id']+'/respond',dict(accept=True),'POST',session=b,who='bob')[0],200)
  code,_,room=self.h.call('/v1/social/rooms',dict(name='Synthetic DJ room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=a);self.assertEqual(code,201,room);rid=room['id'];root='/v1/social/rooms/'+rid
  detail=self.h.call(root,session=a)[2];flags={k:k in('status','music')for k in('status','location','visits','music','voice','control')}
  self.assertEqual(self.h.call('/v1/social/rooms/join',dict(code=detail['code'],consents=flags),'POST',session=b,who='bob')[0],200)
  self.assertEqual(self.h.call(root+'/consents',dict(consents=flags),'PATCH',session=a)[0],200)
  self.assertEqual(self.h.call(root+'/role',dict(accountId=a['user']['id'],role='dj'),'PATCH',session=a)[0],200)
  code,_,playlist=self.h.call('/v1/playlists',dict(name='Synthetic link list',tracks=[dict(title='Synthetic song one',url='https://www.melon.com/song/detail.htm?songId=10000001'),dict(title='Synthetic song two',url='https://www.melon.com/song/detail.htm?songId=10000002')]),'POST',session=a);self.assertEqual(code,201,playlist)
  self.approve(a,ca,['rooms:read']);self.approve(b,cb,['rooms:read'],'bob')
  path=root+'/music';self.assertEqual(self.native(ca,path)[0],403);self.assertEqual(self.native(ca,'/v1/device/music-permission')[0],403)
  permission='/v1/devices/'+ca['deviceId']+'/music-permission';view=self.h.call(permission,session=a)[2];self.assertEqual(view['authority'],'native-functional');self.assertFalse(view['enabled'])
  self.assertEqual(self.h.call(permission,dict(revision=view['revision'],enabled=True),'PUT',session=a)[0],409);self.assertEqual(self.h.call(permission,session=b,who='bob')[0],404)
  ra=self.approve(a,ca,['rooms:read','room-music:read','room-music:control']);rb=self.approve(b,cb,['rooms:read','room-music:read'],'bob')
  self.assertTrue(self.native(ca,'/v1/device/music-permission')[2]['enabled'])
  own_permission=self.native(ca,'/v1/native/rooms/'+rid+'/music-permissions');self.assertEqual(own_permission[0],200,own_permission[2]);self.assertEqual(own_permission[2]['permissions'],dict(receiveMusic=False,shareMusic=False));self.assertEqual(self.native(ca,path)[0],403)
  pa=self.room_approve(a,ca,rid,share=True);pb=self.room_approve(b,cb,rid,who='bob')
  body=dict(revision=0,playlistId=playlist['id'],playlistRevision=playlist['revision'],trackId=playlist['tracks'][0]['id'],rightsConfirmed=True,roomMusicRevision=pa['revision'])
  self.assertEqual(self.native(ca,path,body,'PUT')[0],400)
  body['functionalRevision']=ra
  self.assertEqual(self.native(ca,path,dict(body,rightsConfirmed=False),'PUT')[0],400)
  self.assertEqual(self.native(ca,path,dict(body,extra=True),'PUT')[0],400)
  self.assertEqual(self.native(ca,path,body,'PUT',certificate=self.certs[cb['grantId']])[0],401)
  self.assertEqual(self.native(cb,path,dict(body,functionalRevision=rb),'PUT')[0],403)
  rb=self.approve(b,cb,['rooms:read','room-music:read','room-music:control'],'bob');self.assertEqual(self.native(cb,path,dict(body,functionalRevision=rb),'PUT')[0],403)
  code,_,selected=self.native(ca,path,body,'PUT');self.assertEqual(code,200,selected);self.assertEqual(selected['selection']['currentTrackId'],playlist['tracks'][0]['id'])
  self.assertIsNone(self.native(cb,path)[2]['selection'])
  code,_,review=self.h.call(path+'/review-request',dict(revision=selected['revision'],consent=True),'PATCH',session=a);self.assertEqual(code,200,review)
  code,_,decision=self.h.call('/v1/moderation/content/room-music/'+rid+':'+selected['selection']['id'],dict(checksum=review['checksum'],decision='approved',reviewer='Synthetic admin',reviewNote='Owned synthetic links only'),'POST',session=a);self.assertEqual(code,200,decision)
  received=self.native(cb,path);self.assertEqual(received[0],200,received[2]);self.assertEqual(received[2]['selection']['tracks'],playlist['tracks'])
  second=dict(body,revision=1,trackId=playlist['tracks'][1]['id']);code,_,value=self.native(ca,path,second,'PUT');self.assertEqual(code,200,value);self.assertEqual(value['selection']['currentTrackId'],playlist['tracks'][1]['id']);self.assertEqual(self.native(ca,path,second,'PUT')[0],409)
  self.assertEqual(self.h.call(path,session=e,who='eve')[0],404)
  with psycopg.connect(self.h.dsn)as conn:
   original=conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0];raw=conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(rid,)).fetchone()[0]
   protected=self.h.module.TEAM_ROOM_MUSIC.restore(rid,raw);self.assertEqual(protected['nativeOrigin'],dict(deviceId=ca['deviceId'],grantId=ca['grantId']));self.assertNotIn(playlist['name'].encode(),bytes(raw))
  # A private selection by another installation must survive this sender's withdrawal.
  code,_,other_room=self.h.call('/v1/social/rooms',dict(name='Other synthetic DJ room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=b,who='bob');self.assertEqual(code,201,other_room)
  other_root='/v1/social/rooms/'+other_room['id']
  self.assertEqual(self.h.call(other_root+'/consents',dict(consents=flags),'PATCH',session=b,who='bob')[0],200)
  self.assertEqual(self.h.call(other_root+'/role',dict(accountId=b['user']['id'],role='dj'),'PATCH',session=b,who='bob')[0],200)
  code,_,other_list=self.h.call('/v1/playlists',dict(name='Other synthetic list',tracks=[dict(title='Other synthetic song',url='https://www.melon.com/song/detail.htm?songId=10000003')]),'POST',session=b,who='bob');self.assertEqual(code,201,other_list)
  other_permission=self.room_approve(b,cb,other_room['id'],share=True,who='bob')
  code,_,other_selection=self.native(cb,other_root+'/music',dict(revision=0,playlistId=other_list['id'],playlistRevision=other_list['revision'],trackId=other_list['tracks'][0]['id'],rightsConfirmed=True,roomMusicRevision=other_permission['revision'],functionalRevision=rb),'PUT');self.assertEqual(code,200,other_selection)
  with psycopg.connect(self.h.dsn)as conn:
   other_music=conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(other_room['id'],)).fetchone()[0];other_playlist=conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(other_list['id'],)).fetchone()[0]
  def shared_state():
   with psycopg.connect(self.h.dsn)as conn:return {n:conn.execute('SELECT row_to_json(t)::text FROM '+n+' t ORDER BY row_to_json(t)::text').fetchall()for n in ['native_functional_authorizations','team_room_music','team_content_reviews','team_content_review_events','team_resource_versions']}
  from unittest.mock import patch
  from native_functional_policy import FunctionalError
  from team_room_music import TeamRoomMusic
  original_cleanup=TeamRoomMusic.withdraw_native_source
  def failed_cleanup(service,*args):
   original_cleanup(service,*args)
   raise FunctionalError(503,'FUNCTIONAL_CLEANUP_UNAVAILABLE')
  code,_,current=self.h.call('/v1/devices/'+ca['deviceId']+'/functional-permissions',session=a);self.assertEqual(code,200,current)
  drop={k:v for k,v in current.items()if k not in('deviceId','expiresAt')};drop['approvedPurposes']=self.h.web_purposes(current,['room-music:read','rooms:read']);state_before=shared_state()
  with patch.object(TeamRoomMusic,'withdraw_native_source',new=failed_cleanup):
   code,_,failure=self.h.call('/v1/devices/'+ca['deviceId']+'/functional-permissions',drop,'PUT',session=a);self.assertEqual(code,503,failure)
  self.assertEqual(shared_state(),state_before)
  with psycopg.connect(self.h.dsn)as conn:versions_before=dict(((owner,kind),revision)for owner,kind,revision in conn.execute('SELECT account_id,resource,revision FROM team_resource_versions'))
  self.approve(a,ca,['rooms:read','room-music:read']);self.assertEqual(self.native(ca,path,dict(second,revision=2),'PUT')[0],403)
  self.assertIsNone(self.native(cb,path)[2]['selection'])
  self.assertFalse(self.native(ca,path)[2]['canEdit'])
  with psycopg.connect(self.h.dsn)as conn:
   self.assertEqual(conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(other_room['id'],)).fetchone()[0],other_music);self.assertEqual(conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(other_list['id'],)).fetchone()[0],other_playlist)
   versions_after=dict(((owner,kind),revision)for owner,kind,revision in conn.execute('SELECT account_id,resource,revision FROM team_resource_versions'))
  notified={key for key,value in versions_after.items()if value!=versions_before.get(key)}
  allowed={(a['user']['id'],'rooms'),(a['user']['id'],'content'),(a['user']['id'],'devices'),(b['user']['id'],'rooms')}
  self.assertLessEqual(notified,allowed|{('event-account:'+account,resource)for account,resource in allowed});self.assertIn((a['user']['id'],'content'),notified);self.assertIn((b['user']['id'],'rooms'),notified);self.assertFalse(any(key[0]in {e['user']['id'],'event-account:'+e['user']['id']}for key in notified))
  with psycopg.connect(self.h.dsn)as conn:self.assertIsNone(conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(rid,)).fetchone()[0])
  ra=self.approve(a,ca,['rooms:read','room-music:read','room-music:control'])
  self.assertIsNone(self.native(ca,path)[2]['selection']);self.assertIsNone(self.native(cb,path)[2]['selection'])
  self.assertEqual(self.native(ca,path,dict(body,revision=self.native(ca,path)[2]['revision'],functionalRevision=ra),'PUT')[0],403)
  pa=self.room_approve(a,ca,rid,share=True)
  revision=self.native(ca,path)[2]['revision'];fresh=dict(body,revision=revision,functionalRevision=ra,roomMusicRevision=pa['revision'])
  code,_,new_selection=self.native(ca,path,fresh,'PUT');self.assertEqual(code,200,new_selection);self.assertNotEqual(new_selection['selection']['id'],selected['selection']['id'])
  self.assertIsNone(self.native(cb,path)[2]['selection']) # Fresh publication must be reviewed again.
  code,_,review=self.h.call(path+'/review-request',dict(revision=new_selection['revision'],consent=True),'PATCH',session=a);self.assertEqual(code,200,review)
  code,_,decision=self.h.call('/v1/moderation/content/room-music/'+rid+':'+new_selection['selection']['id'],dict(checksum=review['checksum'],decision='approved',reviewer='Synthetic admin',reviewNote='New explicit synthetic link sharing'),'POST',session=a);self.assertEqual(code,200,decision)
  self.assertIsNotNone(self.native(cb,path)[2]['selection'])
  with psycopg.connect(self.h.dsn)as conn:sender_cipher=conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(rid,)).fetchone()[0]
  rb=self.approve(b,cb,['rooms:read','room-music:control'],'bob');self.assertEqual(self.native(cb,path)[0],403)
  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(rid,)).fetchone()[0],sender_cipher)
  rb=self.approve(b,cb,['rooms:read','room-music:read','room-music:control'],'bob')
  self.assertEqual(self.native(cb,path)[0],403) # Global reapproval alone cannot revive room receive consent.
  self.room_approve(b,cb,rid,who='bob')
  self.assertIsNotNone(self.native(cb,path)[2]['selection']) # A fresh same-owner room approval is required.
  self.assertEqual(self.base(),base)
  with psycopg.connect(self.h.dsn)as conn:peer_before=conn.execute('SELECT row_to_json(g)::text FROM native_v2_grants g WHERE grant_id=%s',(cb['grantId'],)).fetchone()
  code,_,revoked=self.h.call('/v1/devices/'+ca['deviceId'],method='DELETE',session=a);self.assertEqual(code,200,revoked);self.assertEqual(self.native(ca,'/v1/account')[0],401)
  with psycopg.connect(self.h.dsn)as conn:
   self.assertIsNone(conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(rid,)).fetchone()[0]);self.assertEqual(conn.execute('SELECT row_to_json(g)::text FROM native_v2_grants g WHERE grant_id=%s',(cb['grantId'],)).fetchone(),peer_before)

  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0],original);self.assertEqual(conn.execute('SELECT count(*) FROM team_devices').fetchone()[0],0)

 def test_room_consent_auth_free_backup_restores_zero_authority_and_original_cipher(self):
  from pathlib import Path
  from psycopg import sql
  from ops.live import backup
  from native_access_backup import BackupProjectionError,validate_restored_projection
  a=self.h.login();c=self.connect(a);self.approve(a,c,['rooms:read','room-music:read','room-music:control'])
  code,_,room=self.h.call('/v1/social/rooms',dict(name='Synthetic music backup room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=a);self.assertEqual(code,201,room)
  consent=self.room_approve(a,c,room['id'],share=True)
  code,_,playlist=self.h.call('/v1/playlists',dict(name='Original synthetic playlist',tracks=[dict(title='Synthetic retained title',url='https://www.melon.com/song/detail.htm?songId=10000004')]),'POST',session=a);self.assertEqual(code,201,playlist)
  with psycopg.connect(self.h.dsn)as conn:
   private_row=conn.execute('SELECT * FROM native_room_music_authorizations').fetchone();self.assertIsNotNone(private_row[5]);original_playlist=conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0]
  base_state=self.base();key=self.h.state/'visits.key';key_sha=hashlib.sha256(key.read_bytes()).hexdigest();work=self.h.state/'room-music-backup';work.mkdir(mode=0o700);content=self.h.state/'content';blob=b'Synthetic original music journey object';digest=hashlib.sha256(blob).hexdigest();(content/digest).write_bytes(blob)
  tools=Path(self.h.tools['pg_ctl']).parent;layout=backup.Layout(self.h.dsn,content,work,str(tools/'pg_dump'),str(tools/'pg_restore'));archive=backup.snapshot(layout);manifest=backup.authenticated_manifest(archive)
  self.assertEqual(manifest['tables']['native_room_music_authorizations']['rows'],0);self.assertEqual(manifest['tables']['native_functional_authorizations']['rows'],0)
  target='room_music_restore';destination=psycopg.conninfo.make_conninfo(self.h.dsn,dbname=target)
  with psycopg.connect(self.h.dsn,autocommit=True)as conn:conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
  try:
   scratch=work/'scratch';scratch.mkdir(mode=0o700);result=backup.verify_into(layout,archive,destination,scratch);self.assertTrue(result['verified']);self.assertEqual(result['nativeV2Auth']['personalSessionsRestored'],0)
   with psycopg.connect(destination)as conn:
    self.assertEqual(conn.execute('SELECT count(*) FROM native_room_music_authorizations').fetchone()[0],0);self.assertEqual(conn.execute('SELECT count(*) FROM native_functional_authorizations').fetchone()[0],0);self.assertEqual(conn.execute('SELECT count(*) FROM native_v2_credentials').fetchone()[0],0)
    self.assertEqual(conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0],original_playlist)
    self.assertEqual(conn.execute("SELECT count(*) FROM pg_constraint WHERE conrelid='native_room_music_authorizations'::regclass AND contype='f' AND convalidated").fetchone()[0],3)
    conn.execute('INSERT INTO native_room_music_authorizations VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',private_row)
    with self.assertRaises(BackupProjectionError):validate_restored_projection(conn,manifest['nativeV2Auth'],restored_at=1)
    conn.rollback()
   self.assertEqual((scratch/'objects'/digest).read_bytes(),blob)
  finally:
   with psycopg.connect(self.h.dsn,autocommit=True)as conn:conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target)))
  self.assertEqual(self.base(),base_state);self.assertEqual(hashlib.sha256(key.read_bytes()).hexdigest(),key_sha)
  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT * FROM native_room_music_authorizations').fetchone(),private_row);self.assertEqual(conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0],original_playlist)

 def test_room_consent_own_device_events_and_other_installation_cipher_unchanged(self):
  import socket
  from websockets.sync.client import connect
  a,b=self.h.login(),self.h.login('bob');ca=self.connect(a);other=self.connect(b,'bob')
  ra=self.approve(a,ca,['rooms:read','room-music:read','room-music:control']);self.approve(b,other,['rooms:read','room-music:read'],'bob')
  code,_,room=self.h.call('/v1/social/rooms',dict(name='Synthetic two installation music room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=a);self.assertEqual(code,201,room);rid=room['id'];root='/v1/social/rooms/'+rid
  flags={key:False for key in ('status','location','visits','music','voice','control')}
  self.assertEqual(self.h.call('/v1/social/rooms/join',dict(code=room['code'],consents=flags),'POST',session=b,who='bob')[0],200)
  self.assertEqual(self.h.call(root+'/role',dict(accountId=a['user']['id'],role='dj'),'PATCH',session=a)[0],200)
  pa=self.room_approve(a,ca,rid,share=True);self.room_approve(b,other,rid,who='bob')
  code,_,playlist=self.h.call('/v1/playlists',dict(name='Synthetic isolated music',tracks=[dict(title='Synthetic song',url='https://www.melon.com/song/detail.htm?songId=10000005')]),'POST',session=a);self.assertEqual(code,201,playlist)
  code,_,selected=self.native(ca,root+'/music',dict(revision=0,playlistId=playlist['id'],playlistRevision=playlist['revision'],trackId=playlist['tracks'][0]['id'],rightsConfirmed=True,functionalRevision=ra,roomMusicRevision=pa['revision']),'PUT');self.assertEqual(code,200,selected)
  self.assertEqual(self.h.call(root+'/music',session=a)[0],403) # Native consent is separate from Web account music=false.
  self.assertIsNone(self.native(other,root+'/music')[2]['selection'])
  base=self.base()
  with psycopg.connect(self.h.dsn)as conn:sender_cipher=conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(rid,)).fetchone()[0]
  def channel(c):
   raw=socket.create_connection(('127.0.0.1',self.h.port),timeout=5)
   return connect('ws://api.wegoh.invalid/v1/events',sock=raw,origin=None,open_timeout=3,close_timeout=1,additional_headers={'Authorization':'Bearer '+c['accessToken'],'cf-cert-sha256':self.certs[c['grantId']],'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'})
  with channel(ca)as sender,channel(other)as receiver:
   first_sender=json.loads(sender.recv(timeout=3));first=json.loads(receiver.recv(timeout=3));self.assertEqual(first['resources'],['courses','devices','playlists']);self.assertEqual(first_sender['resources'],first['resources']);seq=0
   def receiver_invalidated():
    nonlocal seq
    event=json.loads(receiver.recv(timeout=3));seq+=1;self.assertEqual(event,dict(type='invalidate',epoch=first['epoch'],seq=seq,resources=['devices']))
    with self.assertRaises(TimeoutError):sender.recv(timeout=1.1)
   path='/v1/devices/'+other['deviceId']+'/rooms/'+rid+'/music-permissions';code,_,cut=self.h.call(path,method='DELETE',session=b,who='bob');self.assertEqual(code,200,cut);self.assertEqual(cut['permissions'],dict(receiveMusic=False,shareMusic=False));receiver_invalidated()
   self.assertEqual(self.native(other,root+'/music')[0],403);self.assertIsNotNone(self.native(ca,root+'/music')[2]['selection'])
   self.room_approve(b,other,rid,who='bob');receiver_invalidated();self.assertIsNone(self.native(other,root+'/music')[2]['selection'])
   with psycopg.connect(self.h.dsn)as conn:conn.execute('UPDATE native_room_music_authorizations SET expires_at=1 WHERE grant_id=%s AND room_id=%s',(other['grantId'],rid))
   receiver_invalidated();self.assertEqual(self.native(other,root+'/music')[0],403)
  self.assertEqual(self.base(),base)
  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(rid,)).fetchone()[0],sender_cipher)

 def test_room_member_and_dj_lineage_requires_fresh_per_device_consent(self):
  a,b=self.h.login(),self.h.login('bob');ca,cb=self.connect(a),self.connect(b,'bob')
  self.approve(a,ca,['rooms:read','room-music:read','room-music:control']);rb=self.approve(b,cb,['rooms:read','room-music:read','room-music:control'],'bob')
  self.assertEqual(self.h.call('/v1/social/friends/requests',dict(targetId=b['user']['id']),'POST',session=a)[0],201)
  self.assertEqual(self.h.call('/v1/social/friends/requests/'+a['user']['id']+'/respond',dict(accept=True),'POST',session=b,who='bob')[0],200)
  code,_,room=self.h.call('/v1/social/rooms',dict(name='Synthetic consent lineage room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=a);self.assertEqual(code,201,room);rid=room['id'];root='/v1/social/rooms/'+rid
  detail=self.h.call(root,session=a)[2];flags={k:False for k in ('status','location','visits','music','voice','control')}
  self.assertEqual(self.h.call('/v1/social/rooms/join',dict(code=detail['code'],consents=flags),'POST',session=b,who='bob')[0],200)
  self.assertEqual(self.h.call(root+'/role',dict(accountId=b['user']['id'],role='dj'),'PATCH',session=a)[0],200)
  self.room_approve(a,ca,rid);pb=self.room_approve(b,cb,rid,share=True,who='bob')
  _,_,playlist=self.h.call('/v1/playlists',dict(name='Synthetic member playlist',tracks=[dict(title='Synthetic track',url='https://www.melon.com/song/detail.htm?songId=10000006')]),'POST',session=b,who='bob')
  body=dict(revision=0,playlistId=playlist['id'],playlistRevision=playlist['revision'],trackId=playlist['tracks'][0]['id'],rightsConfirmed=True,functionalRevision=rb,roomMusicRevision=pb['revision'])
  code,_,selection=self.native(cb,root+'/music',body,'PUT');self.assertEqual(code,200,selection)
  base=self.base()
  with psycopg.connect(self.h.dsn)as conn:playlist_cipher=conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0];selection_cipher=conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(rid,)).fetchone()[0]
  # Web account music=false is not Native per-device withdrawal.
  self.assertEqual(self.h.call(root+'/consents',dict(consents=flags),'PATCH',session=b,who='bob')[0],200)
  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT protected FROM team_room_music WHERE room_id=%s',(rid,)).fetchone()[0],selection_cipher)
  self.assertEqual(self.native(cb,root+'/music')[0],200)
  # DJ loss purges only the sender selection/share consent; assigning DJ again is not consent.
  self.assertEqual(self.h.call(root+'/role',dict(accountId=b['user']['id'],role='member'),'PATCH',session=a)[0],200)
  self.assertEqual(self.h.call(root+'/role',dict(accountId=b['user']['id'],role='dj'),'PATCH',session=a)[0],200)
  view=self.native(cb,'/v1/native/rooms/'+rid+'/music-permissions')[2];self.assertTrue(view['permissions']['receiveMusic']);self.assertFalse(view['permissions']['shareMusic'])
  self.assertEqual(self.native(cb,root+'/music',dict(body,revision=selection['revision']+1,roomMusicRevision=view['revision']),'PUT')[0],403)
  pb=self.room_approve(b,cb,rid,share=True,who='bob');body.update(revision=selection['revision']+1,roomMusicRevision=pb['revision'])
  self.assertEqual(self.native(cb,root+'/music',body,'PUT')[0],200)
  # Leaving erases room-only consent. A new membership cannot inherit it.
  self.assertEqual(self.h.call(root+'/leave',method='POST',session=b,who='bob')[0],200)
  self.assertEqual(self.native(cb,root+'/music')[0],404)
  self.assertEqual(self.h.call('/v1/social/rooms/join',dict(code=detail['code'],consents=flags),'POST',session=b,who='bob')[0],200)
  view=self.native(cb,'/v1/native/rooms/'+rid+'/music-permissions');self.assertEqual(view[0],200,view[2]);self.assertEqual(view[2]['permissions'],dict(receiveMusic=False,shareMusic=False));self.assertEqual(self.native(cb,root+'/music')[0],403)
  self.room_approve(b,cb,rid,who='bob');self.assertEqual(self.native(cb,root+'/music')[0],200)
  self.assertEqual(self.h.call('/v1/devices/'+cb['deviceId'],method='DELETE',session=b,who='bob')[0],200)
  self.assertEqual(self.native(cb,root+'/music')[0],401)
  base=self.base()
  fresh=self.connect(b,'bob');self.approve(b,fresh,['rooms:read','room-music:read'],'bob')
  self.assertEqual(self.native(fresh,'/v1/native/rooms/'+rid+'/music-permissions')[2]['permissions'],dict(receiveMusic=False,shareMusic=False));self.assertEqual(self.native(fresh,root+'/music')[0],403)
  # Bob's new grant in another room must retain its own consent when Alice closes this room.
  code,_,other=self.h.call('/v1/social/rooms',dict(name='Synthetic unaffected music room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=b,who='bob')
  self.assertEqual(code,201,other)
  other_room=other['id']
  self.room_approve(b,fresh,other_room,who='bob')
  other_path='/v1/native/rooms/'+other_room+'/music-permissions'

  def music_authority(grant,room):
   with psycopg.connect(self.h.dsn, row_factory=psycopg.rows.dict_row) as conn:
    row=conn.execute('SELECT to_jsonb(g) AS grant, to_jsonb(a) AS consent '
        'FROM native_v2_grants g JOIN native_room_music_authorizations a USING(grant_id) '
        'WHERE g.grant_id=%s AND a.room_id=%s',(grant,room)).fetchone()
    self.assertIsNotNone(row)
    return row

  retired=music_authority(cb['grantId'],rid)
  self.assertEqual(retired['grant']['state'],'REVOKED')
  self.assertIsNone(retired['grant']['account_id'])
  self.assertIsNone(retired['grant']['protected_consent'])
  self.assertEqual(retired['consent']['state'],'WITHDRAWN')
  self.assertIsNone(retired['consent']['protected'])
  unrelated=music_authority(fresh['grantId'],other_room)
  self.assertIsNotNone(unrelated['consent']['protected'])
  allowed=self.native(fresh,other_path)
  self.assertEqual(allowed[0],200)
  self.assertTrue(allowed[2]['permissions']['receiveMusic'])

  self.assertEqual(self.h.call(root+'/leave',method='POST',session=a)[0],200);self.assertEqual(self.native(fresh,root+'/music')[0],404)
  self.assertEqual(music_authority(cb['grantId'],rid),retired)
  self.assertEqual(music_authority(fresh['grantId'],other_room),unrelated)
  self.assertEqual(self.native(fresh,other_path)[2]['permissions'],allowed[2]['permissions'])
  with psycopg.connect(self.h.dsn)as conn:
   self.assertEqual(conn.execute('SELECT protected FROM team_playlists WHERE playlist_id=%s',(playlist['id'],)).fetchone()[0],playlist_cipher)
   self.assertEqual(conn.execute('SELECT count(*) FROM native_room_music_authorizations WHERE room_id=%s AND protected IS NOT NULL',(rid,)).fetchone()[0],0)
  # Only the final newly created synthetic installation added base records.
  for name,rows in base.items():
   with psycopg.connect(self.h.dsn)as conn:current=conn.execute('SELECT row_to_json(t)::text FROM '+name+' t ORDER BY row_to_json(t)::text').fetchall()
   self.assertTrue(set(rows)<=set(current),name)

 def test_room_music_private_table_denies_actual_issuer_and_public_roles(self):
  from pathlib import Path
  from psycopg import sql
  with psycopg.connect(self.h.dsn)as conn:
   conn.execute('CREATE ROLE musicissuer NOLOGIN');grants=(Path(__file__).parent/'ops/live/enrollment-grants.sql').read_text()
   conn.execute(grants.replace('ON DATABASE wegoh_live','ON DATABASE '+sql.Identifier(conn.info.dbname).as_string(conn)).replace('TO wegohenroll','TO musicissuer'))
   self.assertTrue(conn.execute("SELECT has_table_privilege(current_user,'native_room_music_authorizations','SELECT,INSERT,UPDATE,DELETE')").fetchone()[0])
   self.assertFalse(conn.execute("SELECT has_table_privilege('musicissuer','native_room_music_authorizations','SELECT,INSERT,UPDATE,DELETE')").fetchone()[0])
   self.assertEqual(conn.execute("SELECT count(*) FROM information_schema.role_table_grants WHERE table_name='native_room_music_authorizations' AND grantee='PUBLIC'").fetchone()[0],0)
  for statement in ('SELECT * FROM native_room_music_authorizations','DELETE FROM native_room_music_authorizations','UPDATE native_room_music_authorizations SET revision=revision','INSERT INTO native_room_music_authorizations SELECT * FROM native_room_music_authorizations'):
   with self.subTest(statement=statement),self.assertRaises(psycopg.errors.InsufficientPrivilege):
    with psycopg.connect(self.h.dsn)as conn:conn.execute('SET LOCAL ROLE musicissuer');conn.execute(statement)

 def test_same_key_new_personal_grant_does_not_inherit_room_music_consent(self):
  import secrets
  from enrollment_crypto import challenge
  from native_access_codec import derive_revoke_capability,revoke_commitment
  from native_authorization import restore
  a=self.h.login();old=self.connect(a);self.approve(a,old,['rooms:read','room-music:read'])
  code,_,room=self.h.call('/v1/social/rooms',dict(name='Synthetic same key room',courseId=None,courseVersion=None,expiresInHours=1),'POST',session=a);self.assertEqual(code,201,room);rid=room['id']
  self.room_approve(a,old,rid);self.assertEqual(self.native(old,'/v1/social/rooms/'+rid+'/music')[0],200)
  with psycopg.connect(self.h.dsn)as conn:
   row=conn.execute('SELECT protected_receipt FROM native_v2_certificates WHERE installation_key_id=%s AND generation=1',(old['installationKeyId'],)).fetchone()
   certificate=restore('generation',old['installationKeyId']+':1',row[0])['receipt']['certificatePem'];certificates=conn.execute('SELECT row_to_json(t)::text FROM native_v2_certificates t ORDER BY row_to_json(t)::text').fetchall()
  verifier=secrets.token_urlsafe(32);operation=secrets.token_hex(16);scopes=old['scopes']
  request=dict(authorizationVersion=1,operationId=operation,name='Synthetic same key reconnect',certificatePem=certificate,codeChallenge=challenge(verifier),requestedScopes=scopes,revokeCommitment=revoke_commitment(derive_revoke_capability(verifier,old['installationKeyId'],operation)))
  from native_access_codec import decode_request
  decode_request('ACCOUNT_AUTHORIZE',request)
  # ACCOUNT_AUTHORIZE uses mTLS alone, not a current personal access token.
  code,_,pending=self.h.call('/v1/device-authorizations',request,'POST',who=None,host='api.wegoh.invalid',origin=None,certificate=self.certs[old['grantId']]);print('SYNTHETIC_ACCOUNT_AUTHORIZE_STATUS',code,pending.get('state',pending.get('error')),flush=True);self.assertEqual(code,201,pending)
  code,_,notice=self.h.call('/v1/connections/'+pending['userCode'],session=a);print('SYNTHETIC_PHONE_NOTICE_STATUS',code,flush=True);self.assertEqual(code,200,notice)
  code,_,approved=self.h.call('/v1/connections/'+pending['userCode'],dict(authorizationVersion=1,consentVersion=notice['consentVersion'],approvedScopes=scopes,keepSignedIn=True,disclosureVersion=notice['disclosureSnapshot']['disclosureVersion'],disclosureSha256=notice['disclosureSnapshot']['disclosureSha256']),'POST',session=a);print('SYNTHETIC_PHONE_APPROVE_STATUS',code,approved.get('state',approved.get('error')),flush=True);self.assertEqual(code,200,approved)
  code,_,authorized=self.h.call('/v1/device-authorizations',request,'POST',who=None,host='api.wegoh.invalid',origin=None,certificate=self.certs[old['grantId']]);print('SYNTHETIC_AUTHORIZE_AFTER_PHONE_STATUS',code,authorized.get('state',authorized.get('error')),flush=True);self.assertEqual(code,200,authorized);self.assertEqual(authorized['state'],'APPROVED')
  code,_,exchanged=self.h.call('/v1/device-sessions/exchange',dict(authorizationVersion=1,operationId=secrets.token_hex(16),grantId=authorized['grantId'],codeVerifier=verifier),'POST',who=None,host='api.wegoh.invalid',origin=None,certificate=self.certs[old['grantId']]);print('SYNTHETIC_EXCHANGE_STATUS',code,exchanged.get('state',exchanged.get('error')),flush=True);self.assertEqual(code,200,exchanged);new=exchanged['credentialReceipt'];self.certs[new['grantId']]=self.certs[old['grantId']]
  self.assertEqual(new['installationKeyId'],old['installationKeyId']);self.assertNotEqual(new['grantId'],old['grantId']);self.assertEqual(self.native(old,'/v1/account')[0],401)
  self.approve(a,new,['rooms:read','room-music:read'])
  code,_,view=self.native(new,'/v1/native/rooms/'+rid+'/music-permissions');self.assertEqual(code,200,view);self.assertEqual(view['permissions'],dict(receiveMusic=False,shareMusic=False));self.assertEqual(self.native(new,'/v1/social/rooms/'+rid+'/music')[0],403)
  self.room_approve(a,new,rid);self.assertEqual(self.native(new,'/v1/social/rooms/'+rid+'/music')[0],200)
  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT row_to_json(t)::text FROM native_v2_certificates t ORDER BY row_to_json(t)::text').fetchall(),certificates)
