"""LIVE12 contracts: separate participation/report purposes, never a race/SDK claim."""
from api_doc_shared import entry,response,obj,s,n,b,arr,ref,nullable,TIME,READ,BROWSER,NATIVE
from api_doc_models import IDENT,ACCOUNT,CHECK,REV

ROOT='/v1/social/rooms/{room}/missions'
NATIVE_ROOT='/v1/native/rooms/{room}/missions'
PREF=s('방에 먼저 저장한 경로 선호. 내비 적용/도로시간 ACK가 아닙니다.',enum=['balanced','country-roads','short-distance','short-time'])
strict=lambda fields,description:dict(obj(fields,description),additionalProperties=False)
PROGRESS=strict({'eventId':dict(IDENT,description='사용자가 확인을 누를 때 생성한32hex 멱등키. 동일 확인의 응답 유실 재시도에 같은 값을 사용합니다.'),'checkpoint':n('다음으로 직접 확인한 장소 순번1~3. GPS 도착 인증이 아닙니다.',minimum=1,maximum=3),'participationRevision':dict(REV,description='본인 participation.revision. 미션 전체 revision과 다릅니다.')},'본인 수동 장소 확인. 임의 계정·좌표·측정값·SDK출처 추가필드는 거절합니다.')
BODY={
 ('post',ROOT):strict({'preference':PREF},'방장 생성. 기존 방 preference와 같아야 하며 생성은 참여 동의가 아닙니다.'),
 ('put',ROOT+'/{mission}/participation'):strict({'participationRevision':n('본인미션참여현재revision. 처음0. 철회/재가입뒤이전요청을새동의로해석하지않습니다.',minimum=0),'consent':{'const':True,'description':'본인 장소 확인 진행을 현재 방 참여자와 공유함에 명시 동의. 방 가입/기존 위치 동의로 추정하지 않습니다.'}},'모집 중 미션별 명시 참여.'),
 ('post',ROOT+'/{mission}/start'):strict({'revision':REV},'정본 미션 revision으로 고정 참여 명단을 시작합니다.'),
 ('post',ROOT+'/{mission}/progress'):PROGRESS,
 ('post',NATIVE_ROOT+'/{mission}/progress'):PROGRESS,
 ('put',ROOT+'/{mission}/devices/{device}'):strict({'participationRevision':n('본인미션참여현재revision. true허용에필수현재값; false철회는stale값으로막지않습니다.',minimum=0),'revision':n('기기별 mission grant 정본 revision. 아직 없으면0. false 철회는stale값으로 차단하지 않습니다.',minimum=0),'consent':b('본인 기기의 이 미션 조회·수동 진행 보고만 별도 허용. true로 기존rooms-read목적을 자동 설정하지 않습니다.'),'expiresInHours':n('별도 허용기간1~24시간. 실제만료는방/기기만료와의최솟값.',minimum=1,maximum=24)},'브라우저 본인만 미션별 개인 기기 보고 목적을 변경합니다.')}
