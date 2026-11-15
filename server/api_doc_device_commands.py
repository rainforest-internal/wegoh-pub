"""기기 명령 HTTP 계약. 차량 제어 요청 계약과 물리 실행 검증을 구분한다."""
from api_doc_shared import entry,response,obj,s,n,b,arr,ref,nullable,TIME,READ,BROWSER,NATIVE
from api_doc_models import IDENT,ACCOUNT
strict=lambda fields,description:dict(obj(fields,description),additionalProperties=False)
ZERO=n('현재 revision. 미설정0, 변경 후 과거 값409.',minimum=0,maximum=2147483647)
ACTION=strict({'id':s('현재 서버 registry에 등록된 action ID. 기기 JSON으로 등록하지 않습니다.',maxLength=80),'revision':ZERO},'특정 action과 계약 버전. 빈 선택은 미래 action을 허용하지 않습니다.')
ACTIONS=dict(arr(ACTION,'이번에 명시 선택한 현재 action 목록. 11개 차량 제어를 등록하며 기존 허용에 자동 추가하지 않습니다.'),maxItems=16)
OPTION=strict({**ACTION['properties'],'label':s('서버가 검토한 동작명. 클라이언트id로이름을추정하지않습니다. 합성fixture값은실SDK지원이아닙니다.',maxLength=80),'argumentKind':{'type':'string','enum':['empty-object','hvac-celsius','hvac-fan','seat-switch','seat-level','window-position','switch'],'description':'온도·풍량·좌석 스위치·좌석 단계·창문 열림·전역 스위치 계약. 실제 차량 capability 범위는 실행 전에 별도 확인합니다.'}},'응답표시전용. 목적쓰기입력에는id/revision두필드만보냅니다.')
OPTIONS=arr(OPTION,'신뢰서버action에명시된표시/인자계약만. 등록은 물리 지원 증명이 아닙니다.')
HOURS=n('명시 허용기간. 실제 만료는 현재 방/기기 만료와의 최솟값.',enum=[1,4,12,24])
EVENT=s('동일 조작 재시도에 재사용하는16~96자 영숫자/_/-. token이나 개인정보를 넣지 않습니다.',pattern='^[A-Za-z0-9_-]{16,96}$')
ACCESS={'revision':ZERO,'consent':b('기존 읽기 목적과 별도인 명시 허용. 기본false.'),'expiresInHours':HOURS,'actions':ACTIONS}
STAGE=s('저장·배송·수신·SDK접수·상태callback·미확인을 구분합니다. 물리 실행 증명은 아닙니다.',enum=['queued','delivered','received','sdk-accepted','state-confirmed','unknown','rejected','cancelled','expired'])
SEAT=s('차량 좌석 영역. 운전석(ROW_1_LEFT)은 원격 조작에서 제외합니다. 실제 지원 여부는 차량에서 확인합니다.',enum=['ROW_1_CENTER','ROW_1_RIGHT','ROW_2_LEFT','ROW_2_CENTER','ROW_2_RIGHT','ROW_3_LEFT','ROW_3_CENTER','ROW_3_RIGHT'])
EMPTY={'const':{},'description':'인자가 없는 등록 action과 실행 전 거절/미확인 ACK.'}
WINDOW=s('열림 비율을 조작할 측면 창문. 운전석 창문(ROW_1_LEFT)과 지붕·앞유리·뒷유리는 금지합니다.',enum=['ROW_1_RIGHT','ROW_2_LEFT','ROW_2_RIGHT'])
SWITCH=b('켜기 true / 끄기 false. 숫자 0/1은 허용하지 않습니다.')
LEVEL=n('정수 0..10. 실제 차량 capability 범위로 더 제한합니다. bool과 소수는 금지합니다.',minimum=0,maximum=10)
ARGUMENTS={
 'hvac-celsius':strict({'seat':SEAT,'value':dict(n('설정 온도. 섭씨 0..50의 유한 수. bool은 금지합니다.',minimum=0,maximum=50),type='number')},'정확히 seat/value.'),
 'hvac-fan':strict({'seat':SEAT,'value':n('풍량 정수 0..100. bool과 소수는 금지합니다.',minimum=0,maximum=100)},'정확히 seat/value.'),
 'seat-switch':strict({'seat':SEAT,'value':SWITCH},'정확히 seat/value.'),
 'seat-level':strict({'seat':SEAT,'value':LEVEL},'정확히 seat/value.'),
 'window-position':strict({'window':WINDOW,'value':n('요청한 열림 비율. 정수 0=닫힘, 100=완전 열림. 원시 SDK 값이 아닙니다.',minimum=0,maximum=100)},'정확히 window/value.'),
 'switch':strict({'value':SWITCH},'정확히 value. seat/window 금지.')}
