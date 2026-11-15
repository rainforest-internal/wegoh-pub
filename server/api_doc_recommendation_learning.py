"""Explicit optional learning contracts; legacy requests remain rules only."""
from copy import deepcopy
from api_doc_shared import entry, response, obj, s, n, b, ref, READ, BROWSER
from api_doc_recommendations import BODY as RULE_BODY, MODELS as RULE_MODELS, OPS as RULE_OPS

BASE = '/v1/recommendations'
REV = n('현재 계정 학습 목적의 독립 세대. 최초0이며 동의·철회·명시 학습 피드백마다 증가합니다. 설정 revision과 서로 바꿔 쓰지 않습니다.', minimum=0, maximum=2147483647)
SETTINGS_REV = n('GET settings의 현재 revision. 학습 목적 변경도 이 값을 증가시켜 늦은 추천 응답을 무효화합니다.', minimum=0, maximum=2147483647)
STATE = obj({
    'enabled': b('별도 학습 동의와 피드백 사용 목적이 모두 현재 유효하면 true. 기본 false.'),
    'learningRevision': REV,
    'settingsRevision': SETTINGS_REV,
    'modelVersion': dict(type='string', const='personal-logistic-v1', description='서버의 고정 L2 로지스틱 학습 절차 버전. 외부 LLM 또는 논문 LinUCB 구현이라는 뜻이 아닙니다.'),
    'status': s('disabled=동의 없음, collecting-feedback=현재 가용 표본이 아직 학습 조건에 부족함, trained=현재 유효 표본으로 실제 가중치를 계산할 수 있음. 성능·안전성 검증 결과가 아닙니다.', enum=['disabled', 'collecting-feedback', 'trained']),
    'eligibleSamples': n('현재 가용한 동일 id/version/checksum이며 현 동의 세대에 속한 명시 피드백 수. 서로 다른 표본4개 이상·양쪽 응답·두 특징 벡터가 있어야 trained입니다.', minimum=0, maximum=200),
}, '계정 소유자만 읽는 별도 학습 목적 정본. 표본 ID·좌표·가중치를 노출하지 않습니다.')
MODELS = {'RecommendationLearningState': STATE}
COURSE = deepcopy(RULE_MODELS['RecommendedCourse'])
COURSE['properties']['personalModelScore'] = dict(type='number', minimum=0, maximum=1,
    description='실제 학습된 개인 로지스틱 모델의 후보 정렬 값. trained 응답에만 있으며 정확도·추천 성공률·안전 점수가 아닙니다.')
