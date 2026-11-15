"""Explicit browser-admin deployment status, release list and version changes."""
from api_doc_shared import ADMIN, entry, response

REQUEST={'type':'object','additionalProperties':False,'required':['requestId'],'properties':{'requestId':{'type':'string','format':'uuid','pattern':'^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$','description':'명시 클릭마다 생성하는 UUID4. 응답이 불명확하면 같은 ID를 보존하고 상태를 확인합니다.'}}}
REQUEST['properties']['retryOf']={'type':'string','format':'uuid','description':'이전 unknown 작업의 requestId. retryAllowed=true일 때 새 확인 클릭으로만 명시합니다. 같은 새requestId에 다른 retryOf를 붙이면409입니다.'}
SHA={'type':['string','null'],'pattern':'^[a-f0-9]{40}$','description':'실제 current release의 전체 Git commit. 미확인은 null.'}
JOB={'type':['object','null'],'additionalProperties':False,'required':['requestId','state','startedAt','finishedAt','previousRevision','resultRevision'],'properties':{'requestId':{'type':'string','format':'uuid','description':'명시 요청에 결합한 UUID4입니다. 같은 ID 재전송은 이 보존 작업을 조회하며 새로운 배포 작업을 만들지 않습니다.'},'state':{'type':'string','enum':['running','succeeded','failed','unknown'],'description':'failed도 부작용 없음이 아닙니다. unknown은 중단/응답 불명확이며 자동 재시도하지 않습니다.'},'startedAt':{'type':'integer','description':'durable 접수를 기록한 Unix UTC 초입니다. 실제 배포 명령 시작 시각과 구분합니다.'},'finishedAt':{'type':['integer','null'],'description':'종료 또는 orphan을 unknown으로 복구한 관측의 Unix UTC 초입니다. running은null이며 값이 있다는 사실이 배포 성공을 뜻하지 않습니다.'},'previousRevision':SHA,'resultRevision':SHA,'retryOf':{'type':['string','null'],'format':'uuid','description':'새 명시 요청이 재확인한 직전 unknown 작업의 UUID4입니다. 일반 최초 요청은null이며 이전 작업을 삭제하거나 자동 재시도하지 않습니다.'}}}
STATUS={'type':'object','additionalProperties':False,'required':['mode','currentRevision','job','retryAllowed','requestedJob'],'properties':{'mode':{'const':'manual','description':'이 API가 명시 수동 배포 요청 계약임을 나타내는 고정 값입니다. 이 필드만으로 다른 timer의 운영 상태를 증명하지 않습니다.'},'currentRevision':SHA,'job':dict(JOB,description='GET에서는 다른 관리자 포함 전역 최신 작업입니다. POST의 동일 requestId 재전송은 보존된 해당 작업을 반환하며, 기록이 없으면null입니다.'),'requestedJob':dict(JOB,description='GET의 선택 requestId query에 해당하는 보존 작업입니다. query가 없거나 해당 기록이 없으면null이며 전역 job과 구분합니다. POST 응답에서는null입니다.'),'retryAllowed':{'type':'boolean','description':'unknown 작업이며 공유poll flock의 현재 비차단획득이 가능함. 이전 성공/종료의 증명이 아니며 POST에서 재검사합니다.'}}}
JOB['properties']['outcome']={'type':'object','additionalProperties':False,'required':['reason','recovery','phase'],'properties':{
 'reason':{'type':'string','enum':['PREPARATION_FAILED','NEW_RELEASE_UNHEALTHY','ROLLBACK_FAILED','NO_PREVIOUS_RELEASE'],'description':'배포 helper가 실제 실패 지점에서 기록한 고정 사유입니다. 원 로그나 비밀 값은 반환하지 않습니다.'},
 'recovery':{'type':'string','enum':['retained','restored','failed','unavailable'],'description':'기존 서비스 미전환, 이전 버전 readiness 확인 후 복구, 복구 실패, 복구 대상 없음입니다. 현재 서비스 상태는 service에서 별도로 확인합니다.'},
 'phase':{'type':'string','enum':['prepare','rollback','restart'],'description':'해당 요청이 실패한 실제 단계입니다.'}}}
STATUS['required'].append('service')
STATUS['properties']['service']={'type':'object','additionalProperties':False,'required':['ready','revision'],'properties':{
 'ready':{'type':'boolean','description':'고정 loopback API의 현재 readiness HTTP200 관측입니다. 과거 작업의 성공 여부와 구분합니다.'},
 'revision':dict(SHA,description='현재 응답한 프로세스가 보낸 immutable release commit입니다. 구버전 또는 미확인은 null이며 currentRevision과 같다고 추정하지 않습니다.')}}
