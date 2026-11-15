"""Authored single-public-v1 OpenAPI overlay, derived from the single strict wire contract.

Security: OAS 3.1.1 Security Requirement Object (same object=AND, array=OR).
https://spec.openapis.org/oas/v3.1.1.html#security-requirement-object
https://learn.openapis.org/specification/security.html
This module documents routes; it never enables a handler or changes authorization.
"""
import copy
import hashlib
import json
from pathlib import Path
from native_access_codec import wire_contract, disclosure_snapshot, derive_capability, derive_revoke_capability, revoke_commitment

TAG = '16 차량 연결'
SOURCES = ['server/native_access_wire.json', 'server/native_access_codec.py',
           'server/native_authorization.py', 'server/native_access_renewal.py', 'server/native_access_reauthorization.py', 'scripts/native_connect.py']
FIELD = {
 'revokeCommitment':'기기/설치 키와 이 begin operation의 사전 revoke-only capability SHA256 commitment. 새 동의 승인 단계부터 철회만 가능하게 결합하며 capability 자체·조회/복구 권한은 포함하지 않습니다.',
 'certificateReceipt':'같은 설치 키의 검증된 공개 인증서 receipt. 개인 token/계정 권한은 포함하지 않습니다.',
 'credentialReceipt':'같은 개인 grant의 비공개 자격 receipt. 검증 후 암호화 원자 저장하고 실제 본인 API 확인 전에는 연결 완료가 아닙니다.',
 'authorizationVersion':'정확한 JSON 정수 1. 단일 공개 계약이며 버전 선택·구형 본문 추정·자동 fallback을 하지 않습니다.',
 'operation':'이 응답을 만든 정확한 action. 요청한 action과 같아야 합니다.',
 'operationId':'새 작업마다 만든 무작위 128비트의 32자리 소문자 hex. 부작용 전에 암호화 저장하고 응답 유실 시 같은 값·같은 본문을 재사용합니다.',
 'connectionId':'서버가 반환한 연결 요청 ID. 공개 코드·개인 grant ID와 다릅니다.',
 'name':'폰에서 본인이 대조할 기기 이름. Unicode scalar 1~80개/UTF-8 240바이트 이내, 앞뒤 공백·제어문자·surrogate 금지.',
 'deviceName':'실제 요청 기기 이름. 폰에서 차량 화면의 이름·공개 코드와 함께 확인합니다.',
 'csrPem':'자기 키로 서명한 PKCS#10 CSR 한 개. RSA2048/e65537/SHA256, CN=WegoH-32hex 한 개, attributes/extensions 없음. 개인키를 전송하지 않습니다.',
 'certificatePem':'현재 설치 키의 공개 client leaf PEM 한 개. 서버 신뢰 CA가 아니며 TLS 검증을 끄는 용도가 아닙니다.',
 'codeChallenge':'비공개 codeVerifier의 SHA256을 canonical base64url 무패딩으로 표현한 43자. S256만 지원합니다.',
 'requestedScopes':'정확한 정렬·중복 없는 요청 scope. 필수 account:read/device:self:manage와 본인이 선택한 선택 scope만 요청합니다.',
 'approvedScopes':'폰에서 본인이 실제 허용한 요청 scope의 정렬된 부분집합. 필수 scope가 하나라도 없으면 전체 연결을 DENIED로 끝냅니다.',
 'requiredScopes':'변경할 수 없는 필수 scope 두 개. 거절하려면 연결 전체를 취소할 수 있습니다.',
 'codeVerifier':'해당 신청 전에 만든 43~128자 PKCE 비밀. URL·QR·로그·문서 캡처에 넣지 않으며 원 신청의 challenge와 일치해야 합니다.',
 'oldCodeVerifier':'재시작 허가를 받은 이전 신청의 PKCE 비밀. 새로운 challenge의 verifier와 혼동하지 않습니다.',
 'originalBeginHash':'암호화 보존한 최초 begin 요청의 canonical UTF-8 JSON 전체 SHA256. 임의로 재구성한 다른 본문은 거절합니다.',
 'proof':'해당 action의 canonical proof transcript를 같은 CSR 개인키로 RSASSA-PKCS1-v1_5/SHA256 서명한 342자 canonical base64url. 다른 action·host·path·본문에 재사용할 수 없습니다.',
 'proofNonce':'그 신청의 저장된 server nonce. CONNECTION_RECOVER는 begin-recovery, CONNECTION_CANCEL은 connection-cancel, CERTIFICATE_RENEW_BEGIN은 certificate-renewal, CONNECTION_REAUTHORIZE는 account-reauthorization 고정 문자열을 사용합니다. native mTLS action에는 별도 RSA nonce를 추가하지 않습니다.',
 'previousConnectionId':'서버가 EXPIRED_NOT_ISSUED로 확인한 이전 연결 요청. 기존 행·키를 지우지 않습니다.',
 'restartTicket':'서버가 안전한 미발급을 확인해 준 짧은 key-bound 재시작 비밀. 만료됐거나 사용한 ticket으로 신규 발급을 반복하지 않습니다.',
 'grantId':'폰 동의에 결합한 개인 grant ID. 설치 인증서가 개인 grant나 차량 소유권을 대신하지 않습니다.',
 'deviceId':'이 grant의 본인 개인 기기 연결 ID. 새 credential로 바꿔도 같은 grant/device를 유지합니다.',
 'recoveryCapability':'같은 살아 있는 개인 grant의 제한 복구 비밀. 같은 키·현재 슬롯·scope/동의·원 만료를 재검증하며 철회·다른 계정을 되살리지 못합니다.',
 'revokeCapability':'해당 device의 철회만 가능한 목적 분리 비밀. 조회·refresh·다른 기기·차량 제어에 사용할 수 없습니다.',
 'refreshToken':'현재 회전 refresh 비밀. 동일 operation 응답 유실만 같은 결과를 재수령하며 다른 operation으로 옛 refresh를 재생하지 않습니다.',
 'accessToken':'기기/개인 grant/scope/인증서 세대에 결합한 opaque Bearer. JWT가 아니며 URL·QR·로그에 넣지 않습니다.',
 'tokenType':'정확한 Bearer 문자열. 이 사용자 정의 연결 절차를 OAuth2 전체 준수라고 표현하지 않습니다.',
 'installationKeyId':'SubjectPublicKeyInfo DER SHA256. leaf 인증서 DER의 certificateSha256과 다른 값입니다.',
 'certificateSha256':'실제 client leaf DER SHA256. mTLS edge가 검증한 현재 세대와 대조합니다. 클라이언트가 Cloudflare 인증 헤더를 만들어 보내면 안 됩니다.',
 'generation':'설치의 인증서 세대. 개인 계정 동의 버전·credential epoch와 구분합니다.',
 'generationOperationId':'서버가 승인한 이 인증서 세대의 원래 작업 ID. 공개 cert 복구의 대상입니다.',
 'expectedGeneration':'작업의 기준 인증서 세대. CERTIFICATE_RECOVER는 이미 승인된 수령 대상, CERTIFICATE_RENEW_BEGIN·CONNECTION_REAUTHORIZE는 현재 세대이며 새 세대는 정확히 +1입니다.',
 'consentVersion':'현재 목적·scope의 동의 버전. codec/schema/disclosure 버전과 다릅니다.',
 'disclosureVersion':'폰이 실제 표시한 불변 설명 registry의 버전. POST는 직전 GET의 값과 정확히 같아야 합니다.',
 'disclosureSha256':'직전 GET 설명 snapshot의 canonical SHA256. 보관/거부/철회/유지 설명을 바꾸거나 오래된 설명으로 승인하면 거절합니다.',
 'disclosureSnapshot':'현재 요청 scope의 데이터·목적·보관·거부·철회·로그인 유지 설명 정본. 표시 내용과 승인 hash를 같은 snapshot으로 연결합니다.',
 'keepSignedIn':'폰 소유자가 명시 선택한 경우만 true. 기본 false이며 같은 OS 사용자를 공유하는 위험을 먼저 설명합니다.',
 'keepSignedInDefault':'항상 false. 로그인 유지를 동의에 묶어 강제하거나 기본 체크하지 않습니다.',
 'currentAccountDisplayName':'현재 폰 로그인 계정의 표시 이름. 기기 발급 승인자를 모든 사용자의 영구 소유자로 취급하지 않습니다.',
 'accountId':'본인 계정 ID(team- 뒤 40자리 소문자 hex). 이메일·VIN·다른 계정 자료를 반환하는 권한이 아닙니다.',
 'scopes':'현재 살아 있는 grant의 승인 scope. 역할/admin을 이유로 넓히지 않으며 선택 scope 축소 시 옛 receipt를 되살리지 않습니다.',
 'credentialEpoch':'같은 grant의 credential 회전 epoch. 옛 access/refresh/응답 receipt를 거절하는 기준입니다.',
 'slotRevision':'설치의 활성 개인 계정 슬롯 revision. 늦은 이전 계정 응답은 새 슬롯을 다시 열 수 없습니다.',
 'expiresAt':'이 객체의 실제 만료 Unix UTC 초. user code 5분/개인 access 최대15분/인증서 notAfter는 별개입니다.',
 'exchangeExpiresAt':'실제 폰 승인 뒤 개인 교환을 끝낼 기한. 승인 전 코드 기한과 분리됩니다.',
 'grantExpiresAt':'개인 연결의 원래 절대 기한(현재 정책 최대7일). refresh·복구·기술적 인증서 교체로 연장하지 않습니다.',
 'restartExpiresAt':'안전한 미발급 재시작 ticket의 기한. 로컬 시계·timeout만으로 미발급을 추정하지 않습니다.',
 'revokedAt':'서버가 확인한 원래 terminal 철회 시각. 반복 해제도 같은 결과이며 local lock과 구분합니다.',
 'expiredAt':'서버가 확인한 원 grant 만료 시각. 이 acknowledgment 뒤 제한 철회 outbox를 제거할 수 있습니다.',
 'serverTime':'응답 생성 서버의 Unix UTC 초. 로컬 timeout으로 발급·승인·철회 성공을 추정하지 않습니다.',
 'state':'반드시 disposition과 함께 확인할 실제 처리 상태. HTTP200만으로 연결 완료를 표시하지 않습니다.',
 'disposition':'이 상태에서 허용한 다음 행동. WAIT/RECONCILE은 성공·새 발급 허가가 아닙니다.',
 'userCode':'권한 없는 공개 8자 확인 코드. 차량·폰에서 대조하며 token/device code/verifier와 혼동하지 않습니다.',
 'verificationUri':'고정 WegoH /enroll.html URL의 공개 user_code 하나만 포함합니다. 임의 redirect/return_to나 비밀을 받지 않습니다.',
 'interval':'다음 조회까지 지켜야 할 최소 초(5~60). 화면 복귀나 반복 탭으로 polling을 늘리지 않습니다.',
 'retryAfter':'429/대기 응답의 최소 재시도 대기 초. 같은 작업을 보존하며 새 key/profile/operation을 자동 생성하지 않습니다.',
}
SECRET_FIELDS={'codeVerifier','oldCodeVerifier','restartTicket','recoveryCapability','revokeCapability','refreshToken','accessToken','proof'}

