"""Exact phone consent and Native projection for per-device, per-room Voice; each direction is independent."""
import copy
from api_doc_native_functional import TAG, ID, obj, ref, ERROR, BOUNDARY
from native_room_voice_authority import CONTRACT

R={'type':'integer','minimum':0,'maximum':2147483647}
FIELDS={
 'authorizationVersion':{'type':'integer','const':1,'description':'단일 공개 인증 계약의 정수 1입니다. 방별 고지 개정 번호와 구분합니다.'},
 'deviceId':dict(ID,description='현재 본인 연결의 기기 ID입니다. 다른 기기와 공유하지 않습니다.'),
 'grantId':dict(ID,description='직전 GET의 현재 개인 grant ID입니다. 재연결의 새 grant는 이전 방 동의를 상속하지 않습니다.'),
 'roomId':dict(ID,description='현재 본인이 참여한 여행방 ID입니다. 다른 방 동의를 대신하지 않습니다.'),
 'revision':dict(R,description='이 grant와 방의 현재 동의 revision입니다. 최초 0이며 PUT은 직전 GET 값과 같아야 한 번 반영됩니다.'),
 'functionalRevision':dict(R,description='현재 전역 기능 동의 revision입니다. 기본 credential epoch와 별개이며 PUT 때 같은 transaction에서 일치를 확인합니다.'),
 'memberJoinedAt':{'type':'string','format':'date-time','description':'현재 방 가입의 서버 UTC 시각입니다. 나갔다가 재가입하면 이전 값과 동의를 재사용하지 않습니다.'},
 'expiresAt':{'type':'integer','minimum':0,'maximum':253402300799,'description':'기능 동의, 방, 원 개인 연결 기한 중 가장 이른 Unix UTC 초입니다. 설정으로 연장하지 않습니다.'},
 'permissions':obj({
  'receiveVoice':{'type':'boolean','default':False,'description':'이 기기에서 이 방의 허용된 목소리를 들을지 직접 선택합니다. 송신 목적이나 마이크 권한을 요구하지 않습니다.'},
  'transmitVoice':{'type':'boolean','default':False,'description':'이 기기가 사용자의 명시 말하기 행동으로 이 방에 목소리를 보낼지 선택합니다. 수신 목적을 추가하지 않으며 실제 녹음에는 마이크 권한과 오디오 포커스가 필요합니다.'}}),
 'roomVoiceDisclosureVersion':{'type':'integer','const':CONTRACT['disclosureVersion'],'description':'폰에서 읽은 방별 음성 고지의 개정 번호입니다. 공개 인증 버전과 구분합니다.'},
 'roomVoiceDisclosureSha256':{'type':'string','const':CONTRACT['disclosureSha256'],'description':'현재 방별 음성 고지 전체의 canonical SHA256입니다. 오래된 지문으로 자동 재승인하지 않습니다.'}}
FIELDS['permissions']['description']='이 기기와 이 여행방에 대해 별도로 허용한 수신·송신 권한입니다. 두 방향은 독립적이며 전역 기능 동의와 현재 방 참여 권한도 모두 필요합니다.'
MODELS={
 'NativeRoomVoiceSnapshot':obj({k:copy.deepcopy(FIELDS[k])for k in CONTRACT['snapshotFields']}),
 'NativeRoomVoiceConsent':obj({k:copy.deepcopy(FIELDS[k])for k in CONTRACT['ownerPutFields']})}
MODELS['NativeRoomVoiceConsent']['properties']['functionalRevision']['minimum']=1
LIST_FIELDS=CONTRACT['roomList']
MODELS['NativeVoiceRoomItem']=obj({
 'roomId':dict(ID,description='현재 이 기기에 방별 음성을 명시 허용한 본인 참여 방의 ID입니다.'),
 'name':{'type':'string','minLength':1,'maxLength':80,'description':'현재 TeamRooms.access/review_name의 본인별 방 이름 투영입니다. 본인 소유는 원 이름, 타인 방은 현재 공유 검토 이름만, 아니면 기존 여행방 대체값입니다.'},
 'availableDirections':{'type':'array','minItems':1,'maxItems':2,'uniqueItems':True,'items':{'type':'string','enum':['receive','transmit']},'description':'현재 전역 목적과 이 기기 및 방의 명시 동의가 모두 유효한 방향입니다. 이 목록 자체는 권한이 아닙니다.'},
 'revision':dict(FIELDS['revision'],minimum=1),
 'memberJoinedAt':copy.deepcopy(FIELDS['memberJoinedAt']),
 'expiresAt':dict(FIELDS['expiresAt'],description='기본 access 자격, 인증서, 원 grant, 기능 및 방과 방별 동의의 기한 중 가장 이른 Unix UTC 초입니다.')})
