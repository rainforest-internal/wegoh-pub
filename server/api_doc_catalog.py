"""Apply reviewed descriptions to real effective routes, fail closed on missing metadata.

The Python catalog is the documentation source of truth. Generated OpenAPI is a
runtime view, never a second hand-edited route inventory. Runtime handlers remain
the authority for permission, validation and effects.
"""
import copy,json
from api_doc_models import SCHEMAS,ref,obj,s,n,b,arr,IDENT,ACCOUNT,REV,TIME,CHECK,nullable
from api_doc_core import OPS as CORE
from api_doc_course_discovery import OPS as COURSE_DISCOVERY
from api_doc_social import OPS as SOCIAL
from api_doc_trip_plan import OPS as TRIP_PLAN
from api_doc_trip_hand_raise import OPS as TRIP_HAND_RAISE
from api_doc_trip_driving_versus import OPS as TRIP_DRIVING_VERSUS
from api_doc_trips import OPS as TRIPS
from api_doc_trip_merge import OPS as TRIP_MERGE, MODELS as TRIP_MERGE_MODELS
from api_doc_voice import OPS as VOICE
from api_doc_room_music import OPS as ROOM_MUSIC
from api_doc_fuel import OPS as FUEL, MODELS as FUEL_MODELS
from api_doc_discovery import OPS as DISCOVERY,MODELS as DISCOVERY_MODELS
from api_doc_discovery_local import OPS as LOCAL_DISCOVERY, MODELS as LOCAL_DISCOVERY_MODELS
DISCOVERY=dict(DISCOVERY)
DISCOVERY.update(LOCAL_DISCOVERY)
DISCOVERY_MODELS=dict(DISCOVERY_MODELS)
DISCOVERY_MODELS.update(LOCAL_DISCOVERY_MODELS)
from native_access_policy import is_retired_authorization_path
from api_doc_native_functional import OPS as FUNCTIONAL,MODELS as FUNCTIONAL_MODELS,TAG as FUNCTIONAL_TAG
from api_doc_native_room_music import OPS as ROOM_MUSIC_ACCESS,MODELS as ROOM_MUSIC_ACCESS_MODELS
from api_doc_native_room_voice import OPS as ROOM_VOICE_ACCESS,MODELS as ROOM_VOICE_ACCESS_MODELS
CORE={key:value for key,value in CORE.items() if not is_retired_authorization_path(key[1])}
from api_doc_shared import ERROR_TEXT,status
from api_doc_recommendations import OPS as RECOMMENDATIONS,MODELS as RECOMMENDATION_MODELS
from api_doc_recommendation_learning import OPS as LEARNING,MODELS as LEARNING_MODELS,OVERRIDES as LEARNING_OVERRIDES
from api_doc_missions import OPS as MISSIONS,MODELS as MISSION_MODELS
from api_doc_device_commands import OPS as DEVICE_COMMANDS,MODELS as DEVICE_COMMAND_MODELS
from api_doc_history_remix import OPS as HISTORY_REMIX,MODELS as HISTORY_REMIX_MODELS
from api_doc_cautions import OPS as CAUTIONS,MODELS as CAUTION_MODELS
from api_doc_vehicle import OPS as VEHICLE,MODELS as VEHICLE_MODELS


from api_doc_manual_deployment import OPS as MANUAL_DEPLOYMENT
from api_doc_client_diagnostics import OPS as CLIENT_DIAGNOSTICS, TAG as CLIENT_DIAGNOSTICS_TAG, TAG_DESCRIPTION as CLIENT_DIAGNOSTICS_TAG_DESCRIPTION

OPERATIONS={**FUEL,**MANUAL_DEPLOYMENT,**CORE,**SOCIAL,**VOICE,**DISCOVERY,**ROOM_MUSIC,**RECOMMENDATIONS,**MISSIONS,**LEARNING,**DEVICE_COMMANDS,**CAUTIONS,**HISTORY_REMIX,**VEHICLE,**FUNCTIONAL,**ROOM_MUSIC_ACCESS,**ROOM_VOICE_ACCESS}
if len(OPERATIONS)!=len(FUEL)+len(MANUAL_DEPLOYMENT)+len(CORE)+len(SOCIAL)+len(VOICE)+len(DISCOVERY)+len(ROOM_MUSIC)+len(RECOMMENDATIONS)+len(MISSIONS)+len(LEARNING)+len(DEVICE_COMMANDS)+len(CAUTIONS)+len(HISTORY_REMIX)+len(VEHICLE)+len(FUNCTIONAL)+len(ROOM_MUSIC_ACCESS)+len(ROOM_VOICE_ACCESS):raise RuntimeError('Duplicate authored operation')

if set(OPERATIONS) & set(TRIPS):raise RuntimeError('Duplicate authored trip operation')
OPERATIONS.update(TRIPS)
if set(OPERATIONS) & set(TRIP_MERGE):raise RuntimeError('Duplicate authored trip merge operation')
OPERATIONS.update(TRIP_MERGE)
if set(OPERATIONS) & set(TRIP_PLAN):raise RuntimeError("Duplicate authored trip plan operation")
OPERATIONS.update(TRIP_PLAN)
if set(OPERATIONS) & set(TRIP_HAND_RAISE):raise RuntimeError("Duplicate authored trip hand-raise operation")
OPERATIONS.update(TRIP_HAND_RAISE)
if set(OPERATIONS) & set(CLIENT_DIAGNOSTICS):raise RuntimeError('Duplicate authored client diagnostics operation')
OPERATIONS.update(CLIENT_DIAGNOSTICS)
OPERATIONS.update(COURSE_DISCOVERY)
OPERATIONS.update(TRIP_DRIVING_VERSUS)
OPERATIONS.update(LEARNING_OVERRIDES)