ARGS={'anyOf':[EMPTY,*ARGUMENTS.values()],'description':'action의 argumentKind에 맞는 정확한 키·타입·범위를 검사합니다. 서버 상한은 차량 지원 범위가 아닙니다.'}
PROPERTIES={
 'hvac-celsius':['TARGET_CELSIUS'],'hvac-fan':['FAN_LEVEL'],
 'seat-switch':['GLOBAL_POWER','AC','AIR_CLEANER','READING_LIGHT','AMBIENT_LIGHT'],
 'seat-level':['SEAT_HEAT','SEAT_VENTILATION'],'window-position':['WINDOW_POSITION'],
 'switch':['CABIN_LIGHT']}
DRIVING_REJECTION=strict({'reason':{'const':'driving-restricted','description':'주행 중이라 차량이 실행하지 않았습니다.'}},'rejected 전용. 요청의 reason에 그대로 남습니다.')
EVIDENCE={'anyOf':[EMPTY,DRIVING_REJECTION],'description':'빈 증거는 received/unknown/rejected만. rejected는 주행 중 거절이면 {reason:"driving-restricted"}를 보냅니다. 성공 증거는 요청 ID·속성·area·value가 일치해야 합니다. 신규 bool/정수 kind는 타입도 같아야 합니다. 기존 온도·풍량 ACK는 bool을 거부하며 22와 22.0의 수치 동등 비교를 유지합니다.'}
for kind,arguments in ARGUMENTS.items():
 proof={'requestId':IDENT,'property':s('요청한 속성.',enum=PROPERTIES[kind]),**arguments['properties']}
 if kind=='hvac-fan':proof['value']=dict(proof['value'],type='number',description='요청 풍량과 같은 수치. 기존 ACK의 정수/실수 동등 비교를 유지합니다. bool은 금지합니다.')
 EVIDENCE['anyOf'] += [
  strict(dict(proof,kind={'const':'pleos-vehicle-setter-v1','description':'SDK setter 접수.'}),'sdk-accepted. 요청 area 키만 허용합니다.'),
  strict(dict(proof,kind={'const':'pleos-vehicle-getter-v1','description':'별도 getter 값 확인.'},receivedAtElapsedMillis=n('별도 getter 응답의 단조 수신 시각. bool/실수 금지.',minimum=0),capturedAtMillis={'type':'null','description':'OEM 캡처 시각 미제공.'}),'state-confirmed. 요청 percent/bool/단계 그대로이며 물리 실행 증명은 아닙니다.')]