MODELS['NativeVoiceRoomPage']=obj({
 'authorizationVersion':copy.deepcopy(FIELDS['authorizationVersion']),
 'deviceId':copy.deepcopy(FIELDS['deviceId']),'grantId':copy.deepcopy(FIELDS['grantId']),
 'functionalRevision':dict(FIELDS['functionalRevision'],minimum=1),
 'items':{'type':'array','maxItems':20,'items':ref('NativeVoiceRoomItem'),'description':'현재 이 연결에 새 방 이름 고지를 확인한 유효한 방만 방 ID 오름차순으로 최대 20개입니다. 전체 방 목록이 아닙니다.'},
 'nextCursor':{'anyOf':[copy.deepcopy(ID),{'type':'null'}],'description':'추가 적격 방이 있을 때만 직전 페이지 마지막 roomId입니다. 다음 페이지에 그대로 전달하며 자격이 아닙니다.'}})

EXAMPLE=dict(authorizationVersion=1,deviceId='d'*32,grantId='c'*32,roomId='a'*32,revision=0,functionalRevision=1,
 memberJoinedAt='2030-01-01T00:00:00+00:00',expiresAt=2000000000,permissions=dict(receiveVoice=False,transmitVoice=False),
 roomVoiceDisclosureVersion=CONTRACT['disclosureVersion'],roomVoiceDisclosureSha256=CONTRACT['disclosureSha256'])
APIS={
 'ownerGet':('get',CONTRACT['ownerPath'],'본인 기기의 방별 음성 공유 설정 보기'),
 'ownerPut':('put',CONTRACT['ownerPath'],'본인 기기의 방별 음성 공유 저장'),
 'ownerDelete':('delete',CONTRACT['ownerPath'],'본인 기기의 방별 음성 공유 끄기'),
 'nativeGet':('get',CONTRACT['nativePath'],'이 기기의 현재 방별 음성 동의 확인')}
ROOM_LINKED='여행에 연결된 내부 방 ID를 이 방 경로로 보내면 detail=TRIP_CLIENT_UPDATE_REQUIRED입니다. 여행은 /trips/{trip}/ 경로를 사용합니다.'
TRIP_ERROR=obj({'authorizationVersion':{'type':'integer','const':1,'description':'단일 공개 인증 계약의 정수 1입니다.'},'contractVersion':{'type':'integer','const':1,'description':'여행 계약 버전입니다.'},'error':{'type':'string','minLength':1,'description':'고정된 오류 코드이며 요청·계정·자격 내용을 반사하지 않습니다.'}})
TRIP_CONTEXT='여행 상태·명단 검사 결과는 TRIP_STATE_CONFLICT(진행 중 active가 아님), TRIP_CONTEXT_NOT_READY, TRIP_MEMBERSHIP_INCONSISTENT입니다.'
RETRY='응답 유실은 같은 GET으로 현재 정본을 확인합니다. 409는 현재 grant, 가입 시각, 두 revision과 고지를 다시 읽고 사용자 선택을 다시 받습니다. 자동 승인 재송신은 하지 않습니다. ROOM_VOICE_REVISION_EXHAUSTED는 조회로 해소되지 않으므로 변경을 중단하며 카운터를 초기화하지 않습니다.'
OPS={}
for key,(method,path,title)in APIS.items():
 OPS[(method,path)]=dict(tag=TAG,summary=title,prerequisites='본인 폰의 Access와 현재 개인 세션이 필요하며 변경은 같은 세션 CSRF도 필요합니다. Native 조회만 실제 mTLS와 현재 opaque Bearer를 사용합니다.',sequence='현재 기기와 방별 정본 및 고지를 읽고 명시한 선택만 저장합니다.',effects='grant와 기기, 현재 방 가입에 한정한 별도 동의입니다. 전역 기능 목적이나 기본 scope, credential epoch, 원 기한은 넓히지 않습니다. 조회는 승인하지 않습니다.',retry=RETRY,notes='Browser 계정의 방 voice bool과 별개입니다. 현재 방 음성을 저장하거나 음성 복제 또는 학습에 사용하지 않습니다.',responses={'200':{'description':'현재 방별 음성 동의입니다.','content':{'application/json':{'schema':ref('NativeRoomVoiceSnapshot')}}}},errors=['400','401','403','404','503'],example=None)

