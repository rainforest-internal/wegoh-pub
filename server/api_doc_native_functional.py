"""Authored OAS documentation for explicit functional consent, not an auth bypass."""
import copy
from native_functional_defaults import ACCOUNT_PURPOSES, INITIAL_PURPOSES
from native_functional_policy import WIRE
TAG='17 기기 기능 공유'
RECEIVER_PATH = '/v1/device/command-receiver'
RAW_DEFAULTS = '기능 설정 이력이 없는 차량의 초기 저장값은 ' + ', '.join(INITIAL_PURPOSES) + '입니다.'
ACCOUNT_ACCESS = '현재 연결에는 로그인으로 사용하는 계정 기능 ' + ', '.join(sorted(ACCOUNT_PURPOSES)) + '도 포함됩니다.'
ID={'type':'string','pattern':'^[a-f0-9]{32}$','minLength':32,'maxLength':32}
FIELDS={
 'authorizationVersion':{'type':'integer','const':1,'description':'단일 공개 인증 계약의 정수 1입니다. 내부 저장·암호화 버전과 구분합니다.'},
 'deviceId':dict(ID,description='이 개인 연결의 기기 ID입니다. 다른 기기·설치 키·공개 코드를 대신 넣을 수 없습니다.'),
 'grantId':dict(ID,description='직전 GET에서 받은 현재 개인 grant ID입니다. 같은 기기의 이전 계정 grant도 거절합니다.'),
 'revision':{'type':'integer','minimum':0,'maximum':WIRE['revisionMaximum'],'description':'기능 동의의 현재 revision입니다. 기본 scope·credential epoch와 별개이며, PUT은 직전 GET 값과 정확히 같아야 한 번 반영됩니다.'},
 'expiresAt':{'type':'integer','minimum':0,'description':'기능 동의가 유효한 원 개인 연결의 Unix UTC 초 기한입니다. 변경·갱신으로 연장하지 않습니다.'},
 'approvedPurposes':{'type':'array','items':{'type':'string','enum':[row['id']for row in WIRE['purposeRegistry']]},'uniqueItems':True,'maxItems':len(WIRE['purposeRegistry']),'description':'현재 사용할 수 있는 기능 ID의 정렬된 목록입니다. ' + ACCOUNT_ACCESS + ' 브라우저에서 저장할 때 명령 수신 상태는 직전 조회와 같아야 합니다.'},
 'functionalDisclosureVersion':{'type':'integer','const':WIRE['disclosureVersion'],'description':'폰에서 실제 읽은 기능 설명의 개정 번호입니다. 공개 인증 버전과 별개입니다.'},
 'functionalDisclosureSha256':{'type':'string','const':WIRE['disclosureSha256'],'description':'현재 기능 설명 전체의 canonical SHA256입니다. 오래된 설명의 PUT은 409이며, 새 GET 내용을 읽기 전에 자동 재승인하면 안 됩니다.'}}
def obj(properties):return dict(type='object',properties=properties,required=list(properties),additionalProperties=False)
def ref(name):return {'$ref':'#/components/schemas/'+name}
ERROR=obj({'authorizationVersion':copy.deepcopy(FIELDS['authorizationVersion']),'error':{'type':'string','minLength':1,'description':'고정된 오류 코드이며 요청·계정·자격 내용을 반사하지 않습니다.'}})
BOUNDARY=obj({'detail':{'type':'string','description':'기존 인증·Origin·CSRF 경계의 오류입니다. 다른 계정 자격으로 자동 재시도하지 않습니다.'}})
def example(revision=1,purposes=None):
 return dict(authorizationVersion=1,deviceId='d'*32,grantId='c'*32,revision=revision,expiresAt=2000000000,approvedPurposes=sorted(ACCOUNT_PURPOSES.union(INITIAL_PURPOSES if purposes is None else purposes)),functionalDisclosureVersion=WIRE['disclosureVersion'],functionalDisclosureSha256=WIRE['disclosureSha256'])