FIELD_DOCS={
 'handle':'원하는 고유 친구 핸들. 선택적 @ 뒤 ASCII 영문·숫자로 시작하는3~20자이며 밑줄(_)과 점(.)을 허용합니다. 대소문자는 구별하지 않고 소문자로 저장합니다.',
 'expectedHandle':'직전 GET /v1/auth/session의 user.handle. 저장 중 핸들이 바뀌면409이며 현재 세션을 재조회한 뒤 사용자가 다시 저장합니다.',
 'expectedRevision':'직전 차량 프로필 조회 revision. 미등록은0이며409이면 다시 조회하고 명시적으로 저장합니다.',
 'plateNumber':'이용자가 수동 입력한 차량 번호. 한글과 숫자2~16자이며 빈 문자열은 등록 해제입니다.',
 'expectedDisplayName':'직전 본인 계정 조회의 표시 이름. 저장 중 다른 기기에서 이름이 바뀌면409이며 재조회 후 명시 저장합니다.',
 'displayName':'직접 선택한 계정 이름. 최대30 Unicode scalar이며 공백만 또는 양끝 공백과 제어/형식 문자는 거절합니다.',
 'muted':'이 방에서 해당 발화자를 본인 수신에서만 음소거할지 선택합니다. 다른 수신자나 송신 동의는 바꾸지 않습니다.',
 'speakerId':'현재 방의 발화자 team 계정 ID. 신고는 본인이 실제 전달받은 lease의 발화자와 같아야 합니다.',
 'leaseId':'floor-started로 받은32hex 발화 lease ID. 재연결/새 발화에서 재사용하지 않습니다.',
 'id':'요청 객체의 안정 ID. 부모/도메인의 ID 규칙을 따릅니다. 서버 생성 ID는 응답값을 사용합니다.',
 'name':'사용자가 확인할 이름. 공백만인 값·제어문자는 허용하지 않습니다.',
 'title':'이 객체의 사용자 표시 제목. 허용 문자수는 schema 상한을 따릅니다.',
 'url':'HTTPS 링크 metadata. 자격증명·공백·443 이외 포트는 금지되며 서버가 URL을 가져오거나 음악을 재생하지 않습니다.',
 'tracks':'표시 순서의 음악 링크. 빈 배열도 가능하며 최대100개. 각 track id는 선택이고 없으면 서버 발급.',
 'revision':'직전 정본 GET의 현재 revision. 기록 하위 방문/사진 수정은 부모 기록 revision을 사용합니다. 외부 동의가 아직 없을 때만 revision=0입니다.',
 'permissionRevision':'기록 상세의 현재 공유/수집 동의 revision. 데이터 revision과 구분합니다.',
 'targetId':'친구 핸들 검색 결과 또는 현재 관계 목록의 계정 ID. 친구 request ID나 기기 ID가 아닙니다.',
 'accept':'현재 상대가 보낸 incoming 요청을 수락(true) 또는 거절(false).',
 'pack':'사용자가 편집하고 권리를 확인한 불변 코스 JSON. author는 공유 서버에서 현재 계정 표시이름으로 대체됩니다.',
 'rightsConfirmed':'권리와 공개 게시 범위를 사용자가 직접 확인한 뒤 true. 단순 예제 실행만으로 동의를 추정하지 마세요.',
 'reason':'harmful=유해 콘텐츠, privacy=개인정보, rights=권리침해, other=기타. 이 API에는 자유신고문을 받지 않습니다.',
 'checksum':'직전 inspect 또는 다운로드의 정확 SHA-256. 다른 bytes를 같은 승인/신고로 간주하지 않습니다.',
 'decision':'전체 투영본/원문을 실제 검토한 후 approved 또는 rejected. 자동 문구필터 승인 대체가 아닙니다.',
 'reviewer':'검토자 표시이름(필수). 웹 결정에서는 현재 개인계정 이름으로 대체되며 운영 loopback에서만 이 입력값을 기록합니다.',
 'reviewNote':'실제로 검토한 내용과 결정 근거. 비어 있을 수 없고 개인 비밀·키를 넣지 마세요.',
 'codeChallenge':'기기가 비공개 codeVerifier에 SHA-256을 적용해 base64url 패딩 제거한 43자 값. 문서의 반복 A는 형식 예제일 뿐입니다.',
 'codeChallengeMethod':'현재 S256만 지원합니다. plain 방식은 허용하지 않습니다.',
 'deviceCode':'pairing 응답에서 받은 비공개 일회성 grant. 사용자 표시용 userCode와 다르며 URL/로그에 넣지 마세요.',
 'codeVerifier':'신청 때 기기가 만든 43~128자 verifier. 같은 신청의 challenge와 일치해야 합니다.',
 'refreshToken':'현재 기기의 비공개 회전 refresh token. 성공하면 반환한 새 값으로 원자 교체합니다.',
 'courseId':'현재 가용한 게시 코스 ID. 코스를 선택하지 않으면 null이며 courseVersion도 null이어야 합니다.',
 'courseVersion':'선택한 현재 게시 코스 버전. courseId 없으면 null.',
 'expiresInHours':'방 유효기간 시간.1~168. 종료/만료 뒤 멤버 접근은 끝나지만 원기록을 자동 삭제하지 않습니다.',
 'preference':'사용자의 명시 선호 balanced/country-roads/short-distance/short-time. 실제 경로 거리/ETA/국도 SDK ACK를 뜻하지 않습니다.',
 'code':'실제 초대에서 받은 8자 코드. 직접 생성/탐색하지 마세요. 방 신고에서는 가입전 초대 수신자 확인에만 선택 사용합니다.',
 'consents':'방의 본인 동의 여섯 키 전체. status/location 및 현재 availableConsentKeys에 있는 voice만 새로 true로 설정할 수 있습니다. 나머지 목적은 미지원입니다. 기능 off 때 기존 저장 동의를 삭제하지 않습니다.',
 'status':'내 상태 신호를 현재 방 멤버에게 보일지 선택합니다.',
 'location':'명시 선택한 장소의 좌표를 현재 방 멤버에게 보일지 선택합니다. 자동 GPS 수집 동의가 아닙니다.',
 'visits':'방 consents에서는 현재 미지원이므로 false. 기록 grant/export에서는 방문·후기 포함 목적을 별도로 선택합니다.',
 'music':'현재 방 음악 공유는 미지원이므로 false만 허용됩니다.',
 'voice':'방 개인 음성 동의. roomVoice=true 및 availableConsentKeys에 voice가 있을 때만 새로 true를 허용합니다. 기본 false이며 기능 off 때 기존 동의는 보존됩니다.',
 'control':'차량 제어는 미지원이므로 false만 허용됩니다.',
 'accountId':'현재 방 members에서 선택한 팀 계정 ID. 방장 역할 지정 대상입니다.',
 'role':'member/dj/rest/food의 방 역할 metadata. 계정 admin 역할·실차 제어 권한과 다릅니다.',
 'kind':'restroom/smoking/nursing/drowsy/rest/hungry/arrived/join 중 사용자가 선택한 상태 종류.',
 'destination':'사용자가 확인한 장소. 없으면 생략 또는 null. 있으면 현재 status와 location 동의가 모두 필요합니다.',
 'latitude':'위도 도 단위(-90~90). 유한 숫자여야 하며 실차/GPS 증명이 아닙니다.',
 'longitude':'경도 도 단위(-180~180). 유한 숫자여야 합니다.',
 'choice':'agree=찬성, pass=보류. 선택 장소가 현재 보이는 신호에만 저장할 수 있습니다.',
 'startedAt':'기록 시작 시각. ISO8601 시간대 필수, 서버보다5분 넘는 미래는 거절합니다.',
 'endedAt':'기록 종료 시각 또는 미종료 null. 시작보다 빠를 수 없고 시간대가 필요합니다.',
 'place':'사용자가 명시 선택·확인한 장소. 이 보고는 자동 차량 방문 인증이 아닙니다.',
 'visitedAt':'방문 시각. 새 history는 시간대 있는 ISO8601, legacy local visits는 Unix epoch 밀리초입니다.',
 'review':'사용자가 남긴 방문 후기(빈 문자열 허용). 제출 검토 전에는 타인 공유가 제한됩니다.',
 'rating':'선택 평점 정수1~5. 평가하지 않으면 null.',
 'capturedAt':'이 점의 보고 시각. 시간대 필수, 배치 안에서 엄격히 증가해야 합니다.',
 'accuracyMeters':'보고된 정확도 미터0~10000 또는 null. 서버가 GPS 정확도를 인증한 값이 아닙니다.',
 'collectTrace':'이 기록에 새 경로 배치를 입력하도록 명시 허용. false는 새 입력만 중단하며 기존 점을 삭제하지 않습니다.',
 'trace':'기록 grant/export에서 경로 포함을 선택합니다. 자동 위치 수집 동의와 별개입니다.',
 'photos':'별도 사진 목적. visits=true가 필수이며 생략 가능한 내부 grant에서는 기본 false. 방문 공유가 사진 동의를 대신하지 않습니다.',
 'batchId':'클라이언트가 생성한 불변 배치32hex ID. 정확 동일 내용의 응답 유실 재접수에만 같은 ID를 재사용합니다.',
 'streamId':'같은 연속 경로의32hex ID. 다른 참가자/별도 경로와 섞지 마세요.',
 'label':'경로 표시 이름. 전송 source는 browser-reported이며 서버 차량 인증이 아닙니다.',
 'points':'시각 증가 경로 점1~200. 기록 전체100000점. 외부 manifest는별도20000점 제한.',
 'permissions':'본인이 선택한 friends/rooms/history 세 읽기 목적 boolean을 모두 명시합니다.',
 'friends':'이 기기의 친구 목록 읽기 목적. 기본 false이며 pairing과 별도 동의입니다.',
 'rooms':'이 기기의 본인 여행방 읽기 목적. 기본 false.',
 'history':'이 기기의 허용 기록 읽기 목적. 기본 false이며 사진/새쓰기를 포함하지 않습니다.',
 'consent':'이 operation의 명시 목적 동의. 검토 제출과 외부 파일 생성은 서로 다릅니다. false는 가능한 철회 동작, 외부 PUT은 true만 저장 가능합니다.',
 'historyRevision':'외부 동의 대상 기록의 현재 데이터 revision. 수집/공유 permissionRevision과 별개입니다.',
 'expiresAt':'시간대 있는 미래 시각. 외부 동의는 GET serverNow 기준24시간 이내이며 문서의 고정 과거 예제를 그대로 보내지 마세요.',
 'historyIds':'현재 접근·별도 외부 동의를 모두 충족한1~5개 기록 ID. 중복 불가, 선택 순서 보존.',
 'schemaVersion':'코스 JSON 버전. 현재1만 지원합니다.',
 'version':'이 코스 id의 불변 버전. 최초1/이후연속+1이며 이미 게시한 다른 내용을 덮지 못합니다.',
 'author':'코스 작성자 표시이름. 공유 서버는 현재 allowlist 이름으로 대체합니다.',
 'description':'코스 사용자 설명. 상한은 UTF-16 code unit으로도 검증됩니다.',
 'stops':'순서 있는1~3개 장소. stop id는 코스 안에서 유일해야 합니다.',
 'radiusMeters':'도착 반경25~500미터. 이 정의만으로 실제 SDK 위치/차량 도착을 보증하지 않습니다.',
 'action':'장소 도착 행동. 현재 chime 종류와 표시 메시지만 지원합니다.',
 'type':'현재 코스 도착 행동은 chime만 지원합니다.',
 'message':'도착 알림 메시지. 공식 자동차 오디오/포커스 실행 성공은 별도 검증입니다.',
 'poiId':'선택한 장소의 선택적 공급자 ID.',
 'address':'장소 주소 텍스트. 없는 경우 빈 문자열이며 임의 주소를 만들지 마세요.',
 'provider':'실제로 선택한 장소 공급자 식별자.',
}
PARAMS={
 'creator_id':'공개 코스 목록에서 받은 현재 team-40hex 제작자 ID. 비공개 계정 정보는 제공하지 않습니다.',
 'waypointId':'여행 상세의 코스 경유지32hex ID. 해당 여행·코스에 속한 경유지만 지정할 수 있습니다.',
 'placeId':'이 차 places에서 받은 32hex 장소 ID. 다른 차의 ID는 사용할 수 없습니다.',
 'inviteId':'rideInvites 또는 생성 응답의 32hex 태우기 요청 ID.',
 'trip':'현재 여행 목록의 32hex 여행 ID.',
 'signal':'현재 여행 신호 목록의 32hex 신호 ID. 다른 여행의 신호는 사용할 수 없습니다.',
 'proposal':'현재 여행 장소 후보 목록의 32hex 후보 ID.',
 'id':'현재 목록 또는 생성 응답에서 받은32hex ID.',
 'accountId':'여행에서 관리할 계정 ID. 일반 멤버는 본인만 지정할 수 있습니다.',
 'packId':'여행 상세의 courses에서 받은 첨부 코스의 안정 pack ID. 추가한 본인 또는 edit 권한으로 제거할 수 있습니다.',
 'carId':'여행 상세 cars의32hex 차 ID.',
 'requestId':'차 리모컨 요청 생성 또는 상세 remote/remoteRequests에서 받은32hex 대기 요청 ID. 지정된 차주만 응답하고 요청자 본인만 취소할 수 있습니다.',
 'track':'현재 방 공유 playlist에서 받은32hex 곡ID. 삭제·검토·신고는 현재 가입과 music 동의를 다시 검사합니다.',
 'peer':'현재 연결된 친구의 team-40hex 계정 ID. 차주가 이 친구에게 허용할 차량을 선택합니다.',
 'roomId':'선택한 본인 현재 방의32hex ID. 이 query가 선택인 operation은 생략하면 방 보고가null이며 잘못된 방/중복파라미터는거절합니다.',
 'enrollment_id':'등록 시작 응답의32hex enrollmentId. 계정deviceId와 다릅니다.',
 'speaker':'현재 방 members의 본인 이외 발화자 계정 ID. 본인 수신 필터만 바꿉니다.',
 'pack_id':'코스 목록에서 받은 안정 pack ID. 수정버전도 같은 ID를 유지합니다.',
 'follow_id':'내 구독 목록에 있는 구독 식별자.',
 'event_id':'현재 구독 소식의 기존 발행 이벤트 ID.',
 'version':'조회/신고/검토할 정확 코스 버전.1~2147483647이며 목록의 값을 사용합니다.',
 'user_code':'기기에 표시된 유효한8자 사용자 승인 코드. 비공개 deviceCode와 다릅니다.',
 'device_id':'내 기기 목록에서 받은32hex 기기ID. 다른 계정 기기는 접근 불가.',
 'device':'내 기기 목록에서 받은32hex 기기ID. 목적 동의는 해당 소유자만 변경합니다.',
 'purpose':'철회할 단일 읽기 목적 friends/rooms/history.',
 'playlist_id':'본인 목록에서 받은32hex 음악 목록ID.',
 'target':'이 operation의 대상 팀 계정ID. 친구 요청의 상대/기록 수신자/외부 파일 생성자이며 requestId가 아닙니다.',
 'code':'사용자가 실제 받은8자 방 초대 코드. 만료·차단이면404.',
 'room':'본인이 접근 가능한 방의32hex ID. 초대코드와 다릅니다.',
 'identifier':'이 방의 현재 signals 응답에서 받은32hex 신호ID.',
 'item':'현재 기록 목록에서 받은32hex 부모 기록ID.',
 'vid':'이 부모 기록의32hex 방문ID. 수정 revision은 부모 기록의 값을 사용합니다.',
 'visit':'이 부모 기록의32hex 방문ID.',
 'photo':'해당 item/visit에 포함된32hex 사진ID.',
 'kind':'검토 종류 history/room/room-place/photo/room-music. 알려지지 않은 종류는 거절합니다.',
 'key':'검토는 kind별 key(history/room=ID1개,room-place=room:signal,photo=item:visit:photo,room-music=room:selection); Story는 생성응답의manifest32hex ID.',
 'checksum':'개발 upload가 반환한64hex SHA-256. 실제 원본을 검증하지 않은 임의값을 만들지 마세요.',
 'cursor':'직전 응답의 nextCursor를 그대로 전달하는 opaque keyset 커서. 첫 페이지에서는 생략합니다.',
 'content-type':'raw 자산 MIME. 개인 사진과 개발 자산의 허용 MIME은 operation 설명을 따릅니다.',
}

