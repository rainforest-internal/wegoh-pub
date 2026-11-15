"""Same-public-v1 notice text correction; old-hash synthetic grant/pending remain intact."""
import copy,hashlib,json,secrets,unittest
from unittest.mock import patch
import psycopg
import test_team_auth as fixture
import native_access_codec as codec
from native_access_policy import KNOWN_SCOPES,MANDATORY_SCOPES
from native_authorization import protect,restore
from test_enrollment import SyntheticIssuer,make_csr
from enrollment_crypto import validate_csr,public_bytes,digest,challenge
OLD_SNAPSHOT=json.loads('{"disclosureVersion": 2, "scopeDisclosures": [{"scope": "account:read", "required": true, "dataCategories": ["계정 식별자", "표시 이름"], "purpose": "본인 확인과 현재 연결 계정 표시", "retentionPolicyId": "account-read-cache-until-grant", "retention": "조회 캐시는 연결 유효기간(최대7일) 안에서만 사용하고 동의 철회 시 삭제합니다. 로그아웃 시 즉시 잠급니다. 원본 계정 및 본인이 만든 콘텐츠는 별도 탈퇴·삭제 계약을 따릅니다.", "refusalEffect": "이 기기의 개인 연결을 시작하지 않습니다.", "withdrawalEffect": "개인 연결을 종료하고 해당 조회 캐시를 삭제합니다."}, {"scope": "courses:read", "required": false, "dataCategories": ["허용된 코스 정보", "본인 코스 목록"], "purpose": "차량에서 선택한 드라이브 코스를 확인하고 준비", "retentionPolicyId": "course-read-cache-until-grant", "retention": "조회 캐시는 연결 유효기간(최대7일) 안에서만 사용하고 동의 철회 시 삭제합니다. 원본 코스·미업로드 주행 기록은 각각의 별도 보관·삭제 계약을 따르며 이 조회 동의로 재귀속하지 않습니다.", "refusalEffect": "차량에서 코스 목록과 코스 데이터를 조회하지 않습니다.", "withdrawalEffect": "코스 조회와 관련 알림을 중단하고 해당 조회 캐시를 삭제합니다."}, {"scope": "device:self:manage", "required": true, "dataCategories": ["현재 기기 연결 식별자", "동의 범위", "연결 기한·해제 상태"], "purpose": "현재 기기 연결 확인과 해제", "retentionPolicyId": "self-device-until-grant", "retention": "연결 관리 정보는 원 연결 유효기간까지 사용합니다. 철회 시 개인 식별·조회 정보는 목적별로 제거하고 재생 차단에 필요한 비식별 해시만 원 유효기간까지 보관합니다. 사용자 여행 기록을 삭제하는 계약이 아닙니다.", "refusalEffect": "이 기기의 개인 연결을 시작하지 않습니다.", "withdrawalEffect": "개인 연결을 종료하며 다른 기기나 차량을 제어하지 않습니다."}, {"scope": "playlists:read", "required": false, "dataCategories": ["본인 음악 목록 제목", "트랙 제목·링크"], "purpose": "차량에서 미리 준비한 음악 목록 확인", "retentionPolicyId": "playlist-read-cache-until-grant", "retention": "조회 캐시는 연결 유효기간(최대7일) 안에서만 사용하고 동의 철회 시 삭제합니다. 본인이 만든 원본 음악 목록은 별도 삭제 요청을 따릅니다.", "refusalEffect": "차량에서 음악 목록 데이터를 조회하지 않습니다.", "withdrawalEffect": "음악 목록 조회와 관련 알림을 중단하고 해당 조회 캐시를 삭제합니다."}], "bindingMaxSeconds": 604800, "keepSignedInDisclosure": "기본은 임시 연결로, 앱을 다시 실행하면 잠깁니다. 로그인 유지 시 이 차량의 같은 사용자 프로필에서 다른 사람도 내 계정을 이용할 수 있습니다. 최대 7일 후에는 다시 연결하며, 언제든 연결을 해제할 수 있습니다.", "disclosureSha256": "66ba056c31ac835193effe68d2673d9f40db83ae2d4fa3bc3ca5b39fb272d6f5"}\n')
class DisclosurePreservationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):fixture.TeamTests.setUpClass()
 @classmethod
 def tearDownClass(cls):fixture.TeamTests.tearDownClass()
 def setUp(self):self.h=fixture.TeamTests('test_01_jwt_verification_and_exact_hosts');self.h.setUp()
 def digest_value(self,value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 def test_existing_old_notice_grant_and_pending_are_not_rewritten_or_auto_approved(self):
  self.assertEqual(OLD_SNAPSHOT['disclosureSha256'],'66ba056c31ac835193effe68d2673d9f40db83ae2d4fa3bc3ca5b39fb272d6f5')
  for optional in [[],['courses:read'],['playlists:read'],['courses:read','playlists:read']]:
   scopes=sorted(set(MANDATORY_SCOPES)|set(optional));current=codec.disclosure_snapshot(scopes)
   previous=copy.deepcopy(OLD_SNAPSHOT);previous['scopeDisclosures']=[x for x in previous['scopeDisclosures']if x['scope']in scopes];previous.pop('disclosureSha256');old_hash=self.digest_value(previous)
   self.assertEqual(current['disclosureVersion'],2);self.assertNotEqual(current['disclosureSha256'],old_hash)
  a=self.h.login();_,_,b=self.h.pair(a);service=self.h.module.TEAM_NATIVE_AUTHORIZATION
  with service.db()as conn:
   grant=conn.execute('SELECT * FROM native_v2_grants WHERE grant_id=%s',(b['grantId'],)).fetchone()
   old_consent=restore('consent',b['grantId'],grant['protected_consent']);old_consent['disclosureVersion']=2;old_consent['disclosureSha256']=OLD_SNAPSHOT['disclosureSha256']
   conn.execute('UPDATE native_v2_grants SET protected_consent=%s WHERE grant_id=%s',(protect('consent',b['grantId'],old_consent),b['grantId']))
   installation=grant['installation_key_id']
  def b_state():
   result={}
   bindings={'native_v2_grants':('grant_id',b['grantId']),'native_v2_credentials':('grant_id',b['grantId']),'native_v2_approvals':('grant_id',b['grantId']),'native_v2_operations':('grant_id',b['grantId']),'native_v2_installations':('installation_key_id',installation),'native_v2_certificates':('installation_key_id',installation),'native_v2_connections':('installation_key_id',installation),'native_v2_renewals':('installation_key_id',installation)}
   with psycopg.connect(self.h.dsn)as conn:
    for table,(field,key)in bindings.items():
     rows=conn.execute('SELECT row_to_json(t)::text FROM '+table+' t WHERE '+field+'=%s ORDER BY row_to_json(t)::text',(key,)).fetchall();result[table]=hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    raw=conn.execute('SELECT protected_consent FROM native_v2_grants WHERE grant_id=%s',(b['grantId'],)).fetchone()[0];result['renewalOriginalConsentByteDigest']=hashlib.sha256(bytes(raw)).hexdigest()
   return result
  before_b=b_state();self.assertEqual(self.h.native('/v1/account',token=b['accessToken'])[0],200);self.assertEqual(self.h.native('/v1/device/permissions',token=b['accessToken'])[0],200)
  _,csr=make_csr();key_id=digest(public_bytes(validate_csr(csr).public_key()));verifier=secrets.token_urlsafe(32);operation=secrets.token_hex(16)
  request=dict(authorizationVersion=1,operationId=operation,name='Synthetic pending before notice update',csrPem=csr,codeChallenge=challenge(verifier),requestedScopes=sorted(KNOWN_SCOPES),revokeCommitment=codec.revoke_commitment(codec.derive_revoke_capability(verifier,key_id,operation)))
  original_issuer=service.issuer;issuer=SyntheticIssuer();service.issuer=issuer
  try:
   pending=service.begin(request)[1];path='/v1/connections/'+pending['userCode']
   def pending_digest():
    with psycopg.connect(self.h.dsn)as conn:return hashlib.sha256(conn.execute('SELECT row_to_json(t)::text FROM native_v2_connections t WHERE connection_id=%s',(pending['connectionId'],)).fetchone()[0].encode()).hexdigest()
   original_pending=pending_digest()
   approval=dict(authorizationVersion=1,consentVersion=1,approvedScopes=sorted(KNOWN_SCOPES),keepSignedIn=False,disclosureVersion=2,disclosureSha256=OLD_SNAPSHOT['disclosureSha256'])
   with psycopg.connect(self.h.dsn)as conn:grant_count=conn.execute('SELECT count(*)FROM native_v2_grants').fetchone()[0]
   code,_,error=self.h.call(path,approval,'POST',session=a);self.assertEqual(code,409);self.assertEqual(error['error'],'CONSENT_CHANGED')
   self.assertEqual(pending_digest(),original_pending);self.assertEqual(issuer.calls,0)
   with psycopg.connect(self.h.dsn)as conn:self.assertEqual(conn.execute('SELECT count(*)FROM native_v2_grants').fetchone()[0],grant_count)
   code,_,detail=self.h.call(path,session=a);self.assertEqual(code,200);self.assertEqual(detail['disclosureSnapshot'],codec.disclosure_snapshot(sorted(KNOWN_SCOPES)))
   # A cached old page/asset cannot validate the new served disclosure as the old
   # notice. It must load current assets/re-read rather than submit old approval.
   old_wire=codec.wire_contract();old_wire['disclosureRegistry']['scopePolicies']=copy.deepcopy(OLD_SNAPSHOT['scopeDisclosures'])
   with patch.object(codec,'_WIRE',old_wire):
    with self.assertRaises(codec.CodecError):codec.decode_phone_response('PHONE_STATUS',detail,expected_user_code=pending['userCode'])
   codec.decode_phone_response('PHONE_STATUS',detail,expected_user_code=pending['userCode'])
   approval['disclosureSha256']=detail['disclosureSnapshot']['disclosureSha256']
   code,_,error=self.h.call(path,approval,'POST',session=a)
   self.assertEqual(code,409);self.assertEqual(error['error'],'OPERATION_CONFLICT')
   other_owner=self.h.login('bob')
   self.assertEqual(self.h.call(path,approval,'POST',session=other_owner,who='bob')[0],200)
   self.assertEqual(pending_digest(),original_pending);self.assertEqual(issuer.calls,0)
   self.assertEqual(b_state(),before_b);self.assertEqual(self.h.native('/v1/account',token=b['accessToken'])[0],200);self.assertEqual(b_state(),before_b)
  finally:service.issuer=original_issuer
if __name__=='__main__':unittest.main()
