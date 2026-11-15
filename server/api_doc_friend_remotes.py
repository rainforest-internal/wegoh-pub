"""OpenAPI models for controls a driver approves for passengers on one trip."""
from api_doc_shared import s, arr, ref, TIME
from api_doc_models import IDENT
from api_doc_device_commands import OPTION, ARGUMENTS, EVENT, ZERO, strict
from api_doc_control_support import SUPPORT

FRIEND_IDS = [
    'hvac.temperature', 'hvac.fan', 'hvac.power', 'hvac.ac', 'hvac.air_cleaner',
    'seat.heat', 'seat.ventilation', 'window.position', 'light.cabin', 'light.reading', 'light.ambient',
]
FRIEND_KINDS = ['hvac-celsius', 'hvac-fan', 'seat-switch', 'seat-level', 'window-position', 'switch']
ACTION_ID = s('차주가 이 여행에서 허용한 조작 ID.', enum=FRIEND_IDS)
ACTION_REVISION = {'const': 1, 'description': '지원하는 차량 조작 계약 버전.'}
OPTION_FIELDS = dict(OPTION['properties'], id=ACTION_ID, revision=ACTION_REVISION,
    argumentKind=s('선택한 조작이 받는 인자의 종류.', enum=FRIEND_KINDS), support=SUPPORT)

REMOTE = strict({
    'deviceId': IDENT,
    'ownerName': s('같은 차의 운전자 이름.'),
    'deviceName': s('운전자가 정한 연결 차량 이름. 정하지 않았으면 "{운전자 이름}의 차".'),
    'grantRevision': ZERO,
    'expiresAt': dict(TIME, description='현재 기기 연결과 수신 권한의 유효 기한. 여행 종료나 철회 시 더 일찍 중지됩니다.'),
    'actions': arr(strict(OPTION_FIELDS, '이 차량에서 허용한 조작.'), '해당 동승자에게 허용한 조작만 반환합니다.'),
    'requests': dict(arr(ref('TripDeviceRequest'), '현재 탑승·허용에서 본인이 보낸 최근 요청 상태.'), maxItems=5),
}, '현재 여행의 탑승 관계와 차주의 승인이 유효한 차량.')
TRIP_REMOTES = strict({
    'tripId': IDENT, 'remotes': arr(REMOTE, '이 여행에서 내가 조작할 수 있는 차량.'), 'serverNow': TIME,
}, '진행 중인 여행에서 동승자 본인이 사용할 수 있는 리모컨 목록.')
COMMAND = strict({
    'eventId': EVENT, 'grantRevision': ZERO, 'capabilityId': ACTION_ID, 'capabilityRevision': ACTION_REVISION,
    'arguments': {'anyOf': [ARGUMENTS[kind] for kind in FRIEND_KINDS], 'description': '선택한 조작에 맞는 좌석·창문·설정값.'},
}, '진행 중인 여행에서 동승자가 선택한 차량에 보내는 명령.')


REMOTE_POLICY = strict({
    'enabled': {'type': 'boolean', 'description': '차주가 이번 여행의 현재 동승자에게 미리 허용했는지. 기본 false.'},
    'actions': dict(arr(ACTION_ID, '이번 차에서 허용할 조작 ID. 중복 금지.'), uniqueItems=True, maxItems=11),
    'deviceId': {'anyOf': [IDENT, {'type': 'null'}], 'description': '차주가 현재 연결한 차량. 끈 상태는 null일 수 있습니다.'},
}, '요청·수락 없는 차주 사전 허용. 친구·탑승·차단·현재 기기·수신 조건은 별도로 재검사합니다.')
REMOTE_POLICY_INPUT = dict(REMOTE_POLICY, required=['enabled', 'actions'],
    allOf=[{'if': {'properties': {'enabled': {'const': True}}}, 'then': {'properties': {'actions': {'minItems': 1}}}}])
REMOTE_POLICY_RESULT = strict({'remotePolicy': REMOTE_POLICY}, '이번 여행 차의 현재 리모컨 허용 설정.')
