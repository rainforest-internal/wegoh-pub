"""Contest reviewer /reviewer contracts; documentation only, never grants access.

The routes are registered with include_in_schema=False because they live outside
/v1. Every mounted /reviewer route must have an authored operation here.
"""
import copy

from api_doc_models import obj, s, b, nullable

TAG = '심사자 00 즉시 로그인'
TAG_TEXT = ('허용한 이메일 도메인(WEGOH_REVIEWER_EMAIL_DOMAINS)과 정확히 일치하는 주소로 creator 심사자 계정을 시작합니다. '
            '쿠키는 /reviewer 아래에서만 보내지고 차량 연결 확인·승인·거절만 할 수 있습니다.')
SECURITY = 'ReviewerSession'
METHODS = ('get', 'post', 'put', 'patch', 'delete')
CODE = {'name': 'user_code', 'in': 'path', 'required': True, 'description': '차량 화면의 8자 연결 코드.',
        'schema': {'type': 'string', 'pattern': '^[A-HJ-NP-Z2-9]{8}$'}}
ASSET = {'name': 'name', 'in': 'path', 'required': True, 'description': '심사자 화면이 쓰는 고정 파일 이름.',
         'schema': {'type': 'string', 'enum': ['reviewer.js', 'pleos-tokens.css', 'studio.css', 'enroll.css',
                                               'favicon.svg', 'native-access-wire.json']}}
SESSION = obj({'authenticated': b('심사자 세션이 유효한지.'),
               'user': nullable(obj({'displayName': s('표시 이름.'), 'role': s('항상 creator.')}, '심사자 계정.')),
               'csrfToken': nullable(s('변경 요청의 X-WegoH-CSRF 값.'))}, '심사자 세션 상태.')
ERRORS = {'400': '요청 형식이 다릅니다.', '401': '심사자 세션이 없거나 만료·위조됐습니다.',
          '403': '허용 도메인이 아니거나 팀 명단 주소, Origin·CSRF 불일치입니다.', '404': '기능이 꺼져 있거나 없는 경로입니다.',
          '409': '연결 상태가 바뀌었습니다.', '410': '연결 코드가 만료됐습니다.', '413': '본문이 너무 큽니다.',
          '429': '빈도 제한을 넘었습니다.', '503': '일시적으로 처리할 수 없습니다.'}


def _json(schema, description='처리 결과.'):
    return {'200': {'description': description, 'content': {'application/json': {'schema': schema}}}}


OPS = {
    ('get', '/reviewer'): dict(summary='심사자 화면', auth=False, params=[CODE | {'in': 'query', 'required': False}],
        ok={'200': {'description': '이메일 입력과 연결 코드·QR 링크 입력, 연결 승인 화면.', 'content': {'text/html': {'schema': s('HTML')}}}},
        errors=('404',), text='user_code query가 있으면 코드 칸을 미리 채웁니다. QR 링크 전체를 붙여 넣어도 코드를 뽑습니다.'),
    ('get', '/reviewer/assets/{name}'): dict(summary='심사자 화면 고정 파일', auth=False, params=[ASSET],
        ok={'200': {'description': '고정 정적 파일.'}}, errors=('404',), text='목록 밖 파일은 404입니다.'),
    ('get', '/reviewer/v1/session'): dict(summary='심사자 세션 확인', auth=False, ok=_json(SESSION),
        errors=('400', '403', '429'), text='쿠키가 없거나 무효이면 authenticated=false로 200을 돌려줍니다.'),
    ('post', '/reviewer/v1/login'): dict(summary='심사자 이메일 즉시 로그인', auth=False, ok=_json(SESSION),
        body=obj({'email': s('허용 도메인과 정확히 일치하는 주소. 하위 도메인 불허, 로컬부는 RFC 5322 dot-atom.')}, '심사자 로그인 요청.'),
        errors=('400', '403', '413', '429', '503'),
        text=('같은 Origin이 필요합니다. 주소별 subject는 `reviewer:`+이메일이며 Access로 가입한 같은 주소 계정과 별개입니다. '
              '팀 명단 주소는 거절합니다. 성공하면 HttpOnly·Secure·SameSite=Strict·Path=/reviewer 쿠키(7일, 서버 비밀 HMAC 서명)를 줍니다. '
              'IP별 분당 10회, 전체 분당 60회로 제한합니다.')),
    ('delete', '/reviewer/v1/session'): dict(summary='심사자 로그아웃', auth=False, ok=_json(SESSION),
        errors=('403', '429'), text='같은 Origin이 필요하며 쿠키를 지웁니다.'),
    ('get', '/reviewer/v1/connections/{user_code}'): dict(summary='차량 연결 정보 확인', auth=True, params=[CODE],
        base=('get', '/v1/connections/{user_code}'), errors=('400', '401', '403', '404', '410', '429', '503'),
        text='웹 차량 연결 확인과 같은 처리이며 신원만 심사자 쿠키에서 가져옵니다.'),
    ('post', '/reviewer/v1/connections/{user_code}'): dict(summary='차량 연결 승인', auth=True, params=[CODE], mutate=True,
        base=('post', '/v1/connections/{user_code}'), errors=('400', '401', '403', '404', '409', '410', '413', '429', '503'),
        text='웹 차량 연결 승인과 같은 본문·결과입니다. 같은 Origin과 X-WegoH-CSRF가 필요합니다.'),
    ('delete', '/reviewer/v1/connections/{user_code}'): dict(summary='차량 연결 거절·해제', auth=True, params=[CODE], mutate=True,
        base=('delete', '/v1/connections/{user_code}'), errors=('400', '401', '403', '404', '409', '429', '503'),
        text='웹 차량 연결 거절과 같은 본문·결과입니다. 같은 Origin과 X-WegoH-CSRF가 필요합니다.'),
}