# Per-action behavior is authored; schema shape/closed fields come only from wire.
ACTION={
 'CONNECTION_BEGIN':('연결 요청 만들기','최초 설치의 기기/개발 PC','키·CSR·PKCE·정확한 begin 본문/operationId를 네트워크 전에 암호화 저장합니다.',
 '이 요청 → 공개 확인 URL에서 본인 로그인·명시 승인 한 번 → 같은 키 claim → mTLS session exchange → 본인 API 확인.',
 '요청·공개 코드만 저장합니다. 승인 전 인증서·개인 token 발급은0입니다. 같은 설치 키의 다른 operation이 오면 아직 claim되지 않은 이전 코드를 즉시 만료시키고(폰에서는 410) 새 코드를 만듭니다. 거절된 begin은 이전 코드를 건드리지 않습니다.',
 '응답 유실이면 같은 begin/body/op를 재사용합니다. 새 키·폴더·다른 operation으로 자동 반복하지 않습니다. 차량이 코드를 취소·계정 전환·로그아웃으로 버린 뒤에만 새 operation을 보냅니다.'),
 'CONNECTION_REAUTHORIZE':('만료된 차량 인증서를 같은 키로 다시 연결하기','원 설치 키·CSR·서버가 승인한 인증서 세대를 보존한 기기',
 '기존 공개 인증서가 실제 만료됐고 설치가 사고 차단되지 않아야 합니다. 같은 키의 전체 본문 proof와 PKCE·현재 expectedGeneration이 필요하며, 서버가 인증된 CA GET으로 정확한 이전 certificateId/DER/CA의 active 상태를 재검증합니다.',
 '같은 key·새 operation/PKCE를 보존 → 이 공개 enroll 요청 → 기기/코드/범위를 본인 폰에서 한 번 새로 승인 → 동일 claim → 검증한 새 leaf mTLS로 SESSION_EXCHANGE → 본인 API 확인.',
 '개인 grant가 만료됐거나 임시 연결이 잠겼어도 새 본인 동의로 별도 fresh grant를 만듭니다. 기존 grant·이전 scope·기한을 부활시키지 않습니다. 새 leaf는 발급 후 main CAS까지 stage이며 명시 동의 전에 CA POST/token은0입니다.',
 '명시 CA 철회·설치 ban·CA 결과 불명은 차단합니다. 일반 TLS/401/403을 철회나 재발급 허가로 추정하지 않습니다. 응답 유실은 같은 body/op로 복구하고 기존 키/CSR 전달·새 개인 폴더·관리자 수동 발급으로 우회하지 않습니다.'),
 'CONNECTION_RESTART':('미발급으로 확인된 코드 다시 시작하기','이전 요청을 보존한 같은 기기',
 '서버의 EXPIRED_NOT_ISSUED/USER_RESTART_ALLOWED와 아직 유효한 restartTicket·기존 key/verifier를 받았고 사용자가 재시작을 명시했습니다.',
 '기존 recover → 새 PKCE/operation + 옛 verifier/ticket의 목적분리 proof → 새 공개 코드에서 새 동의.',
 '기존 행/키를 유지하고 ticket을 한 번 소비합니다. 이전 동의를 새 코드로 옮기지 않습니다.',
 'ISSUING/UNCERTAIN/ISSUED는 이 경로로 새 CA POST를 만들 수 없습니다. timeout/로컬 만료만으로 호출하지 않습니다.'),
 'CONNECTION_RECOVER':('응답이 끊긴 연결 상태 복구하기','같은 키·원 begin·PKCE를 보존한 기기',
 '원 operation/CSR/canonical begin hash/verifier와 begin-recovery 목적의 키 서명이 필요합니다.',
 '기존 원문으로 서명 → 상태 조회 → disposition에 따라 대기/claim/기존 cert 수령/같은 grant 교환.',
 '조회 자체는 새 CA POST·새 grant·계정 token을 만들지 않습니다. 다른 키 상태나 원문을 노출하지 않습니다.',
 'OPERATION_NOT_FOUND이면 같은 원 begin만 반복합니다. RECONCILE은 불확실 상태 유지이며 GET 부재/시간 경과를 미발급으로 해석하지 않습니다.'),
 'CONNECTION_CANCEL':('차량에서 취소한 연결 코드 바로 끝내기','코드를 띄웠다가 취소·로그아웃·계정 전환한 같은 기기',
 '취소할 원 begin/ACCOUNT_AUTHORIZE의 operationId와 그 PKCE verifier, connection-cancel 목적의 같은 설치 키 서명이 필요합니다. ACCOUNT 코드는 그 인증서의 키로 서명합니다.',
 '차량 화면의 코드 취소 → 로컬 잠금과 함께 서명한 취소 요청 저장 → 이 요청 → 서버 EXPIRED/TERMINAL 확인 후 저장분 제거.',
 '그 코드만 지금 만료시켜 폰 조회·승인과 차량 재조회가 410 AUTHORIZATION_EXPIRED가 됩니다. 폰이 이미 승인했어도 claim·SESSION_EXCHANGE 전이면 그 코드로는 claim·교환이 410이 되고 차량 슬롯을 차지하지 않습니다. 다른 키·verifier·operation으로는 끝낼 수 없고 인증서·grant·token을 만들거나 지우지 않습니다.',
 '반복 호출은 같은 EXPIRED 결과입니다. ISSUING/UNCERTAIN/ISSUED는 409이며 그 연결은 claim·GRANT_REVOKE 경로로 정리합니다. 이미 교환한 ACCOUNT 세션은 코드 취소로 끝나지 않고 SESSION_REVOKE로 정리합니다. 네트워크가 실패해도 차량의 로컬 취소는 그대로이며, 다음 연결 요청이 같은 키의 이전 코드를 끝내고 아니면 원래 만료(최대 5분)에 끝납니다.'),
 'CONNECTION_CLAIM':('승인 후 같은 키의 인증서 받기','원 연결 기기',
 '폰의 현재 유효한 명시 승인·회원 상태·원 PKCE와 server nonce의 정확 action proof가 필요합니다.',
 'interval 준수 → claim → ISSUED receipt의 DER/SPKI/KU/EKU/notAfter 검증·설치 → SESSION_EXCHANGE.',
 '서버가 ISSUING을 durable commit한 뒤 처음 한 번만 외부 CA 발급을 시도합니다. 이 프로세스는 개인 token을 쓰지 못합니다.',
 '202 WAIT는 최소 interval 대기, ISSUING/UNCERTAIN은 복구 조회입니다. 새 CSR/key/profile 또는 새 CF POST로 우회하지 않습니다.'),
 'ACCOUNT_AUTHORIZE':('기존 인증서로 개인 계정 연결하기','현재 유효 인증서를 가진 기기',
 '실제 mTLS leaf와 요청 공개 leaf의 DER/SPKI가 같아야 합니다. 인증서만으로 개인 계정 권한은 없습니다.',
 '기존 cert·새 PKCE/operation → 같은 폰 동의 한 번 → 승인 grant의 SESSION_EXCHANGE. 새 cert는 발급하지 않습니다.',
 '계정별 가족 이용·명시 재연결·scope 확대의 새 동의 요청을 생성합니다. 같은 설치 키의 다른 operation이 오면 아직 claim되지 않은 이전 코드(로그아웃 뒤 차량에서 취소한 코드 포함)를 즉시 만료시키고(폰에서는 410) 새 코드를 만듭니다. 이전 token·역할·인증서만으로 개인 권한을 승계하지 않습니다.',
 '동일 operation/본문은 같은 코드·현재 승인 상태를 돌려줍니다. 인증 오류를 새 설치 키/수동 CSR·퇴역 API로 우회하지 않습니다.'),
 'SESSION_EXCHANGE':('명시 승인된 개인 연결 완료하기','인증서 수령을 끝낸 같은 기기',
 '현재 세대 mTLS·같은 owner/동의/scope·살아 있는 승인 grant와 원 PKCE가 필요합니다.',
 'certificate 검증 → 이 교환 → 암호화 credential 원자 저장 → GET account/permissions 확인 → 연결 완료.',
 'grant당 기기 하나와 현재 슬롯을 원자 생성/교체합니다. 개인 token은 인증서·원 동의·scope에 결합합니다.',
 '같은 operation/본문의 응답 유실은 동일 암호화 receipt를 재수령합니다. 늦은/철회/옛 슬롯 receipt를 수용하지 않습니다.'),
 'SESSION_RECOVER':('같은 개인 연결의 credential 복구하기','암호화 active-account state를 보존한 같은 기기',
 '현재 mTLS·같은 grant/device의 recoveryCapability·현재 살아 있는 scope/동의/슬롯이 필요합니다.',
 '실제 서버 상태 확인 → 새 operation으로 제한 복구 → 같은 owner/device/원 만료의 receipt 검증 → 계정 재확인.',
 '동일 grant의 자격만 교체합니다. 선택 scope 축소는 새 QR 없이 현재 축소 정본만 받으며 다른 계정/권한/원 기한을 만들지 않습니다.',
 '필수 scope 철회·만료·logout 후 부활은 불가합니다. recoveryCapability를 URL·일반 API·refresh에 사용하지 않습니다.'),
 'SESSION_REFRESH':('개인 access credential 갱신하기','현재 개인 연결 기기',
 '현재 mTLS·grant/device·한 번 쓰는 current refresh와 사전 저장한 operation이 필요합니다.',
 '회전 전 operation 저장 → refresh → 새 receipt 원자 저장 → 이전 access/refresh 폐기 → 계정 확인.',
 '같은 device의 epoch만 회전하며 원 grant 만료는 연장하지 않습니다. 정상15분 갱신은 QR·CA POST가0입니다.',
 '같은 operation의 유실 응답만 재수령합니다. 다른 operation으로 옛 refresh를 재생하지 말고 권위 있는 STALE_EPOCH는 같은 grant 복구로 처리합니다.'),
 'GRANT_REVOKE':('기기 ID 수령 전에도 내 연결 승인 해제하기','본인 기기의 logout/outbox 처리기',
 '같은 설치 키의 실제 mTLS와 신청 전에 commitment한 exact grant revokeCapability만 필요합니다. deviceId·개인 Bearer·recoveryCapability는 요구하지 않습니다. 현재 leaf 또는 이 grant에 정확히 결합한 검증된 staged leaf만 허용합니다.',
 'begin 전에 capability/commitment 보존 → 폰 승인·grantId 수령 → local 잠금 시 deviceId가 없어도 이 revoke-only outbox 저장 → 요청 → 동일 grantId/terminal 시각 ack 확인 후 outbox 제거.',
 'APPROVED 또는 TOKEN_ISSUED 개인 grant만 terminal로 닫고 목적자료를 제거합니다. 조회·refresh·계정 전환·설치 전체 차단/키 삭제/다른 grant 철회 권한이 아닙니다. exchange 응답 유실도 새 개인 token을 수령할 필요 없이 해제합니다.',
 'offline/응답 유실이면 local privacy lock을 유지하고 같은 operation/목적 capability만 재전송합니다. staged leaf가 서버 current로 아직 바뀌지 않아도 이 exact grant의 해제 예외만 허용하며 인증서의 일반 API 접근권한으로 확대하지 않습니다.'),
 'SESSION_REVOKE':('내 개인 기기 연결 해제하기','본인 기기의 local logout/outbox 처리기',
 '실제 같은 설치 키 mTLS와 해당 grant/device의 revoke 전용 capability가 필요합니다. 개인 Bearer 조회 권한은 요구하지 않습니다.',
 'local privacy lock/WSS close/개인 표시 중단 → 이 요청 → 서버의 revokedAt/expiredAt 확인 → outbox 제거.',
 '이 개인 grant만 terminal로 닫고 재실행도 원 철회 결과를 반환합니다. 설치 key/cert·다른 사용자 기록·다른 기기는 폐기하지 않습니다.',
 'offline이면 즉시 local lock 후 revoke-only 암호화 outbox를 보존합니다. timeout을 원격 철회 완료라고 표시하지 않습니다.'),
 'CERTIFICATE_RENEW_BEGIN':('같은 개인 연결의 인증서 교체 준비하기','같은 설치 키와 살아 있는 현재 개인 grant를 보존한 기기',
 '같은 CSR/설치키의 정확 action proof, 현재 grant/device/recoveryCapability와 현재 expectedGeneration이 필요합니다. 기존 mTLS leaf가 만료돼도 이 enroll 경로는 서버 TLS1.3과 키 proof·목적 capability로 인증합니다.',
 '원 키를 유지해 새 PKCE/operation 저장 → 이 요청 → CERTIFICATE_RENEW_CLAIM → 공개 leaf 검증·임시 저장 → 새 leaf mTLS로 CREDENTIAL_REBIND → 본인 API 재확인.',
 '현재 grant/slot/epoch/동의/원 절대 만료에 결합한 짧은 기술 갱신 lease만 만듭니다. 이 단계의 CA POST·새 계정·새 동의·QR은0입니다.',
 '같은 operation/본문은 같은 lease입니다. 권한 철회·grant 만료·다른 계정·scope 변화는 갱신 허가가 아니며 새 키/CSR 수동 발급으로 우회하지 않습니다. 인증서와 grant가 모두 만료된 재연결은 이 경로의 지원 범위가 아닙니다.'),
 'CERTIFICATE_RENEW_CLAIM':('승인된 기술 갱신 인증서 받기','갱신 begin을 보존한 같은 설치 기기',
 '갱신 connection의 PKCE/verifier/server nonce와 CERTIFICATE_RENEW_CLAIM 전용 proof, 현재 회원·grant·slot·epoch·동의·기한 lease가 필요합니다. 같은 URL의 최초 CONNECTION_CLAIM과 proof action을 섞지 않습니다.',
 'interval 준수 → 갱신 claim → CERTIFICATE_RECEIPT의 DER/SPKI/현재세대+1/notAfter 검증 → 기존 개인 credential을 덮지 않고 staged cert 보관 → CREDENTIAL_REBIND.',
 'ISSUING commit 뒤 CA 발급을 시도하고 공개 leaf만 stage합니다. 아직 current generation·개인 credential·원 grant 만료를 바꾸지 않습니다. 개인 capability는 issuer bootstrap에 저장하지 않습니다.',
 'UNCERTAIN/ISSUING은 인증된 CA GET으로만 재조정하며 신규 POST를 맹목 반복하지 않습니다. 여러 후보·불명 결과는 잠금을 유지합니다. 철회/계정변경 뒤 늦게 도착한 leaf가 개인 권한을 되살리지 못합니다.'),
 'CREDENTIAL_REBIND':('새 인증서로 같은 개인 연결 전환하기','검증한 staged leaf를 같은 키에 설치한 기기',
 '새 staged leaf의 실제 mTLS와 현재 같은 grant/device/recoveryCapability가 필요합니다. 원 lease의 설치 revision/slot/epoch/동의 snapshot/원 절대 기한이 정확히 현재여야 합니다.',
 '새 leaf 검증·stage → 이 native mTLS 요청 → 같은 grant receipt의 owner/device/scopes/원 만료 검증 → 암호화 원자 교체 → 본인 API 확인 → 연결 유지.',
 '한 transaction에서 정확히 다음 인증서 세대를 current로 올리고 credential epoch를 회전합니다. 기존 leaf와 옛 token은 거절하며 원 grant/device/계정/scope/동의·만료는 유지합니다. 새 계정 동의나 QR·CA POST를 만들지 않습니다.',
 '같은 operation 유실 응답은 정확한 current receipt만 재수령합니다. 철회·scope 축소·slot/epoch 경합은 STALE_EPOCH/terminal로 거절하며 기존 권한을 복원하지 않습니다. staged leaf 수령만으로 연결 성공을 표시하지 않습니다.'),
 'CERTIFICATE_RECOVER':('이미 승인된 인증서 세대 다시 받기','같은 설치 키와 원 갱신 작업을 보존한 기기',
 '이 enroll endpoint만 client cert/Bearer 없이 서버 TLS1.3로 도달합니다. 원 generation 작업·PKCE·nonce·설치키 proof가 필요합니다.',
 'old mTLS가 거절되어도 이 정확 경로에서 공개 receipt 조회 → DER/SPKI/세대/notAfter 검증·설치 → 개인 grant 인가 별도 확인.',
 '서버가 이미 승인한 공개 cert receipt만 반환합니다. 개인 계정·scope·access/refresh·capability·새 CA 발급은0입니다.',
 '다른 키/세대/작업 또는 철회된 설치는 거절합니다. 호스트 전체의 mTLS를 해제하거나 새 인증서를 자동 발급하는 경로가 아닙니다.'),
}
PHONE={
 'PHONE_STATUS':('휴대폰에서 연결 내용 확인하기','차량 공개 URL을 연 본인 웹 사용자',
 'Access 로그인 후 개인 웹 session을 시작합니다. 원 user_code 하나를 유지하며 버전 선택 query나 임의 복귀 주소를 추가하지 않습니다.',
 '기기 이름/코드·본인 계정·요청 데이터/목적/보관·거부/철회·유지 위험을 확인한 뒤만 승인 또는 취소합니다.',
 'GET/QR 스캔/뒤로는 동의가 아니며 발급·개인 token을 만들지 않습니다.',
 '만료/다른 승인자/잘못된 코드면 내용을 숨깁니다. 코드나 복귀 URL을 순회·치환하지 않습니다.'),
 'PHONE_APPROVE':('확인한 기기에 내 계정 연결 허용하기','휴대폰의 실제 본인 사용자',
 '현재 Access/개인 session·같은 Origin·현재 X-WegoH-CSRF 및 직전 GET의 동의 버전/hash가 모두 필요합니다.',
 '코드/기기와 범위 확인 → 선택 scope/유지 선택 → 명시 연결 버튼 → 차량이 자동 교환하며 폰에서 다시 QR를 요구하지 않습니다.',
 '필수 두 scope가 없으면 DENIED이며 새 CF cert/grant/token은0입니다. 위치/친구/음성/차량 제어는 포함하지 않습니다.',
 '오래되거나 바뀐 설명409에는 현재 내용부터 재조회합니다. 페이지 닫힘·재시도·admin 역할에서 동의를 추정하지 않습니다.'),
 'PHONE_DENY':('연결 거절 또는 해제하기','현재 요청을 확인한 본인 웹 사용자',
 '승인과 같은 Access/session·Origin/CSRF 검증이 필요합니다. Back과 명시 거절을 구분합니다.',
 '현재 요청 확인 → 취소 버튼 → 이 DELETE → 기기가 terminal 상태를 확인합니다.',
 '승인 전 거절과 본인이 이미 APPROVED한 요청의 철회를 같은 DELETE로 처리합니다. 해당 개인 grant를 terminal로 닫고 목적별 개인 자료를 제거하며 공개 인증서·다른 사람/기기의 여행 기록은 보존합니다.',
 '서버는 발급 불명 결과의 공개 CA 증거만 GET으로 확인하며, 기기는 기존 키로 새 목적의 명시 동의를 받습니다. 취소된 동의의 PKCE·개인 token을 복원하지 않습니다. 연결 완료 기기는 본인 기기 관리 또는 GRANT_REVOKE/SESSION_REVOKE로 해제합니다.'),
}