EXPLANATION={
 'nativeGet':('내 기기 기능 공유 확인','현재 기기 앱이 같은 인증서 mTLS와 현재 opaque Bearer로 조회합니다. 브라우저 쿠키·운영 키·URL 자격은 사용할 수 없습니다.','기본 연결의 device:self:manage가 필요합니다. 현재 grant·설치 키·slot·credential epoch·원 기한을 다시 확인하며, 다른 기기 ID를 입력받지 않습니다.',RAW_DEFAULTS + ' 최초 설정은 revision 1입니다. ' + ACCOUNT_ACCESS,'기능 표시 전에 이 정본을 확인합니다. 401/403/410은 원 권위를 확인하고, 조회 실패를 승인 상태로 간주하지 않습니다.'),
 'ownerGet':('내 기기의 기능 공유 설정 보기','본인 폰 웹의 현재 로그인 계정이 서명된 Access와 개인 세션으로 조회합니다.','경로의 기기를 현재 계정이 소유하고 현재 grant·설치 slot이 살아 있어야 합니다. 다른 소유자·만료·철회 기기는 같은 404로 거절합니다.','기기의 현재 기능 목록과 revision을 반환합니다. ' + ACCOUNT_ACCESS,'이 GET의 grantId/revision과 현재 설명을 표시한 뒤, 사용자가 선택한 경우에만 PUT합니다. GET 성공을 기능 전체의 실행·차량 권한 승인으로 표시하지 않습니다.'),
 'ownerPut':('내 기기의 기능 공유 선택 저장','본인 폰 웹이 현재 Access·개인 세션·해당 세션 CSRF를 같은 요청에 보냅니다. Native Bearer는 이 소유자 승인 요청을 대신할 수 없습니다.','직전 GET의 정확한 grantId·revision·설명 버전/hash와 사용자의 명시 선택이 필요합니다. 서버는 본문 수신 뒤에도 현재 브라우저 세션·소유자·기한을 재확인합니다.','기능 동의만 암호화 저장하고 revision을 한 번 증가시킵니다. 기본 4개 scope·개인 token·credential epoch·원 grant 기한을 넓히거나 연장하지 않습니다. 같은 revision을 다시 보내면 409입니다.','응답이 유실되면 GET으로 결과를 확인합니다. 409에서 새 revision으로 자동 재승인하지 말고 변경된 내용과 설명을 다시 보여줍니다. FUNCTIONAL_REVISION_EXHAUSTED라면 카운터를 초기화하지 않고 변경을 중단합니다. 브라우저는 명령 수신 상태를 바꿀 수 없습니다. device-commands:receive 값을 바꾸는 PUT은 403입니다.'),
 'ownerDelete':('내 기기의 기능 하나 끄기','본인 폰 웹이 현재 Access·개인 세션·해당 세션 CSRF로 명시 해제합니다.','현재 본인 기기와 알려진 purpose ID만 대상입니다. 원 개인 연결·scope·다른 기기 권한을 대신 해제하지 않습니다.','계정 기본 기능의 DELETE는 현재 목록을 반환합니다. 웹에서 변경 가능한 기능은 목록에서 제거합니다. 명령 수신을 대상으로 한 DELETE는 403입니다.','응답 유실은 GET으로 확인할 수 있습니다. 404이면 소유자·기한·기능 ID를 다시 확인합니다. 409 FUNCTIONAL_REVISION_EXHAUSTED는 GET 재조회로 해소되지 않으므로 카운터 초기화나 자동 재승인 없이 변경을 중단합니다. 로컬 표시 중단과 서버 해제 확인을 구분합니다.')}
