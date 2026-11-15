"""Display-only support observations from the authenticated receiver."""
from api_doc_shared import TIME, nullable
from api_doc_device_commands import strict
from device_command_registry import DRIVER_AREA, ProductionCommandRegistry, SEATS

PATH = '/v1/device/control-support'
REMOTE_AREAS = [area for area in SEATS if area != DRIVER_AREA]
NUMBER = nullable({'type': 'number', 'description': '명령 단위의 지원 범위·증분. bool에는 null. 실제 설정값이 아닙니다.'})
AREA = strict({'id': {'type': 'string', 'enum': REMOTE_AREAS, 'description': '실제 SDK가 지원하는 좌석 또는 창문 위치. 운전석(ROW_1_LEFT)은 원격 조작에서 제외하므로 보고하면 400입니다.'}, 'min': NUMBER, 'max': NUMBER, 'step': NUMBER},
              '좌석 또는 창문 위치. 창문은 ROW_1_RIGHT·ROW_2_LEFT·ROW_2_RIGHT만, 범위는 정규화된0..100%.')
FIELDS = {'status': {'type': 'string', 'enum': ['known', 'unknown'], 'description': '지원 명세를 관측했는지. 미관측을 미지원으로 단정하지 않습니다.'},
          'available': {'type': 'boolean', 'description': 'known일 때 READ_WRITE 지원 여부. 실제 현재 전원 상태나 실행 권한이 아닙니다.'},
          'areas': {'type': 'array', 'items': AREA, 'maxItems': 8, 'description': '중복 없는 지원 위치. 미확인·미지원·전역 실내등이면 빈 목록.'},
          'zones': {'type': 'array', 'maxItems': 4, 'description': '하나의 SDK 조절 구역으로 묶여 함께 바뀌는 좌석 묶음. '
                    '각 묶음은 areas에 있는 좌석 2개 이상이고 서로 겹치지 않습니다. 운전석은 areas에 올 수 없으므로 운전석을 포함한 묶음도 400입니다. 묶음에 없는 좌석은 단독 조절입니다. 창문·전역 조작·미지원이면 빈 목록. '
                    '응답은 좌석 순서(1열 왼쪽→3열 오른쪽)로 정렬합니다.',
                    'items': {'type': 'array', 'items': {'type': 'string', 'enum': REMOTE_AREAS}, 'minItems': 2, 'maxItems': 8, 'uniqueItems': True}}}
SUPPORT = strict(dict(FIELDS, observedAt=nullable(TIME), expiresAt=nullable(TIME)),
                 '최대90초 입력 힌트. unknown 또는 available=false는 실행 권한이 아닙니다. 명령은 기존 권한과 실제 SDK를 다시 검사합니다.')
ACTION = strict({'id': {'type': 'string', 'enum': [a['id'] for a in ProductionCommandRegistry().describe()], 'description': '고정 등록된 조작 ID. 새 실행 항목을 등록하지 않습니다.'},
                 'revision': {'type': 'integer', 'const': 1, 'description': '고정 명령 계약의 개정1.'}, **FIELDS}, '고정 등록 조작의 관측 결과. 중복과 새 조작 등록은 금지.')
BODY = strict({'functionalRevision': {'type': 'integer', 'minimum': 1, 'maximum': 2147483647, 'description': '현재 기능 정본 revision. 권한을 넓히지 않습니다.'},
               'receiverRevision': {'type': 'integer', 'minimum': 1, 'maximum': 2147483647, 'description': '직전 수신 상태 GET에서 받은 revision.'},
               'actions': {'type': 'array', 'items': ACTION, 'maxItems': 11, 'description': '관측한 조작 명세. 누락된 항목은 unknown.'}},
              '정확히 이 세 필드만. 현재값·SDK 오류·기기·계정·시간을 받지 않습니다. 최대12288bytes.')
RESULT = strict({'status': {'const': 'accepted', 'description': '지원 힌트 저장 접수.'}, 'observedAt': TIME, 'expiresAt': TIME},
                '서버 UTC ISO8601 시간. 현재 원 grant와 기능 기한보다 연장하지 않습니다.')


def apply(schema, auth):
    operation = schema.get('paths', {}).get(PATH, {}).get('put')
    if operation is None:
        return schema
    operation.update(summary='현재 차량의 조작 지원 범위 보고', operationId='nativeControlSupportPut',
        description='현재 차량 Native mTLS·Bearer·수신 목적·receiver ON을 재검사합니다. '
        '지원 정보만 기존 암호화 기능 payload에 저장하며 동의 revision이나 devices 이벤트를 바꾸지 않습니다. '
        'grant/device/credential epoch/기능·수신revision/90초 기한이 다르면 unknown입니다.',
        security=[{'NativeMTLS': [], 'DeviceBearer': []}],
        servers=[{'url': auth.native_origin, 'description': 'Native mTLS AND opaque Bearer'}],
        requestBody={'required': True, 'content': {'application/json': {'schema': BODY}}},
        **{'x-wegoh-native-access': True, 'x-wegoh-executable': False})
    operation['responses']['200'] = {'description': '지원 힌트 저장. 권한·현재 설정값은 변경하지 않습니다.',
        'content': {'application/json': {'schema': RESULT}}}
    for code in ('400', '401', '403', '409', '413', '503'):
        operation['responses'][code] = {'description': '거절된 지원 보고. 기존 snapshot을 덮지 않습니다.',
            'content': {'application/json': {'schema': {'$ref': '#/components/schemas/NativeFunctionalError'}}}}
    return schema