MODELS={
 'MissionSafety':obj({'state':{'const':'unavailable','description':'검증된 제조사 점수 계약이 없어미산정.'},'value':{'type':'null','description':'임의점수없음.'},'source':{'type':'null','description':'검증된공급자없음.'},'observedAt':{'type':'null','description':'실제측정시각없음.'},'verifiedMeasurementKinds':arr(s('서버가 검증한 측정kind.'),'현재빈배열. 기기선언으로추가되지않습니다.'),'computedByWegoH':{'const':False,'description':'별도점수계산없음.'}},'지원미확인과실제0점을구분합니다.'),
 'MissionCourse':obj({'id':s('방에서선택한승인코스ID.'),'version':n('선택한불변버전.',minimum=1),'checksum':CHECK,'checkpointCount':n('해당승인버전의장소수1~3.',minimum=1,maximum=3)},'생성시고정한목표. 승인철회/변경시진행닫힘.'),
 'MissionParticipant':obj({'accountId':ACCOUNT,'name':s('현재접근가능한계정의표시이름.'),'completedCheckpoints':n('순서대로직접확인한누적장소수.',minimum=0,maximum=3),'revision':REV},'현재동의/멤버십/차단검사를통과한진행공유만.'),
 'Mission':obj({'id':IDENT,'roomId':IDENT,'ownerId':ACCOUNT,'revision':REV,'state':s('enrolling/active/completed/cancelled 또는현재권한에서interrupted/result-withdrawn/course-unavailable.',enum=['enrolling','active','completed','cancelled','interrupted','result-withdrawn','course-unavailable']),'title':{'const':'함께 경로 완주하기','description':'자유문구를받지않는고정미션명.'},'course':ref('MissionCourse'),'routePreference':obj({'value':PREF,'appliedToNavigation':{'const':False,'description':'현재내비경로적용ACK없음.'}},'명시경로계획. 속도/시간내기아님.'),'checkpoints':arr(obj({'ordinal':n('1부터시작하는코스장소순번.',minimum=1,maximum=3),'label':s('고정한 승인 코스 버전에서 체크섬 검증 후 읽은 실제 장소 이름. 현재 승인되지 않은 코스는 반환하지 않습니다.')},'순서있는확인대상.'),'승인 코스의 1~3개 장소. 현재 코스 미승인 시 빈 배열.'),'participants':arr(ref('MissionParticipant'),'현재공유가능한명시참여자. 결과철회/코스미승인은빈배열.'),'participation':obj({'consent':b('본인참여가현재멤버십까지유효한지.'),'revision':n('본인참여revision. 미참여0.',minimum=0),'nextCheckpoint':nullable(n('다음수동확인순번. 완료/미참여null.',minimum=1,maximum=3))},'다음확인요청에사용하는본인정본.'),'confirmationSource':{'const':'user-confirmed','description':'수동보고. 위치/SDK검증아님.'},'physicalArrivalVerified':{'const':False,'description':'실제차량도착을인증하지않음.'},'safety':ref('MissionSafety'),'createdAt':dict(TIME,description='미션을서버에생성한시각.'),'completedAt':nullable(dict(TIME,description='현재공유가능한완료결과의서버시각. 철회/미완료null.')),'expiresAt':dict(TIME,description='부모여행방만료시각. 종료/만료후접근404.'),'serverNow':dict(TIME,description='이응답의서버현재시각. 클라이언트시계로기간을늘리지마세요.'),'nativeReportingPurpose':{'const':'mission-progress','description':'기존rooms-read와별도로미션/개인기기별허용해야하는목적.'}},'한미션현재정본. 속도/순위/내기/제조사안전점수없음.'),
 'MissionList':obj({'missions':arr(ref('Mission'),'브라우저현재방최대50개. Native는명시참여+미션별기기허용교집합만.'),'preference':PREF,'serverNow':TIME},'새GET으로현재철회/차단/기간을확인합니다.'),
 'MissionGrant':obj({'deviceId':IDENT,'purpose':{'const':'mission-progress','description':'본인미션확인읽기/보고목적.'},'consent':b('저장된별도허용여부.'),'revision':n('개인grantrevision. 미참여상태false no-op이면0.',minimum=0),'expiresAt':nullable(dict(TIME,description='실제grant만료. 아직참여/허용이없으면null.'))},'이 차의 미션 전송을 켜야 허용할 수 있습니다. 허용 기간은 차량 연결과 여행 기간 안으로 제한됩니다.'),
 'MissionDevices':obj({'purpose':{'const':'mission-progress','description':'현재 차량의 미션 진행 전송 설정.'},'devices':arr(obj({'deviceId':IDENT,'name':s('현재본인기기이름.'),'roomsRead':b('이 차량에서 내 여행을 볼 수 있는지 나타냅니다.'),'progressEnabled':b('이 차량에서 미션 진행을 전송할 수 있는지 나타냅니다. 미션별 허용과 기간은 별도로 확인합니다.'),'consent':b('저장된미션별허용. 만료/재가입후activefalse일수있음.'),'active':b('현재참여nonce/roomJoinedAt/기기purpose revision/기간까지유효.'),'revision':n('기기별미션허용revision. 없으면0.',minimum=0),'expiresAt':nullable(TIME)},'개인토큰/인증서/nonce를반환하지않는본인기기상태.'),'철회되지않은본인기기최대100개. 남의기기없음.'),'serverNow':TIME},'이 차의 미션 전송 설정과 미션별 허용 상태를 확인합니다.')}