REQUEST['properties']['targetRevision']={'type':'string','pattern':'^[a-f0-9]{40}$','minLength':40,'maxLength':40,'description':'저장되어 있고 현재 인증·SQL 구조와 호환되고 버전 관리 API를 유지하는 버전의 전체 commit입니다. GET /v1/operations/releases에서 selectable=true인 값을 사용합니다. 생략하면 최신 origin/main을 받습니다. 임의 branch/tag/URL은 받지 않습니다.'}
JOB['properties']['targetRevision']=dict(SHA,description='명시적으로 고른 저장 버전입니다. null 또는 과거 기록의 생략은 최신 main 요청입니다. 같은 requestId나 unknown 재시도의 대상은 바꾸지 않습니다.')
RELEASE_ITEM={'type':'object','additionalProperties':False,'required':['revision','createdAt','current','selectable','reason'],'properties':{
 'revision':{'type':'string','pattern':'^[a-f0-9]{40}$','description':'설치된 불변 버전의 전체 commit입니다.'},
 'createdAt':{'type':['string','null'],'format':'date-time','description':'설치 manifest의 UTC 시각입니다. 실행 성공 시각이나 Git commit 시각은 아닙니다. 미확인은 null입니다.'},
 'current':{'type':'boolean','description':'현재 선택된 release pointer와 같은 버전인지 나타냅니다.'},
 'selectable':{'type':'boolean','description':'목록 조회 시점에 파일·의존성·인증 계약·SQL 구조 검사를 통과해 선택 가능한지 나타냅니다. 실제 전환 직전에 다시 검사하며 실행 상태를 보장하지 않습니다.'},
 'reason':{'type':['string','null'],'enum':[None,'INVALID_REVISION','NOT_INSTALLED','UNSAFE_RELEASE','INVALID_MANIFEST','INTEGRITY_MISMATCH','DEPENDENCIES_INVALID','CURRENT_UNAVAILABLE','SCHEMA_INCOMPATIBLE','AUTHORIZATION_INCOMPATIBLE','MANAGEMENT_INCOMPATIBLE','CURRENT_RELEASE','UNTRUSTED_REVISION'],'description':'전환 불가의 고정 코드입니다. CURRENT_RELEASE는 현재 버전, SCHEMA_INCOMPATIBLE은 SQL 불일치, AUTHORIZATION_INCOMPATIBLE은 인증 계약 불일치, MANAGEMENT_INCOMPATIBLE은 버전 관리 API 없는 과거 버전, 나머지는 원본·파일·의존성·현재 상태 검증 실패이며 경로·로그·비밀 값은 포함하지 않습니다.'}}}
RELEASE_LIST={'type':'object','additionalProperties':False,'required':['mode','currentRevision','releases'],'properties':{
 'mode':{'const':'manual','description':'명시 요청으로만 버전을 전환합니다.'},'currentRevision':SHA,
 'releases':{'type':'array','maxItems':20,'items':RELEASE_ITEM,'description':'최근 저장된 버전 최대20개입니다. 호환되지 않는 버전은 이유와 함께 비활성으로 반환합니다. 외부 Git 주소를 조회하거나 배포하지 않습니다.'}}}
EXAMPLE={'mode':'manual','currentRevision':'a'*40,'job':{'requestId':'12345678-1234-4123-8123-123456789abc','state':'unknown','startedAt':1793444400,'finishedAt':1793444401,'previousRevision':'a'*40,'resultRevision':'a'*40,'retryOf':None},'retryAllowed':True,'requestedJob':None,'service':{'ready':True,'revision':'a'*40}}
OPS={('get','/v1/operations/deployment'):entry('운영 설정','수동 배포 상태와 현재 서버 버전',ADMIN+' Native에서는 제공하지 않습니다.',
 '설정에서 현재 버전과 마지막 작업을 조회합니다. API 재시작/응답 유실 뒤에도 이 정본을 다시 읽습니다.',
 'mode=manual, 실제 currentRevision과 마지막 durable job만 반환합니다. 로그·경로·계정·키는 공개하지 않습니다.',
 '안전한 조회. unknown은 성공/실패로 바뀌지 않습니다. retryAllowed는 시점관측이며 새UUID+retryOf의 명시 확인을 POST에서 재검사합니다. 자동 재시도하지 않습니다.',{'200':response(STATUS,'현재 배포 상태. job=null은 기록된 수동 작업이 없음. 예시 unknown은 성공이 아닙니다.')},['400','401','403','404','503']),
 ('post','/v1/operations/deployments'):entry('운영 설정','최신 main 또는 저장된 호환 버전 적용',ADMIN+' Native/creator/viewer는 사용할 수 없습니다.',
 '기본은 고정 origin/main이며 targetRevision을 보내면 저장된 호환 버전으로 전환합니다. 본문은 requestId(UUID4), unknown의 새 명시 재요청은 retryOf도 필수입니다. 먼저 상태를 읽고 확인창에서 요청합니다.',
 '202는 durable 접수이며 배포 성공이 아닙니다. 원본·후손·무결성·호환성·readiness·복구 검사를 유지합니다. timer를 켜지 않습니다.',
 '본문은 최대1024byte/5초이고 지연 수신408·초과413입니다. 수신 후 현재 세션과 admin 역할을 다시 확인합니다. 같은 requestId/retryOf는 같은 작업을 반환합니다. 이전unknown은 보존하며 retryOf는 최신unknown과일치해야하고실제poll공유락을재검사합니다. 다른 작업 실행 중409이며 GET으로 확인합니다. 응답 유실/unknown은 자동 재전송/성공 표시를 하지 않습니다.',{'202':response(STATUS,'접수 또는 동일 requestId의 원작업 상태. 성공은 job.state=succeeded에서만 판단합니다.')},['400','401','403','404','409','413','429','503'],example={'requestId':EXAMPLE['job']['requestId']})}

OPS[('get','/v1/operations/deployment')]['responses']['200']['content']['application/json']['example']=EXAMPLE
OPS[('post','/v1/operations/deployments')]['responses']['202']['content']['application/json']['example']={**EXAMPLE,'retryAllowed':False,'job':{**EXAMPLE['job'],'state':'running','finishedAt':None,'resultRevision':None}}

OPS[('post','/v1/operations/deployments')]['responses']['408']={'description':'본문이 5초 안에 완료되지 않았습니다. 배포 bridge는 호출되지 않습니다.'}

