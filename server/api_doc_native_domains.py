"""Current Native contracts for the four integrated domains; no new authority."""
from copy import deepcopy
from native_functional_policy import WIRE
from team_event_versions import PROTOCOL as EVENTS_PROTOCOL
from api_doc_recommendation_learning import BODY as LEARNING_BODY, STATE, MODELS as LEARNING_MODELS
from api_doc_recommendations import MODELS as RULE_MODELS
from api_doc_device_commands import BODY as COMMAND_BODY
from api_doc_missions import BODY as MISSION_BODY
from api_doc_vehicle import BODY as VEHICLE_BODY
from api_doc_trips import BODY as TRIP_BODY, NATIVE_TRIPS
from api_doc_trip_plan import BODY as TRIP_PLAN_BODY, NATIVE as NATIVE_TRIP_PLAN
from api_doc_trip_hand_raise import BODY as TRIP_HAND_RAISE_BODY, NATIVE as NATIVE_TRIP_HAND_RAISE
from api_doc_trip_merge import BODY as TRIP_MERGE_BODY, NATIVE as NATIVE_TRIP_CONTEXT
from api_doc_native_functional import BOUNDARY
from api_doc_voice import BODY as VOICE_BODY

NATIVE = {'NativeMTLS': [], 'DeviceBearer': []}
FR = dict(type='integer', minimum=1, maximum=WIRE['revisionMaximum'],
    description='직전 기능 정본의 revision입니다. 같은 업무 transaction에서 현재 grant·기기·목적과 정확히 대조합니다. 철회 후 재승인한 새 revision으로 자동 재전송하지 않습니다.')


def selected(rule):
    path = rule['path']
    if '/driving-data' in path:
        return False
    return ((rule['method'].lower(), path) in NATIVE_TRIPS
        or (rule['method'].lower(), path) in NATIVE_TRIP_CONTEXT
        or (rule['method'].lower(), path) in NATIVE_TRIP_PLAN
        or (rule['method'].lower(), path) in NATIVE_TRIP_HAND_RAISE
        or path in ('/v1/native/trips/{id}/driving-versus', '/v1/native/trips/{id}/driving-score', '/v1/native/trips/{id}/cars/{carId}/driving-score')
        or '/voice-clips' in path or path == '/v1/social/trips/{room}/voice/filters'
        or path == '/v1/device/vehicle-domain'
        or path.startswith(('/v1/native/rooms/', '/v1/native/trips/')) and ('/reports/' in path or path.endswith(('/device-reports', '/vehicle-domain')))
        or path.startswith('/v1/recommendations/') or path.startswith('/v1/social/cautions')
        or ('/missions' in path and path.startswith('/v1/native/rooms/'))
        or (rule['method'] == 'GET' and path == '/v1/native/trips/{room}/missions')
        or path.startswith('/v1/device/requests/') or path == '/v1/device/command-inbox'
        or (path.startswith('/v1/social/rooms/') and ('/device-requests' in path or path.endswith('/device-command-access'))))


def native_body(body, *, recommendation=False):
    result = deepcopy(body)
    if 'oneOf' in result:
        result['oneOf'] = [native_body(item, recommendation=recommendation) for item in result['oneOf']]
        return result
    if 'functionalRevision' not in result['properties']:
        result['properties']['functionalRevision'] = deepcopy(FR)
    if 'functionalRevision' not in result['required']:
        result['required'].append('functionalRevision')
    if recommendation and 'anchor' in result['properties']:
        anchor = result['properties']['anchor']
        device = anchor['oneOf'][1]
        device['properties']['kind'] = dict(type='string', const='device-location', description='기기가 보고한 위치이며 물리 GPS 검증이나 방 공유 권한이 아닙니다.')
        device['properties']['position']['description'] = '이번 추천에 명시 전송한 기기 보고값입니다. 기존 위경도·정확도·시각 상한을 유지하며 저장하지 않습니다.'
        device['properties']['position']['properties']['accuracyMeters']['description'] = '기기가 보고한 정확도 미터입니다. 실측 보증이 아닙니다.'
        device['description'] = '현재 추천에만 명시 전송한 기기 보고 위치입니다. browser-location을 Native 출처로 보내지 않습니다.'
        anchor['description'] = '명시 선택한 장소 또는 이번 전송에 별도 동의한 device-location입니다. 친구·방 위치 공유나 학습 동의가 아닙니다.'
    return result


