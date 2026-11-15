"""Exact phone consent and Native projection for per-device, per-room music."""
import copy
from api_doc_native_functional import TAG, ID, obj, ref, ERROR, BOUNDARY
from native_room_music_authority import CONTRACT

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
 'permissions':dict(obj({
  'receiveMusic':{'type':'boolean','default':False,'description':'이 기기에서 이 방에 현재 공유 가능한 음악 목록과 링크를 볼지 직접 선택합니다.'},
  'shareMusic':{'type':'boolean','default':False,'description':'이 기기에서 이 방에 본인 음악 목록을 공유할지 직접 선택합니다. 실제 공유는 현재 DJ 역할과 별도 권리 확인도 필요합니다.'}}),description='현재 개인 grant·기기·방 가입에 한정한 수신과 공유의 별도 선택입니다. 기본은 모두false이며 전역 기능 목적을 자동 추가하지 않습니다.'),
 'roomMusicDisclosureVersion':{'type':'integer','const':CONTRACT['disclosureVersion'],'description':'폰에서 읽은 방별 음악 고지의 개정 번호입니다. 공개 인증 버전과 구분합니다.'},
 'roomMusicDisclosureSha256':{'type':'string','const':CONTRACT['disclosureSha256'],'description':'현재 방별 음악 고지 전체의 canonical SHA256입니다. 오래된 지문으로 자동 재승인하지 않습니다.'}}
MODELS={
 'NativeRoomMusicSnapshot':obj({k:copy.deepcopy(FIELDS[k])for k in CONTRACT['snapshotFields']}),
 'NativeRoomMusicConsent':obj({k:copy.deepcopy(FIELDS[k])for k in CONTRACT['ownerPutFields']})}
MODELS['NativeRoomMusicConsent']['properties']['functionalRevision']['minimum']=1
EXAMPLE=dict(authorizationVersion=1,deviceId='d'*32,grantId='c'*32,roomId='a'*32,revision=0,functionalRevision=1,
 memberJoinedAt='2030-01-01T00:00:00+00:00',expiresAt=2000000000,permissions=dict(receiveMusic=False,shareMusic=False),
 roomMusicDisclosureVersion=CONTRACT['disclosureVersion'],roomMusicDisclosureSha256=CONTRACT['disclosureSha256'])
APIS={
 'ownerGet':('get',CONTRACT['ownerPath'],'본인 기기의 방별 음악 공유 설정 보기'),
 'ownerPut':('put',CONTRACT['ownerPath'],'본인 기기의 방별 음악 공유 저장'),
 'ownerDelete':('delete',CONTRACT['ownerPath'],'본인 기기의 방별 음악 공유 끄기'),
 'nativeGet':('get',CONTRACT['nativePath'],'이 기기의 현재 방별 음악 동의 확인')}
ROOM_LINKED='여행에 연결된 내부 방 ID를 이 방 경로로 보내면 detail=TRIP_CLIENT_UPDATE_REQUIRED입니다. 여행은 /trips/{trip}/ 경로를 사용합니다.'
TRIP_ERROR=obj({'authorizationVersion':{'type':'integer','const':1,'description':'단일 공개 인증 계약의 정수 1입니다.'},'contractVersion':{'type':'integer','const':1,'description':'여행 계약 버전입니다.'},'error':{'type':'string','minLength':1,'description':'고정된 오류 코드이며 요청·계정·자격 내용을 반사하지 않습니다.'}})
TRIP_MUSIC='/v1/social/trips/{trip}/music'
TRIP_DESCRIPTION={
 'ownerGet':' 여행 DTO는 tripId/contractVersion=1을 사용하고 roomId는 숨깁니다. 여행이 끝났거나 탈퇴했어도 본인 참여 기록이 있으면 조회되며, 이때 permissions는 모두 false입니다. 이 경로는 409를 반환하지 않습니다.',
 'ownerPut':' 여행 DTO는 tripId/contractVersion=1을 함께 보냅니다. 하나라도 true로 켜려면 계획·진행 중 여행의 현재 수락 멤버여야 합니다. 모두 false인 끄기는 종료·탈퇴 뒤에도 허용합니다. 저장 허가 기한은 기존 값보다 늘지 않습니다.',
 'ownerDelete':' 여행 DTO를 반환합니다. 종료·탈퇴 뒤에도 본인 참여 기록이 있으면 두 동의를 끄고 이 기기의 공유 선택을 지웁니다. 이 경로는 409를 반환하지 않습니다.',
 'nativeGet':' 여행 DTO를 반환합니다. 계획·진행 중 여행의 현재 수락 멤버만 조회합니다. 차량 여행 상세의 음악 요약은 이 기기의 receiveMusic과 전역 목적을 함께 확인합니다.'}