def describe_fields(schema):
    for name,node in schema.get('properties',{}).items():
        if not node.get('description'):
            if name not in FIELD_DOCS:raise RuntimeError('Request field requires authored description: '+name)
            node['description']=FIELD_DOCS[name]
        describe_fields(node)
    for key in ('items',):
        if isinstance(schema.get(key),dict):describe_fields(schema[key])
    for key in ('anyOf','oneOf','allOf'):
        for item in schema.get(key,[]):describe_fields(item)

def sample(schema):
    if schema.get('$ref'):return None
    if 'const'in schema:return schema['const']
    if 'enum'in schema:return schema['enum'][0]
    if 'anyOf'in schema:
        if any(x.get('type')=='null'for x in schema['anyOf']):return None
        return sample(schema['anyOf'][0])
    kind=schema.get('type');kind=next((x for x in kind if x!='null'),None)if isinstance(kind,list)else kind
    if isinstance(schema.get('type'),list)and'null'in schema['type']:return None
    if kind=='object':return{k:sample(v)for k,v in schema.get('properties',{}).items()if k in schema.get('required',[])}
    if kind=='array':return[sample(schema['items'])for _ in range(schema.get('minItems',0))]
    if kind=='boolean':return False
    if kind in('number','integer'):return schema.get('minimum',1)
    if schema.get('format')=='date-time':return'2026-01-01T09:00:00+09:00'
    if schema.get('pattern')=='^team-[a-f0-9]{40}$':return'team-'+'0'*40
    if schema.get('pattern')=='^[a-f0-9]{32}$':return'0'*32
    if schema.get('pattern')=='^[a-f0-9]{64}$':return'0'*64
    if schema.get('pattern','').startswith('^https://'):return'https://example.invalid/selected-track'
    return'사용자가 선택한 값'