MODELS={
 'CommandAction':ACTION,
 'CommandActionOption':OPTION,
 'CommandReceivedGrant':strict({'targetDeviceId':IDENT,'ownerId':ACCOUNT,'ownerName':s('현재room멤버의정본이름.'),'deviceName':s('이명시허용으로공개되는현재소유기기의정본이름.'),'grantRevision':ZERO,'expiresAt':TIME,'actions':OPTIONS},'소유자 자신의 방 명령 허용과 기기 수신 조건을 충족하는 연결 차량.'),
 'CommandAccess':obj({'deviceId':IDENT,'revision':ZERO,'consent':b('저장한 별도 목적. 현재유효성은active로 확인.'),'expiresAt':nullable(TIME),'actions':ACTIONS,'supportedControlActions':OPTIONS},'소유 기기 command-delivery 목적. 등록/인증서 조작 없음.'),
 'CommandMember':obj({'roomId':IDENT,'revision':ZERO,'consent':b('본인 계정의 현재 방 명령 참여. 기본false.'),'joinedAt':TIME,'expiresAt':nullable(TIME),'actions':ACTIONS},'기기 없는 요청자도 개인 웹 세션으로 별도 선택할 수 있습니다.'),
 'CommandGrant':obj({'roomId':IDENT,'deviceId':IDENT,'requesterId':ACCOUNT,'revision':ZERO,'consent':b('본인 계정에서 사용할 조작을 허용.'),'deviceRevision':ZERO,'participationRevision':ZERO,'ownerJoinedAt':TIME,'requesterJoinedAt':TIME,'expiresAt':nullable(TIME),'actions':ACTIONS},'현재 본인 계정·방 참여·기기·기간과 세 동의의 조작 교집합.'),
 'DeviceRequest':obj({'id':IDENT,'roomId':nullable(IDENT),'targetDeviceId':IDENT,'requesterId':ACCOUNT,'ownerId':ACCOUNT,'capabilityId':s('생성 때 실제 registry로 검증한 action.'),'capabilityRevision':ZERO,'stage':STAGE,'lastAcknowledgedStage':nullable(STAGE),'mayHaveExecuted':b('배송 뒤 취소해도 실행하지 않았다고 단정할 수 없습니다.'),'expiresAt':TIME,'createdAt':TIME,'reason':nullable(s('취소/기간/철회 등 현재 정본 이유. 차량이 주행 중이라 거절하면 driving-restricted.')),'physicalExecutionVerified':{'const':False,'description':'ACK/합성fixture를 독립적인 물리 실행 증명으로 표시하지 않습니다.'}},'인자를 다시 노출하지 않는 현재 상태. queued는저장/delivered는HTTP lease배송뿐.'),
 'CommandList':obj({'requests':arr(ref('DeviceRequest'),'현재 허용된 당사자만. 목록/inbox는 배송·수신ACK가 아닙니다.'),'serverNow':TIME,'supportedControlActions':OPTIONS},'기존 읽기 허용을 새 명령 목적에 사용하지 않습니다.'),
 'CommandLease':{'allOf':[ref('DeviceRequest'),obj({'arguments':ARGS,'leaseId':s('정확한 대상 기기에만 반환하는 짧은 lease. URL/WSS/로그에 넣지 않습니다.'),'leaseExpiresAt':TIME,'serverNow':dict(TIME,description='응답을 생성한 서버 UTC 시각입니다. 클라이언트는 요청 시작 단조 시각에 남은 lease 기간을 더해 보수적으로 제한하며 로컬 벽시계를 신뢰하지 않습니다.')},'claim 후 최대 30초이며 요청 만료를 넘지 않는 명시 배송 lease. 같은 claim으로 연장하지 않습니다. 실제 실행 직전에도 현재 동의를 확인해야 합니다.')]},
 'CommandCancellation':obj({'id':IDENT,'stage':STAGE,'mayHaveExecuted':b('배송된 효과를 rollback했다고 주장하지 않습니다.'),'physicalExecutionVerified':{'const':False,'description':'실차 확인 없음.'}},'뒤로는 이 취소 API를 자동 실행하지 않습니다.'),
 'CommandWithdrawal':obj({'status':{'const':'withdrawn','description':'명시 grant 철회.'},'revision':ZERO},'과거 UI revision으로 본인 철회를 막지 않습니다.'),
 'CommandRoomAccess':obj({'roomId':IDENT,'revision':ZERO,'consent':b('본인 웹 계정의 별도 목적.'),'joinedAt':TIME,'currentJoinedAt':TIME,'active':b('현재 epoch/기간까지 유효.'),'expiresAt':nullable(TIME),'actions':ACTIONS,'serverNow':TIME,'supportedControlActions':OPTIONS,'grants':arr(ref('CommandGrant'),'본인 계정과 차량에 저장한 허용.'),'receivedGrants':arr(ref('CommandReceivedGrant'),'본인이 현재 직접 조작할 수 있는 자기 차량.'),'participants':arr(obj({'accountId':ACCOUNT,'revision':ZERO,'joinedAt':TIME,'actions':ACTIONS,'active':b('본인 계정의 명시 참여.')},'현재 방의 자기 계정 참여 정보.'),'현재 revision으로 grant를 결합할 metadata.')},'본인 차량 조작을 위한 방별 허용.')}