FAILURES={400:'잘못된 필드·중복 JSON·정렬·타입·ID입니다. 본문을 현재 명세와 대조하고 같은 잘못된 요청을 반복하지 않습니다.',401:'현재 개인 자격 또는 브라우저 세션이 유효하지 않습니다. 다른 자격·퇴역 API로 우회하지 않습니다.',403:'현재 인증·Origin·CSRF 또는 동의가 부족합니다. 명시 동의를 추정하거나 관리자 역할로 확대하지 않습니다.',404:'기능이 꺼져 있거나 현재 본인 기기/경로/목적을 사용할 수 없습니다. 다른 소유자 여부는 공개하지 않습니다.',408:'본문 수신 제한 5초를 넘긴 REQUEST_TIMEOUT입니다. 현재 GET으로 정본을 확인하고 자동 승인 재전송은 하지 않습니다.',409:'grant·revision·설명 지문이 바뀌면 GET으로 재확인하고 사용자 선택을 다시 확인합니다. FUNCTIONAL_REVISION_EXHAUSTED는 revision 한도이므로 GET이나 같은 PUT으로 해소되지 않습니다. 카운터를 초기화하거나 새 동의를 자동 생성하지 말고 변경을 중단합니다.',410:'원 개인 연결이 만료됐습니다. 같은 token이나 기능 변경으로 기한을 연장하지 않습니다.',413:'본문은 최대 12288바이트입니다. 기능 동의 이외의 자료를 보내지 않습니다.',429:'요청 제한입니다. 안내된 대기 뒤 현재 상태를 조회합니다.',503:'기능 동의의 무결성 또는 저장소를 확인할 수 없습니다. 승인 상태로 간주하지 않습니다.'}

MODELS={
 'NativeFunctionalSnapshot':obj({key:copy.deepcopy(FIELDS[key])for key in WIRE['apis']['nativeGet']['responseFields']}),
 'NativeFunctionalConsent':obj({key:copy.deepcopy(FIELDS[key])for key in WIRE['apis']['ownerPut']['requestFields']}),
 'NativeFunctionalError':ERROR}
OPS={}
for key,api in WIRE['apis'].items():
 summary,actor,precondition,effect,retry=EXPLANATION[key]
 OPS[(api['method'].lower(),api['path'])]=dict(tag=TAG,summary=summary,prerequisites=actor+' '+precondition,sequence='현재 GET으로 기기와 기능 동의를 확인한 뒤 명시한 요청만 전송합니다.',effects=effect,retry=retry,notes='기능 권한은 기본 계정 scope·credential epoch·원 만료와 별도로 검사합니다.',responses={'200':{'description':'현재 기능 동의 정본입니다.','content':{'application/json':{'schema':ref('NativeFunctionalSnapshot')}}}},errors=['400','401','403','404','503'],example=None)

RECEIVER_UPDATE = obj({
    'grantId': FIELDS['grantId'],
    'revision': {'type': 'integer', 'minimum': 1, 'maximum': WIRE['revisionMaximum'],
                 'description': '직전 GET으로 확인한 이 차량의 리모컨 수신 revision입니다. 다른 기능 동의의 revision과 독립적입니다.'},
    'enabled': {'type': 'boolean', 'description': '이 차량이 명령을 수신하면 true, 수신을 일시 중지하면 false입니다.'},
})
MODELS['CommandReceiverState'] = obj({'deviceId': FIELDS['deviceId'], **RECEIVER_UPDATE['properties']})

for method, summary, effect in (
    ('get', '이 차량의 리모컨 수신 상태 확인', '현재 연결의 수신 여부와 다음 변경에 사용할 grantId와 revision을 반환합니다.'),
    ('put', '이 차량의 리모컨 수신 중지 또는 재개',
     '수신 중지는 이 차의 대기 명령을 취소하고 이미 전달한 명령의 결과를 미확정으로 남깁니다. '
     '동승자의 여행별 승인은 유지됩니다. 수신을 재개해도 지난 명령이나 철회된 승인이 복구되지는 않습니다.'),
):
    OPS[(method, RECEIVER_PATH)] = dict(
        tag=TAG, summary=summary, prerequisites='현재 차량의 mTLS 인증서, 개인 Bearer와 device:self:manage 권한이 필요합니다.',
        sequence='차량 앱은 GET으로 수신 상태를 확인합니다. 사용자가 스위치를 바꾸면 직전 grantId와 revision, 선택한 enabled를 PUT합니다.',
        effects=effect, retry='응답 유실이나 409 충돌 시 현재 상태를 GET으로 다시 읽습니다.',
        notes='수신이 꺼진 차량도 이 API로 자기 상태를 조회하고 켤 수 있습니다.',
        responses={'200': {'description': '인증된 차량 한 대의 수신 상태입니다.',
                           'headers': {'Cache-Control': {'schema': {'type': 'string'}, 'description': 'private, no-store'}},
                           'content': {'application/json': {'schema': ref('CommandReceiverState')}}}},
        errors=['400','401','403','404','410','429','503'] + (['408','409','413'] if method == 'put' else []),
        example={'grantId': 'c' * 32, 'revision': 1, 'enabled': False} if method == 'put' else None,
    )