def mounted_reviewer_operations(app):
    from fastapi.routing import APIRoute, iter_route_contexts
    found = set()
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if isinstance(route, APIRoute) and (route.path == '/reviewer' or route.path.startswith('/reviewer/')):
            found.update((method.lower(), route.path) for method in route.methods - {'HEAD', 'OPTIONS'})
    return found


def apply_reviewer_documentation(original, auth, app=None):
    schema = copy.deepcopy(original)
    if app is not None:
        mounted = mounted_reviewer_operations(app)
        missing = sorted(mounted - set(OPS))
        if missing:
            raise RuntimeError('Mounted reviewer route lacks authored documentation: ' + repr(missing))
        selected = [key for key in OPS if key in mounted]
    else:
        selected = list(OPS)
    for method, path in selected:
        doc = OPS[(method, path)]
        if doc.get('base'):
            base = schema['paths'].get(doc['base'][1], {}).get(doc['base'][0])
            if base is None:
                continue
            responses = {code: copy.deepcopy(value) for code, value in base['responses'].items() if code.startswith('2')}
            body = copy.deepcopy(base.get('requestBody'))
        else:
            responses, body = copy.deepcopy(doc['ok']), None
            if doc.get('body'):
                body = {'required': True, 'content': {'application/json': {'schema': copy.deepcopy(doc['body'])}}}
        for code in doc['errors']:
            responses[code] = {'description': ERRORS[code], 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/ApiError'}}}}
        operation = {
            'tags': [TAG], 'summary': doc['summary'],
            'description': '### 용도\n' + doc['summary'] + '\n\n### 선행 조건·계정\n' +
                           ('POST /reviewer/v1/login으로 받은 심사자 쿠키가 필요합니다.' if doc['auth'] else '공개 웹 호스트의 /reviewer 경로로 보냅니다.') +
                           '\n\n### 동작\n' + doc['text'],
            'operationId': 'reviewer_' + method + '_' + path.strip('/').replace('/', '_').replace('{', '').replace('}', ''),
            'responses': responses, 'security': [{SECURITY: []}] if doc['auth'] else [],
            'servers': [{'url': auth.public_origin, 'description': '공개 웹 호스트의 /reviewer 경로.'}],
            'x-wegoh-surface': 'browser', 'x-wegoh-native-access': False, 'x-wegoh-executable': False,
            'x-wegoh-configured': bool(getattr(getattr(auth, 'reviewer', None), 'enabled', False)),
            'x-wegoh-documentation': {'authoring': 'explicit-operation-contract',
                                      'source': 'reviewer_login.py handler; this document never grants access.'},
        }
        if doc.get('params'):
            operation['parameters'] = copy.deepcopy(doc['params'])
        if body:
            operation['requestBody'] = body
        if method in schema['paths'].get(path, {}):
            raise RuntimeError('Reviewer operation shadows an existing operation: ' + method + ' ' + path)
        schema['paths'].setdefault(path, {})[method] = operation
    components = schema.setdefault('components', {})
    components.setdefault('securitySchemes', {})[SECURITY] = {
        'type': 'apiKey', 'in': 'cookie', 'name': '__Secure-wegoh_reviewer',
        'description': '심사자 즉시 로그인 쿠키(7일, HMAC 서명, Path=/reviewer). /reviewer 밖 API에는 쓸 수 없습니다.'}
    if selected and not any(tag.get('name') == TAG for tag in schema.get('tags', [])):
        schema.setdefault('tags', []).append({'name': TAG, 'description': TAG_TEXT})
    coverage = schema.get('x-wegoh-documentation-coverage')
    if coverage is not None:
        coverage['reviewerOperations'] = len(selected)
        coverage['operations'] = sum(method in METHODS for item in schema['paths'].values() for method in item)
    return schema