def apply_native_domain_documentation(original, auth):
    schema = deepcopy(original)
    models = schema.setdefault('components', {}).setdefault('schemas', {})
    settings = deepcopy(RULE_MODELS['RecommendationSettings'])
    settings['properties']['learning'] = deepcopy(STATE)
    settings['properties']['learning']['additionalProperties'] = False
    settings['properties']['learning']['description'] += ' settingsRevision은 바깥 revision과 같습니다. 조회는 업무 저장·학습 승인·표본 생성 없이 현재 권위 잠금을 유지한 같은 REPEATABLE READ transaction에서 계산합니다.'
    settings['required'].append('learning')
    settings['additionalProperties'] = False
    settings['description'] = 'Native 전용 읽기 projection입니다. 기존 브라우저 7필드에 별도 학습 상태 6필드만 추가하며 학습을 승인하지 않습니다.'
    models['NativeRecommendationSettings'] = settings
    result = deepcopy(LEARNING_MODELS['RecommendationResult'])
    result['properties']['anchor']['properties']['kind'] = dict(type='string', enum=['selected-place', 'device-reported'], description='좌표를 반사하지 않는 명시 선택 또는 기기 보고 출처입니다. 물리 위치 검증이 아닙니다.')
    models['NativeRecommendationResult'] = result
    bodies = {**VOICE_BODY, **VEHICLE_BODY, **COMMAND_BODY, **MISSION_BODY, **LEARNING_BODY, **TRIP_BODY, **TRIP_MERGE_BODY, **TRIP_PLAN_BODY, **TRIP_HAND_RAISE_BODY}
    vote_delete = ('delete', '/v1/social/trips/{id}/signals/{signal}/vote')
    bodies[vote_delete] = dict(type='object', properties={}, required=[], additionalProperties=False,
        description='웹 투표 철회는 본문을 생략할 수 있습니다. Native는 functionalRevision을 JSON 본문에 명시합니다.')
    for rule in WIRE['nativeRoutes']:
        if not selected(rule):
            continue
        path, method = rule['path'], rule['method'].lower()
        operation = schema['paths'][path][method]
        native_only = '/voice-clips' in path or path.startswith(('/v1/device/', '/v1/native/'))
        browser = dict(CloudflareAccess=[], TeamSession=[])
        if method != 'get':
            browser['CurrentSessionCSRF'] = []
        operation['security'] = ([deepcopy(NATIVE)] if native_only else [browser] + ([deepcopy(NATIVE)] if auth.native_origin else []))
        operation['servers'] = ([] if native_only else [dict(url=auth.public_origin, description='기존 본인 웹 로그인과 변경 시 현재 CSRF')])
        if auth.native_origin:
            operation['servers'].append(dict(url=auth.native_origin, description='TLS1.3 mTLS AND 같은 인증서의 현재 opaque Bearer'))
        operation['x-wegoh-native-access'] = True
        feature = getattr(auth, 'functional_access', None)
        operation['x-wegoh-feature-enabled'] = bool(feature and feature.enabled and feature.base.enabled)
        operation['x-wegoh-native-functional-purposes'] = dict(all=rule['all'], any=rule['any'])
        operation['x-wegoh-surface'] = 'native' if native_only else 'browser-and-native'
        operation['x-wegoh-executable'] = not native_only
        description = operation['description'].replace('추천은 브라우저 개인 기능이며 Native 호스트 허용목록은 열지 않습니다.', '브라우저의 기존 계정 목적과 Native의 별도 기능 목적을 각각 확인합니다.').replace('Native는 미공개이며 운영 Bearer가 개인 권한을 대신하지 않습니다.', 'Native는 현재 cautions:read 목적의 GET만 허용하며 쓰기·공유 승인을 대신하지 않습니다.')
        description += '\n\n### Native 현재 권위\n같은 개인 인증서와 Bearer의 단일 NativePrincipal을 사용합니다. 현재 grant·설치 slot·credential epoch·원 기한과 명시 기능 목적을 같은 업무 transaction에서 재확인합니다. 필요한 모든 목적: ' + ', '.join(rule['all']) + '. 친구·방·미션 참여·기기별 별도 동의는 자동 승인하지 않습니다. 전역 재승인으로 종료된 동의나 명령을 부활시키지 않습니다.'
        if method == 'post' or (method, path) == vote_delete or method != 'get' and (method, path) in NATIVE_TRIP_PLAN:
            description += ' Native 본문에는 현재 functionalRevision이 필수입니다. 응답이 불확실하면 현재 정본을 먼저 읽으며 새 revision으로 자동 재전송하지 않습니다.'
        if (method, path) in NATIVE_TRIPS:
            description += ' 차량은 여행 목록·상세·초대 응답 및 wire에 명시된 통합 상세·신호·투표·장소 조회 경로를 허용합니다. 여행 생성·관리·링크 경로는 403입니다. 응답은 웹과 같은 필드를 쓰며 상세는 owner/invite 권한자에게만 link의 active·expiresAt을 반환하며, 권한이 없으면 null입니다. 상세에 링크 토큰·초대 URL은 반환하지 않습니다. 멤버·차단 검사는 웹과 같습니다.'
            description += f' rooms:read 기기는 /v1/events에서 {EVENTS_PROTOCOL}로 자기 여행의 변경 영역을 받아 해당 REST 정본을 다시 읽습니다. 이 형식의 devices는 기기 권한 상태를 나타냅니다. 서브프로토콜을 생략한 기존 클라이언트에는 리소스 이름으로 알립니다.'
        if '/device-requests' in path:
            description += ' Native 요청의 원 grant·기기·revision을 저장합니다. 요청 목적 철회는 그 출처의 대기 효과만 종료하며 다른 기기·브라우저 요청은 보존합니다. 이미 배송·실행됐을 수 있는 결과는 unknown으로 남기며 물리 취소를 보장하지 않습니다.'
        operation['description'] = description
        if (method, path) in bodies and (method == 'post' or (method, path) == vote_delete or method != 'get' and (method, path) in NATIVE_TRIP_PLAN):
            base = deepcopy(bodies[(method, path)])
            body = native_body(base, recommendation=path == '/v1/recommendations/query')
            model_name = 'NativeDomain' + operation['operationId'][0].upper() + operation['operationId'][1:] + 'Body'
            models[model_name] = body
            if (method, path) == vote_delete:
                operation['requestBody'] = dict(required=False, description=bodies[vote_delete]['description'],
                    content={'application/json': {}})
            content = operation['requestBody']['content']['application/json']
            content['schema'] = {'$ref': '#/components/schemas/' + model_name} if native_only or (method, path) == vote_delete else dict(oneOf=[base, {'$ref': '#/components/schemas/' + model_name}], description='브라우저는 기존 본문, Native는 같은 본문에 현재 functionalRevision을 명시합니다.')
            old_example = deepcopy(content.get('example'))
            if old_example is not None:
                if native_only:
                    content['example'] = dict(old_example, functionalRevision=1)
                else:
                    content.pop('example', None)
                    content['examples'] = dict(browser=dict(value=old_example), native=dict(value=dict(old_example, functionalRevision=1)))
        if method == 'get' and path == '/v1/social/trips/{trip}/voice-clips':
            operation.setdefault('parameters', []).append(dict(name='cursor', **{'in':'query'}, required=False,
                description='최초 조회는 생략합니다. 이전 응답의 cursor 한 개만 사용합니다.',
                schema=dict(type='string', pattern='^[a-f0-9]{32}:(0|[1-9][0-9]{0,15})$', maxLength=49)))
        if path == '/v1/recommendations/settings':
            operation['responses']['200']['content']['application/json']['schema'] = {'oneOf': [dict(allOf=[{'$ref':'#/components/schemas/RecommendationSettings'}, {'not': {'required':['learning']}}]), {'$ref':'#/components/schemas/NativeRecommendationSettings'}]}
        if path == '/v1/recommendations/query':
            operation['responses']['200']['content']['application/json']['schema'] = {'anyOf': [{'$ref':'#/components/schemas/RecommendationResult'}, {'$ref':'#/components/schemas/NativeRecommendationResult'}]}
        if path.startswith('/v1/social/cautions'):
            operation['responses']['400'] = dict(description='Native 초기 요청 검사에서 잘못된 cursor·중복/알 수 없는 query·URL 자격은 HTTP400 detail=INVALID_REQUEST로 거절합니다. 401/error 형태로 바꾸거나 다른 자격으로 재시도하지 않습니다.', content={'application/json':dict(schema=dict(type='object', properties={'detail':dict(type='string', description='현재 경계의 오류 설명입니다.')}, required=['detail']), examples={'nativeInvalidQuery':{'value':{'detail':'INVALID_REQUEST'}}})})
            if path == '/v1/social/cautions':
                for parameter in operation['parameters']:
                    if parameter['name'] == 'cursor':
                        parameter['description'] = '브라우저와 현재 Native cautions:read가 직전 nextCursor 한 개를 그대로 사용합니다. 첫 페이지는 생략합니다. Native는 cursor 외 query·중복 키·URL 자격을 거절하며 WSS query를 허용하지 않습니다.'
                    elif parameter['name'] == 'eventId':
                        parameter['description'] = '브라우저 소유자 전용 불확실 저장 확인입니다. cursor와 함께 쓰지 않습니다. Native는 이 키를 허용하지 않으며 HTTP400 detail=INVALID_REQUEST입니다.'
                        parameter['x-wegoh-browser-only'] = True
                operation['description'] += ' Native 목록은 query 없는 첫 페이지 또는 단일 불투명 cursor의 다음 페이지입니다. eventId 확인은 브라우저 소유자만 사용합니다.'
    for method, path in [('put','/v1/devices/{device}/reporting-permissions'),
                         ('delete','/v1/devices/{device}/reporting-permissions/{purpose}')]:
        operation = schema['paths'][path][method]
        operation['responses'] = {code:value for code,value in operation['responses'].items() if not code.startswith('2')}
        operation.update(deprecated=True, **{'x-wegoh-executable':False,
            'x-wegoh-terminal-contract':'functional-permissions-required'})
        operation['responses']['409'] = dict(description='이전 저장소는 변경하지 않습니다. 현재 기능 정본을 읽고 사용자가 명시 선택합니다.', content={'application/json':dict(schema=deepcopy(BOUNDARY),example={'detail':'Use current functional permissions'})})
    return schema