from api_doc_control_support import PATH as SUPPORT_PATH, RESULT as SUPPORT_RESULT
OPS[('put', SUPPORT_PATH)] = dict(
 tag=TAG, summary='현재 차량의 조작 지원 범위 보고',
 prerequisites='현재 차량의 mTLS·개인 Bearer, 수신 목적과 현재 기능·수신 revision이 필요합니다.',
 sequence='실제 SDK에서 지원 명세만 읽고 보고합니다. 현재 설정값·SDK 오류·기기·계정·시간을 보내지 않습니다.',
 effects='암호화 기능 payload의 짧은 기한 지원 힌트만 갱신합니다. 동의 revision·기기 이벤트·실제 설정값은 바꾸지 않습니다.',
 retry='만료 또는 연결·권한 변경 시 unknown입니다. 거절을 새 권한으로 자동 재승인하지 않습니다.',
 notes='고정 명령·차주 허용과 교집합으로만 표시하며 실제 실행 전에 기존 권한·SDK 검증을 반복합니다.',
 responses={'200': {'description': '서버 시각의 지원 힌트 접수입니다.', 'content': {'application/json': {'schema': SUPPORT_RESULT}}}},
 errors=['400','401','403','404','408','409','413','429','503'], example=None)

from api_doc_client_reports import PATH as REPORT_PATH, RESULT as REPORT_RESULT, OPERATION as REPORT_OPERATION
OPS[('post', REPORT_PATH)] = dict(
 tag=TAG, **{key: REPORT_OPERATION[key] for key in ('summary','prerequisites','sequence','effects','retry','notes')},
 responses={'200': {'description': '보고 접수입니다.', 'content': {'application/json': {'schema': REPORT_RESULT}}}},
 errors=['400','401','404','408','413','429','503'], example=None)