ERRORS=['400','401','403','404','409','413','429','503']
RETRY='409는현재GET을새로읽고사용자가다음행동을선택합니다. 진행응답유실은같은eventId/순번으로만재시도하며추가증가하지않습니다. 참여/허용을자동재시도하거나추정하지마세요.'
EFFECT='암호화미션/본인진행과현재방rooms무효화알림만변경합니다. raw위치·안전점수·음성·차량제어·자동도착/내비출발을생성하지않습니다. 방멤버/차단/참여nonce/기간을현재조회합니다.'
OPS={}
def add(method,path,summary,sequence,schema='Mission',created=False,example=None,native=False,effects=EFFECT):
 OPS[(method,path)]=entry('15 협동미션',summary,(NATIVE+' 본인rooms-read+미션참여+해당개인기기mission-progress별도허용이모두현재유효해야합니다. 기존읽기목적은쓰기가아닙니다.' if native else (READ if method=='get' else BROWSER)+' 현재방멤버만가능하며참여는별도명시동의입니다.'),sequence,effects,RETRY,{'201'if created else'200':response(ref(schema),'현재정본. 사용자수동확인이지실제GPS도착인증이아닙니다.')},ERRORS,example=example,notes='속도/도착순서경주·내기·임의안전점수없음. 방만료/탈퇴404,고정참여자이탈interrupted,완료후철회result-withdrawn. Native인증서등록/CSR/lifecycle변경없음.')
add('get',ROOT,'현재 방의 협동미션 목록 읽기','방열기→이목록GET→참여/다음장소현재정본확인.',schema='MissionList',effects='DB쓰기없이현재방·미션참여/철회를계산합니다. 과거동의로남의진행을되살리지않습니다.')
add('post',ROOT,'승인 코스의 협동미션 만들기','방장이기존여행방에승인코스와선호저장→preference일치POST→각자가별도참여.',created=True,example={'preference':'country-roads'})
add('put',ROOT+'/{mission}/participation','본인 미션 참여와 진행 공유에 명시 동의','모집상태와공유범위를읽고사용자가참여→consenttrue. 생성/방가입이참여를대신하지않습니다.',example={'consent':True,'participationRevision':0})
add('delete',ROOT+'/{mission}/participation','본인 미션 참여 철회','사용자철회→새nonce로기존기기허용폐기. stale revision을요구하지않습니다.')
add('post',ROOT+'/{mission}/start','명시 참여한 두 명 이상으로 미션 시작','방장이참여→2명이상동의확인→미션revisionPOST. 시작시참여명단nonce고정.',example={'revision':3})
add('post',ROOT+'/{mission}/progress','본인이 다음 장소를 직접 확인','정본participation.nextCheckpoint/revision확인→새eventId→수동확인클릭.',example={'eventId':'1'*32,'checkpoint':1,'participationRevision':1})
add('delete',ROOT+'/{mission}','방장이 모집/진행 미션 취소','방장명시취소만. 완료결과삭제API가아닙니다.')
add('get',ROOT+'/{mission}/devices','본인 기기의 미션 별도 허용 상태 읽기','미션에 참여한 뒤 이 차의 전송 설정과 미션별 허용 상태를 확인합니다.',schema='MissionDevices',effects='본인기기명과목적상태만조회합니다. 토큰/키/인증서/남의기기를반환하지않습니다.')
add('put',ROOT+'/{mission}/devices/{device}','본인 기기에 이 미션 조회·보고만 별도 허용 또는 철회','본인이 미션에 참여하고 차량의 미션 전송을 켠 뒤 차량과 허용 기간을 고릅니다. false철회는stale revision으로막지않습니다.',schema='MissionGrant',example={'revision':0,'consent':True,'expiresInHours':1,'participationRevision':1})
add('get',NATIVE_ROOT,'허용된 본인 미션만 Native에서 읽기','같은개인mTLS와Bearer→본인웹참여/기기별별도허용후GET. 허용없으면빈목록.',schema='MissionList',native=True,effects='본인현재참여·기기별미션허용교집합만조회합니다. 일반rooms읽기만으로공개되지않습니다.')
add('post',NATIVE_ROOT+'/{mission}/progress','개인 기기가 명시 허용된 본인 확인만 보고','앱이사용자수동확인을받음→정본다음순번/참여revision/eventIdPOST. Native는참여·기기허용을설정할수없습니다.',native=True,example={'eventId':'2'*32,'checkpoint':1,'participationRevision':1})