OPS[('get','/v1/operations/deployment')]['sequence']+=' 선택적 requestId UUID4 query는 보존된 본인 요청을 requestedJob에서 조회합니다. job은 다른 관리자 포함 전역 최신 작업이며 두 값을 혼동하지 않습니다. 없는 요청은 requestedJob=null입니다. 조회는 작업을 만들거나 재시도하지 않습니다.'

OPS[('get','/v1/operations/releases')]=entry('운영 설정','저장된 서버 버전과 전환 가능 여부',ADMIN+' Native에서는 제공하지 않습니다.',
 'AI 또는 관리자가 목록을 읽고 selectable=true의 전체 revision을 선택합니다. 조회는 배포를 시작하지 않습니다.',
 '고정 설치 경로의 최대20개 metadata만 반환합니다. 브랜치·태그·URL·명령은 입력하지 않습니다.',
 'POST deployments에 새UUID4 requestId와 targetRevision을 전달하고 GET deployment?requestId로 성공·복구를 확인합니다. 기본 요청과 unknown 재시도에도 같은 대상 바인딩을 지킵니다.',{'200':response(RELEASE_LIST,'설치된 버전 목록. 실제 전환 전 무결성·호환성을 다시 검사합니다.')},['400','401','403','404','503'])
OPS[('post','/v1/operations/deployments')]['sequence']+=' targetRevision을 명시하면 저장된 호환 버전만 전환하고 외부 fetch를 요구하지 않습니다. 생략하면 최신main입니다. 선택 버전이 실패하면 이전 버전 복구 경로를 동일하게 사용합니다. 데이터·키는 되돌리거나 지우지 않습니다.'


# Additive controller v2 capabilities. Their absence is a legacy/unknown
# controller, never evidence that an engine or migration is installed.
OPERATION={'type':'string','enum':['deploy','engine-update'],'default':'deploy'}
OPERATION['description']='생략하면 기존 deploy입니다. engine-update는 명시한 전체 targetRevision이 필수이며 최초 root launcher 설치는 운영자 작업입니다.'
REQUEST['properties']['operation']=OPERATION
REQUEST['allOf']=[{'if':{'required':['operation'],'properties':{'operation':{'const':'engine-update'}}},'then':{'required':['targetRevision']}}]
JOB['properties']['operation']=OPERATION
DIAGNOSTIC={'type':'object','additionalProperties':False,'required':['code','phase','operatorAction','operatorNeeded'],'properties':{
 'code':{'type':'string','pattern':'^[A-Z][A-Z0-9_]{0,79}$','description':'검토된 고정 진단 코드. 내부 예외나 raw log가 아닙니다.'},
 'phase':{'type':['string','null'],'enum':[None,'prepare','plan','engine','migration','authorization','backup','restart','rollback','bootstrap','complete']},
 'operatorAction':{'type':'string','pattern':'^[A-Z][A-Z0-9_]{0,79}$','description':'고정 다음 조치 코드. 명령·경로·토큰을 포함하지 않습니다.'},
 'operatorNeeded':{'type':'boolean'}}}
ENGINE={'type':'object','additionalProperties':False,'required':['protocol','revision','manifestSha256','state'],'properties':{
 'protocol':{'type':['integer','null'],'minimum':1},'revision':SHA,
 'manifestSha256':{'type':['string','null'],'pattern':'^[a-f0-9]{64}$'},
 'state':{'type':'string','enum':['ready','bootstrap_required','invalid']}}}
STATUS['properties'].update({'controllerVersion':{'type':'integer','minimum':1},'engine':ENGINE,'diagnostic':DIAGNOSTIC,
 'manualTimerDisabled':{'type':'boolean','description':'실제 관측값만 반환합니다.'}})
STATUS['properties']['manualTimerDisabled']['description']='실제 운영 관측값입니다. 누락으로 timer 비활성을 추정하지 않습니다.'
JOB['properties']['diagnostic']=DIAGNOSTIC
STATE={'type':['string','null'],'maxLength':128}
AUTH_PLAN={'type':'object','additionalProperties':False,'properties':{
 'compatible':{'type':'boolean'},'transitionId':{'type':['string','null'],'maxLength':128},'corePreserved':{'type':'boolean'},
 'functional':{'type':'object','additionalProperties':False,'properties':{'fromDisclosure':{'type':['integer','null']},'toDisclosure':{'type':['integer','null']},'existingStoredConsentPreserved':{'type':'boolean'},'defaultPolicyChanged':{'type':'boolean'}}},
 'clientUpdateRequiredForFunctional':{'type':'boolean'},'baseReauthorizationRequired':{'type':'boolean'},
 'rollback':{'type':'object','additionalProperties':False,'properties':{'compatibilityFloor':STATE,'preTrafficOnly':{'type':'boolean'},'requiresNoPostTransitionWrites':{'type':'boolean'}}},
 'reasonCode':{'type':['string','null'],'maxLength':80}}}