MODELS['CommandAccessSnapshot']={'allOf':[ref('CommandAccess'),obj({'active':b('현재 기기/기간까지 허용됨.'),'serverNow':TIME,'physicalExecutionSupported':{'const':False,'description':'프로토콜과 실제물리지원분리.'}},'현재 기기 상태와 등록된 요청 계약.')] }
D='/v1/devices/{device}/command-access';R='/v1/social/rooms/{room}';G=R+'/device-command-grants/{device}/{peer}';Q=R+'/device-requests';M=R+'/device-command-access';I='/v1/device/command-inbox';C='/v1/device/requests/{identifier}'
BODY={('put',D):strict(ACCESS,'기기 소유자 별도 목적. 미래 action의 암묵 허용 없음.'),('put',M):strict(dict(ACCESS,joinedAt=TIME),'본인 현재 방 epoch/action 선택.'),('put',G):strict(dict(ACCESS,deviceRevision=ZERO,participationRevision=ZERO,ownerJoinedAt=TIME,requesterJoinedAt=TIME),'peer에는 기기 소유자 본인의 계정 ID를 사용합니다. 타인에게 허용하면 403입니다.'),('post',Q):strict({'eventId':EVENT,'targetDeviceId':IDENT,'grantRevision':ZERO,'capabilityId':s('검증 registry action. 미등록503/queue쓰기없음.',maxLength=80),'capabilityRevision':ZERO,'arguments':ARGS,'expiresInSeconds':n('요청5~300초. 동의 만료를 넘지 않습니다.',minimum=5,maximum=300)},'등록된 차량 제어 요청을 저장합니다. 미등록 action은503입니다.'),('post',C+'/claim'):strict({'claimId':EVENT},'정확한 현재 기기의 명시 배송.'),('post',C+'/ack'):strict({'ackId':EVENT,'leaseId':s('같은 claim 응답의 비공개 lease.',maxLength=100),'stage':s('received→sdk-accepted→state-confirmed. 거절/미확인 별도.',enum=['received','sdk-accepted','state-confirmed','rejected','unknown']),'evidence':EVIDENCE},'실제 registry validator가 필요하며 기기 상태문자열만 신뢰하지 않습니다.')}
OPS={}
ERRORS=['400','401','403','404','409','410','413','429','503']
EFFECT='GCM 별도목적/grant/요청·lease·ACK 정본과 기존devices/rooms 무효화만. 등록·인증서·위치보고·차량 앱이 receiverActive 상태이고 action별 주행 규제를 만족할 때 capability 검사를 거쳐 SDK setter를 한 번 시도할 수 있습니다. 실제 물리 실행 검증은 별개입니다.'
def add(method,path,summary,model,native=False,example=None,created=False):
 OPS[(method,path)]=entry('17 기기 명령 프로토콜',summary,(NATIVE if native else READ if method=='get' else BROWSER)+' 방 명령은 현재 소유자가 자기 차량에 허용한 조작·가입 세대·기간을 확인합니다. 동승자는 진행 중인 여행의 전용 리모컨을 사용합니다.','현재GET→사용자명시선택→정본revision변경. inbox/목록GET은배송이 아닙니다.',EFFECT,'응답불명은동일event/claim/ackID와동일본문으로재시도.409는재조회/명시선택.취소/뒤로는배송된효과rollback아님.',{'201'if created else'200':response(ref(model),'현재정본.물리성공주장없음.')},ERRORS,example=example,notes='여행 리모컨으로 허용할 수 있는 등록 action은 11개입니다. 차량 앱이 receiverActive 상태일 때 주행 중 동승자 조작으로 실행할 수 있는 액션은 hvac.temperature, hvac.fan, hvac.power, hvac.ac, hvac.air_cleaner, window.position, light.reading, light.ambient 8개입니다. seat.heat·seat.ventilation은 Pleos 시트 UX_RESTRICTIONS_NO_SETUP(64) 제약에 따라, light.cabin은 제품 결정에 따라 정차 중에만 실행합니다. 운전석(ROW_1_LEFT) 좌석·창문 요청은 400이며, 차량 앱은 운전석이 포함된 SDK 구역의 구역 조작(hvac.power 제외)도 거절합니다. 기존 동의는 확대하지 않습니다. 실차·마켓 승인과 OEM 주행 중 허용은 미검증입니다.')