def _ref(name):
    return {'$ref':'#/components/schemas/'+name}


def _closed(properties, required=None, description=None):
    value={'type':'object','properties':properties,'required':list(properties) if required is None else required,'additionalProperties':False}
    if description:value['description']=description
    return value


SCOPE_DISCLOSURE_FIELDS = {
 'scope':'이 고지가 설명하는 요청 scope의 정확한 ID입니다. 기능 목적 ID나 별도 권한 부여가 아닙니다.',
 'required':'이 scope가 개인 연결의 필수 조건인지 나타내는 고정 값입니다. 필수 항목 거절은 연결 전체 거절이며 선택 scope를 자동 승인하지 않습니다.',
 'dataCategories':'이 scope로 처리할 데이터 범주의 고정 안내 목록입니다. 실제 개인 데이터나 조회 결과를 포함하지 않습니다.',
 'purpose':'이 scope의 데이터 이용 목적을 사용자에게 알리는 현재 고정 문구입니다. 문구만으로 접근 권한을 생성하지 않습니다.',
 'retentionPolicyId':'이 고지가 참조하는 보관 정책의 식별자입니다. 원 기록의 삭제 명령이나 권한이 아닙니다.',
 'retention':'이 scope의 조회 캐시와 원본 데이터 보관을 구분해 알리는 현재 고정 안내입니다.',
 'refusalEffect':'이 scope의 승인을 거절했을 때 개인 연결에 미치는 영향을 알리는 고정 안내입니다.',
 'withdrawalEffect':'이 scope를 철회했을 때 연결과 해당 조회 캐시에 미치는 영향을 알리는 고정 안내입니다.'}