PLAN={'type':'object','additionalProperties':False,'required':['planId','currentRevision','targetRevision','engineRevision','migrations','schema','authorizationCompatibility','backupRequired','canApply','reason','planDBVerified','migrationHistory'],'properties':{
 'planId':{'type':['string','null'],'pattern':'^[a-f0-9]{64}$'},'currentRevision':SHA,'targetRevision':SHA,'engineRevision':SHA,
 'migrations':{'type':'array','maxItems':100,'items':{'type':'object','additionalProperties':False,'required':['id','checksum'],'properties':{'id':{'type':'string','maxLength':128},'checksum':{'type':'string','pattern':'^[a-f0-9]{64}$'}}}},
 'schema':{'type':'object','additionalProperties':False,'required':['from','to','rollbackFloor'],'properties':{'from':STATE,'to':STATE,'rollbackFloor':STATE}},
 'authorizationCompatibility':AUTH_PLAN,'backupRequired':{'type':'boolean'},'canApply':{'type':'boolean'},
 'reason':{'type':['string','null'],'maxLength':80},'planDBVerified':{'const':False,'description':'현재 읽기 전용 계획은 운영 DB를 읽지 않습니다. 실제 적용 직전에 별도로 검사합니다.'},
 'migrationHistory':{'const':'unknown'},'diagnostic':DIAGNOSTIC}}
OPS[('get','/v1/operations/deployment-plan')]=entry('운영 설정','설치된 서버 버전의 변경 계획 조회',ADMIN+' Native에서는 제공하지 않습니다.',
 'targetRevision 전체40자리 하나로 검증된 설치 대상을 조회합니다. Git fetch·DB 조회·migration·배포·engine 선택을 실행하지 않습니다.',
 'schema 전후와 rollback 하한·인증 및 기능 동의 호환·백업 필요 여부를 반환합니다. planDBVerified=false/migrationHistory=unknown을 실제 DB 검증으로 표시하지 않습니다.',
 '안전한 조회만 수행합니다. canApply는 정적 계획이며 실행 허가·DB 준비·실제 적용 성공이 아닙니다. 구형 controller는503과 고정 bootstrap 진단을 반환합니다.',
 {'200':response(PLAN,'설치된 대상의 정적 계획. 실제 DB 이력/객체는 적용 직전에 재검사합니다.')},['400','401','403','404','503'])
OPS[('post','/v1/operations/deployments')]['sequence']+=' operation=engine-update는 write-fetch 후 검증한 trusted main engine의 불변 설치·검증·원자적 선택 작업이며 targetRevision이 필수입니다. 동일 requestId/retryOf는 operation까지 고정하며 변경하거나 자동 재생하지 않습니다. 최초 고정 root helper bootstrap은 기존 API로 수행할 수 없습니다.'

ENGINE['properties'].update({'availableRevision':SHA,'updateAvailable':{'type':'boolean'},'reason':{'type':['string','null'],'maxLength':80}})
ENGINE['properties']['availableRevision']['description']='이미 로컬 fetch된 고정 origin/main의 검증된 engine 후보입니다. 상태 조회가 외부 fetch를 시작하지 않습니다. 앱 release 설치/SQL 계획과 별개입니다.'
REQUEST['properties']['targetRevision']['description']='deploy에서는 저장된 selectable=true 앱 버전입니다. engine-update에서는 status.engine.availableRevision의 검증된 고정 main 후보만 허용합니다. 전체40자리이며 임의 branch/tag/URL/명령은 받지 않습니다.'

AUTH_PLAN['required']=list(AUTH_PLAN['properties'])
AUTH_PLAN['properties']['transitionId'].update(maxLength=80,pattern='^[a-z0-9._-]{1,80}$')
AUTH_PLAN['properties']['functional']['required']=list(AUTH_PLAN['properties']['functional']['properties'])
AUTH_PLAN['properties']['functional']['properties']['defaultPolicyChanged']={'type':['boolean','null']}
for key in ('clientUpdateRequiredForFunctional','baseReauthorizationRequired'):
    AUTH_PLAN['properties'][key]={'type':['boolean','null'],'description':'미확인 계약은 null이며 재연결/업데이트가 불필요하다고 추정하지 않습니다.'}
AUTH_PLAN['properties']['rollback']['required']=list(AUTH_PLAN['properties']['rollback']['properties'])
AUTH_PLAN['properties']['reasonCode']={'type':'string','enum':['AUTH_UNCHANGED','AUTH_TRANSITION_SUPPORTED','AUTH_ROLLBACK_PRETRAFFIC_ONLY','AUTH_CORE_CHANGED','AUTH_FUNCTIONAL_TRANSITION_UNSUPPORTED','AUTH_DATA_WRITE_PROFILE_REQUIRED','AUTH_DATA_WRITE_PROFILE_UNSUPPORTED','AUTH_CONTRACT_INVALID','AUTH_TRANSITION_MANIFEST_INVALID']}