def safe(value):
    if value is True:return False
    if isinstance(value,dict):return{k:safe(v)for k,v in value.items()}
    if isinstance(value,list):return[safe(v)for v in value]
    return value

def validate_tag_registry(operations, descriptions):
    missing = sorted({item['tag'] for item in operations.values()
                      if not isinstance(descriptions.get(item['tag']), str) or not descriptions[item['tag']].strip()})
    if missing:
        raise RuntimeError('Authored operation tag description missing: ' + ', '.join(missing))

# DELETE handlers that never read a request body (checked against each handler); GET handlers never read one.
BODYLESS={('delete',path)for path in(
 '/v1/devices/{device}/command-access','/v1/devices/{device}/reporting-permissions/{purpose}',
 '/v1/social/rooms/{room}/device-command-access','/v1/social/rooms/{room}/device-command-grants/{device}/{peer}',
 '/v1/social/rooms/{room}/device-requests/{identifier}','/v1/social/rooms/{room}/device-reporting',
 '/v1/social/rooms/{room}/report-receiving','/v1/social/rooms/{room}/missions/{mission}',
 '/v1/social/rooms/{room}/missions/{mission}/participation','/v1/social/trips/{room}/device-command-access',
 '/v1/social/trips/{room}/device-command-grants/{device}/{peer}','/v1/social/trips/{room}/device-requests/{identifier}',
 '/v1/social/trips/{room}/missions/{mission}','/v1/social/trips/{room}/missions/{mission}/participation',
 '/v1/social/trips/{trip}/device-reporting','/v1/social/trips/{trip}/report-receiving')}