def _kind(kind, wire):
    if kind.startswith('ServerNonce,'):
        kind='ServerNonce'
    if kind in ('certificateReceipt','credentialReceipt'):
        return _ref('NativeAccess'+kind[0].upper()+kind[1:])
    if kind == 'DisclosureSnapshot':
        registry=wire['disclosureRegistry']
        # The full fixed snapshot is request-specific; describe its actual registry
        # members rather than accepting arbitrary free-form policy content.
        fixed_policies=[]
        for policy in registry['scopePolicies']:
            properties={name:{'const':value,'type':('boolean' if type(value) is bool else 'array' if type(value) is list else 'string'),'description':SCOPE_DISCLOSURE_FIELDS[name]}
                        for name,value in policy.items()}
            fixed=_closed(properties)
            fixed['const']=copy.deepcopy(policy)
            fixed['title']=policy['scope']
            fixed_policies.append(fixed)
        item={'oneOf':fixed_policies}
        return _closed({'disclosureVersion':{'const':registry['version'],'type':'integer','description':'요청 scope의 고지 registry 개정 번호입니다. 공개 인증 계약 버전과 구분하며 직전 서버 snapshot과 일치해야 합니다.'},
          'disclosureSha256':{'type':'string','pattern':'^[a-f0-9]{64}$','description':'요청 scope에 해당하는 고지, 개정 번호, 연결 기한과 로그인 유지 안내를 담은 snapshot의 canonical JSON SHA256입니다. hash 필드 자신을 제외해 계산하며 직전 서버 snapshot을 그대로 대조합니다.'},
          'scopeDisclosures':{'type':'array','minItems':2,'maxItems':len(registry['scopePolicies']),'uniqueItems':True,'items':item,'description':'Exact registry members only; the runtime additionally verifies exact requested-scope subset, order and canonical snapshot hash.'},
          'bindingMaxSeconds':{'const':wire['lifetimes']['bindingSeconds'],'type':'integer','description':'개인 연결이 유지될 수 있는 최대 초의 고정 안내입니다. 조회나 승인 재시도로 현재 grant의 원 기한을 연장하지 않습니다.'},
          'keepSignedInDisclosure':{'const':registry['keepSignedInDisclosure'],'type':'string','description':'폰에서 로그인 유지 선택 전에 읽을 현재 고정 안내입니다. 실제 keepSignedIn 선택과 별개이며 기본 동의로 간주하지 않습니다.'}})
    if kind=='Version':return {'type':'integer','const':1}
    if kind=='Id':return {'type':'string','pattern':'^[a-f0-9]{32}$'}
    if kind in ('InstallationKeyId','CertificateSha256'):return {'type':'string','pattern':'^[a-f0-9]{64}$'}
    if kind=='AccountId':return {'type':'string','pattern':'^team-[a-f0-9]{40}$'}
    if kind in ('Secret','ServerNonce','S25643'):return {'type':'string','minLength':43,'maxLength':43,'pattern':'^[A-Za-z0-9_-]{43}$','description':'Canonical base64url; decoder also rejects noncanonical pad-bit aliases.'}
    if kind=='RSA2048Signature342':return {'type':'string','minLength':342,'maxLength':342,'pattern':'^[A-Za-z0-9_-]{342}$'}
    if kind=='PkceVerifier':return {'type':'string','minLength':43,'maxLength':128,'pattern':'^[A-Za-z0-9._~-]{43,128}$'}
    if kind=='Timestamp':return {'type':'integer','minimum':0,'maximum':253402300799}
    if kind in ('Counter','Epoch'):return {'type':'integer','minimum':1 if kind=='Epoch' else 0,'maximum':9007199254740991}
    if kind in ('Generation','ConsentVersion'):return {'type':'integer','minimum':1,'maximum':2147483647}
    if kind=='PollInterval':return {'type':'integer','minimum':5,'maximum':60}
    if kind=='RetryAfter':return {'type':'integer','minimum':5,'maximum':86400}
    if kind=='UserCode':return {'type':'string','pattern':'^[A-HJ-NP-Z2-9]{8}$'}
    if kind=='DeviceName':return {'type':'string','minLength':1,'maxLength':80,'description':'Also <=240 UTF-8 bytes, no C0/C1/surrogate or surrounding whitespace.'}
    if kind in ('ScopeSet','ApprovedScopeSet','RequiredScopes'):
        value={'type':'array','uniqueItems':True,'maxItems':4,'items':{'type':'string','enum':[p['scope'] for p in wire['disclosureRegistry']['scopePolicies']]}}
        if kind=='RequiredScopes':value['const']=sorted(p['scope'] for p in wire['disclosureRegistry']['scopePolicies'] if p['required'])
        elif kind=='ScopeSet':
            value['minItems']=2
            value['allOf']=[{'contains':{'const':p['scope']}} for p in wire['disclosureRegistry']['scopePolicies'] if p['required']]
        else:value['minItems']=0
        value['description']='Lexically sorted; only requested scopes may be approved. Required scopes missing from approval produce DENIED.'
        return value
    if kind=='SingleValidatedPem':return {'type':'string','maxLength':8192,'description':'One actual signed ASCII CSR or client leaf PEM, validated cryptographically; SDK/CLI creates it, not a copied example key.'}
    if kind in ('KeepSignedIn','literal false'):return {'type':'boolean',**({'const':False} if kind=='literal false' else {'default':False})}
    if kind in ('literal Bearer','CredentialKind'):return {'type':'string','const':'Bearer'}
    if kind.startswith('integer literal'):return {'type':'integer','const':int(kind.removeprefix('integer literal'))}
    if kind=='DisclosureVersion':return {'type':'integer','const':wire['disclosureRegistry']['version']}
    if kind=='State':return {'type':'string','enum':wire['states']}
    if kind=='Disposition':return {'type':'string','enum':wire['dispositions']}
    if kind=='AuthorizationOperation':return {'type':'string','enum':[item['action'] for item in wire['operations']]}
    if kind=='FixedPhoneUri':return {'type':'string','format':'uri','pattern':r'^https://wegoh\.devforest\.io/enroll\.html\?user_code=[A-HJ-NP-Z2-9]{8}$'}
    if kind=='APPROVED or DENIED':return {'type':'string','enum':['APPROVED','DENIED']}
    if kind=='literal DENIED':return {'type':'string','const':'DENIED'}
    raise RuntimeError('Undocumented native wire type')