COURSE['properties']['reasons']['items']['enum'].append('learnedFromExplicitCourseFeedback')
COURSE['properties']['reasons']['items']['description'] += ' learnedFromExplicitCourseFeedback=현 동의의 실제 학습 가중치를 이 후보 정렬에 사용함.'
COURSE['description'] = '현재 가용 코스 최대100개에 명시 조건을 적용한 후보. 기존 형식은 규칙 순서이며 별도 학습 요청의 실제 추론만 개인 모델 순서입니다. 공개 상세도 현 공개 제한을 다시 확인합니다.'
MODELS['RecommendedCourse'] = COURSE
RESULT = deepcopy(RULE_MODELS['RecommendationResult'])
RESULT['properties']['algorithm'] = s('기존4필드 또는 학습 표본 부족은 explicit-rules-v1. 명시 learningRevision과 유효 학습 표본으로 실제 추론한 경우만 personal-logistic-v1.', enum=['explicit-rules-v1', 'personal-logistic-v1'])
RESULT['properties']['aiUsed'] = b('현재 별도 목적과 요청 세대가 맞고 실제 학습 모델로 코스 순서를 계산한 경우에만 true. 휴게소 정렬은 계속 명시 시설·거리 규칙입니다.')
QUERY_LEARNING = deepcopy(STATE)
QUERY_LEARNING['properties'].pop('enabled')
QUERY_LEARNING['properties'].pop('settingsRevision')
QUERY_LEARNING['required'] = ['learningRevision', 'modelVersion', 'status', 'eligibleSamples', 'aiUsed']
QUERY_LEARNING['properties']['status'] = s('collecting-feedback는 현재 유효 표본 부족, trained는 현 표본으로 학습한 모델 상태입니다. 후보가 없어 추론하지 않았을 때도 모델 상태는 trained일 수 있으므로 이번 사용은 aiUsed로 확인합니다.', enum=['collecting-feedback','trained'])
QUERY_LEARNING['properties']['aiUsed'] = deepcopy(RESULT['properties']['aiUsed'])
QUERY_LEARNING['properties']['scoreMeaning'] = s('trained일 때만 있는 모델 정렬 값의 한계 설명. 성능·안전 보장이 아닙니다.')
RESULT['properties']['learning'] = QUERY_LEARNING
RESULT['properties']['unsupported']['properties']['modelTraining'] = b('기존4필드 규칙 요청이면 true. 별도 학습 요청이면 false로 지원 여부만 표시하며 실제 사용 여부는 aiUsed와 learning.status로 구분합니다.')
RESULT['description'] = '기존 규칙 또는 별도 명시 목적의 개인 학습으로 코스를 정렬합니다. GPS·방문·사진·연료·의료·가격·교통은 학습 특징으로 사용하지 않습니다.'
MODELS['RecommendationResult'] = RESULT
FEEDBACK = deepcopy(RULE_MODELS['RecommendationSettings'])
FEEDBACK['properties']['learningRevision'] = deepcopy(REV)
FEEDBACK['description'] = '기존5필드 피드백은 규칙 전용 정본입니다. 학습 세대를 명시한 코스 피드백 성공일 때만 새 learningRevision이 추가됩니다.'
MODELS['RecommendationFeedbackResult'] = FEEDBACK

PUT_BODY = dict(obj({'revision': REV, 'recommendationRevision': SETTINGS_REV,
    'consent': dict(type='boolean', const=True, description='사용자가 이번에 확인한 별도 학습 동의. 예제 true는 유효 계약 값이며 Try editor는 자동 동의하지 않는 false로 시작합니다.')},
    '피드백 사용 목적을 먼저 켠 뒤 별도 학습에 명시 동의합니다. 위치·개인 기록을 학습에 쓰는 동의가 아닙니다.'), additionalProperties=False)
BODY = {('put', BASE+'/learning'): PUT_BODY}
for method, suffix in [('post', '/query'), ('post', '/feedback')]:
    legacy = deepcopy(RULE_BODY[(method, BASE+suffix)])
    learned = deepcopy(legacy)
    learned['properties']['learningRevision'] = deepcopy(REV)
    learned['required'].append('learningRevision')
    if suffix == '/feedback':
        learned['properties']['kind'] = dict(type='string', const='course', description='명시 학습 세대를 보낸 피드백은 현재 가용한 공개 코스만 허용합니다. 휴게소는 기존 규칙 형식으로만 응답합니다.')
    learned['description'] += ' 현재 별도 학습 동의의 learningRevision을 명시한 확장 형식입니다.'
    BODY[(method, BASE+suffix)] = {'oneOf': [legacy, learned],
        'description': '기존 형식은 규칙 전용입니다. 새 세대 필드를 추가한 명시 요청만 학습 목적을 사용하며, 오래된 세대는409로 거절합니다.'}

OPS = {}
def add(method, summary, sequence, effects, errors, example=None):
    OPS[(method, BASE+'/learning')] = entry('16 내 취향 추천', summary,
        (READ if method=='get' else BROWSER)+' 브라우저 본인 계정만 사용하며 Native 호스트는404입니다.',
        sequence, effects,
        '409는 learning/settings 두 정본을 다시 읽고 사용자가 다시 선택합니다. 응답 유실 때 자동 동의·재전송하지 않습니다. 철회는 revision 없이 가능하며 다시 GET하여 확인합니다.',
        {'200': response(ref('RecommendationLearningState'), '현재 별도 학습 목적의 정본. trained는 추천 성능 또는 실차 검증 완료를 뜻하지 않습니다.')},
        errors, example=example, notes='외부 모델/네트워크를 사용하지 않습니다. 현재 가용 코스의 장소 수·공개 장소 사이 직선 범위와 이번 동의 이후 명시한 좋아요/관심없음만 사용합니다.')