def apply_documentation(schema,body_contracts):
    validate_tag_registry(OPERATIONS, TAG_DESCRIPTIONS)
    models={name:copy.deepcopy(value) for name,value in SCHEMAS.items() if name not in ('PairingCreated','PairingInfo','Tokens')}
    models.update(FUEL_MODELS)
    models.update(DISCOVERY_MODELS)
    models.update(RECOMMENDATION_MODELS)
    models.update(LEARNING_MODELS)
    models.update(MISSION_MODELS)
    models.update(DEVICE_COMMAND_MODELS)
    models.update(HISTORY_REMIX_MODELS)
    models.update(CAUTION_MODELS)

    models.update(VEHICLE_MODELS)
    models.update(FUNCTIONAL_MODELS)
    models.update(ROOM_MUSIC_ACCESS_MODELS)
    models.update(ROOM_VOICE_ACCESS_MODELS)
    models.update(TRIP_MERGE_MODELS)
    models['DrivePack']=copy.deepcopy(body_contracts[('post','/v1/packs')]['properties']['pack']);describe_fields(models['DrivePack'])
    models['PublishedCourse']=obj({'id':s('코스 안정 ID.'),'version':n('게시 버전.'),'checksum':CHECK,'state':s('새 버전은 approved로 즉시 공개. 기존 버전은 신고·운영 상태에 따라 quarantined/rejected 가능.'),'source':ref('RemixPublicationSource')},'불변 코스 게시·사후 공개 상태 metadata. 재창작이면 공개 최소출처가별도로있고개인기록ID는없습니다.',required=['id','version','checksum','state'])
    models['CourseSummary']=obj({'id':s('코스 ID.'),'version':n('현재 게시 버전.'),'title':s('코스 제목.'),'author':s('서버의 작성자 이름.'),'description':s('코스 설명.'),'stopCount':n('1~3 장소 수.'),'checksum':CHECK},'현재 가용한 게시 코스 목록 항목.')
    models['OwnedCourseSummary']={'allOf':[ref('CourseSummary'),obj({
        'state':s('공개 상태 호환값. approved는 가용, 실제 신고 격리/사후 거절만 제한.'),
        'tags':arr(s('공개 태그.'),'브라우저 작성자 목록의 버전별 태그.'),
    },'작성자 목록 추가 상태.',required=['state'])]}
    models['LegacyPlace']=obj({'id':s('공급자 장소 ID.'),'provider':s('장소 공급자.'),'name':s('장소 이름.'),'address':s('주소 또는 빈문자열.'),'latitude':{'type':'number','description':'보고 위도.'},'longitude':{'type':'number','description':'보고 경도.'},'visitedAt':n('Unix epoch 밀리초.')},'legacy 저장소에서 장소별 최근 방문.')
    models['SocialOverview']=obj({'people':arr(ref('Person'),'호환용 빈 배열. 친구 추가는 핸들 정확 일치 검색을 사용합니다.'),'friends':arr(obj({'id':ACCOUNT,'name':s('현재 표시 이름.'),'hasVehicle':b('번호판이 등록된 현재 live 기기 보유. 번호판은 반환하지 않습니다.')},'현재 친구와 차량 분류.'),'현재 수락 관계.'),'requests':arr(obj({'id':ACCOUNT,'name':s('상대 이름.'),'direction':s('incoming 또는 outgoing.')},'계정 단위 친구요청.'),'미처리요청. native빈배열.'),'blocks':arr(obj({'id':ACCOUNT,'name':nullable(s('현재 이름.')),'available':b('현재 계정 사용가능여부.')},'내 차단.'),'native빈배열.'),'rooms':arr(ref('RoomSummary'),'본인 활성 방. native빈배열.'),'history':arr(ref('HistorySummary'),'현재 overview는빈배열이며기록목록API를따로사용.'),'capabilities':ref('Capabilities')},'현재 사회 관계 정본.')
    models['RoomInvite']=obj({'id':IDENT,'code':s('8자초대코드.'),'name':s('현재공개가능한방명또는고정대체값.'),'review':ref('Review'),'expiresAt':TIME,'serverNow':TIME,'expiresInSeconds':{'type':'number','description':'서버기준남은초.'},'courseId':nullable(s('선택코스ID.')),'courseVersion':nullable(n('선택버전.')),'course':nullable(ref('CourseRef')),'consentKeys':arr(s('status/location/visits/music/voice/control.'),'지원동의키전체.'),'availableConsentKeys':arr(s('status/location/music 및 활성화된 경우 voice.'),'현재 true를 새로 설정할 수 있는 목적. 세션 roomVoice와 함께 확인합니다.')},'가입전최소초대정보.')
    schema.setdefault('components',{}).setdefault('schemas',{}).update(models)
    effective={(method,path)for path,operations in schema['paths'].items()for method in operations if method in('get','post','put','patch','delete')}
    if effective!=set(OPERATIONS):raise RuntimeError('OpenAPI authored coverage differs: missing='+repr(sorted(effective-set(OPERATIONS)))+' orphan='+repr(sorted(set(OPERATIONS)-effective)))
    tags={}
    for(method,path),doc in OPERATIONS.items():
        operation=schema['paths'][path][method];tags[doc['tag']]=True
        operation['summary']=doc['summary'];operation['tags']=[doc['tag']]
        operation['description']='\n\n'.join(['### 용도\n'+doc['summary'],'### 선행 조건·계정\n'+doc['prerequisites'],'### 호출 순서\n'+doc['sequence'],'### 결과·부작용\n'+doc['effects'],'### 재시도·복구\n'+doc['retry']]+([doc['notes']]if doc['notes']else[]))
        operation['x-wegoh-documentation']={'authoring':'explicit-operation-contract','review':'Independent meaning review is required; coverage checks do not approve semantics.','source':'Runtime handler is authoritative; this catalog never grants access.'}
        operation['responses']=copy.deepcopy(doc['responses'])
        for code in doc['errors']:
            if code in doc['responses']:continue  # an authored response (own schema) is never replaced by shared text
            # Body timeout/size statuses exist only where the handler reads a request body.
            if code in('408','413')and(method=='get'or(method,path)in BODYLESS):continue
            authored=doc.get('errorDescriptions',{}).get(code)
            description=authored or ERROR_TEXT.get(code,{'415':'개발 자산 MIME을 지원하지 않습니다. 허용 media 목록을 확인하세요.'}.get(code))
            if not description:raise RuntimeError('Missing authored error '+code)
            # Only the shared 422 means FastAPI path/header validation; an authored 422 is a handler detail.
            operation['responses'][code]={'description':description,'content':{'application/json':{'schema':ref('ValidationError'if code=='422'and(not authored or path=='/v1/studio/course-follows/{follow_id}')else'ApiError')}}}
        for code,result in operation['responses'].items():
            if int(code)<300 and path in('/v1/packs/{pack_id}/versions/{version}','/v1/moderation/packs/{pack_id}/versions/{version}'):
                result.setdefault('headers',{})['ETag']={'description':'Double-quoted SHA-256 of exact returned canonical JSON bytes.','schema':{'type':'string'}}
            if code=='429':result.setdefault('headers',{})['Retry-After']={'description':'When returned by the persistent account rate limiter, wait 60 seconds. Capacity/busy responses may omit it; do not assume it is always present.','schema':{'type':'string'}}
            if code=='400'and path=='/v1/devices/token':result.setdefault('headers',{})['Retry-After']={'description':'Only authorization_pending/slow_down include 5 seconds. invalid_grant has no retry grant.','schema':{'type':'string'}}
            if code=='409'and method=='post'and path.endswith('/photos'):
                result.setdefault('headers',{})['X-WegoH-Error-Code']={'description':'Only PHOTO_VISIT_LIMIT or PHOTO_STORAGE_LIMIT for those quotas. Revision conflicts do not carry a quota code.','schema':{'type':'string','enum':['PHOTO_VISIT_LIMIT','PHOTO_STORAGE_LIMIT']}}
        if path=='/v1/social/friends/search'and method=='get':
            operation['parameters']=[{'name':'handle','in':'query','required':True,'description':'정확한 친구 핸들, 선택적 @ 및 대소문자 무시.','schema':{'type':'string','maxLength':21,'pattern':'^@?[A-Za-z0-9][A-Za-z0-9_.]{2,19}$'}}]
        if path=='/v1/profile/handle'and method=='put':
            operation['responses']['429']['headers']['Retry-After']['description']='시도 제한 60초, 성공 변경 후 제한 86400초. 응답 값을 따릅니다.'
        if path=='/v1/social/cautions'and method=='get':
            operation['parameters']=[{'name':'cursor','in':'query','required':False,'description':'직전 nextCursor를 그대로 지정합니다. 첫 페이지에서는 생략하며 eventId와 함께 쓰지 않습니다.','schema':{'type':'string','maxLength':256}},
                {'name':'eventId','in':'query','required':False,'description':'본인 불확실 저장의32hex ID로 기존 결과만 확인합니다. cursor와 함께 쓰지 않으며 GET은 관측을 생성하지 않습니다.','schema':{'type':'string','pattern':'^[0-9a-f]{32}$'}}]
        if method=='get' and path in ('/v1/social/trips/{id}/signals','/v1/social/trips/{id}/places'):
            operation.setdefault('parameters',[]).extend([
                {'name':'limit','in':'query','required':False,'description':'페이지당 최대 조회 수. 기본 50, 최대 100.','schema':{'type':'integer','minimum':1,'maximum':100,'default':50}},
                {'name':'cursor','in':'query','required':False,'description':'이전 응답의 nextCursor. 첫 페이지는 생략.','schema':{'type':'string','pattern':'^(0|[1-9][0-9]{0,4})$'}}])
        if method=='get' and path=='/v1/social/trip-archives':
            operation.setdefault('parameters',[]).append({'name':'cursor','in':'query','required':False,
                'description':'이전 응답의 nextCursor. 페이지당 최대 50개.','schema':{'type':'string','pattern':'^[a-f0-9]{32}$'}})

        for parameter in operation.get('parameters',[]):
            name=parameter['name']
            if name=='id' and path.startswith('/v1/social/trips/'):
                parameter['description']='내 여행 목록 또는 생성 응답의32hex 여행 ID. 현재 여행 멤버십을 다시 확인합니다.'
            if name=='room' and '/trips/' in path:
                parameter['description']='현재 여행 목록의 32hex 여행 ID. 이 경로는 내부 방 ID를 받지 않습니다.'
            if name=='peer' and '/device-command-grants/'in path:parameter['description']='현재 방에서 명시 참여한 요청자 team-40hex 계정ID. 기기소유자가별도로허용하며타인ID추측으로권한이생기지않습니다.'
            if name=='peer' and path=='/v1/social/friends/{peer}/profile':parameter['description']='친구 목록에서 프로필 보기를 선택한 상대의 team-40hex 계정 ID.'
            if path.startswith('/v1/social/cautions/')and name=='item':parameter['description']='목록/저장 응답의32hex 관측 ID. ID를 알아도 현재 소유/별도공유 권한이 없으면404입니다.'

            if name=='mission':parameter['description']='현재방missions목록의32hex 미션ID. 다른방ID를알아도권한이생기지않습니다.'
            if path.startswith('/v1/social/remix-drafts/') and name=='draft_id':parameter['description']='본인 재창작 응답의32hex remixDraftId. 개인세션/현재원권리도필요하며ID자체는권한이아닙니다.'
            if path=='/v1/moderation/voice-reports/{identifier}/resolve'and name=='identifier':parameter['description']='admin 음성 신고 목록에서 받은32hex 신고 ID. 방 신호 ID가 아닙니다.'
            if not parameter.get('description'):
                if name not in PARAMS:raise RuntimeError('Missing parameter description: '+name)
                parameter['description']=PARAMS[name]
            if name=='purpose':parameter['schema']={'type':'string','enum':['location','visits'] if path=='/v1/devices/{device}/reporting-permissions/{purpose}' else ['friends','rooms','history']}
            if name=='purpose' and path=='/v1/devices/{device}/reporting-permissions/{purpose}':parameter['description']='철회할 별도 쓰기 목적 location 또는 visits. 기존 읽기3목적이 아닙니다.'
        media=operation.get('requestBody',{}).get('content',{}).get('application/json')
        if media:
            describe_fields(media['schema'])
            valid=copy.deepcopy(doc['example'])if doc['example']is not None else sample(media['schema'])
            if path.endswith('/export-permissions/{target}')and method=='put':
                valid.update(consent=True,visits=True,trace=False,photos=False,expiresAt='2026-01-01T10:00:00+09:00')
            if path=='/v1/packs'and method=='post':
                valid={'rightsConfirmed':True,'pack':{'schemaVersion':1,'id':'my-course','version':1,'title':'내 코스','author':'현재 계정 이름으로 대체','description':'직접 확인한 코스','stops':[{'id':'first','name':'직접 선택한 장소','latitude':0,'longitude':0,'radiusMeters':100,'action':{'type':'chime','message':'장소에 도착했습니다'}}]}}
            media['example']=valid
            operation['x-wegoh-try-example']=safe(valid)
            media['schema']['examples']=[valid]
            operation['description']+='\n\n### 요청 예제\n아래는 구조 예제이며 ID·revision·날짜·좌표는 실제 사용자가 확인한 정본으로 바꿔야 합니다. 동의/권리는 사용자 확인 후에만 true를 보냅니다. Try it out 초기본문은 자동 동의를 막기 위해 false를 유지합니다.\n```json\n'+json.dumps(valid,ensure_ascii=False,indent=2)+'\n```'
        # Describe the actual shared read alternatives, without changing handlers.
        if method=='get'and path in('/v1/packs','/v1/packs/{pack_id}/versions/{version}'):
            operation['security']=[{'CloudflareAccess':[]},{'NativeMTLS':[],'DeviceBearer':[]}]
        if method=='get'and path in('/v1/playlists','/v1/playlists/{playlist_id}','/v1/studio/packs','/v1/studio/packs/{pack_id}/versions/{version}'):
            operation['security']=[{'CloudflareAccess':[],'TeamSession':[]},{'NativeMTLS':[],'DeviceBearer':[]}]
        if method=='get' and path in ('/v1/packs/{pack_id}/versions/{version}/cover',
                '/v1/studio/packs/{pack_id}/versions/{version}/cover','/v1/moderation/packs/{pack_id}/versions/{version}/cover'):
            operation['x-wegoh-executable']=False
            operation['x-wegoh-availability']='브라우저의 코스 화면에서 대표 JPEG를 조회합니다.'
            if path.startswith('/v1/packs/'):
                operation['security']=[{'CloudflareAccess':[]}]
        if path.startswith('/v1/local/')or path.startswith('/v1/studio/session')or path.startswith('/v1/assets')or path=='/v1/dev/status':
            operation['x-wegoh-executable']=False
            operation['x-wegoh-availability']=('Public Access plus operator Bearer; native/shared loopback unavailable; Swagger execution disabled.'if path.startswith('/v1/assets')or path=='/v1/dev/status'else'Local compatibility contract only; shared service returns404.')
        if path=='/v1/app-release':operation['security']=[{'CloudflareAccess':[]}]
        if path=='/v1/studio/session':
            operation['responses']['200']['content']['application/json']['schema']=(obj({'creator':s('고정 로컬 창작자 표시 이름.'),'mode':s('local-workspace.')},'로컬 세션 시작 결과.')if method=='post'else status('signed-out'))
        if path=='/v1/local/visits':operation.setdefault('parameters',[]).append({'name':'X-WegoH-Local-Visit','in':'header','required':True,'description':'로컬 사용자의 명시 선택 방문 저장. 값1이 필요하며 공유 서비스에서는 이 헤더로 활성화할 수 없습니다.','schema':{'const':'1'}})
        if path.startswith('/v1/local/packs/'):
            operation.setdefault('parameters',[]).append({'name':'X-WegoH-Local-Report','in':'header','required':True,'description':'로컬 사용자의 명시 신고. 값1. 공유서비스 우회가 아닙니다.','schema':{'const':'1'}})
        if path=='/v1/assets'and method=='post':
            operation.pop('x-wegoh-body-contract',None)
            operation['requestBody']={'required':True,'content':{mime:{'schema':{'type':'string','format':'binary','maxLength':26214400,'description':'개발 raw bytes, 25MiB 이하.'}}for mime in('application/json','image/png','image/jpeg','audio/wav','audio/mpeg','audio/ogg')}}
            for parameter in operation.get('parameters',[]):
                if parameter['name']=='content-type':parameter['required']=True
        if path=='/v1/assets/{checksum}':
            operation['responses']['200']['content']={mime:{'schema':{'type':'string','format':'binary'}}for mime in('application/json','image/png','image/jpeg','audio/wav','audio/mpeg','audio/ogg')}
        if path=='/v1/dev/status'or path.startswith('/v1/assets'):
            operation['security']=[{'CloudflareAccess':[],'OperatorBearer':[]}]
        if path.startswith('/v1/local/')or path.startswith('/v1/studio/session'):
            operation['security']=[]
    schema['tags']=[{'name':name,'description':TAG_DESCRIPTIONS[name]}for name in sorted(tags)]
    schema['components']['securitySchemes']['OperatorBearer']={'type':'http','scheme':'bearer','description':'운영자 전용 key. 현재 public host는 Access도 함께 필요합니다. 일반 개발 서버에서는 자체 Bearer를 검증하며 공유 loopback/native는 경계404입니다. Swagger/APK에 key를 입력하지 않으며 Try it out 비활성.'}
    schema['info']['description']=INTRO
    schema['x-wegoh-documentation-coverage']={'operations':len(effective),'keys':'Exact effective first-route HTTP operations; missing/orphan catalog entries fail generation.','excluded':NON_OPERATION_ROUTES,'semanticApproval':'Coverage is structural; two independent domain reviewers compare actual handlers and consumer meaning.'}
    return schema