def _field(name,kind,wire,*,request=False):
    value=copy.deepcopy(_kind(kind,wire))
    value['description']=FIELD[name]+(' '+value['description'] if value.get('description') else '')
    if request and name in SECRET_FIELDS:value['writeOnly']=True
    if not request and name in ('accessToken','refreshToken','recoveryCapability','revokeCapability'):
        value['description']+=' 아래 값은 실제 서버 발급 자격이며 Try it out 예제의 비활성 표식과 다릅니다.'
    return value


def _request(operation,wire):
    types=wire['requestFieldTypes'];required=operation['requestRequired'];optional=operation['requestOptional']
    properties={name:_field(name,types[name],wire,request=True) for name in required+optional}
    fixed=operation.get('fixedRequestValues',{})
    for name,value in fixed.items():properties[name]={'type':'string','const':value,'description':FIELD[name]}
    return _closed(properties,required,'추가/중복 JSON key, bool을 정수로 처리하는 coercion, 잘못된 crypto/proof는 실제 decoder가 거절합니다. JSON Schema integer 자체의 1.0 허용과 runtime 정확 타입은 구분합니다.')


def _response_variant(operation,variant,wire):
    properties={name:_field(name,kind,wire) for name,kind in {**wire['responseCommonFields'],**variant['required'],**variant['optional']}.items()}
    properties['operation']['const']=operation['action']
    properties['state']['const']=variant['state'];properties['disposition']['const']=variant['disposition']
    required=list(wire['responseCommonFields'])+list(variant['required'])
    return _closed(properties,required)


def _description(action,metadata):
    title,actor,prerequisite,sequence,effects,retry=metadata
    return ('**호출 주체** '+actor+'\n\n**호출 전** '+prerequisite+'\n\n**순서** '+sequence+
            '\n\n**부작용** '+effects+'\n\n**실패·재시도** '+retry+
            '\n\n**브라우저 실행** native/public-enroll 호출은 SDK 또는 `python3 scripts/native_connect.py connect`를 사용합니다. '
            'Swagger Authorize는 기기 mTLS 개인키를 주입하지 못하며, 개인키/CF API 토큰을 입력하면 안 됩니다. '
            '폰 웹 변경은 현재 Access·개인 session·같은 Origin·CSRF가 있어야 합니다. '
            '이 사용자 정의 연결을 OAuth2/JWT 표준 전체 구현으로 표시하지 않습니다.')


def _path(path):
    return path.replace('{connectionId}','{connection_id}').replace('{deviceId}','{device_id}').replace('{userCode}','{user_code}')


def apply_native_access_documentation(schema,auth):
    """Return a deep-copied schema overlay. Missing routes stay contract-only, disabled."""
    schema=copy.deepcopy(schema);wire=wire_contract()
    feature_enabled=bool(getattr(getattr(auth,'native_authorization',None),'enabled',False))
    schemas=schema.setdefault('components',{}).setdefault('schemas',{})
    security=schema['components'].setdefault('securitySchemes',{})
    security.setdefault('NativeMTLS',{'type':'mutualTLS','description':'Actual verified current installation certificate over TLS1.3; never spoof Cloudflare certificate headers.'})
    security.setdefault('DeviceBearer',{'type':'http','scheme':'bearer','description':'Opaque personal credential, not JWT; current mTLS/slot/epoch/scope/ACL all required.'})
    security['DeviceBearer'].pop('bearerFormat',None)
    for name,value in {
        'CloudflareAccess':{'type':'apiKey','in':'cookie','name':'CF_Authorization','description':'Browser-managed Access login; not a native API credential.'},
        'TeamSession':{'type':'apiKey','in':'cookie','name':'__Host-wegoh_team','description':'Actual current personal browser session.'},
        'CurrentSessionCSRF':{'type':'apiKey','in':'header','name':'X-WegoH-CSRF','description':'Fresh current-session CSRF plus exact Origin; not an API key to share.'}
    }.items():security.setdefault(name,value)
    for name,definition in wire['receipts'].items():
        schemas['NativeAccess'+name[0].upper()+name[1:]]=_closed({key:_field(key,kind,wire) for key,kind in definition['required'].items()})
    error_schema=_closed({'authorizationVersion':_field('authorizationVersion','Version',wire),'error':{'type':'string','description':'이 단일 인증 계약의 고정 오류 코드입니다. 오류별 다음 행동을 따르며 요청의 비밀이나 다른 계정 상태를 반사하지 않습니다.','enum':sorted({value for values in wire['errors'].values() for value in values})},'retryAfter':_field('retryAfter','RetryAfter',wire)},['authorizationVersion','error'])
    schemas['NativeAccessError']=error_schema
    groups={}
    for operation in wire['operations']:
        key=(operation['method'].lower(),_path(operation['path']))
        groups.setdefault(key,[]).append(operation)
    paths=schema.setdefault('paths',{})
    expected=set(groups)|{(item['method'].lower(),_path(item['path'])) for item in wire['phoneOperations']}
    retired=('/v2/','/v1/enrollments','/v1/devices/pairings','/v1/devices/token')
    if any(path.startswith(retired) for path in paths):
        raise RuntimeError('Retired public authentication route is still registered')
    prefixes=('/v1/connections','/v1/device-authorizations','/v1/device-sessions','/v1/installations/')
    actual={(method,path) for path,operations in paths.items() if path.startswith(prefixes)
            for method in operations if method in ('get','post','put','patch','delete')}
    if actual-expected:
        raise RuntimeError('Native handler lacks authored wire documentation')
    tag={'name':TAG,'description':'단일 공개 v1: 한 QR/본인 폰 동의 한 번의 자동 연결. 필수 두 목적과 명시 선택 scope만 허용하며 수동 CSR/PEM·버전 선택은 필요하지 않습니다.'}
    schema['tags']=[tag]+[item for item in schema.get('tags',[]) if item.get('name')!=TAG]
    schema['tags']=[item for item in schema['tags'] if item.get('name')!='15 차량 인증서']
    for (method,path),operations in groups.items():
        present=method in paths.get(path,{})
        target=paths.setdefault(path,{}).setdefault(method,{})
        target['tags']=[TAG];target['summary']=' / '.join(ACTION[item['action']][0] for item in operations)
        target['operationId']='nativeAccess'+''.join(part.title() for part in operations[0]['action'].lower().split('_'))
        target['description']='\n\n---\n\n'.join(_description(item['action'],ACTION[item['action']]) for item in operations)
        target['description']+='\n\n**현재 문서 상태** '+('실제 수집된 handler의 계약입니다. 외부 운영·실차 수용 성공은 별도 증거입니다.' if present else '명세만 존재하며 현재 수집된 handler가 없습니다. 호출 가능·배포 완료를 뜻하지 않습니다.')
        host=operations[0]['host'];target['servers']=[{'url':wire['origins'][host]}]
        target['security']=[] if host=='enroll' else [{'NativeMTLS':[]}]
        target['x-wegoh-surface']='certificate-enrollment' if host=='enroll' else 'native'
        target['x-wegoh-executable']=False
        target['x-wegoh-handler-present']=present
        target['x-wegoh-feature-enabled']=feature_enabled
        target['x-wegoh-live-verified']=False
        target['x-wegoh-contract-actions']=[item['action'] for item in operations]
        target['x-wegoh-wire-sha256']=hashlib.sha256(Path(__file__).with_name('native_access_wire.json').read_bytes()).hexdigest()
        requests=[];responses={}
        for item in operations:
            request_schema=_request(item,wire)
            # Initial and renewal claim have identical closed JSON shapes; the
            # connection kind and signed action distinguish them at runtime.
            # Repeating that shape in oneOf would reject every valid request.
            if request_schema not in requests:requests.append(request_schema)
            for variant in item['responseVariants']:
                responses.setdefault(str(variant['httpStatus']),[]).append(_response_variant(item,variant,wire))
        target['requestBody']={'required':True,'content':{'application/json':{'schema':requests[0] if len(requests)==1 else {'oneOf':requests},'examples':{item['action']:{'summary':'합성 형태 예제: 실제 CSR/proof/token은 SDK/CLI가 생성·수령합니다. 복사해 실행할 자격이 아닙니다.','value':_request_example(item,wire)} for item in operations}}}}
        target['responses']={status:{'description':'정확한 state/disposition을 확인해 다음 행동을 결정합니다. HTTP200 자체가 연결 완료는 아닙니다.','content':{'application/json':{'schema':variants[0] if len(variants)==1 else {'oneOf':variants}}}} for status,variants in responses.items()}
        for status,variants in responses.items():
            target['responses'][status]['content']['application/json']['examples']={item['action']+'_'+variant['state']+'_'+variant['disposition']:{'summary':'합성 상태 예제; 실제 운영 발급 결과가 아닙니다.','value':_response_example(item,variant,wire)} for item in operations for variant in item['responseVariants'] if str(variant['httpStatus'])==status}
        for status,codes in wire['errors'].items():
            target['responses'][status]={'description':_error_description(status,codes),'content':{'application/json':{'schema':_ref('NativeAccessError'),'examples':{code:{'summary':code,'value':{'authorizationVersion':1,'error':code,**({'retryAfter':5} if status=='429' else {})}} for code in codes}}}}
        target['parameters']=_parameters(path)
    for operation in wire['phoneOperations']:
        action=operation['action'];method=operation['method'].lower();path=_path(operation['path'])
        present=method in paths.get(path,{})
        target=paths.setdefault(path,{}).setdefault(method,{})
        target.update(tags=[TAG],summary=PHONE[action][0],description=_description(action,PHONE[action]),
                      operationId='nativeAccess'+''.join(part.title() for part in action.lower().split('_')),
                      servers=[{'url':wire['origins']['web']}])
        target['security']=[{'CloudflareAccess':[],'TeamSession':[],**({'CurrentSessionCSRF':[]} if method!='get' else {})}]
        target['description']+='\n\n**현재 문서 상태** '+('실제 수집된 handler 계약이며 외부 운영 성공은 별도 증거입니다.' if present else '현재 수집된 handler가 없는 명세 경로로 실행할 수 없습니다.')
        target['x-wegoh-surface']='browser';target['x-wegoh-handler-present']=present
        target['x-wegoh-executable']=bool(present and feature_enabled and getattr(auth,'enabled',False));target['x-wegoh-live-verified']=False
        target['x-wegoh-feature-enabled']=feature_enabled
        target['parameters']=_parameters(path)
        if 'requestRequired' in operation:
            target['requestBody']={'required':True,'content':{'application/json':{'schema':_closed({name:_field(name,kind,wire,request=True) for name,kind in operation['requestRequired'].items()}),'examples':{'selectedPurposes':{'summary':'직전 GET의 실제 동의 snapshot으로 대체합니다.','value':{name:_sample_value(name,kind,wire) for name,kind in operation['requestRequired'].items()}}}}}}
        target['responses']={'200':{'description':'현재 폰 요청의 정본 상태. APPROVED도 차량의 실제 credential/API 확인 완료와 다릅니다.','content':{'application/json':{'schema':_closed({name:_field(name,kind,wire) for name,kind in operation['responseRequired'].items()}),'examples':{'synthetic':{'summary':'합성 정본 예제, 실제 사용자/승인 결과가 아닙니다.','value':{name:('DENIED' if action=='PHONE_DENY' else 'APPROVED' if action=='PHONE_APPROVE' else 'PENDING') if name=='state' else _sample_value(name,kind,wire) for name,kind in operation['responseRequired'].items()}}}}}}}
        for status,codes in PHONE_ERRORS[action].items():
            if not set(codes)<=set(wire['errors'][status]):raise RuntimeError('Phone error outside the public vocabulary: '+action+' '+status)
            examples={code:{'summary':'고정 공개 v1 오류 코드의 형태 예제','value':{'authorizationVersion':1,'error':code}} for code in codes}
            text=PHONE_409[action] if status=='409' else PHONE_TEXT[status]
            target['responses'][status]={'description':', '.join(codes)+'. '+text,'content':{'application/json':{'schema':_ref('NativeAccessError'),'examples':examples}}}
    _annotate_native_reads(schema,auth)
    _annotate_browser_management(schema,wire)
    schema['x-wegoh-native-events']={
        'url':wire['origins']['native'].replace('https://','wss://',1)+'/v1/events',
        'security':[{'NativeMTLS':[],'DeviceBearer':[]}],
        'transport':'TLS1.3 + actual current mTLS certificate + Authorization Bearer header. No Origin, query credentials or Sec-WebSocket-Protocol credentials; clients never manufacture Cloudflare certificate headers.',
        'authorization':'Before101 require current member, same installation/certificate generation, live grant/slot/epoch and both mandatory scopes. Zero/single-required-scope grants are HTTP403 before upgrade.',
        'scopeProjection':{'mandatoryOnly':['devices'],'courses:read':['courses','devices'],'playlists:read':['devices','playlists'],'bothOptional':['courses','devices','playlists']},
        'frameFields':{'snapshot':['type','epoch','seq','resources'],'invalidate':['type','epoch','seq','resources'],'heartbeat':['type','epoch','seq']},
        'fields':{'epoch':'New16lowerhex per connection.','seq':'Starts0; increments only for an allowed invalidation, never for hidden resources.','resources':'Sorted unique permitted names only. No identifiers, titles, counts, coordinates, tokens or global revisions.'},
        'example':{'type':'snapshot','epoch':'0123456789abcdef','seq':0,'resources':['devices']},
        'lifecycle':'Current device/grant only. Revalidate every send loop; account/scope/slot/credential changes close1008 and require a new authorized snapshot. This invalidation feed accepts no commands/client payloads; voice and vehicle-control consent are separate.',
        'acceptance':'Wire/actual local HTTP-WebSocket tests are separate from live Cloudflare WSS and vehicle acceptance. No deployment success is implied by documentation.'}
    schema['x-wegoh-native-documentation-coverage']={'wireActions':len(wire['operations']),'phoneActions':len(wire['phoneOperations']),'collectedHandlerOperations':len(actual),'contractOnlyOperations':len(expected-actual),'semanticApproval':'Independent handler/consumer review required; decoder/schema tests do not approve meaning or deployment.'}
    intro='## 차량 연결 기본: 단일 v1\n\n`python3 scripts/native_connect.py doctor` → `python3 scripts/native_connect.py connect` → 본인 폰에서 기기/공개 코드/범위를 확인하고 한 번 승인합니다. 키·CSR·인증서·개인 grant 교환은 자동이며 실제 본인 API 확인 뒤에만 연결 완료입니다. 코스/음악은 `connect --courses --playlists`로 명시 요청합니다.\n\n' \
          'QR과 Studio 수동 코드는 같은 `/enroll.html?user_code=CODE`로 갑니다. 먼저 **'+TAG+'**를 보세요. 공개 enroll의 purpose proof, 폰의 Access·session·CSRF, Native의 mTLS·opaque Bearer 경계는 서로 다릅니다. Swagger는 개인키·CF API 토큰을 받지 않으며 Native/public-enroll 호출은 검증된 CLI/SDK로 수행합니다. 공개 연결은 단일 v1 계약을 사용합니다. 실제 배포·실차·출시 승인은 별도입니다.\n\n## 웹·업무 API\n\n'
    schema.setdefault('info',{})['description']=intro+schema.get('info',{}).get('description','')
    return schema