# Each field distinguishes static planning from actual DB/service observations.
JOB['properties']['outcome']['description']='원 요청 당시 helper가 기록한 실패·복구 결과입니다. 현재 서비스 건강이나 미기록 원인을 추정하지 않습니다.'
STATUS['properties']['service']['description']='고정 loopback 서비스의 현재 readiness와 실제 응답 프로세스 revision입니다.'
STATUS['properties']['controllerVersion']['description']='실제 설치된 고정 controller 프로토콜 버전입니다. 누락은 구형 또는 미확인입니다.'
DIAGNOSTIC['description']='관리자에게 제공하는 고정 코드와 안전한 다음 조치입니다. 원로그·경로·키를 포함하지 않습니다.'
DIAGNOSTIC['properties']['phase']['description']='진단을 기록한 고정 단계이며 미기록은 null입니다.'
DIAGNOSTIC['properties']['operatorNeeded']['description']='현재 API로 해결할 수 없어 별도 운영자 작업이 필요한지 나타냅니다.'
ENGINE['description']='설치 검증된 현재 engine과 이미 로컬에 검증된 고정 main 후보입니다.'
for key,description in {
 'protocol':'선택된 engine manifest의 지원 프로토콜 정수입니다. 미확인은 null입니다.',
 'revision':'검증된 현재 engine의 전체 Git revision입니다. 앱 pointer·실제 서비스 버전과 다릅니다.',
 'manifestSha256':'선택된 engine의 검증된 manifest SHA256입니다. 미확인은 null입니다.',
 'state':'현재 engine 준비·최초 운영자 설치 필요·무결성 실패를 구분합니다.',
 'updateAvailable':'검증된 고정 main 후보가 현재 engine과 달라 명시 갱신 대상으로 제공되는지 나타냅니다.',
 'reason':'후보를 제공하지 못한 고정 코드입니다. 내부 예외 원문은 반환하지 않습니다.'
}.items(): ENGINE['properties'][key]=dict(ENGINE['properties'][key],description=description)
for key,description in {
 'planId':'정규화된 정적 계획 SHA256입니다. 실행 승인이나 실제 DB 적합성 증명이 아닙니다.',
 'currentRevision':'계획 시점의 현재 앱 release pointer revision입니다.',
 'targetRevision':'조회에서 지정하고 설치·무결성을 검증한 대상 앱 release revision입니다.',
 'engineRevision':'이 계획을 해석하는 실제 선택 engine revision입니다.',
 'migrations':'검토된 순서의 migration ID와 원본 checksum입니다. 조회는 SQL을 실행하지 않습니다.',
 'schema':'지원되는 schema 전후 상태와 코드 rollback 하한의 정적 선언입니다.',
 'backupRequired':'실제 적용 전에 기존 암호화 백업 완료가 필요한지 나타냅니다.',
 'canApply':'알려진 schema 경로·인증 계약의 정적 적용 가능 여부입니다. 실제 DB 상태를 승인하지 않습니다.',
 'reason':'정적 적용 불가의 고정 코드이며 미기록·정상은 null일 수 있습니다.',
 'migrationHistory':'운영 DB를 읽지 않은 이 조회에서는 항상 unknown입니다.'
}.items(): PLAN['properties'][key]=dict(PLAN['properties'][key],description=description)
PLAN['properties']['migrations']['items']['properties']['id']['description']='버전 관리되고 검토된 migration 식별자입니다.'
PLAN['properties']['migrations']['items']['properties']['checksum']['description']='해당 migration 원본의 SHA256입니다. 적용 이력과의 대조는 실행 직전에 수행합니다.'
for key,description in {'from':'기대하는 현재 schema 상태 ID입니다. 미확인은 null입니다.','to':'대상이 요구하는 schema 상태 ID입니다. 미확인은 null입니다.','rollbackFloor':'현재 DB 형식을 읽을 수 있는 코드 rollback 최소 상태 ID입니다. 미확인은 null입니다.'}.items():
    PLAN['properties']['schema']['properties'][key]=dict(STATE,description=description)
AUTH_PLAN['description']='계정 연결 core·기능 동의·구형 클라이언트·저장 형식의 정적 호환 계획입니다. 실제 DB 행 검사가 아닙니다.'
for key,description in {
 'compatible':'검토된 authorization transition으로 대상 계약을 안전하게 해석할 수 있는지 나타냅니다.',
 'transitionId':'검토된 정적 전이 식별자입니다. 동일 계약 또는 미확인일 때 null일 수 있습니다.',
 'corePreserved':'기존 계정·기기 연결 core 계약을 보존하는 알려진 전이인지 나타냅니다.',
 'functional':'기능 동의 disclosure·기존 저장 동의 해석·기본 정책 변경을 별도로 설명합니다.',
 'rollback':'대상 적용 후 이전 코드로 복구할 수 있는 저장 계약의 하한과 트래픽 조건입니다.',
 'reasonCode':'호환성 판단의 고정 코드입니다. 미확인 계약을 자동 승인하지 않습니다.'
}.items(): AUTH_PLAN['properties'][key]['description']=description
for key,description in {
 'fromDisclosure':'현재 코드의 기능 동의 disclosure 버전이며 미확인은 null입니다.',
 'toDisclosure':'대상 코드의 기능 동의 disclosure 버전이며 미확인은 null입니다.',
 'existingStoredConsentPreserved':'기존 저장 동의 해석을 보존하는 알려진 계약이라는 정적 판단입니다. 실제 DB 행 검증은 아닙니다.',
 'defaultPolicyChanged':'알려진 기능 기본 정책 변경 여부이며 판단 불가는 null입니다.'
}.items(): AUTH_PLAN['properties']['functional']['properties'][key]['description']=description
for key,description in {
 'compatibilityFloor':'저장된 profile/functional 형식을 안전하게 읽고 쓸 수 있는 최소 코드 계약입니다.',
 'preTrafficOnly':'새 형식 쓰기 트래픽 전에만 이전 코드 rollback이 허용되는지 나타냅니다.',
 'requiresNoPostTransitionWrites':'전이 후 새로운 형식 쓰기가 없어야 복구 가능한 조건인지 나타냅니다.'
}.items(): AUTH_PLAN['properties']['rollback']['properties'][key]=dict(AUTH_PLAN['properties']['rollback']['properties'][key],description=description)