ROOM_LIST_KEY=('get',CONTRACT['roomList']['path'])
OPS[ROOM_LIST_KEY]=dict(tag=TAG,summary='이 기기에서 음성으로 연결할 여행방 선택 목록',prerequisites='현재 Native mTLS AND opaque Bearer와 음성 수신 또는 송신 목적 하나 이상이 필요합니다. rooms:read는 요구하지 않습니다.',sequence='목록에서 선택한 뒤 현재 기능 정본과 방별 own GET을 다시 읽고 그 revision으로 Voice WS에 연결합니다.',effects='현재 기기와 grant 및 현재 가입에 명시 동의한 방향의 방만 반환합니다. 새 방 이름 고지를 확인하지 않은 기존 동의는 이 목록에 자동 승계하지 않습니다. 승인이나 동의 변경은 없습니다.',retry='직전 nextCursor만 선택적으로 보냅니다. 철회나 만료 또는 devices invalidate 뒤에는 옛 화면을 지우고 명시 재조회합니다.',notes='기존 음성 송수신 동의를 다시 쓰지 않으며 방 이름 공유 철회는 기존 여행방 대체값으로 투영합니다.',responses={'200':{'description':'최대 20개 적격 방 선택 참조와 다음 cursor입니다.','content':{'application/json':{'schema':ref('NativeVoiceRoomPage')}}}},errors=['400','401','403','404','503'],example=None)