add('get', '본인 추천 학습 목적과 현재 표본 상태 읽기',
    '개인 로그인→settings GET→이 GET. 기본 disabled를 확인하고 목적을 자동 활성화하지 않습니다.',
    '현재 유효 가용 표본의 상태만 계산하며 새 동의·학습 피드백을 생성하지 않습니다.', ['401','403','404','503'])
add('put', '별도 추천 학습 목적에 명시 동의',
    'settings의 useFeedback를 별도로 저장→두 GET의 현재 revision 확인→사용자 확인 후 consent=true. 처음 동의 또는 철회 후 동의는 표본0에서 시작합니다.',
    '암호화된 새 동의 세대와 빈 표본을 저장하고 settings revision을 증가시킵니다. 이미 켜진 현재 목적의 반복 동의는 표본을 지우지 않습니다. 예전 규칙 피드백은 가져오지 않습니다.',
    ['400','401','403','404','408','409','413','429','503'], {'revision':0,'recommendationRevision':1,'consent':True})
add('delete', '추천 학습 동의와 저장 표본 철회',
    '사용자가 학습 사용 중지→이 DELETE→두 정본을 다시 읽습니다. 기존 학습 세대의 늦은 요청은 거절됩니다.',
    '표본과 동의 세대를 암호화 tombstone으로 교체하고 settings revision을 증가시킵니다. 기존 여행기록·코스·규칙 피드백은 삭제하지 않습니다.', ['401','403','404','429','503'])
OPS[('put', BASE+'/learning')]['errorDescriptions'] = {'408':'본문 수신5초 초과입니다. 정본을 다시 확인한 뒤 사용자가 재시도합니다.'}

OVERRIDES = {key: deepcopy(RULE_OPS[key]) for key in [('post', BASE+'/query'), ('post', BASE+'/feedback')]}
OVERRIDES[('post', BASE+'/query')]['sequence'] += ' 별도 학습을 사용하려면 learning GET의 현재 learningRevision을 추가합니다. 기존 형식은 동의가 켜져 있어도 규칙 전용입니다.'
OVERRIDES[('post', BASE+'/query')]['effects'] += ' 학습 요청은 현 동의 세대와 동일 게시 버전의 표본으로 실제 L2 로지스틱 가중치를 계산하고 코스 후보만 다시 정렬합니다. 표본 부족은 aiUsed=false와 collecting-feedback으로 응답하며 모델 순위를 꾸미지 않습니다.'
OVERRIDES[('post', BASE+'/query')]['notes'] = '개인 학습은 비민감 공개 코스 특징의 제한된 로컬 모델이며 임상·연료·가격·교통 예측이 아닙니다. 학습 상태와 aiUsed를 구분합니다.'
OVERRIDES[('post', BASE+'/feedback')]['sequence'] += ' 별도 학습 피드백은 현재 learningRevision을 추가하고 kind=course만 보냅니다. 기존5필드는 학습 동의 이후에도 규칙에만 사용합니다.'
OVERRIDES[('post', BASE+'/feedback')]['effects'] = '현재 가용한 정확 코스 버전/checksum과 서버가 다시 구한 공개 특징을 이번 동의 세대에 암호화 저장합니다. 같은 id/version은 이전 label을 대체하며 최대200개입니다. 사후 공개 제한된 표본은 모델에서 제외되고 새 버전으로 자동 이동하지 않습니다. 기존5필드는 종전 규칙 피드백만 대체합니다.'
OVERRIDES[('post', BASE+'/feedback')]['responses']['200'] = response(ref('RecommendationFeedbackResult'), '새 설정 revision과, 학습 형식 성공인 경우에만 새 learningRevision입니다.')