TAG_DESCRIPTIONS={
 CLIENT_DIAGNOSTICS_TAG:CLIENT_DIAGNOSTICS_TAG_DESCRIPTION,
 '여행':'최대 20명의 여행: 초대·차·코스와 준비/진행/종료 상태, 독립 역할·본인 공유, 장소 후보·신호·투표. 통합 상세는 내부 방 ID와 목적별 자료를 포함하지 않습니다.',
 '20 유가':'선택 지역·유종의 명시 가상/공급자 가격과 공용 캐시.',
 '운영 설정':'현재 관리자 개인 세션으로 고정 origin/main 수동 배포를 요청하고 실제 작업 상태·서버 버전을 확인합니다. 자동 배포는 사용하지 않습니다.',
 FUNCTIONAL_TAG:'본인 기기의 기본 연결과 별도로 선택하는 기능 동의. 원 scope·키·grant·기한을 자동 확대하지 않으며 현재 소유자·revision·설명을 확인합니다.',
 '18 기기 보고와 수신':'기본꺼짐 별도 쓰기 목적과 현재 방의 양측 송수신 교집합. 최신 GCM 보고만 저장하며 물리 GPS·도착·제어·기기등록 성공은 주장하지 않습니다.',
 '17 기기 명령 프로토콜':'별도 기본off 목적/action판/현재 방·기기 교집합의 요청·lease·ACK. 11개 차량 제어 계약을 등록하며 실제 차량 지원과 물리 성공은 별도로 확인합니다.',
 '16 내 취향 추천':'명시 취향·선택 장소의 규칙 추천과, 추가 학습 동의·현 세대를 명시한 개인 코스 모델을 구분합니다. 현재 승인·별도 목적을 확인하며 도로시간·가격·연료·의학 예측은 제공하지 않습니다.',
 '15 협동미션':'현재 명시 참여자가 가용 코스의 장소를 순서대로 직접 확인하는 협동 진행. 속도·도착 경쟁·임의 안전점수는 제공하지 않습니다.',
 '17 기록 재창작':'현재 가용 원코스 또는 실제 저장 방문을 별도 재사용 목적으로 새 편집초안에 연결합니다. 친구 읽기와 원권리는 분리하고 게시 직전에 다시 검사합니다.',
 '18 주의 구간 경험':'사용자의 명시 관측·시각·장소를 기본 비공개로 저장하고 별도 친구 목적·내용 검토·기간을 교차 확인합니다. 현재 도로 진위·차량 SDK 탐지·안전 점수를 인증하지 않습니다.',
 '14 여행방 음악':'별도 음악 목적의 DJ/현재곡·검토된 원곡 링크 metadata. 기기는 rooms 및 별도 음악 읽기 동의가 필요하며 음원복제·재생·SDK 실행이 아닙니다.',
 '15 차량 인증서':'별도 최초등록 호스트의 CSR/proof·명시 웹승인·관리CA 인증서 수령. 개인 계정 pairing과 분리되며 실운영 설정 전503입니다.',
 '14 시설 후보':'공식 고정데이터와 명시 선택 장소 또는 이번 GPS 전송 동의로 찾는 시설 후보. 직선거리와 실제 도로 진입, 영업, 가격은 구분합니다.',
 '01 인증':'Access 로그인과 WegoH 개인 세션을 구분합니다. 쿠키/CSRF 복사를 요구하지 않습니다.',
 '02 기기 연결':'별도 native 호스트의 개인 mTLS 인증서+S256 기기 token 연결과 철회. 실제 운영 활성화는 별도 근거로 확인합니다.',
 '03 기기 읽기 동의':'기존 course/music 연결에서 자동 확대하지 않는 friends/rooms/history 목적별 기본 false.',
 '04 코스':'불변 버전 게시 즉시 catalogue/download. 사후 신고·거절 제한 유지. 내비 실행 API가 아닙니다.',
 '05 운영 검수':'현재 admin의 전체 내용 검토. 큐 조회나 기계검사가 승인/마켓 검토를 대신하지 않습니다.',
 '06 호환·개발':'현재 공유서비스에서 닫힌 로컬/운영 호환 API와 별도 legacy 방문저장소.',
 '07 음악 링크':'개인 HTTPS 링크 metadata 관리. 음원 업로드/재생/방 DJ제어가 아닙니다.',
 '08 친구':'계정 단위 요청/수락/차단. 친구가 되었다고 위치/기록/사진 동의가 생기지 않습니다.',
 '09 여행방':'기간·멤버십·목적별 동의가 매번 적용되는 선택 장소/상태 요청.',
 '10 여행기록':'개인 기록·명시 방문·browser-reported 경로와 검수/친구 목적별 공유.',
 '11 사진':'raw upload·별도 사진 동의·검토·현재 JPEG 접근. JSON Swagger binary 실행은 제한됩니다.',
 '13 방 음성':'별도 개인 voice 동의의 기본 off 단일 송신자 WSS와 본인 음소거·음성 미보관 신고 metadata. 물리 청취/차량 AudioFocus 승인은 별도입니다.',
 '12 외부 영상':'외부 파일 목적별 동의와 단기 JSON manifest. 실제 영상 파일 생성은 client에서 별도로 수행합니다.'}