def apply_room_voice_documentation(original,auth):
 schema=copy.deepcopy(original);schema.setdefault('components',{}).setdefault('schemas',{}).update(copy.deepcopy(MODELS))
 feature=getattr(auth,'functional_access',None);enabled=bool(feature and feature.enabled and feature.base.enabled)
 for key,(method,path,title)in APIS.items():
  operation=schema['paths'][path][method];native=key=='nativeGet';mutate=method!='get'
  operation.update(operationId='nativeRoomVoice'+key[0].upper()+key[1:],summary=title,tags=[TAG],security=[{'NativeMTLS':[],'DeviceBearer':[]}]if native else[dict({'CloudflareAccess':[],'TeamSession':[]},**({'CurrentSessionCSRF':[]}if mutate else{}))],servers=[{'url':auth.native_origin if native else auth.public_origin}],**{'x-wegoh-native-access':native,'x-wegoh-executable':enabled and not native,'x-wegoh-feature-enabled':enabled})
  actor='현재 기기가 실제 mTLS와 같은 연결의 Bearer로 조회합니다. 브라우저 쿠키나 URL 자격은 사용할 수 없습니다.'if native else'본인 폰 웹의 현재 Access와 개인 세션으로 조회하며 변경은 같은 세션의 CSRF도 필요합니다. Native 요청은 승인할 수 없습니다.'
  effect='최초에는 두 값이 false입니다. receiveVoice에는 room-voice:receive만, transmitVoice에는 room-voice:transmit만 현재 승인되어야 합니다. 두 방향은 독립이며 rooms:read나 반대 목적을 요구하지 않습니다. Native 본인 GET은 두 음성 목적 중 하나 이상으로 허용합니다. 방별 선택이 전역 목적을 자동 추가하지 않습니다. 다른 소유자, 만료, 철회, 이전 grant는 거절합니다.'
  if key=='ownerPut':effect+=' 정확 8필드만 받고 최대 12288바이트, 본문 수신 제한 5초입니다. 가입 시각과 전역 기능 revision, 방별 revision을 같은 transaction에서 확인해 한 번 저장합니다.'
  if key=='ownerDelete':effect+=' 본문 없이 이 기기의 이 방 두 동의를 즉시 끕니다. 이 기기의 이 방에서 두 방향을 중단하고 대기 음성을 지웁니다. 이미 전달된 소리는 되돌릴 수 없으며 다른 기기, Browser 동의와 원기록은 보존합니다. 반복 해제는 권한을 만들지 않습니다.'
  operation['description']='**호출 주체** '+actor+'\n\n**권한과 효과** '+effect+'\n\n**수명과 철회** 전역 목적은 해당 방향만 철회합니다. 현재 연결은 revision 변경으로 종료되지만 남은 방향은 명시 재개할 수 있습니다. 방 나가기, 기기 해제, 만료 뒤 재승인이나 재등록만으로 예전 동의가 부활하지 않습니다. Browser 방 voice bool과 Native 동의는 별개입니다. 새 방 가입이나 새 grant는 폰에서 별도 선택해야 합니다. devices invalidate를 받으면 정본을 다시 읽고 예전 표시를 지웁니다.\n\n**재시도** '+RETRY
  operation['parameters']=[dict(name=name,**{'in':'path'},required=True,description=FIELDS['deviceId'if name=='device'else'roomId']['description'],schema=copy.deepcopy(ID),example=('d'if name=='device'else'a')*32)for name in ('device','room')if'{'+name+'}'in path]
  if key=='ownerPut':operation['requestBody']=dict(required=True,description='직전 GET과 현재 고지를 읽은 본인의 선택입니다. 알 수 없는 필드와 중복 키는 거절합니다.',content={'application/json':{'schema':ref('NativeRoomVoiceConsent'),'example':{k:EXAMPLE[k]for k in CONTRACT['ownerPutFields']}}})
  else:operation.pop('requestBody',None)
  operation['responses']={'200':dict(description='현재 방별 정본입니다. HTTP200은 동의나 음성 송수신 성공을 자동 생성하지 않습니다.',headers={'Cache-Control':{'schema':{'type':'string'},'description':'private, no-store'}},content={'application/json':{'schema':ref('NativeRoomVoiceSnapshot'),'example':copy.deepcopy(EXAMPLE)}})}
  for code,text in {400:'타입, ID, 중복 키, 알 수 없는 필드를 확인합니다.'if key=='ownerPut'else'경로의 기기·방(여행) ID 형식이 틀렸습니다(INVALID_FUNCTIONAL_REQUEST). 본문은 받지 않습니다.',401:'현재 계정 또는 개인 자격이 유효하지 않습니다.',403:'현재 기능 목적, 방별 동의, Origin 또는 CSRF가 부족합니다.'if method!='get'else'현재 기능 목적이나 방별 동의가 부족하거나 팀 권한이 없습니다. 조회는 Origin·CSRF를 확인하지 않습니다.',404:'기능이 꺼져 있거나 현재 본인 기기 또는 참여 방을 사용할 수 없습니다.',503:'동의 또는 저장소 무결성을 확인할 수 없습니다.'}.items():operation['responses'][str(code)]={'description':text,'content':{'application/json':{'schema':{'oneOf':[ERROR,BOUNDARY]}}}}
  if key=='ownerPut':
   for code,text in {408:'본문 수신이 5초를 넘긴 REQUEST_TIMEOUT입니다. 정본 GET을 확인하고 자동 승인 재전송하지 않습니다.',409:ROOM_LINKED+' '+RETRY,413:'본문은 최대 12288바이트입니다.'}.items():operation['responses'][str(code)]={'description':text,'content':{'application/json':{'schema':{'oneOf':[ERROR,BOUNDARY]}}}}
   operation.pop('x-wegoh-body-contract',None)
  else:operation['responses']['409']={'description':ROOM_LINKED,'content':{'application/json':{'schema':copy.deepcopy(BOUNDARY),'example':{'detail':'TRIP_CLIENT_UPDATE_REQUIRED'}}}}

 operation=schema['paths'][ROOM_LIST_KEY[1]][ROOM_LIST_KEY[0]]
 operation.update(operationId='nativeVoiceRoomList',summary=OPS[ROOM_LIST_KEY]['summary'],tags=[TAG],description=OPS[ROOM_LIST_KEY]['prerequisites']+'\n\n'+OPS[ROOM_LIST_KEY]['sequence']+'\n\n'+OPS[ROOM_LIST_KEY]['effects']+'\n\n'+OPS[ROOM_LIST_KEY]['notes']+'\n\n20개 적격 결과 뒤 한 개를 더 확인한 경우에만 nextCursor를 보냅니다. 중복, 빈 값, 다른 query 또는 URL 자격은 거절합니다.',security=[{'NativeMTLS':[],'DeviceBearer':[]}],servers=[{'url':auth.native_origin}],**{'x-wegoh-native-access':True,'x-wegoh-executable':False,'x-wegoh-feature-enabled':enabled})
 operation['parameters']=[dict(name='cursor',**{'in':'query'},required=False,description='직전 nextCursor의 소문자 32hex 방 ID 하나만 허용합니다. 첫 페이지는 생략하며 중복이나 추가 query는 거절합니다.',schema=copy.deepcopy(ID),example='a'*32)]
 operation.pop('requestBody',None)
 operation['responses']={'200':{'description':'현재 기기 및 grant의 적격 방만 반환합니다. 빈 배열은 새 동의나 숨겨진 방 수를 나타내지 않습니다.','content':{'application/json':{'schema':ref('NativeVoiceRoomPage'),'example':dict(authorizationVersion=1,deviceId='d'*32,grantId='c'*32,functionalRevision=1,items=[],nextCursor=None)}}}}
 for code,text in {400:'허용된 소문자 32hex cursor 하나인지 확인합니다.',401:'현재 개인 자격이나 동일 인증서를 확인할 수 없습니다.',403:'현재 음성 목적이 하나도 없습니다.',404:'Native 또는 기능을 사용할 수 없습니다.',503:'현재 동의나 저장소 무결성을 확인할 수 없습니다.'}.items():operation['responses'][str(code)]={'description':text,'content':{'application/json':{'schema':{'oneOf':[ERROR,BOUNDARY]}}}}
 schema['x-wegoh-voice']['nativeAccess']=True
 schema['x-wegoh-voice']['native']={
  'path':'/v1/social/rooms/{room}/voice',
  'host':auth.native_origin,
  'security':[{'NativeMTLS':[],'DeviceBearer':[]}],
  'queryAllowed':False,'cookieOrOriginAllowed':False,'subprotocolCredentialsAllowed':False,
  'preconditions':{'X-WegoH-Functional-Revision':dict(type='integer',minimum=1,maximum=2147483647),'X-WegoH-Room-Voice-Revision':dict(type='integer',minimum=1,maximum=2147483647)},
  'admission':'(room-voice:receive AND receiveVoice) OR (room-voice:transmit AND transmitVoice); same current grant/key/join/member/block/expiry, no rooms:read dependency',
  'receive':'Only current room-voice:receive AND this saved receiveVoice permits PCM delivery. No microphone permission required.',
  'transmit':'Only current room-voice:transmit AND this saved transmitVoice permits floor/binary. Client must separately hold foreground mic permission and audio focus.',
  'lifetime':'Pinned functional/room revisions; fresh short authority transactions per frame/control/delivery and idle250ms. Withdrawal closes old socket and owned queues; no automatic reopen or consent revival.',
  'audioPersisted':False,'transport':'TLS1.3 WSS, exact verified same-certificate opaque Bearer; production edge must overwrite all client-selected certificate metadata'}

 for key,(method,path,title) in APIS.items():
  if '{room}' not in path:continue
  trip_path=path.replace('/rooms/{room}/','/trips/{trip}/')
  if trip_path not in schema['paths']:continue
  operation=copy.deepcopy(schema['paths'][path][method])
  operation['operationId']='nativeTripVoice'+key[0].upper()+key[1:]
  operation['summary']=title.replace('방','여행')
  operation['description']+=' 여행 DTO는 tripId/contractVersion=1을 사용하고 roomId는 숨깁니다. 기존 저장 허가 기한을 늘리지 않습니다. 이 가입에 저장된 선택이 없는 여행은 본인의 여행 voice 공유 설정이 켜져 있으면 승인된 음성 목적의 방향이 revision 0에서 true로 시작합니다. 저장된 선택(끄기 포함)이 있으면 그 값이 우선하고, 재참여는 새 가입이므로 다시 이 기본값에서 시작합니다. 여행이 진행 중(active)이 아니거나 탈퇴했으면 GET은 permissions를 모두 false로 반환하고, DELETE와 모두 false인 PUT은 계속 허용합니다. 하나라도 켜는 PUT은 진행 중 여행의 현재 수락 멤버만 할 수 있습니다.'
  for parameter in operation['parameters']:
   if parameter['name']=='room':parameter.update(name='trip',description='현재 본인이 참여한 여행의 32hex ID입니다. 내부 방 ID는 받지 않습니다.',example='a'*32)
  response=operation['responses']['200']['content']['application/json']
  response['schema']=ref('NativeTripVoiceSnapshot')
  if key=='nativeGet':
   response['schema']=ref('NativeTripVoiceRuntime')
   operation['description']='현재 기기가 실제 mTLS와 같은 연결의 Bearer 및 rooms:read로 조회합니다. 진행 중(active) 여행의 수락 멤버 본인의 계정 참여 설정을 읽습니다. receiveVoice와 transmitVoice는 같은 participating 값이며, revision은 계정과 여행의 음성 참여 변경 번호입니다. 현재 grant·functionalRevision·가입 시각·기한을 유지합니다. 이 기기의 방향별 저장값이나 전역 room-voice 목적은 이 여행의 참여를 바꾸지 않습니다. 참여는 PATCH /v1/social/trips/{id}/sharing의 voice 설정이 결정합니다. 실제 수신에는 rooms:read, 송신에는 rooms:interact가 필요합니다. 마이크 접근은 해당 Android 앱에서 별도로 허용받고 말하기 동작에서만 사용합니다.'
  else:
   operation['description']+=' 이 기기·여행 저장값은 여행 워키토키 WSS와 음성 메시지 송수신 판단에 쓰이지 않습니다. 여행 음성 참여는 계정의 PATCH /v1/social/trips/{id}/sharing voice 설정이 결정합니다.'
  for code,result in operation['responses'].items():
   if code!='200':result['content']={'application/json':{'schema':{'oneOf':[copy.deepcopy(TRIP_ERROR),copy.deepcopy(BOUNDARY)]}}}
  if method=='put':operation['responses']['400']['description']+=' 여행 PUT은 tripId와 contractVersion=1도 정확히 보내야 하며 아니면 INVALID_TRIP_PERMISSION_REQUEST입니다.'
  operation['responses']['404']['description']+=' 이 여행에 본인 참여 기록이 없으면 TRIP_UNAVAILABLE입니다.'
  if key=='ownerGet':operation['responses'].pop('409',None)
  elif key=='ownerDelete':operation['responses']['409']['description']='ROOM_VOICE_REVISION_EXHAUSTED: 저장 revision이 상한에 도달했습니다. 조회로 해소되지 않으므로 변경을 중단합니다.'
  elif key=='nativeGet':
   operation['responses']['409']['description']=TRIP_CONTEXT+' 여행 상세를 다시 읽습니다.'
   operation['responses']['403']['description']+=' 서버의 음성 기능이 꺼져 있으면 TRIP_VOICE_UNAVAILABLE입니다.'
   operation['responses']['404']['description']+=' 수락 멤버 중 차단 관계가 있으면 ROOM_UNAVAILABLE입니다.'
  else:operation['responses']['409']['description']=RETRY+' 켜는 선택은 '+TRIP_CONTEXT
  example=response.get('example',{})
  example.pop('roomId',None);example.update(tripId='a'*32,contractVersion=1)
  if method=='put':
   body=operation['requestBody']['content']['application/json']
   body['schema']=ref('NativeTripVoiceConsent')
   body['example'].update(tripId='a'*32,contractVersion=1)
  schema['paths'][trip_path][method]=operation

 if any(path.startswith('/v1/social/trips/') for path in schema['paths']):
  schema['x-wegoh-trip-voice']=copy.deepcopy(schema['x-wegoh-voice'])
  schema['x-wegoh-trip-voice']['path']='/v1/social/trips/{trip}/voice'
  schema['x-wegoh-trip-voice']['authority']='Current accepted active trip and one account participation setting shared by browser and native. Device microphone permission remains local. Native identity, finite original grants, current joinedAt and independent voice revision remain required. Blocking stops only the two parties; other participants continue. Legacy linked room paths deny 409/404.'
  schema['x-wegoh-trip-voice']['native']['path']='/v1/social/trips/{trip}/voice'
  schema['x-wegoh-trip-voice']['native']['preconditions']['X-WegoH-Room-Voice-Revision']['minimum']=1
  schema['x-wegoh-trip-voice']['native']['admission']='Current same-certificate native grant with rooms:read for receive and rooms:interact for transmit, current functional revision, account trip participation, current membership and voice revision. Legacy device direction grants are not used for trip voice.'
  schema['x-wegoh-trip-voice']['native']['receive']='Current account trip participation and rooms:read allow delivery. Device microphone permission is not required for listening.'
  schema['x-wegoh-trip-voice']['native']['transmit']='Current account trip participation and rooms:interact allow floor requests; the client sends only while its microphone button is held with local microphone permission and foreground safety.'

 for path,operations in list(schema['paths'].items()):
  if not path.startswith('/v1/social/trips/{room}/voice/'):continue
  legacy=path.replace('/trips/','/rooms/')
  if legacy not in schema['paths']:continue
  for method in list(operations):
   if method not in schema['paths'][legacy]:continue
   # The catalog already authored the trip contract; keep it and only give browser-only trip calls a stable id.
   if operations[method].get('x-wegoh-native-access'):continue
   operations[method]['operationId']='tripVoice'+method.title()+path.rsplit('/voice/',1)[1].replace('/','_').replace('{','').replace('}','')
 return schema