TRIP_CONTEXT='여행 상태·명단 검사 결과는 detail=TRIP_STATE_CONFLICT(계획·진행 중이 아님), TRIP_CONTEXT_NOT_READY, TRIP_MEMBERSHIP_INCONSISTENT입니다.'
RETRY='응답 유실은 같은 GET으로 현재 정본을 확인합니다. 409는 현재 grant, 가입 시각, 두 revision과 고지를 다시 읽고 사용자 선택을 다시 받습니다. 자동 승인 재송신은 하지 않습니다. ROOM_MUSIC_REVISION_EXHAUSTED는 조회로 해소되지 않으므로 변경을 중단하며 카운터를 초기화하지 않습니다.'
OPS={}
for key,(method,path,title)in APIS.items():
 OPS[(method,path)]=dict(tag=TAG,summary=title,prerequisites='본인 폰의 Access와 현재 개인 세션이 필요하며 변경은 같은 세션 CSRF도 필요합니다. Native 조회만 실제 mTLS와 현재 opaque Bearer를 사용합니다.',sequence='현재 기기와 방별 정본 및 고지를 읽고 명시한 선택만 저장합니다.',effects='grant와 기기, 현재 방 가입에 한정한 별도 동의입니다. 전역 기능 목적이나 기본 scope, credential epoch, 원 기한은 넓히지 않습니다. 조회는 승인하지 않습니다.',retry=RETRY,notes='Browser 계정의 방 music bool과 별개입니다. 원음원 재생이나 DRM 권한을 만들지 않습니다.',responses={'200':{'description':'현재 방별 음악 동의입니다.','content':{'application/json':{'schema':ref('NativeRoomMusicSnapshot')}}}},errors=['400','401','403','404','503'],example=None)