NON_OPERATION_ROUTES=[
 '`GET /health/live`: 프로세스 생존 확인. 200 `{"status":"alive"}`. 공유 서비스에서는 서버 자체의 loopback 클라이언트 프로브가 기준이고 공개 호스트에서는 Access 로그인 뒤에만 닿습니다. 배포 차단막이 켜진 서버의 loopback 프로브는 `deploymentGate` 상태와 `X-WegoH-Release` 헤더를 함께 반환합니다.',
 '`GET /health/ready`: DB·방문 암호화·콘텐츠 저장소 준비 확인. 200 `{"status":"ready"}`, 저장소를 쓸 수 없으면 503 `{"status":"unavailable"}`, 방문 기록 이전이 남아 있으면 503 `{"status":"private-migration-required"}`. 서버 릴리스 커밋을 알면 `X-WegoH-Release` 헤더를 붙입니다. 접근 경계는 `/health/live`와 같습니다.',
 '`GET /`: 웹 첫 화면 HTML. 팀 인증을 쓰는 서버는 `studio.html`, 아니면 `platform.html`을 no-store로 반환합니다.',
 '`/` 정적 파일 mount: `server/web`의 화면·스크립트·스타일 파일을 그대로 전달합니다. 업무 API가 아닙니다.',
 '`GET /openapi.json`, `GET /developer/openapi.json`: 이 명세 JSON. 공개 호스트에서 Access 로그인한 admin 계정만 받습니다. 로그인 없음 401, admin이 아님 403, 다른 호스트 404이며 응답은 private, no-store입니다.',
 '`GET /api-docs`, `GET /api-docs.html`, `GET /developer/docs`: 이 Swagger 화면 HTML. 접근 조건은 `/openapi.json`과 같습니다.',
 '`WSS /v1/events`: 변경 알림 WebSocket. 메시지·호스트별 인증·상한·종료 코드는 `x-wegoh-events`(native 목적은 `x-wegoh-native-events`)에 있습니다.',
 '`WSS /v1/social/rooms/{room}/voice`: 방 음성 PCM WebSocket. 형식·lease·상한·종료 코드는 `x-wegoh-voice`에 있습니다.',
 '`WSS /v1/social/trips/{trip}/voice`: 여행 음성 PCM WebSocket. 방 음성과 같은 형식·상한을 쓰며 여행 참여 조건은 `x-wegoh-trip-voice`에 있습니다.']