BOOTSTRAP={'type':'object','additionalProperties':False,'required':['revision','receiptSha256','verified'],'description':'최초 운영자가 설치한 고정 wrapper/controller의 실제 파일 지문 대조 결과입니다. controllerVersion 또는 앱 버전으로 설치를 추정하지 않습니다.','properties':{
 'revision':dict(SHA,description='고정 bootstrap 설치 receipt에 결합한 원본 revision입니다. 미확인은 null입니다.'),
 'receiptSha256':{'type':['string','null'],'pattern':'^[a-f0-9]{64}$','description':'root 설치 receipt의 SHA256입니다. 내용·경로·비밀 원문은 반환하지 않습니다.'},
 'verified':{'type':'boolean','description':'고정 설치 파일·unit drop-in의 실제 지문이 receipt와 일치하는지 나타냅니다. 누락/불일치는 false입니다.'}}}
STATUS['properties']['bootstrap']=BOOTSTRAP

JOB['properties']['previousRevision']=dict(SHA,description='원 작업 시작 전 앱 pointer(deploy) 또는 선택 engine(engine-update)의 revision입니다. 실제 응답 서비스 버전과 별도입니다.')
JOB['properties']['resultRevision']=dict(SHA,description='원 작업 종료 시 관측한 앱 pointer(deploy) 또는 engine(engine-update)의 revision입니다. 이 값만으로 현재 서비스 건강을 증명하지 않습니다.')
JOB['properties']['targetRevision']=dict(SHA,description='요청에 결합한 명시 대상입니다. deploy의 생략/과거 기록은 null(최신 main), engine-update 신규 요청은 정확한 검증 main revision입니다.')

GATE_PROOF={'type':['object','null'],'additionalProperties':False,'required':['version','sourceRevision','instanceId','state','operationId','activeHTTP','activeWS','trafficAdmitted'],'description':'실제 loopback 고정 wrapper의 현재 프로세스 관측입니다. 요청수0만으로 worker DB drain이나 최초 설치 완료를 증명하지 않습니다.','properties':{
 'version':{'const':1,'description':'실제 실행된 고정 ASGI wrapper의 proof 프로토콜입니다.'},
 'sourceRevision':dict(SHA,description='실행 프로세스가 시작할 때 불변 release 경로에서 캡처한 실제 revision입니다.'),
 'instanceId':{'type':'string','format':'uuid','description':'프로세스별 임의 관측 식별자입니다. 기기·계정 인증 정보가 아닙니다.'},
 'state':{'type':'string','enum':['open','closed','invalid'],'description':'현재 읽은 쓰기 차단 파일 상태입니다. invalid는 fail-closed이며 서비스 ready와 별도입니다.'},
 'operationId':{'type':['string','null'],'format':'uuid','description':'고정 gate 파일의 명시 배포 요청 UUID4입니다. 잘못된 gate는 null입니다.'},
 'activeHTTP':{'type':'integer','minimum':0,'description':'health를 제외하고 wrapper 안에서 아직 완료되지 않은 HTTP 요청 수입니다.'},
 'activeWS':{'type':'integer','minimum':0,'description':'wrapper 안에서 아직 종료되지 않은 WebSocket 연결 수입니다.'},
 'trafficAdmitted':{'type':'boolean','description':'이 프로세스가 시작한 뒤 non-health 요청을 한 번이라도 허용했는지 나타냅니다. false는 DB 변경 여부 자체의 증명이 아닙니다.'}}}
STATUS['properties']['service']['properties']['deploymentGate']=GATE_PROOF
STATUS['properties']['service']['properties']['enrollmentGate']=GATE_PROOF

JOB['properties']['engineRevision']=dict(SHA,description='접수 시 고정한 실행 engine revision입니다. 이후 engine pointer가 바뀌어도 기존 deploy 요청의 해석을 바꾸지 않습니다.')
DIAGNOSTIC['properties']['phase']['enum']=[None,'prepare','backup','migration','restart','rollback','engine','maintenance']
DIAGNOSTIC['properties']['code']['enum']=['CONTROLLER_UNSUPPORTED','ENGINE_BOOTSTRAP_REQUIRED','ENGINE_MANIFEST_INVALID','ENGINE_INTEGRITY_INVALID','ENGINE_UNTRUSTED_REVISION','ENGINE_PENDING_SWITCH','ENGINE_UNAVAILABLE','MIGRATION_MANIFEST_REQUIRED','MIGRATION_MANIFEST_INVALID','MIGRATION_INTEGRITY_INVALID','MIGRATION_PATH_UNSUPPORTED','MIGRATION_HISTORY_INVALID','MIGRATION_GATE_REQUIRED','MIGRATION_FAILED','SCHEMA_UNSUPPORTED','SCHEMA_ACTUAL_MISMATCH','SCHEMA_RESULT_MISMATCH','BACKUP_FAILED','BACKUP_DATABASE_MISMATCH','AUTHORIZATION_INCOMPATIBLE','TRAFFIC_GATE_UNAVAILABLE','TRAFFIC_NOT_DRAINED','ROLLBACK_FLOOR_BLOCKED','ROLLBACK_FAILED','NEW_RELEASE_UNHEALTHY','OPERATION_FAILED']
DIAGNOSTIC['properties']['operatorAction']['enum']=['BOOTSTRAP_CONTROLLER','REVIEW_RELEASE','OPERATOR_RECOVERY','UPDATE_ENGINE','INSPECT_MIGRATION','INSPECT_TRAFFIC_GATE','VERIFY_BACKUP','REVIEW_AUTH_COMPATIBILITY']
ENGINE['properties']['reason']['enum']=[None,'ENGINE_BOOTSTRAP_REQUIRED','ENGINE_MANIFEST_INVALID','ENGINE_INTEGRITY_INVALID','ENGINE_UNTRUSTED_REVISION','ENGINE_PENDING_SWITCH','ENGINE_UNPRIVILEGED_REQUIRED','ENGINE_OPERATION_UNSUPPORTED','ENGINE_UNAVAILABLE']

