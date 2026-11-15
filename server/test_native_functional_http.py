from native_functional_defaults import INITIAL_PURPOSES, account_purposes
"""Current v1 explicit functional consent: owned PrivatePG/HTTP, no live services."""
import hashlib,json,unittest
from concurrent.futures import ThreadPoolExecutor
import psycopg
import test_team_auth as fixture
from native_functional_policy import WIRE
class FunctionalHttpTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  fixture.TeamTests.setUpClass()
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def setUp(self):
  self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp()
 def state(self):
  result={}
  with psycopg.connect(self.h.dsn)as conn:
   for table in ['native_v2_grants','native_v2_credentials','native_v2_approvals','native_v2_operations','native_v2_installations','native_v2_certificates']:
    rows=conn.execute('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY row_to_json(t)::text').fetchall();result[table]=hashlib.sha256(json.dumps(rows).encode()).hexdigest()
  return result
 def prepare(self):
  a,b=self.h.login(),self.h.login('bob');_,_,credential=self.h.pair(a)
  path='/v1/devices/'+credential['deviceId']+'/functional-permissions'
  status,_,self.initial=self.h.call(path,session=a);self.assertEqual(status,200,self.initial)
  return a,b,credential,path
 def body(self,c,revision=None,purposes=None):
  return dict(authorizationVersion=1,grantId=c['grantId'],revision=self.initial['revision'] if revision is None else revision,
              approvedPurposes=self.h.web_purposes(self.initial,purposes or ['history:write']),
              functionalDisclosureVersion=WIRE['disclosureVersion'],functionalDisclosureSha256=WIRE['disclosureSha256'])
 def test_owner_native_consent_cas_and_base_preservation(self):
  a,b,c,path=self.prepare();before=self.state()
  status,_,default=self.h.native('/v1/device/functional-permissions',token=c['accessToken']);self.assertEqual(status,200,default);self.assertEqual(default['approvedPurposes'],sorted(account_purposes(INITIAL_PURPOSES)));self.assertEqual(default['revision'],1);self.assertEqual(default['expiresAt'],c['grantExpiresAt'])
  without_friend_list=[purpose for purpose in default['approvedPurposes'] if purpose!='friends:read']
  status,_,unchanged=self.h.call(path,self.body(c,purposes=without_friend_list),'PUT',session=a)
  self.assertEqual((status,unchanged),(200,dict(default,functionalDisclosureVersion=WIRE['disclosureVersion'],functionalDisclosureSha256=WIRE['disclosureSha256'])))
  self.assertEqual(self.h.call(path,session=b,who='bob')[0],404)
  self.assertEqual(self.h.call(path,self.body(c,1),'PUT',session=a,csrf=False)[0],403)
  self.assertEqual(self.h.call(path,dict(self.body(c,1),grantId='f'*32),'PUT',session=a)[0],409)
  code,_,approved=self.h.call(path,self.body(c,1),'PUT',session=a);self.assertEqual(code,200,approved);self.assertEqual(approved['approvedPurposes'],sorted(account_purposes(['device-commands:receive','history:write'])));self.assertEqual(approved['revision'],2)
  self.assertEqual(self.h.call(path,self.body(c,1),'PUT',session=a)[0],409)
  code,_,native=self.h.native('/v1/device/functional-permissions',token=c['accessToken']);self.assertEqual(code,200,native);self.assertEqual(native,dict(approved,functionalDisclosureVersion=2,functionalDisclosureSha256='ec92f07e28aa015408006bd5430f9d9b440870238fabc9393c176c263d4e6657'))
  self.assertEqual(self.h.call(path,method='PUT',session=a,raw=b'{"revision":1,"revision":1}')[0],400)
  code,_,withdrawn=self.h.call(path+'/history:write',method='DELETE',session=a);self.assertEqual(code,200,withdrawn);self.assertEqual(withdrawn['approvedPurposes'],sorted(account_purposes(['device-commands:receive'])));self.assertEqual(withdrawn['revision'],3)
  self.assertEqual(self.h.call(path+'/history:write',method='DELETE',session=a)[2],withdrawn)
  self.assertEqual(self.h.native('/v1/account',token=c['accessToken'])[0],200)
  self.assertEqual(before,self.state())
  with psycopg.connect(self.h.dsn)as conn:
   self.assertEqual(conn.execute('SELECT count(*)FROM team_devices').fetchone()[0],0)
   self.assertEqual(conn.execute("SELECT count(*)FROM native_device_refs WHERE kind='native'").fetchone()[0],1)
   self.assertEqual(conn.execute("SELECT count(*)FROM pg_constraint WHERE conname LIKE '%_functional_device_ref' AND convalidated").fetchone()[0],7)
   raw=bytes(conn.execute('SELECT protected FROM native_functional_authorizations').fetchone()[0]);self.assertNotIn(b'history:write',raw)
 def test_concurrent_exact_revision_and_default_off(self):
  a,b,c,path=self.prepare();before=self.state()
  bodies=[self.body(c,purposes=['history:write']),self.body(c,purposes=['vehicle-visits:report'])]
  with ThreadPoolExecutor(max_workers=2)as pool:codes=list(pool.map(lambda body:self.h.call(path,body,'PUT',session=a)[0],bodies))
  self.assertEqual(sorted(codes),[200,409]);self.assertEqual(before,self.state())
  code,_,snapshot=self.h.call(path,session=a);self.assertEqual(code,200);self.assertEqual(snapshot['revision'],self.initial['revision']+1);self.assertIn(snapshot['approvedPurposes'],[sorted(account_purposes(body['approvedPurposes'])) for body in bodies])
  self.assertEqual(self.h.call(path,dict(self.body(c,1),approvedPurposes=['courses:read']),'PUT',session=a)[0],400)
 def test_expiry_and_reference_row_are_not_authority(self):
  a,b,c,path=self.prepare()
  with psycopg.connect(self.h.dsn)as conn:
   conn.execute("INSERT INTO native_device_refs(device_id,kind)VALUES(%s,'native')",('f'*32,))
   conn.execute((fixture.ROOT/'server/native_functional_schema.sql').read_text())
  phantom='/v1/devices/'+'f'*32+'/functional-permissions'
  self.assertEqual(self.h.call(phantom,session=a)[0],404)
  with psycopg.connect(self.h.dsn)as conn:conn.execute('UPDATE native_v2_grants SET expires_at=1 WHERE grant_id=%s',(c['grantId'],))
  self.assertEqual(self.h.call(path,session=a)[0],404)
  self.assertEqual(self.h.native('/v1/device/functional-permissions',token=c['accessToken'])[0],410)
 def test_auth_free_encrypted_restore_and_base_logout_purge(self):
  from pathlib import Path
  from psycopg import sql
  from ops.live import backup
  from native_access_backup import BackupProjectionError,validate_restored_projection
  a,b,c,path=self.prepare()
  self.assertEqual(self.h.call(path,self.body(c),'PUT',session=a)[0],200)
  original=self.state();base=self.h.state/'functional-backup';base.mkdir(mode=0o700)
  content=self.h.state/'content';blob=b'Synthetic journey object retained';digest=hashlib.sha256(blob).hexdigest();(content/digest).write_bytes(blob)
  tools=Path(self.h.tools['pg_ctl']).parent
  layout=backup.Layout(self.h.dsn,content,base,str(tools/'pg_dump'),str(tools/'pg_restore'))
  archive=backup.snapshot(layout);manifest=backup.authenticated_manifest(archive)
  self.assertEqual(manifest['tables']['native_functional_authorizations']['rows'],0)
  self.assertEqual(original,self.state())
  target='functional_restore'
  destination=psycopg.conninfo.make_conninfo(self.h.dsn,dbname=target)
  with psycopg.connect(self.h.dsn,autocommit=True)as conn:conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
  try:
   work=base/'scratch';work.mkdir(mode=0o700)
   result=backup.verify_into(layout,archive,destination,work)
   self.assertTrue(result['verified']);self.assertEqual(result['nativeV2Auth']['personalSessionsRestored'],0)
   self.assertEqual((work/'objects'/digest).read_bytes(),blob);self.assertEqual((content/digest).read_bytes(),blob)
   with psycopg.connect(destination)as conn:
    self.assertEqual(conn.execute('SELECT count(*)FROM native_functional_authorizations').fetchone()[0],0)
    self.assertEqual(conn.execute('SELECT count(*)FROM native_device_refs').fetchone()[0],1)
    self.assertEqual(conn.execute('SELECT count(*)FROM native_v2_credentials').fetchone()[0],0)
    self.assertEqual(conn.execute('SELECT state,account_id,protected_consent FROM native_v2_grants').fetchone(),('REVOKED',None,None))
    self.assertEqual(conn.execute("SELECT count(*)FROM pg_constraint WHERE conname LIKE '%_functional_device_ref' AND convalidated").fetchone()[0],7)
    # A mistakenly restored consent is not accepted as a valid auth-free restore.
    conn.execute("INSERT INTO native_functional_authorizations SELECT grant_id,device_id,installation_key_id,1,'REVOKED',NULL,expires_at FROM native_v2_grants")
    with self.assertRaises(BackupProjectionError):validate_restored_projection(conn,manifest['nativeV2Auth'],restored_at=1)
    conn.rollback()
  finally:
   with psycopg.connect(self.h.dsn,autocommit=True)as conn:conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target)))
  self.assertEqual(original,self.state())
  self.assertEqual(self.h.native('/v1/device',method='DELETE',token=c['accessToken'])[0],200)
  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT state,protected FROM native_functional_authorizations').fetchone(),('REVOKED',None))
 def test_populated_seven_fk_migration_and_encrypted_restore_preserve_ciphertext(self):
  from pathlib import Path
  from copy import copy
  from psycopg import sql
  from starlette.requests import Request
  from private_records import VisitCipher
  from native_authorization import NativeAuthorizationError
  from ops.live import backup
  a,b,c,path=self.prepare();self.assertEqual(self.h.call(path,self.body(c),'PUT',session=a)[0],200)
  owner=a['user']['id'];legacy='e'*32;room='1'*32;mission='2'*32
  tables=['team_mission_device_grants','team_device_command_access','team_device_command_grants','team_device_commands','team_vehicle_purposes','team_vehicle_latest_reports','team_vehicle_report_receipts']
  cipher=VisitCipher();keypath=self.h.state/'visits.key';key_digest=hashlib.sha256(keypath.read_bytes()).hexdigest()
  def protected(label):return cipher.protect('synthetic-populated-seven',label,dict(kind=label,synthetic=True,original='preserved encrypted fixture'))
  def digest_rows(conn):
   conn.execute("SET LOCAL timezone='UTC'")
   result={}
   for table in tables+['team_devices']:
    rows=conn.execute(sql.SQL('SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text').format(sql.Identifier(table))).fetchall()
    result[table]=(len(rows),hashlib.sha256(json.dumps(rows).encode()).hexdigest())
   return result
  def seed(conn,device,tag):
   raw={table:protected(table+':'+tag)for table in tables}
   conn.execute("INSERT INTO team_mission_device_grants(mission_id,account_id,device_id,protected,expires_at)VALUES(%s,%s,%s,%s,now()+interval '1 hour')",(mission,owner,device,raw[tables[0]]))
   conn.execute('INSERT INTO team_device_command_access(device_id,protected)VALUES(%s,%s)',(device,raw[tables[1]]))
   conn.execute('INSERT INTO team_device_command_grants(room_id,device_id,requester_id,owner_id,protected)VALUES(%s,%s,%s,%s,%s)',(room,device,owner,owner,raw[tables[2]]))
   conn.execute('INSERT INTO team_device_commands(request_id,room_id,device_id,requester_id,owner_id,event_hash,protected)VALUES(%s,%s,%s,%s,%s,%s,%s)',(tag*32,room,device,owner,owner,tag*64,raw[tables[3]]))
   conn.execute("INSERT INTO team_vehicle_purposes(device_id,account_id,protected,expires_at)VALUES(%s,%s,%s,now()+interval '1 hour')",(device,owner,raw[tables[4]]))
   conn.execute("INSERT INTO team_vehicle_latest_reports(room_id,device_id,kind,account_id,protected)VALUES(%s,%s,'location',%s,%s)",(room,device,owner,raw[tables[5]]))
   conn.execute('INSERT INTO team_vehicle_report_receipts(device_id,event_id,account_id,protected)VALUES(%s,%s,%s,%s)',(device,tag*32,owner,raw[tables[6]]))
   return raw
  with psycopg.connect(self.h.dsn)as conn:
   conn.execute("INSERT INTO team_rooms(room_id,owner_id,code_hash,protected,expires_at)VALUES(%s,%s,%s,%s,now()+interval '1 hour')",(room,owner,'f'*64,protected('room')))
   conn.execute('INSERT INTO team_missions(mission_id,room_id,owner_id,protected)VALUES(%s,%s,%s,%s)',(mission,room,owner,protected('mission')))
   conn.execute('INSERT INTO team_mission_members(mission_id,account_id,protected)VALUES(%s,%s,%s)',(mission,owner,protected('member')))
   conn.execute("INSERT INTO team_devices(device_id,account_id,protected,access_hash,access_expires_at,refresh_hash,expires_at)VALUES(%s,%s,%s,%s,now()+interval '1 hour',%s,now()+interval '1 hour')",(legacy,owner,protected('legacy-device'),hashlib.sha256(('L'*43).encode()).hexdigest(),hashlib.sha256(('R'*43).encode()).hexdigest()))
   # Reproduce the original seven legacy-device FKs while their tables are empty,
   # then seed real encrypted rows BEFORE applying the exact migration source.
   for table in tables:
    conn.execute(sql.SQL('ALTER TABLE {} DROP CONSTRAINT {}').format(sql.Identifier(table),sql.Identifier(table+'_functional_device_ref')))
    conn.execute(sql.SQL('ALTER TABLE {} ADD CONSTRAINT {} FOREIGN KEY(device_id)REFERENCES team_devices(device_id)').format(sql.Identifier(table),sql.Identifier(table+'_pre_migration_device_fk')))
   legacy_cipher=seed(conn,legacy,'3');before_migration=digest_rows(conn)
   self.assertTrue(all(before_migration[t][0]==1 for t in tables))
   conn.execute((fixture.ROOT/'server/native_functional_schema.sql').read_text())
   self.assertEqual(before_migration,digest_rows(conn))
   self.assertEqual(conn.execute('SELECT kind FROM native_device_refs WHERE device_id=%s',(legacy,)).fetchone()[0],'retired')
   native_cipher=seed(conn,c['deviceId'],'4');source_rows=digest_rows(conn)
   self.assertTrue(all(source_rows[t][0]==2 for t in tables))
   for table in tables:
    # A migrated FK really rejects a missing reference, not just NOT VALID data.
    with self.assertRaises(psycopg.errors.ForeignKeyViolation):
     with conn.transaction():conn.execute(sql.SQL('UPDATE {} SET device_id=%s WHERE device_id=%s').format(sql.Identifier(table)),('d'*32,c['deviceId']))
  base_state=self.state();work=self.h.state/'populated-seven';work.mkdir(mode=0o700);content=self.h.state/'content'
  blob=b'Synthetic original journey bytes retained';blob_id=hashlib.sha256(blob).hexdigest();(content/blob_id).write_bytes(blob)
  tools=Path(self.h.tools['pg_ctl']).parent;layout=backup.Layout(self.h.dsn,content,work,str(tools/'pg_dump'),str(tools/'pg_restore'))
  archive=backup.snapshot(layout);target='populated_seven_restore';destination=psycopg.conninfo.make_conninfo(self.h.dsn,dbname=target)
  with psycopg.connect(self.h.dsn,autocommit=True)as conn:conn.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
  try:
   scratch=work/'scratch';scratch.mkdir(mode=0o700);result=backup.verify_into(layout,archive,destination,scratch)
   self.assertTrue(result['verified']);self.assertEqual(result['nativeV2Auth']['personalSessionsRestored'],0)
   with psycopg.connect(destination)as conn:
    self.assertEqual(source_rows,digest_rows(conn))
    for table in tables:
     for device,raw in [(legacy,legacy_cipher[table]),(c['deviceId'],native_cipher[table])]:
      restored=bytes(conn.execute(sql.SQL('SELECT protected FROM {} WHERE device_id=%s').format(sql.Identifier(table)),(device,)).fetchone()[0]);self.assertEqual(restored,raw)
     missing=conn.execute(sql.SQL('SELECT count(*)FROM {} t LEFT JOIN native_device_refs r ON r.device_id=t.device_id WHERE r.device_id IS NULL').format(sql.Identifier(table))).fetchone()[0];self.assertEqual(missing,0)
    self.assertEqual(conn.execute("SELECT count(*)FROM pg_constraint WHERE conname LIKE '%_functional_device_ref' AND confrelid='native_device_refs'::regclass AND convalidated").fetchone()[0],7)
    self.assertEqual(conn.execute('SELECT count(*)FROM native_functional_authorizations').fetchone()[0],0)
    self.assertEqual(conn.execute('SELECT count(*)FROM native_v2_credentials').fetchone()[0],0)
    self.assertEqual(conn.execute('SELECT active_grant_id FROM native_v2_installations').fetchone()[0],None)
   # Old legacy and modern bearer bytes both remain unable to authenticate into
   # the restored database. Copy only service configuration, never live state.
   restored_auth=copy(self.h.module.TEAM_AUTH);restored_auth.dsn=destination
   restored_base=copy(self.h.module.TEAM_NATIVE_AUTHORIZATION);restored_base.auth=restored_auth
   for token in [c['accessToken'],'L'*43]:
    headers={'host':'api.wegoh.invalid','authorization':'Bearer '+token,'cf-cert-sha256':self.h._native_fingerprint,'cf-cert-presented':'true','cf-cert-verified':'true','cf-cert-revoked':'false'}
    request=Request(dict(type='http',method='GET',path='/v1/account',query_string=b'',scheme='http',client=('127.0.0.1',1234),server=('api.wegoh.invalid',80),headers=[(k.encode(),v.encode())for k,v in headers.items()]))
    with self.assertRaises(NativeAuthorizationError)as error:restored_base.authenticate(request)
    self.assertEqual(error.exception.status,401)
   self.assertEqual((scratch/'objects'/blob_id).read_bytes(),blob)
  finally:
   with psycopg.connect(self.h.dsn,autocommit=True)as conn:conn.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target)))
  self.assertEqual(base_state,self.state());self.assertEqual(hashlib.sha256(keypath.read_bytes()).hexdigest(),key_digest)
  with psycopg.connect(self.h.dsn)as conn:self.assertEqual(source_rows,digest_rows(conn))
if __name__=='__main__':unittest.main()