empty={'revision':0,'consent':True,'expiresInHours':1,'actions':[]}
add('get',D,'본인 기기의 별도 명령 목적 읽기','CommandAccessSnapshot');add('put',D,'기기의 명령 목적/action판 명시 선택','CommandAccess',example=empty);add('delete',D,'기기 명령 목적 철회','CommandAccess')
add('get',M,'현재 방 명령 목적과 grant 정본 읽기','CommandRoomAccess');add('put',M,'본인 웹 계정의 방 명령 참여 선택','CommandMember',example=dict(empty,joinedAt='2026-10-28T00:00:00Z'))
add('put',G,'본인 계정에서 사용할 차량 조작 허용','CommandGrant',example=dict(empty,deviceRevision=1,participationRevision=1,ownerJoinedAt='2026-10-28T00:00:00Z',requesterJoinedAt='2026-10-28T00:00:00Z'));add('delete',G,'소유자가 peer grant 철회','CommandWithdrawal')
add('get',Q,'현재 허용된 본인 요청 상태 읽기','CommandList');add('post',Q,'등록 action에 짧은 요청 만들기','DeviceRequest',created=True,example={'eventId':'1'*32,'targetDeviceId':'2'*32,'grantRevision':1,'capabilityId':'unavailable','capabilityRevision':1,'arguments':{},'expiresInSeconds':30});add('delete',Q+'/{identifier}','본인 요청 명시 취소','CommandCancellation')
add('get',I,'현재 기기의 차량 요청 metadata 읽기','CommandList',native=True)
add('post',C+'/claim','짧은 명시 배송 lease 받기','CommandLease',native=True,example={'claimId':'3'*32});add('post',C+'/ack','기기 ACK 단계를 등록 계약과 대조','DeviceRequest',native=True,example={'ackId':'4'*32,'leaseId':'synthetic-format-only','stage':'received','evidence':{}})
# 410 exists only for a native principal (GRANT_EXPIRED from the native credential check) and for
# an expired delivery lease on claim/ack. Browser-only room/device consent routes never answer 410.
NATIVE_CAPABLE={('get',I),('post',C+'/claim'),('post',C+'/ack'),('get',M),('get',Q),('post',Q),('delete',Q+'/{identifier}')}
for key,doc in OPS.items():
 if key not in NATIVE_CAPABLE:doc['errors']=[code for code in doc['errors'] if code!='410']
for suffix in ('/claim','/ack'):
 OPS[('post',C+suffix)]['errorDescriptions']={'410':'Command lease expired(배송 lease 기한 경과) 또는 GRANT_EXPIRED(차량 연결 원 기한 경과)입니다. '
  '명령이 실행됐다고 추정하지 말고 inbox를 다시 읽습니다.'}
# Reading the device consent or the vehicle inbox has no state conflict (inbox skips stale requests).
for key in (('get',D),('get',I)):OPS[key]['errors']=[code for code in OPS[key]['errors'] if code!='409']