AUTH_PLAN['type']=['object','null']
PLAN['properties']['canRollback']={'type':'boolean','description':'정적 SQL schema 경로만의 이전 코드 호환성입니다. 실제 DB·authorization·차단/drain·새 쓰기 여부의 복구 승인을 대체하지 않습니다.'}
REQUEST['properties']['targetRevision']['description']='deploy에서는 설치된 selectable=true 앱 버전입니다. engine-update에서는 사용자가 명시한 전체40자리 revision을 고정 origin/main write-fetch 후 정확히 대조합니다. status.engine.availableRevision은 마지막 로컬 검증값이며 원격 최신 보장이 아닙니다. 임의 branch/tag/URL/명령은 받지 않습니다.'
ENGINE['properties']['availableRevision']['description']='마지막 로컬 fetch의 고정 origin/main에서 검증한 engine 후보입니다. 상태 조회가 fetch하지 않으므로 현재 원격 최신이라고 보장하지 않습니다.'
OPS[('post','/v1/operations/deployments')]['sequence']+=' engine-update의 명시 전체SHA는 write-fetch한 고정 origin/main의 실제 revision과 일치해야 합니다. 이전 status의 로컬 availableRevision만으로 새 원격 main 도달성을 제한하거나 현재 최신으로 표시하지 않습니다.'

GATE_PROOF['properties']['activeHTTP']['description']='health와 정확한 관리자 진단 GET3경로를 제외하고 wrapper 안에서 아직 완료되지 않은 일반 HTTP 요청 수입니다. 0만으로 worker DB drain을 증명하지 않습니다.'
GATE_PROOF['properties']['trafficAdmitted']['description']='이 프로세스가 일반 업무 요청을 한 번이라도 허용했는지 나타냅니다. health·기존 관리자 권한 검사를 거치는 정확한 진단 GET3는 제외되며, false는 DB 변경 여부 자체의 증명이 아닙니다.'
OPS[('get','/v1/operations/deployment')]['sequence']+=' 고정 쓰기 차단 중에도 기존 Host·Access·현재 admin·개인 세션 검사를 통과한 이 GET과 releases/deployment-plan GET만 조회할 수 있습니다. 로그인/배포 POST·일반 업무·WSS는 이 예외에 포함하지 않습니다.'

DIAGNOSTIC['properties']['code']['enum']+=['MAINTENANCE_RECOVERY_REQUIRED','MIGRATION_PROOF_REQUIRED','TRANSITION_SERVICE_FAILED']
PLAN['properties']['canRollback']['description']='정적 SQL schema와 알려진 역방향 authorization·저장 형식 호환성을 함께 판단한 값입니다. 실제 DB·트래픽 차단/drain·전이 후 쓰기 여부 검증을 대체하지 않으며, 조건부 실제 복구는 실행 직전에 다시 검사합니다.'


MANAGEMENT_LOCATION={'type':'object','additionalProperties':False,'required':['configured','origin'],'properties':{
 'configured':{'type':'boolean','description':'별도 운영자가 관리 origin을 설정했고 형식을 검증했는지 나타냅니다. DNS·서비스 실행·로그인 성공을 보장하지 않습니다.'},
 'origin':{'type':['string','null'],'format':'uri','description':'설정된 정규 HTTPS 관리 origin입니다. 미설정은 null, 제품/native/issuer와 같은 origin이나 경로·사용자정보·port는 거절합니다.'}}}
OPS[('get','/v1/operations/management-location')]=entry('운영 설정','독립 관리 서비스 주소 조회',ADMIN+' Native에서는 제공하지 않습니다.',
 '기존 관리 메뉴에서 한 번 조회하여 명시 링크만 표시합니다. 새 서비스는 별도 Access·관리 로그인과 CSRF를 사용합니다.',
 '조회는 리다이렉트·관리 로그인·배포를 실행하지 않습니다. configured=false는 실행 링크를 만들지 않습니다.',
 '기존 앱이 내려가도 독립 관리 origin은 별도 설치 후 직접 접속합니다. 예시 주소를 실서비스로 추정하지 않습니다.',
 {'200':response(MANAGEMENT_LOCATION,'독립 관리 origin 설정 상태. 운영 도메인·서비스 검증과 별도입니다.')},['400','401','403','404','503'])
MOVED={'type':'object','additionalProperties':False,'required':['detail','code','managementOrigin'],'properties':{
 'detail':{'type':'string','description':'독립 서비스 사용을 안내하는 고정 문구입니다.'},
 'code':{'const':'MANAGEMENT_SERVICE_REQUIRED','description':'앱 UID의 배포 중계가 독립 관리 서비스로 이동했음을 나타냅니다.'},
 'managementOrigin':{'type':'string','format':'uri','description':'형식을 검증한 별도 관리 origin입니다. 자동 이동하거나 쿠키를 전달하지 않습니다.'}}}