def _parameters(path):
    result=[]
    for name in ('connection_id','device_id','user_code'):
        if '{'+name+'}' in path:
            kind='UserCode' if name=='user_code' else 'Id'
            result.append({'name':name,'in':'path','required':True,'description':FIELD[{'connection_id':'connectionId','device_id':'deviceId','user_code':'userCode'}[name]],'schema':_kind(kind,wire_contract())})
    return result


# Browser phone routes (native_authorization.browser_router): detail() reads no body and only
# looks the code up; approve/deny read the body, and an HTTPException from the browser session is
# mapped by http_error_response (401 AUTHENTICATION_REQUIRED, 403 INVALID_PROOF). None is rate limited.
_PHONE_COMMON={'401':['AUTHENTICATION_REQUIRED'],'403':['INVALID_PROOF'],'404':['OPERATION_NOT_FOUND','ROUTE_NOT_FOUND'],
    '410':['AUTHORIZATION_EXPIRED'],'503':['SERVICE_UNAVAILABLE']}
_PHONE_BODY={'400':['INVALID_REQUEST'],'408':['REQUEST_TIMEOUT'],'413':['REQUEST_TOO_LARGE']}
PHONE_ERRORS={'PHONE_STATUS':_PHONE_COMMON,
    'PHONE_APPROVE':{**_PHONE_COMMON,**_PHONE_BODY,'409':['OPERATION_CONFLICT','CONSENT_CHANGED']},
    'PHONE_DENY':{**_PHONE_COMMON,**_PHONE_BODY,'409':['OPERATION_CONFLICT']}}
PHONE_TEXT={'400':'Content-Type이 application/json이 아니거나 동의 본문 형식이 틀렸습니다. 같은 본문을 반복하지 않습니다.',
    '401':'브라우저 개인 세션이 없거나 만료됐거나 계정을 쓸 수 없습니다. Access 로그인과 개인 세션을 다시 확인합니다.',
    '403':'팀 명단 계정이 아니거나 변경 요청의 Origin·X-WegoH-CSRF가 맞지 않습니다.',
    '404':'없는 코드·다른 계정이 처리한 코드·철회된 연결이거나 공개 웹 호스트가 아닙니다. 코드를 순회하지 않습니다.',
    '408':'본문을 5초 안에 받지 못했습니다. 코드 상태를 다시 조회합니다.',
    '410':'코드 기한이 지났습니다. 차량에서 새 코드를 받습니다.',
    '413':'본문이 12288바이트를 넘었습니다.',
    '503':'저장소를 확인할 수 없습니다. 허용·거절 성공으로 표시하지 말고 다시 조회합니다.'}
PHONE_409={'PHONE_APPROVE':'OPERATION_CONFLICT는 이미 처리된 코드이거나 연결 차량 한도이고, CONSENT_CHANGED는 동의 문구가 바뀐 경우입니다. 코드 상태를 다시 조회해 사용자가 다시 확인합니다.',
    'PHONE_DENY':'처리 중 다른 결정이 먼저 저장됐습니다. 코드 상태를 다시 조회합니다.'}