def apply_room_music_documentation(original,auth):
 schema=copy.deepcopy(original);schema.setdefault('components',{}).setdefault('schemas',{}).update(copy.deepcopy(MODELS))
 feature=getattr(auth,'functional_access',None);enabled=bool(feature and feature.enabled and feature.base.enabled)
 for key,(method,path,title)in APIS.items():
  operation=schema['paths'][path][method];native=key=='nativeGet';mutate=method!='get'
  operation.update(operationId='nativeRoomMusic'+key[0].upper()+key[1:],summary=title,tags=[TAG],security=[{'NativeMTLS':[],'DeviceBearer':[]}]if native else[dict({'CloudflareAccess':[],'TeamSession':[]},**({'CurrentSessionCSRF':[]}if mutate else{}))],servers=[{'url':auth.native_origin if native else auth.public_origin}],**{'x-wegoh-native-access':native,'x-wegoh-executable':enabled and not native,'x-wegoh-feature-enabled':enabled})
  actor='현재 기기가 실제 mTLS와 같은 연결의 Bearer로 조회합니다. 브라우저 쿠키나 URL 자격은 사용할 수 없습니다.'if native else'본인 폰 웹의 현재 Access와 개인 세션으로 조회하며 변경은 같은 세션의 CSRF도 필요합니다. Native 요청은 승인할 수 없습니다.'
  effect='최초에는 두 값이 false입니다. receiveMusic은 rooms:read와 room-music:read, shareMusic은 rooms:read와 room-music:control이 이미 명시 승인되어야 합니다. 방별 선택이 전역 목적을 자동 추가하지 않습니다. 다른 소유자, 만료, 철회, 이전 grant는 거절합니다.'
  if key=='ownerPut':effect+=' 정확 8필드만 받고 최대 12288바이트, 본문 수신 제한 5초입니다. 가입 시각과 전역 기능 revision, 방별 revision을 같은 transaction에서 확인해 한 번 저장합니다.'
  if key=='ownerDelete':effect+=' 본문 없이 이 기기의 이 방 두 동의를 즉시 끕니다. 송신 선택은 표적 삭제하지만 원음악 목록, 다른 기기의 동의, 다른 송신자의 원본은 삭제하지 않습니다. 반복 해제는 권한을 만들지 않습니다.'
  operation['description']='**호출 주체** '+actor+'\n\n**권한과 효과** '+effect+'\n\n**수명과 철회** 전역 목적 철회, 방 나가기, DJ 권한 상실, 기기 해제 뒤 재승인이나 재등록만으로 예전 공유가 부활하지 않습니다. 수신 철회는 송신자 원본을 지우지 않습니다. 새 방 가입이나 새 grant는 폰에서 별도 선택해야 합니다. devices invalidate를 받으면 정본을 다시 읽고 예전 표시를 지웁니다.\n\n**재시도** '+RETRY
  operation['parameters']=[dict(name=name,**{'in':'path'},required=True,description=FIELDS['deviceId'if name=='device'else'roomId']['description'],schema=copy.deepcopy(ID),example=('d'if name=='device'else'a')*32)for name in ('device','room')if'{'+name+'}'in path]
  if key=='ownerPut':operation['requestBody']=dict(required=True,description='직전 GET과 현재 고지를 읽은 본인의 선택입니다. 알 수 없는 필드와 중복 키는 거절합니다.',content={'application/json':{'schema':ref('NativeRoomMusicConsent'),'example':{k:EXAMPLE[k]for k in CONTRACT['ownerPutFields']}}})
  else:operation.pop('requestBody',None)
  operation['responses']={'200':dict(description='현재 방별 정본입니다. HTTP200은 동의나 음악 재생 성공을 자동 생성하지 않습니다.',headers={'Cache-Control':{'schema':{'type':'string'},'description':'private, no-store'}},content={'application/json':{'schema':ref('NativeRoomMusicSnapshot'),'example':copy.deepcopy(EXAMPLE)}})}
  for code,text in {400:'타입, ID, 중복 키, 알 수 없는 필드를 확인합니다.'if key=='ownerPut'else'경로의 기기·방(여행) ID 형식이 틀렸습니다(INVALID_FUNCTIONAL_REQUEST). 본문은 받지 않습니다.',401:'현재 계정 또는 개인 자격이 유효하지 않습니다.',403:'현재 기능 목적, 방별 동의, Origin 또는 CSRF가 부족합니다.'if method!='get'else'현재 기능 목적이나 방별 동의가 부족하거나 팀 권한이 없습니다. 조회는 Origin·CSRF를 확인하지 않습니다.',404:'기능이 꺼져 있거나 현재 본인 기기 또는 참여 방을 사용할 수 없습니다.',503:'동의 또는 저장소 무결성을 확인할 수 없습니다.'}.items():operation['responses'][str(code)]={'description':text,'content':{'application/json':{'schema':{'oneOf':[ERROR,BOUNDARY]}}}}
  if key=='ownerPut':
   for code,text in {408:'본문 수신이 5초를 넘긴 REQUEST_TIMEOUT입니다. 정본 GET을 확인하고 자동 승인 재전송하지 않습니다.',409:ROOM_LINKED+' '+RETRY,413:'본문은 최대 12288바이트입니다.'}.items():operation['responses'][str(code)]={'description':text,'content':{'application/json':{'schema':{'oneOf':[ERROR,BOUNDARY]}}}}
   operation.pop('x-wegoh-body-contract',None)
  else:operation['responses']['409']={'description':ROOM_LINKED,'content':{'application/json':{'schema':copy.deepcopy(BOUNDARY),'example':{'detail':'TRIP_CLIENT_UPDATE_REQUIRED'}}}}
 # Existing music business calls remain one current v1 path with distinct actors.
 from api_doc_room_music import BASE, SNAPSHOT, BROWSER_SNAPSHOT, DEVICE
 for method in ('get','put','delete'):
  operation=schema['paths'][BASE][method]
  operation['security']=[dict({'CloudflareAccess':[],'TeamSession':[]},**({'CurrentSessionCSRF':[]}if method!='get'else{})),{'NativeMTLS':[],'DeviceBearer':[]}]
  operation['x-wegoh-native-access']=True
  operation['servers']=[{'url':auth.public_origin,'description':'Browser account music consent'},{'url':auth.native_origin,'description':'Native global purposes AND per-grant/device/room consent'}]
  operation['responses']['200']['content']['application/json']['schema']={'oneOf':[copy.deepcopy(BROWSER_SNAPSHOT),copy.deepcopy(SNAPSHOT)]}
  if method=='get':
   browser=copy.deepcopy(BROWSER_SNAPSHOT);browser['not']={'required':['nativeReadOnly']}
   native=copy.deepcopy(SNAPSHOT)
   native['properties']['nativeReadOnly']={'type':'boolean','description':'Native GET에만 반환하며 canEdit의 반대입니다. true이면 이 조회 주체의 현재 DJ 역할, 전역 음악 쓰기 목적 또는 이 기기의 방별 공유 동의가 부족합니다. false도 실제 PUT의 현재 revision, 권리 및 권위 검사를 대신하지 않습니다.'}
   native['required']=list(native['required'])+['nativeReadOnly']
   operation['responses']['200']['content']['application/json']['schema']={'oneOf':[browser,native]}
   operation['responses']['200']['description']='Browser는 revision/canEdit/selection과 공유 playlist를 반환합니다. Native GET은 기존 revision/canEdit/selection/nativeReadOnly만 반환합니다.'
   operation['responses']['200']['content']['application/json']['examples']={'browser':{'value':dict(revision=0,canEdit=False,selection=None,playlist=dict(tracks=[],limit=200,canAdd=True))},'nativeReadOnly':{'value':dict(revision=0,canEdit=False,selection=None,nativeReadOnly=True)},'nativeDJ':{'value':dict(revision=0,canEdit=True,selection=None,nativeReadOnly=False)}}
  if method!='get':
   browser=copy.deepcopy(operation['requestBody']['content']['application/json']['schema']);native=copy.deepcopy(browser)
   native['properties'].update(functionalRevision=dict(FIELDS['functionalRevision'],minimum=1),roomMusicRevision=dict(FIELDS['revision'],minimum=1,description='직전 GET /v1/native/rooms/{room}/music-permissions의 revision입니다. shareMusic이 저장돼 있어야 하므로 1 이상이며 다르면 409 ROOM_MUSIC_REVISION_CHANGED입니다.'))
   native['required']=list(browser['required'])+['functionalRevision','roomMusicRevision'];native['additionalProperties']=False
   operation['requestBody']['content']['application/json']['schema']={'oneOf':[browser,native]}
   operation['requestBody']['content']['application/json']['examples']={'browser':{'value':copy.deepcopy(operation['requestBody']['content']['application/json']['example'])},'native':{'value':dict(operation['requestBody']['content']['application/json']['example'],functionalRevision=1,roomMusicRevision=1)}}
 for path in ('/v1/devices/{device}/music-permission','/v1/device/music-permission'):
  schema['paths'][path]['get']['responses']['200']['content']['application/json']['schema']=copy.deepcopy(DEVICE)
 for method in ('put','delete'):
  operation=schema['paths']['/v1/devices/{device}/music-permission'][method]
  operation['responses'].pop('200',None);operation['x-wegoh-executable']=False
  operation['deprecated']=True
  operation['x-wegoh-terminal-contract']='functional-permissions-required'
  operation['description']+=' 이 이전 변경 경로는 현재 소유자·세션·Origin/CSRF와 기기 상태를 검사한 뒤409로만 끝나며 동의를 바꾸지 않습니다. PUT은 기존 revision 정수와 enabled=true 본문 형식도 먼저 검사합니다. 변경은 현재 functional-permissions에서 명시 선택해야 하며 이 경로를 자동 재전송하지 않습니다.'
  operation['responses']['409']['content']={'application/json':{'schema':copy.deepcopy(BOUNDARY),'example':{'detail':'Use current functional permissions'}}}
  operation['responses']['409']['description']='Use current functional permissions: 이전 별도 저장 요청은 거절됩니다. 현재 functional-permissions의 정본을 읽고 사용자 선택을 새로 받습니다. 이 경로에 자동 재전송하지 않습니다.'

 for key,(method,path,title) in APIS.items():
  if '{room}' not in path:continue
  trip_path=path.replace('/rooms/{room}/','/trips/{trip}/')
  if trip_path not in schema['paths']:continue
  operation=copy.deepcopy(schema['paths'][path][method])
  operation['operationId']='nativeTripMusic'+key[0].upper()+key[1:]
  operation['summary']=title.replace('방','여행')
  operation['description']+=TRIP_DESCRIPTION[key]
  for parameter in operation['parameters']:
   if parameter['name']=='room':parameter.update(name='trip',description='현재 본인이 참여한 여행의 32hex ID입니다. 내부 방 ID는 받지 않습니다.',example='a'*32)
  response=operation['responses']['200']['content']['application/json']
  response['schema']=ref('NativeTripMusicSnapshot')
  example=response.get('example',{})
  example.pop('roomId',None);example.update(tripId='a'*32,contractVersion=1)
  if method=='put':
   body=operation['requestBody']['content']['application/json']
   body['schema']=ref('NativeTripMusicConsent')
   body['example'].update(tripId='a'*32,contractVersion=1)
  for code,result in operation['responses'].items():
   if code!='200':result['content']={'application/json':{'schema':{'oneOf':[copy.deepcopy(TRIP_ERROR),copy.deepcopy(BOUNDARY)]}}}
  operation['responses']['400']['description']+=' 여행 PUT은 tripId와 contractVersion=1도 정확히 보내야 하며 아니면 INVALID_TRIP_PERMISSION_REQUEST입니다.' if method=='put' else ''
  operation['responses']['404']['description']+=' 이 여행에 본인 참여 기록이 없으면 TRIP_UNAVAILABLE입니다.'
  if key in ('ownerGet','ownerDelete'):operation['responses'].pop('409',None)
  elif key=='nativeGet':operation['responses']['409']={'description':TRIP_CONTEXT+' 여행 상세를 다시 읽습니다.','content':{'application/json':{'schema':copy.deepcopy(BOUNDARY),'example':{'detail':'TRIP_STATE_CONFLICT'}}}}
  else:operation['responses']['409']['description']=RETRY+' 켜는 선택은 '+TRIP_CONTEXT
  schema['paths'][trip_path][method]=operation

 from api_doc_room_music import TRIP_LINK, BROWSER_SNAPSHOT as TRIP_BROWSER_SNAPSHOT
 def trip_shape(model):
  if '$ref' in model:
   model=copy.deepcopy(schema['components']['schemas'][model['$ref'].rsplit('/',1)[1]])
  model=copy.deepcopy(model)
  model.setdefault('properties',{}).update(tripId=dict(ID,description='현재 수락한 여행 ID입니다. 내부 방 ID와 구분하며 다른 여행의 자료를 조회할 수 없습니다.'),contractVersion={'type':'integer','const':1,'description':'여행 음악 응답 형식의 계약 버전입니다. 기기 인증 버전이나 공유 revision과 구분합니다.'})
  model.setdefault('required',[]).extend(['tripId','contractVersion'])
  if 'canEdit' in model['properties']:
   model['description']='여행 음악 정본입니다. 웹 응답이며 차량 Native 호스트는 이 경로를 쓰지 않습니다.'
   model['properties']['canEdit']=dict(model['properties']['canEdit'],description='현재 DJ이고 본인 여행 music 공유 설정이 켜져 있으면 true입니다.')
  for item in model['properties'].get('selection',{}).get('anyOf',[]):
   if item.get('type')=='object':
    item['properties'].update(kind={'const':'playlist-link','description':'멜론 플레이리스트 링크 선택일 때만 반환합니다.'},provider={'const':'melon','description':'링크 선택일 때만 반환하는 외부 음악 서비스입니다. 서버 재생 권한을 뜻하지 않습니다.'},url={'type':'string','format':'uri','description':'링크 선택일 때만 반환하는 검증·검토된 멜론 HTTPS 링크입니다. 각 사용자가 직접 열며 서버가 가져오거나 재생하지 않습니다.'},title={'type':'string','description':'링크 선택일 때만 반환하는 표시 제목입니다.'})
    item['description']=item.get('description','')+' 공유 곡 선택의 playlistId는 tripId로 바꿔 반환합니다.'
  return model
 browser={'CloudflareAccess':[],'TeamSession':[]}
 for path,operations in list(schema['paths'].items()):
  if not path.startswith('/v1/social/trips/{trip}/music'):continue
  legacy=path.replace('/trips/{trip}/','/rooms/{room}/')
  if legacy not in schema['paths']:continue
  for method,operation in operations.items():
   if method not in schema['paths'][legacy]:continue
   source=schema['paths'][legacy][method]
   # Trip music is a browser API: the native host answers 403 for these paths.
   operation['operationId']='tripMusic'+method.title()+path.split('/music',1)[1].replace('/','_').replace('{','').replace('}','')
   operation['security']=[dict(browser,**({'CurrentSessionCSRF':[]}if method!='get'else{}))]
   operation['servers']=[{'url':auth.public_origin}]
   operation['x-wegoh-native-access']=False;operation['x-wegoh-surface']='browser'
   operation.pop('x-wegoh-native-configured',None);operation.pop('x-wegoh-body-contract',None)
   operation['x-wegoh-executable']=source.get('x-wegoh-executable',True)
   for parameter in operation.get('parameters',[]):
    if parameter.get('name')=='trip':parameter['description']='현재 수락한 여행의 32hex ID입니다. 내부 방 ID는 받지 않습니다.'
   if 'requestBody' in source:
    body=copy.deepcopy(source['requestBody']);content=body['content']['application/json']
    if 'oneOf' in content['schema']:content['schema']=content['schema']['oneOf'][0]
    if 'examples' in content:content['example']=content.pop('examples')['browser']['value']
    if method=='put' and path==TRIP_MUSIC:
     content['schema']={'oneOf':[content['schema'],copy.deepcopy(TRIP_LINK)]}
    operation['requestBody']=body
    if 'x-wegoh-try-example' in source:operation['x-wegoh-try-example']=copy.deepcopy(source['x-wegoh-try-example'])
   success=next(code for code in operation['responses'] if code.startswith('2'))
   media=operation['responses'][success].setdefault('content',{}).setdefault('application/json',{})
   media['schema']=trip_shape(TRIP_BROWSER_SNAPSHOT if path==TRIP_MUSIC else media['schema'])
   media.pop('examples',None)
   if path==TRIP_MUSIC and method=='get':media['example']=dict(revision=0,canEdit=False,selection=None,playlist=dict(tracks=[],limit=200,canAdd=True),tripId='a'*32,contractVersion=1)
   schema['paths'][path][method]=operation
 return schema

for (method,path),operation in list(OPS.items()):
 if '{room}' in path:
  trip_path=path.replace('/rooms/{room}/','/trips/{trip}/')
  value=copy.deepcopy(operation)
  value['summary']=value['summary'].replace('방','여행')
  value['effects']+=' tripId와 contractVersion=1의 새 DTO를 사용합니다. 내부 방 ID와 유한하지 않은 허가 기한은 내보내지 않습니다.'
  OPS[(method,trip_path)]=value

for model_type in ('Snapshot','Consent'):
 model=copy.deepcopy(MODELS['NativeRoomMusic'+model_type])
 model['properties'].pop('roomId',None)
 model['properties'].update(tripId=dict(ID,description='수락한 여행 ID입니다.'),contractVersion={'type':'integer','const':1,'description':'여행 계약 버전입니다.'})
 model['required']=[key for key in model['required'] if key!='roomId']+['tripId','contractVersion']
 MODELS['NativeTripMusic'+model_type]=model
BODY={('put','/v1/devices/{device}/trips/{trip}/music-permissions'):copy.deepcopy(MODELS['NativeTripMusicConsent'])}