for key in [('get','/v1/operations/deployment'),('get','/v1/operations/releases'),('get','/v1/operations/deployment-plan'),('post','/v1/operations/deployments')]:
    OPS[key]['responses']['503']=response({'oneOf':[MOVED,{'type':'object','additionalProperties':False,'required':['detail'],'properties':{'detail':{'type':'string','description':'기존 서비스/설정 확인 불가의 안전한 고정 문구입니다.'}}}]},'독립 서비스 설정 후 기존 앱 중계는 현재 admin/세션 및 변경 CSRF 검사를 유지한 채 MANAGEMENT_SERVICE_REQUIRED로 거절합니다. 설정 전에는 기존 계약을 유지합니다.')
    OPS[key]['sequence']+=' 독립 WEGOH_MANAGEMENT_ORIGIN 설정 이후 이 제품 앱 경로는 503 MANAGEMENT_SERVICE_REQUIRED와 검증된 별도 origin을 반환하며 broker를 호출하지 않습니다. 자동302·로그인·POST 재전송은 하지 않습니다.'

# Errors of manual_deployment.py gate()/response() and the controller's actual replies.
# Read actions (status, plan, releases) never return BUSY in ops/live/manual_deploy.py; only start does.
import copy as _copy
UNSUPPORTED={'type':'object','additionalProperties':False,'required':['detail','diagnostic'],'properties':{
 'detail':{'const':'Deployment controller update required','description':'제어기가 이 동작을 모르는 이전 버전입니다.'},
 'diagnostic':{'type':'object','additionalProperties':False,'required':['code','phase','operatorAction','operatorNeeded'],'description':'고정 진단 값입니다.','properties':{
  'code':{'const':'CONTROLLER_UNSUPPORTED','description':'제어기 버전 불일치.'},'phase':{'const':'prepare','description':'준비 단계에서 멈췄습니다.'},
  'operatorAction':{'const':'BOOTSTRAP_CONTROLLER','description':'운영자가 제어기를 새로 설치합니다.'},'operatorNeeded':{'const':True,'description':'운영자 작업이 필요합니다.'}}}}}
for key in [('get','/v1/operations/deployment'),('get','/v1/operations/releases'),('get','/v1/operations/deployment-plan'),('post','/v1/operations/deployments')]:
    OPS[key]['responses']['503']['content']['application/json']['schema']['oneOf'].append(UNSUPPORTED)
    OPS[key]['responses']['503']['description']=('MANAGEMENT_SERVICE_REQUIRED(독립 관리 서비스로 이동), Deployment controller update required(CONTROLLER_UNSUPPORTED), '
        'Deployment status unavailable; refresh before another explicit request(제어 socket 응답 없음), Deployment control unavailable(제어기 오류) '
        '또는 Management service configuration invalid입니다. POST 응답을 잃었으면 성공·실패를 추정하지 말고 GET deployment로 확인합니다.')
GATE={'401':'Start a team session first·Team session expired(개인 세션 없음·만료) 또는 Account unavailable입니다. Access와 개인 세션을 다시 확인합니다.',
 '403':'Action not permitted(현재 팀 명단의 admin이 아님) 또는 Team access denied입니다.',
 '404':'Not found: 공개 웹 호스트가 아닌 주소로 왔습니다.'}
OPS[('get','/v1/operations/deployment')]['errorDescriptions']=dict(GATE,**{
 '400':'Only one UUID4 requestId lookup is accepted(query가 requestId 하나가 아님) 또는 Selected release is unavailable; refresh the release list(제어기가 요청을 거절)입니다.'})
OPS[('get','/v1/operations/releases')]['errorDescriptions']=dict(GATE,**{
 '400':'Query fields are not accepted: query 없이 호출합니다.'})
OPS[('get','/v1/operations/deployment-plan')]['errorDescriptions']=dict(GATE,**{
 '400':'One full installed targetRevision is required(query가 40hex targetRevision 하나가 아님) 또는 Selected release is unavailable; refresh the release list(설치되지 않은 대상)입니다.'})
OPS[('get','/v1/operations/management-location')]['errorDescriptions']=dict(GATE,**{
 '400':'Query fields are not accepted: query 없이 호출합니다.'})
OPS[('get','/v1/operations/management-location')]['responses']['503']=response({'type':'object','additionalProperties':False,'required':['detail'],
 'properties':{'detail':{'const':'Management service configuration invalid','description':'WEGOH_MANAGEMENT_ORIGIN 형식이 맞지 않습니다.'}}},
 'Management service configuration invalid: 설정된 독립 관리 origin 형식이 맞지 않습니다. 운영자가 설정을 고칩니다.')
OPS[('post','/v1/operations/deployments')]['errorDescriptions']=dict(GATE,**{
 '400':('Query fields are not accepted, Invalid JSON, A UUID4 requestId is required, Operation must be deploy or engine-update, '
        'Engine update requires an explicit full targetRevision, A full target revision is required, retryOf must be a UUID4 '
        '또는 Selected release is unavailable; refresh the release list입니다.'),
 '403':'Action not permitted(admin 아님), Team access denied, Origin denied 또는 CSRF verification failed입니다.',
 '413':'Request too large: 본문이 1024바이트를 넘었습니다.',
 '429':'Request limit exceeded: 계정당 10회/분을 넘었습니다. Retry-After: 60을 따릅니다.'})
BUSY=_copy.deepcopy(STATUS)
BUSY['properties']['error']={'const':'BUSY','description':'제어기가 이 요청을 시작하지 않았습니다.'}
BUSY['required']=BUSY['required']+['error']
OPS[('post','/v1/operations/deployments')]['responses']['409']=response(BUSY,
 'error=BUSY와 현재 상태를 함께 반환합니다. 다른 작업이 실행 중이거나, 같은 requestId에 다른 retryOf·targetRevision·operation을 보냈거나, '
 'retryOf가 최신 unknown 작업·재시도 가능 상태와 맞지 않습니다. GET deployment로 확인한 뒤 사용자가 다시 선택합니다.')