def _error_description(status,codes):
    action={'400':'입력/정확 JSON 타입·proof 형식을 고칩니다. 같은 잘못된 본문을 반복하지 않습니다.',
            '401':'현재 자격이 없거나 만료됐습니다. 같은 grant의 제한 복구 또는 본인 폰 명시 재연결을 따르며 키를 재생성하지 않습니다.',
            '403':'scope/동의/현재 계정·cert binding을 거절했습니다. 폰 변경은 같은 Origin·현재 session CSRF도 확인합니다. 역할·CSR 재발급·헤더 위조로 우회하지 않습니다.',
            '404':'정확 호스트/경로 또는 본인 작업을 찾지 못했습니다. ID/코드나 다른 사용자 상태를 순회하지 않습니다.',
            '408':'본문 수신 시간 초과. 저장한 같은 작업의 현재 상태부터 확인합니다.',
            '409':'동일 operation의 다른 본문·동의/slot/epoch 또는 설치 이행 상태 충돌입니다. 원 상태 확인 전 새 발급하지 않습니다.',
            '410':'코드/승인 교환/grant 기한을 구분합니다. 명시 허가된 미발급만 같은 키 재시작, 유효 cert의 개인 연결은 새 폰 동의입니다.',
            '413':'본문 상한을 넘었습니다. crypto 원문을 잘라 전송하지 않습니다.',
            '429':'retryAfter/Retry-After 최소 간격을 지켜 같은 operation으로 조회합니다.',
            '503':'저장소/issuer/서비스를 확인할 수 없습니다. 발급·연결·철회 성공으로 표시하거나 CA POST를 반복하지 않습니다.'}.get(status,'실제 서버의 고정 오류 코드에 맞춰 정본 상태를 확인합니다.')
    return ', '.join(codes)+'. '+action


def _annotate_browser_management(schema,wire):
    """One current owner-only DTO; no retired permission-body alternative."""
    models=schema['components']['schemas'];paths=schema['paths']
    iso={'type':'string','format':'date-time','description':'Actual UTC ISO8601; not a fabricated last-used time.'}
    vehicle_name=dict(_field('name','DeviceName',wire),description='소유자가 정한 차량 이름. 정하지 않았으면 "{계정 이름}의 차"이며 연결 요청 이름과 다릅니다.')
    models['NativeAccessBrowserDevice']=_closed({'id':_field('deviceId','Id',wire),'name':vehicle_name,
        'createdAt':iso,'lastUsedAt':{'type':'null','description':'Current contract does not collect last-used timestamps.'},
        'expiresAt':iso,'authorizationVersion':_field('authorizationVersion','Version',wire)})
    models['NativeAccessBrowserPermissions']=_closed({'authorizationVersion':_field('authorizationVersion','Version',wire),
        'deviceId':_field('deviceId','Id',wire),'name':vehicle_name,
        'revision':_field('consentVersion','ConsentVersion',wire),'consentVersion':_field('consentVersion','ConsentVersion',wire),
        'scopes':_field('scopes','ScopeSet',wire),'keepSignedIn':_field('keepSignedIn','KeepSignedIn',wire),
        'expiresAt':iso,'grantExpiresAt':_field('grantExpiresAt','Timestamp',wire)})
    models['NativeAccessBrowserRevoked']=_closed({'authorizationVersion':_field('authorizationVersion','Version',wire),
        'deviceId':_field('deviceId','Id',wire),'status':{'type':'string','const':'revoked','description':'현재 본인 기기의 개인 grant를 해제한 결과입니다. 설치 키·공개 인증서·원 여행 기록이나 다른 계정을 삭제했다는 뜻이 아닙니다.'}})
    subset={'type':'array','minItems':0,'maxItems':4,'uniqueItems':True,
        'items':{'type':'string','enum':sorted(item['scope'] for item in wire['disclosureRegistry']['scopePolicies'])},
        'description':'Exact sorted subset of currently approved scopes. No expansion. Missing either mandatory scope terminates the personal grant.'}
    models['NativeAccessScopeReduction']=_closed({'revision':_field('consentVersion','ConsentVersion',wire),'scopes':subset})
    read_security=[{'CloudflareAccess':[],'TeamSession':[]}]
    mutation_security=[{'CloudflareAccess':[],'TeamSession':[],'CurrentSessionCSRF':[]}]
    list_target=paths.get('/v1/devices',{}).get('get')
    if list_target:
        list_target['security']=read_security
        media=list_target.setdefault('responses',{}).setdefault('200',{}).setdefault('content',{}).setdefault('application/json',{})
        media['schema']=_closed({'devices':{'type':'array','maxItems':100,'items':_ref('NativeAccessBrowserDevice'),'description':'현재 본인 계정의 살아 있는 개인 연결을 생성 최신순으로 최대100개 반환합니다. 다른 계정·비밀 자격·실제 수집하지 않는 마지막 사용 시각을 만들지 않습니다.'}})
        media.pop('examples',None)
        list_target['description']=list_target.get('description','')+'\n\n현재 계정의 살아 있는 개인 슬롯만 생성 최신순 최대100개로 반환합니다. authorizationVersion=1이며 lastUsedAt은 수집하지 않아 null입니다. 키·grantId·인증서·token·다른 계정은 노출하지 않습니다. 키를 잃어도 폰에서 본인 기기를 해제할 수 있습니다.'
    target=paths.get('/v1/devices/{device_id}',{}).get('delete')
    if target:
        target['security']=mutation_security
        target['description']=target.get('description','')+'\n\n현재 폰의 Access·개인 session·Origin/CSRF로 정확한 본인 device만 해제합니다. 개인 grant/token·목적 자료를 제거하고 WSS를 종료하며 설치 key/공개 cert·다른 계정·여행기록은 보존합니다. 다른 owner/이미 철회한 기기는404이며 응답 유실에는 본인 목록을 다시 확인합니다. 설치 전체 차단 권한이 아닙니다.'
    for method in ('get','put'):
        target=paths.get('/v1/devices/{device}/permissions',{}).get(method)
        if not target:continue
        target['security']=read_security if method=='get' else mutation_security
        target['description']=target.get('description','')+'\n\n단일 계약의 현재 scopes·동의 revision·keepSignedIn·원 절대 만료만 사용합니다. PUT은 정확한 {revision,scopes}이며 현재 정본의 정렬 부분집합만 철회할 수 있습니다. 범위 확대403·오래된 revision409에는 정본을 다시 읽습니다. 선택 scope 축소는 즉시 이전 token/WSS를 차단하고 같은 grant의 SESSION_RECOVER로 새 QR 없이 축소 정본만 받습니다. 필수 scope 제거는 전체 연결 종료이며 원 여행기록/다른 설치와 원 grant 만료는 보존합니다. 중복 JSON key·잘못된 본문은400입니다.'
        media=target.setdefault('responses',{}).setdefault('200',{}).setdefault('content',{}).setdefault('application/json',{})
        refs=[_ref('NativeAccessBrowserPermissions')]+([_ref('NativeAccessBrowserRevoked')] if method=='put' else [])
        media['schema']=refs[0] if len(refs)==1 else {'oneOf':refs}
        media.pop('examples',None)
        if method=='put':
            example={'revision':1,'scopes':sorted(item['scope'] for item in wire['disclosureRegistry']['scopePolicies'] if item['required'])}
            target['requestBody']={'required':True,'content':{'application/json':{'schema':_ref('NativeAccessScopeReduction'),
                'examples':{'withdrawOptional':{'summary':'현재 GET의 revision으로 선택 범위만 철회합니다. 실제 본인 동의 정본을 먼저 확인합니다.','value':example}}}}}
        target['x-wegoh-management']='owner-only/downward-only; browser session/Origin/CSRF for mutation; no installation ban or new grant/scope authority'


def _annotate_native_reads(schema,auth):
    native_origin=getattr(auth,'native_origin','')
    from native_access_policy import ROUTES
    for rule in ROUTES:
        path=rule.template.replace('{version}','{version}');method=rule.method.lower()
        operation=schema.get('paths',{}).get(path,{}).get(method)
        if not operation:continue
        operation['x-wegoh-native-configured']=bool(native_origin)
        if not native_origin:continue
        native={'NativeMTLS':[],'DeviceBearer':[]}
        if native not in operation.setdefault('security',[]):operation['security'].append(native)
        operation['x-wegoh-required-scopes']=sorted({'account:read','device:self:manage',rule.scope})
        operation['description']=operation.get('description','')+'\n\n**Native v1** TLS1.3 + 현재 설치 mTLS + opaque 개인 Bearer를 모두 요구합니다. 본인 ACL과 명시 scope의 교집합이며 admin도 이를 우회하지 못합니다. 필수 scope 또는 현재 generation/slot/epoch가 없으면 거절합니다. '+FIELD['scopes']
        operation.setdefault('servers',[])
        if not any(server.get('url')==native_origin for server in operation['servers']):
            operation['servers'].append({'url':native_origin})