def apply_native_functional_documentation(original,auth):
 schema=copy.deepcopy(original);models=schema.setdefault('components',{}).setdefault('schemas',{})
 models['NativeFunctionalSnapshot']=obj({key:copy.deepcopy(FIELDS[key])for key in WIRE['apis']['nativeGet']['responseFields']})
 legacy=copy.deepcopy(models['NativeFunctionalSnapshot'])
 legacy['properties']['functionalDisclosureVersion']['const']=2
 legacy['properties']['functionalDisclosureSha256']['const']='ec92f07e28aa015408006bd5430f9d9b440870238fabc9393c176c263d4e6657'
 legacy['properties']['approvedPurposes']['items']['enum']=next(row['purposeIds'] for row in WIRE['previousDisclosures'] if row['version']==2)
 legacy['properties']['approvedPurposes']['maxItems']=19
 models['NativeFunctionalLegacySnapshot']=legacy
 previous=copy.deepcopy(models['NativeFunctionalSnapshot'])
 frozen=next(row for row in WIRE['previousDisclosures'] if row['version']==3)
 previous['properties']['functionalDisclosureVersion']['const']=3
 previous['properties']['functionalDisclosureSha256']['const']=frozen['sha256']
 models['NativeFunctionalV3Snapshot']=previous
 current=copy.deepcopy(models['NativeFunctionalSnapshot'])
 current['properties']['approvedDisclosureVersion']={'anyOf':[{'type':'integer','minimum':1},{'type':'null'}],
  'description':'실제 원문 저장 승인의 설명 버전. 표시용 functionalDisclosureVersion과 별개. 현재 점수 기능 승인과 함께 확인하며 inactive이면 null.'}
 current['required'].append('approvedDisclosureVersion')
 models['NativeFunctionalCurrentPresentation']=current
 v4=copy.deepcopy(current);frozen=next(row for row in WIRE['previousDisclosures'] if row['version']==4)
 v4['properties']['functionalDisclosureVersion']['const']=4
 v4['properties']['functionalDisclosureSha256']['const']=frozen['sha256']
 v4['properties']['approvedPurposes']['items']['enum']=frozen['purposeIds']
 v4['properties']['approvedDisclosureVersion']={'anyOf':[{'type':'integer','enum':[1,2,3,4]},{'type':'null'}],
  'description':'고정된 v4 표시는 v4 이하 설명 승인만 그대로 보이고, 이후 설명 승인은 null로 숨깁니다.'}
 models['NativeFunctionalV4Snapshot']=v4
 models['NativeFunctionalConsent']=obj({key:copy.deepcopy(FIELDS[key])for key in WIRE['apis']['ownerPut']['requestFields']})
 models['NativeFunctionalError']=ERROR
 tags=schema.setdefault('tags',[])
 if not any(tag.get('name')==TAG for tag in tags):tags.append(dict(name=TAG,description='본인의 현재 기기에 별도 기능 동의를 설정합니다. 기본 scope·기한·실차 권한을 확장하는 API가 아닙니다.'))
 feature=getattr(auth,'functional_access',None);enabled=bool(feature and feature.enabled and feature.base.enabled)
 for key,api in WIRE['apis'].items():
  path=api['path'];method=api['method'].lower()
  if method not in schema.get('paths',{}).get(path,{}):continue
  operation=schema['paths'][path][method];summary,actor,precondition,effect,retry=EXPLANATION[key]
  native=key=='nativeGet'
  operation.update(operationId='nativeFunctional'+key[0].upper()+key[1:],summary=summary,tags=[TAG],description='**호출 주체** '+actor+'\n\n**선행 조건** '+precondition+'\n\n**부작용** '+effect+'\n\n**실패·재시도** '+retry,security=[{'NativeMTLS':[],'DeviceBearer':[]}]if native else[dict({'CloudflareAccess':[],'TeamSession':[]},**({'CurrentSessionCSRF':[]}if method!='get'else{}))],servers=[{'url':auth.native_origin if native else auth.public_origin,'description':'Native TLS1.3 mTLS AND opaque Bearer'if native else'본인 웹 Access AND 개인 세션; 변경은 현재 CSRF도 필요'}],**{'x-wegoh-native-access':native,'x-wegoh-executable':enabled and not native,'x-wegoh-feature-enabled':enabled,'x-wegoh-functional-purpose-count':len(WIRE['purposeRegistry'])})
  parameters=[]
  if native:
   parameters.append(dict(name='X-WegoH-Functional-Presentation',**{'in':'header'},required=False,
    description='응답 표시 형식만 선택합니다. 생략/2는 고정 v2 설명·19개 목적 부분집합, 3·4는 고정된 종전 v3·v4, 5는 현재 설명입니다. 내부 권한·실제 동의 버전·revision·기한은 바꾸지 않으며 중복/미등록 값은 400입니다.',
    schema=dict(type='string',enum=['2','3','4','5'],default='2'),example='5'))
  if '{device}'in path:parameters.append(dict(name='device',**{'in':'path'},required=True,description=FIELDS['deviceId']['description'],schema=dict(ID,description=FIELDS['deviceId']['description']),example='d'*32))
  if '{purpose}'in path:parameters.append(dict(name='purpose',**{'in':'path'},required=True,schema={'type':'string','enum':[r['id']for r in WIRE['purposeRegistry']]},description='현재 기능 목록의 정확한 ID입니다. 기본 scope 문자열이 아닙니다.',example='rooms:read'))
  operation['parameters']=parameters
  if key=='ownerPut':
   body=example(1);body={k:v for k,v in body.items()if k not in ('deviceId','expiresAt')}
   operation.pop('x-wegoh-body-contract',None)
   operation['requestBody']=dict(required=True,description='직전 GET과 현재 설명을 읽은 본인의 선택입니다. 알 수 없는 필드·중복 키는 거절합니다.',content={'application/json':{'schema':ref('NativeFunctionalConsent'),'example':body}})
  else:operation.pop('requestBody',None)
  success=example(2,[])if key=='ownerDelete'else example()
  responses={'200':dict(description='현재 기능 동의 정본입니다. HTTP200은 개별 도메인 실행·실차 지원을 대신하지 않습니다.',headers={'Cache-Control':{'schema':{'type':'string'},'description':'private, no-store; 개인 동의 응답은 공유 캐시에 저장하지 않습니다.'}},content={'application/json':{'schema':ref('NativeFunctionalSnapshot'),'example':success}})}
  if native:
   responses['200']['content']['application/json']['schema']={'oneOf':[ref('NativeFunctionalCurrentPresentation'),ref('NativeFunctionalLegacySnapshot'),ref('NativeFunctionalV3Snapshot'),ref('NativeFunctionalV4Snapshot')]}
   responses['200']['description'] += ' 예시는 명시 header 5입니다. 이전 응답 표시는 교차 차량 공개 권한을 승인하지 않습니다.'
  codes=[400,401,403,404,503]+([408,409,413,429]if key=='ownerPut'else[409]if key=='ownerDelete'else[410]if native else[])
  for code in codes:responses[str(code)]={'description':FAILURES[code],'content':{'application/json':{'schema':{'oneOf':[ref('NativeFunctionalError'),BOUNDARY]}}}}
  if key in ('ownerPut','ownerDelete'):
   responses['403']['description'] += ' RECEIVER_VEHICLE_ONLY이면 인증된 차량 앱의 리모컨 수신 설정에서 변경합니다.'
  operation['responses']=responses
 for op in schema.get('paths', {}).get(RECEIVER_PATH, {}).values():
  op['x-wegoh-native-access'] = True
  op['x-wegoh-feature-enabled'] = enabled
  for status, response in op['responses'].items():
   if status != '200':
    response['content']['application/json']['schema'] = {'oneOf': [ref('NativeFunctionalError'), BOUNDARY]}
 from api_doc_control_support import apply
 schema=apply(schema,auth)
 # vehicle_control_support.report_support answers {authorizationVersion,error}; the shared native
 # authentication and body reader (read_body) answer {detail}. A rejected report never overwrites the snapshot.
 support=schema.get('paths',{}).get(SUPPORT_PATH,{}).get('put')
 if support is not None:
  functional,detail=ref('NativeFunctionalError'),{'$ref':'#/components/schemas/ApiError'}
  either={'oneOf':[functional,detail]}
  for code,shape,text in (
    ('400',either,'error=INVALID_CONTROL_SUPPORT(필드·조작·위치·범위 형식, 운전석 포함) 또는 detail=INVALID_REQUEST(Content-Type)입니다. 기존 지원 정보는 그대로입니다.'),
    ('401',either,'error=INVALID_CREDENTIAL(Native 기기 요청이 아님) 또는 Native 인증의 detail 오류입니다.'),
    ('403',either,'error=FUNCTIONAL_PURPOSE_REQUIRED(명령 수신 목적 없음)·VEHICLE_OWNER_REQUIRED(차량 계정 아님)·FUNCTIONAL_CONSENT_INACTIVE(기능 동의 비활성) 또는 Native 인증의 detail 오류입니다.'),
    ('404',functional,'error=ROUTE_NOT_FOUND: 기능 동의 서비스가 꺼져 있습니다.'),
    ('409',functional,'error=FUNCTIONAL_REVISION_CHANGED 또는 RECEIVER_CHANGED: 수신 상태를 GET으로 다시 읽고 새 revision으로 보고합니다.'),
    ('413',detail,'detail=REQUEST_TOO_LARGE: 본문이 12288바이트를 넘었습니다.'),
    ('503',either,'저장소·기능 동의 무결성을 확인할 수 없습니다. 보고 성공으로 표시하지 않습니다.')):
   support['responses'][code]={'description':text,'content':{'application/json':{'schema':shape}}}
 from api_doc_client_reports import apply as apply_reports
 return apply_reports(schema,auth)