INTRO="""# WegoH API 빠른 시작

이 명세는 현재 배포 handler를 설명하는 OpenAPI 3.1 문서입니다. 개발자용 공식 stock Swagger UI이며 제품의 Pleos 화면과 구분합니다. 예제는 합성 형식이며 실계정·실장소·token을 포함하지 않습니다.

1. 브라우저에서 Cloudflare Access에 로그인하고 이 페이지 상단 **로그인**으로 WegoH 개인 세션을 시작합니다. GET `/v1/auth/session`의 `authenticated`를 확인하세요.
2. **Try it out → Execute**는 같은 origin의 개인 쿠키를 브라우저가 자동 전송합니다. 현재 세션 CSRF도 메모리에서 자동 추가합니다. Cookie·공통 운영 key를 Authorize에 복사하지 마세요. 변경 요청은 별도 확인창 이후에만 전송됩니다.
3. 먼저 GET으로 실제 ID와 revision을 얻고 해당 리소스의 수정 본문에 넣습니다. 409는 최신 정본을 읽고 사용자 선택을 다시 확인하라는 뜻입니다. HTTP 2xx라도 생성된 대상/저장동의와 실효 공유·실행 성공은 구분합니다.
4. 친구: overview → request → 상대 respond → 별도 기록grant. 방: invite → join 동의 → 상세. 기록: create → visits/선택 경로 → 명시 검토 제출 → 현재 승인 및 친구별 grant. 사진은 방문 공유와 별도입니다.
5. 외부 영상: 현재 승인된 기록 → 소유자의 별도 export consent(자기 자신도 필요) → active GET → manifest → 현재 client의 파일 생성 → 저장/공유 직전 manifest 재검증. manifest는 MP4나 외부 게시 완료가 아닙니다. 이미 저장된 사본은 회수할 수 없습니다.

## 계정·native·실행 경계
브라우저는 Access+개인세션/Origin/CSRF, native는 별도 호스트의 TLS1.3·기기별 mTLS 인증서와 그 인증서에 결합한 개인 S256 기기 token을 함께 사용합니다. 개인 인증서만으로 계정 token을 대신하지 않으며 origin 활성화와 실제 edge 헤더 덮어쓰기는 별도 운영 검증입니다. 새 기기 목적은 기본 false이며 읽기 허용이 사진·새 쓰기·실차 제어를 뜻하지 않습니다. 실차 AudioFocus/Navi ACK/차량 제어·마켓승인을 이 문서가 증명하지 않습니다. binary/로컬/기기 bootstrap은 이 브라우저 실행기에서 차단되며 실제 명세는 계속 볼 수 있습니다.

## 오류와 재시도
오류는 보통 `{\"detail\":\"...\"}`이며 경로 형식의 FastAPI 422는 detail 배열입니다. 각 operation에 실제 적용 상태를 표시했습니다. 생성 POST는 응답 유실 후 무조건 반복하지 말고 대상 목록/정본을 확인하세요. token refresh는 회전형이며 병렬 재전송을 피합니다. 경로 batch만 명시 batchId의 정확 동일 내용에 대해 중복 접수를 지원합니다.

## 실시간 변경 피드
`WSS /v1/events`는 snapshot/invalidate/heartbeat만 보내는 알림입니다. REST가 정본이며 invalidate 뒤 해당 REST를 다시 읽습니다. 개인 이름·좌표·token·본문은 이벤트에 없습니다. browser는 동일 Origin+쿠키, native는 별도 host의 같은 개인 mTLS 인증서+Authorization Bearer 및 현재 목적을 사용합니다. CF 인증서 철회는 새 요청/upgrade에서 평가되므로 기존 native WSS는60초 경과 후 다음 재검증 주기에 종료하고 새 edge handshake가 필요합니다. 계정/기기 token/목적 철회는 기존1초 재검증을 유지합니다. URL/query/subprotocol 자격증명은 금지입니다. client command를 보내면1008 종료하며 재연결은 새 epoch snapshot부터 시작합니다. 현재 목적·계정·역할 변경도 종료 후 재연결해야 합니다. 종료 코드와 연결 상한은 x-wegoh-events에 있습니다.

음성은 세션 `capabilities.roomVoice=true`일 때만 열리며 이 events feed로 PCM을 보내지 않습니다. 방 음성은 `/v1/social/rooms/{room}/voice` WSS와 개인 voice 동의, 여행 음성은 `/v1/social/trips/{trip}/voice` WSS와 `GET /v1/social/trips/{id}/voice-participation`의 여행 참여 설정을 사용합니다. 단일 worker에서 한 번에 한 명만 말하고(floor) 자동 송신은 없습니다. 실시간 음성 원본과 받아쓰기는 저장하지 않습니다. 녹음한 한 건을 보내는 여행 음성 메시지는 별도 `voice-clips` REST operation이며 서버 프로세스 메모리에만 잠시 보관합니다. 형식·lease·상한·종료 코드는 x-wegoh-voice와 x-wegoh-trip-voice에 있습니다. 서버 전송 성공은 실제 청취나 차량 오디오 포커스를 증명하지 않습니다.

## HTTP operation 밖의 경로
아래 경로는 실제로 등록돼 있지만 업무 REST operation이 아니어서 `paths`에 넣지 않습니다. 같은 목록이 `x-wegoh-documentation-coverage.excluded`에 있습니다.

"""+'\n'.join('- '+item for item in NON_OPERATION_ROUTES)+"""

## 출처·생성
명시 Python operation catalog와 named models에서 실제 등록된 첫 HTTP route에 문서를 결합합니다. 누락/고아 operation은 생성 실패로 차단합니다. 구조 coverage는 의미 승인과 별도이며 두 독립 reviewer가 handler와 소비 흐름을 읽습니다. 공식 문서의 선택·비적용 근거는 저장소 `docs/api-documentation-sources.json`을 참조하세요.
"""