# Public, nonproduction fixture. No private key was written or retained.
PUBLIC_EXAMPLE = {'csr': '-----BEGIN CERTIFICATE REQUEST-----\nMIICdjCCAV4CAQAwMTEvMC0GA1UEAwwmV2Vnb0gtMTExMTExMTExMTExMTExMTEx\nMTExMTExMTExMTExMTEwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQCY\n2wO/W/xVMZ5dHkQBcWmln4EWU0l16/YEhgm3vKIBOW77pIxq6DTZ2ZKEAw3OWxKT\nazm5+5Zg0n3KS6FzgHOUdmMr//1kd3oLDtnGD4GRwRdXT0mYJyMnOFsaQQd5uMEM\nlsWkHNSSRcqFzHNF8P/staTn8aQgK0FwM6iQ0k6kqAJzCQxQTa3Aw/1/lgGLIHi2\nEU+4H8qPG1TY3vQRmjVkvGZrBs464LAlQtPX/+j+ICE0FR0Std4E7ZkS2vz5I8cI\nBoMtBlWN134LgBXMbjrnSj7mu5z+qSQndm0i3qQjLGsvo0Bil923vJ6q3hTG2rwS\n0WvsZD1XTnEbzWkS5+INAgMBAAGgADANBgkqhkiG9w0BAQsFAAOCAQEAS1pmOqM7\nnqBeqjk1wEInyB64zG/lVExK1xGtXNB3nVZf1tydl2hjfYTjK+/FYyxZMiPKC6YO\nNvnMBmALpse6yb9LBwY1X/D81N9piOsEu019fgTA1SYXP2+x1hX2Mu0ZRlB8hRMP\nuDoDfE/apMOPg3o8xeVGc3RwtHJotu4cgirt2YIn6iUiDcqE/GEqjM8mFVmHI9jG\nMC/vkf1qbe2skSAwG3Dwjx2Hg2gXrRsTpXWl3OY/CfC0Ebq34RWB/EEe9vALH5C6\nk26PjRdOrfmJ3EzUkoN8aKOemyjr1NAV8FJz+yqbd8WkzbhvJLtvayzFc8zgU+Kz\n89TozeToKbjTOw==\n-----END CERTIFICATE REQUEST-----\n', 'certificate': '-----BEGIN CERTIFICATE-----\nMIIDDDCCAfSgAwIBAgIBKjANBgkqhkiG9w0BAQsFADArMSkwJwYDVQQDDCBXZWdv\nSCBEb2N1bWVudGF0aW9uIFN5bnRoZXRpYyBDQTAeFw0yNjAxMDEwMDAwMDBaFw0y\nODAxMDEwMDAwMDBaMDExLzAtBgNVBAMMJldlZ29ILTExMTExMTExMTExMTExMTEx\nMTExMTExMTExMTExMTExMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA\nmNsDv1v8VTGeXR5EAXFppZ+BFlNJdev2BIYJt7yiATlu+6SMaug02dmShAMNzlsS\nk2s5ufuWYNJ9ykuhc4BzlHZjK//9ZHd6Cw7Zxg+BkcEXV09JmCcjJzhbGkEHebjB\nDJbFpBzUkkXKhcxzRfD/7LWk5/GkICtBcDOokNJOpKgCcwkMUE2twMP9f5YBiyB4\nthFPuB/KjxtU2N70EZo1ZLxmawbOOuCwJULT1//o/iAhNBUdErXeBO2ZEtr8+SPH\nCAaDLQZVjdd+C4AVzG4650o+5ruc/qkkJ3ZtIt6kIyxrL6NAYpfdt7yeqt4Uxtq8\nEtFr7GQ9V05xG81pEufiDQIDAQABozUwMzAMBgNVHRMBAf8EAjAAMA4GA1UdDwEB\n/wQEAwIHgDATBgNVHSUEDDAKBggrBgEFBQcDAjANBgkqhkiG9w0BAQsFAAOCAQEA\neLVisHpPtsWPF1wIyndujcfwGtXO/PiHZ5aFfWsVuBzjbqZh8x57NvtEYZzvZx3E\nnELwlVc3BqwuHx9+T6PTeAceKKQcjcCKxidU9Rp70LPUVit2DJ1KfrUSIaVDBKEH\nGJ5kjgPB9m1QY5o3Nu76yLYPwYiFm3Sh2L/18ryUirLdCWdY8ZZsH3xSeH2EqioZ\nRIYbK2zCcTc5jkJmrTVwiCIRR1DHkBm+9W6+6Q0IcSnaauFYNpfio6I4H4gdbIz/\n/qIuXsG4/tu75YwoGzFfXC7jPdeDBcT4PzAOWTWzTBQ0zvIINAqIZHJirgS7VgS0\nk0z8NOD+zgwB69YKHca9mg==\n-----END CERTIFICATE-----\n', 'keyId': '75001a5bbdd0a6502bfe487e2ad0a27c6805a5bb3a94ef8cc2ef8d04a4c0b5c6', 'certificateSha256': '856a55de4470a07af0e4cd32b3699d84ab9847307dba1970d8497731a9019fa4', 'certificateExpiresAt': 1830297600}


EXAMPLE_TIME=1793318400
EXAMPLE_VERIFIER='V'*43


def _sample_value(name,kind,wire):
    from enrollment_crypto import challenge
    import base64
    mandatory=sorted(p['scope'] for p in wire['disclosureRegistry']['scopePolicies'] if p['required'])
    snapshot=disclosure_snapshot(mandatory)
    fixed={'authorizationVersion':1,'operationId':'a'*32,'connectionId':'b'*32,'previousConnectionId':'b'*32,
       'grantId':'c'*32,'deviceId':'d'*32,'generationOperationId':'a'*32,
       'name':'내 차량','deviceName':'내 차량','currentAccountDisplayName':'여행자','accountId':'team-'+'e'*40,
       'csrPem':PUBLIC_EXAMPLE['csr'],'certificatePem':PUBLIC_EXAMPLE['certificate'],
       'installationKeyId':PUBLIC_EXAMPLE['keyId'],'certificateSha256':PUBLIC_EXAMPLE['certificateSha256'],
       'originalBeginHash':'f'*64,'codeVerifier':EXAMPLE_VERIFIER,'oldCodeVerifier':EXAMPLE_VERIFIER,'codeChallenge':challenge(EXAMPLE_VERIFIER),
       'userCode':'ABCD2345','verificationUri':wire['phone']['current'].replace('<UserCode>','ABCD2345'),
       'requestedScopes':mandatory,'approvedScopes':mandatory,'requiredScopes':mandatory,'scopes':mandatory,
       'keepSignedIn':False,'keepSignedInDefault':False,'consentVersion':1,
       'disclosureVersion':wire['disclosureRegistry']['version'],'disclosureSha256':snapshot['disclosureSha256'],
       'disclosureSnapshot':snapshot,'proof':base64.urlsafe_b64encode(bytes(256)).rstrip(b'=').decode(),
       'proofNonce':base64.urlsafe_b64encode(b'n'*32).rstrip(b'=').decode(),
       'accessToken':base64.urlsafe_b64encode(b'a'*32).rstrip(b'=').decode(),
       'refreshToken':base64.urlsafe_b64encode(b'r'*32).rstrip(b'=').decode(),
       'recoveryCapability':derive_capability(EXAMPLE_VERIFIER,'c'*32,'recovery'),
       'revokeCapability':derive_revoke_capability(EXAMPLE_VERIFIER,PUBLIC_EXAMPLE['keyId'],'a'*32),
       'revokeCommitment':revoke_commitment(derive_revoke_capability(EXAMPLE_VERIFIER,PUBLIC_EXAMPLE['keyId'],'a'*32)),
       'restartTicket':base64.urlsafe_b64encode(b't'*32).rstrip(b'=').decode(),
       'generation':1,'expectedGeneration':1,'slotRevision':1,'credentialEpoch':1,'tokenType':'Bearer',
       'serverTime':EXAMPLE_TIME,'expiresAt':EXAMPLE_TIME+300,'exchangeExpiresAt':EXAMPLE_TIME+300,
       'grantExpiresAt':EXAMPLE_TIME+wire['lifetimes']['bindingSeconds'],'restartExpiresAt':EXAMPLE_TIME+60,
       'revokedAt':EXAMPLE_TIME,'expiredAt':EXAMPLE_TIME,'interval':5,'retryAfter':5}
    if kind=='certificateReceipt':
        return dict(certificatePem=PUBLIC_EXAMPLE['certificate'],certificateSha256=PUBLIC_EXAMPLE['certificateSha256'],
            installationKeyId=PUBLIC_EXAMPLE['keyId'],generation=1,generationOperationId='a'*32,
            expiresAt=PUBLIC_EXAMPLE['certificateExpiresAt'])
    if kind=='credentialReceipt':
        fields=wire['receipts']['credentialReceipt']['required']
        return {key:EXAMPLE_TIME+wire['lifetimes']['accessSeconds'] if key=='expiresAt' else _sample_value(key,value,wire)
                for key,value in fields.items()}
    if name in fixed:return fixed[name]
    raise RuntimeError('Undocumented example field')


def _request_example(operation,wire):
    result={name:_sample_value(name,wire['requestFieldTypes'][name],wire) for name in operation['requestRequired']}
    result.update(operation.get('fixedRequestValues',{}))
    if 'originalBeginHash' in result:
        # This is explicitly a nonexecutable synthetic template. Real clients hash
        # their encrypted exact original request; they never reuse this fixture.
        result['originalBeginHash']='f'*64
    return result


def _response_example(operation,variant,wire):
    result={name:_sample_value(name,kind,wire) for name,kind in {**wire['responseCommonFields'],**variant['required']}.items()
            if name not in ('operation','state','disposition')}
    result.update(operation=operation['action'],state=variant['state'],disposition=variant['disposition'])
    if operation['action']=='CERTIFICATE_RENEW_CLAIM' and 'certificateReceipt' in result:
        result['certificateReceipt']['generation']=2
    if operation['action']=='CREDENTIAL_REBIND' and 'credentialReceipt' in result:
        result['credentialReceipt']['generation']=2
        result['credentialReceipt']['credentialEpoch']=2
    return result