from copy import deepcopy

MODELS['TripMission'] = deepcopy(MODELS['Mission'])
for field in ('roomId', 'expiresAt'):
    MODELS['TripMission']['properties'].pop(field)
    MODELS['TripMission']['required'].remove(field)
MODELS['TripMission']['properties'].update(tripId=IDENT, contractVersion={'const':1, 'description':'여행 기능 계약 버전.'})
MODELS['TripMission']['required'] += ['tripId', 'contractVersion']
MODELS['TripMission']['description'] = '같은 여행의 최대20명 명시 참여. 준비에서는 모집만, 진행 중에만 시작·확인. 종료 후 새 진행은 거부합니다.'
MODELS['TripMissionList'] = deepcopy(MODELS['MissionList'])
MODELS['TripMissionList']['properties']['missions']['items'] = ref('TripMission')
MODELS['TripWebMissionList'] = deepcopy(MODELS['TripMissionList'])
MODELS['TripWebMissionList']['properties']['courseAvailable'] = b('여행 소유자가 미션에 사용할 승인 코스를 서버에서 찾았는지 표시합니다.')
MODELS['TripWebMissionList']['required'].append('courseAvailable')
MODELS['TripMissionWithdrawal'] = obj({'id':IDENT, 'consent':{'const':False, 'description':'본인 미션 참여 철회.'},
    'revision':n('본인 참여 revision. 미참여0.', minimum=0)}, '종료·탈퇴 후에도 본인 철회만 허용합니다.')
for (method, path), operation in list(OPS.items()):
    trip_path = path.replace('/rooms/', '/trips/')
    contract = deepcopy(operation)
    contract['summary'] = contract['summary'].replace('방장', '여행 소유자').replace('현재 방', '현재 여행').replace('여행방', '여행')
    contract['notes'] += ' 연결된 방의 구형 rooms 경로는 수락 멤버409/외부인404. 새 경로는 여행 수락 명단·상태를 검사합니다. 방 만료시각을 만들지 않으며 기기 허가는 기존 기기 기한과 최대24시간 목적 기한을 유지합니다.'
    for response_value in contract['responses'].values():
        schema = response_value.get('content', {}).get('application/json', {}).get('schema', {})
        if schema.get('$ref') == ref('Mission')['$ref']:
            schema.update(ref('TripMissionWithdrawal' if method == 'delete' and path.endswith('/participation') else 'TripMission'))
        elif schema.get('$ref') == ref('MissionList')['$ref']:
            schema.update(ref('TripWebMissionList' if path == ROOT else 'TripMissionList'))
    OPS[(method, trip_path)] = contract
for (method, path), schema in list(BODY.items()):
    contract = deepcopy(schema)
    if path.startswith('/v1/native/'):
        contract['properties']['functionalRevision'] = n('같은 업무 transaction에서 재검증할 현재 기기 기능 revision.', minimum=1, maximum=2147483647)
        if 'functionalRevision' not in contract['required']:
            contract['required'].append('functionalRevision')
    BODY[(method, path.replace('/rooms/', '/trips/'))] = contract