for (method,path),operation in list(OPS.items()):
 if '{room}' in path:
  trip_path=path.replace('/rooms/{room}/','/trips/{trip}/')
  value=copy.deepcopy(operation)
  value['summary']=value['summary'].replace('방','여행')
  value['effects']+=' tripId와 contractVersion=1의 새 DTO를 사용합니다. 내부 방 ID와 유한하지 않은 허가 기한은 내보내지 않습니다.'
  OPS[(method,trip_path)]=value

for model_type in ('Snapshot','Consent'):
 model=copy.deepcopy(MODELS['NativeRoomVoice'+model_type])
 model['properties'].pop('roomId',None)
 model['properties'].update(tripId=dict(ID,description='수락한 여행 ID입니다.'),contractVersion={'type':'integer','const':1,'description':'여행 계약 버전입니다.'})
 model['required']=[key for key in model['required'] if key!='roomId']+['tripId','contractVersion']
 MODELS['NativeTripVoice'+model_type]=model
MODELS['NativeTripVoiceRuntime']=copy.deepcopy(MODELS['NativeTripVoiceSnapshot'])
MODELS['NativeTripVoiceRuntime']['properties']['revision'].update(minimum=1,description='현재 계정과 여행의 독립 음성 참여 변경 번호입니다.')
MODELS['NativeTripVoiceRuntime']['properties']['permissions']['description']='두 값 모두 현재 계정의 여행 워키토키 참여 설정에서 결정합니다. 마이크 권한이나 실제 송신 시작 상태가 아닙니다.'
for field in MODELS['NativeTripVoiceRuntime']['properties']['permissions']['properties'].values():
 field.update(description='현재 계정이 이 여행의 워키토키에 참여하면 true입니다. 실제 마이크 사용은 사용자가 누르는 동안만 허용합니다.')
BODY={('put','/v1/devices/{device}/trips/{trip}/voice-permissions'):copy.deepcopy(MODELS['NativeTripVoiceConsent'])}
