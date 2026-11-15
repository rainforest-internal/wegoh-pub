"""Room DJ metadata and separately approved native reading; no audio proxy."""
from api_doc_shared import *
OPS={}
def add(method,path,*args,**kw):OPS[(method,path)]=entry(*args,**kw)
TAG='14 여행방 음악'
R=n('현재 방 음악 선택 revision. 비어 있는 최초 상태는0이며 변경에는 GET에서 읽은 값을 보냅니다.',minimum=0)
TRACK=obj({'id':IDENT,'title':s('본인 음악 목록에 저장하고 검토한 곡 제목.'),'url':s('권리를 확인한 원음원 HTTPS 링크. 서버는 이 주소를 가져오거나 음원을 복제하지 않습니다.',format='uri')},'음원 서비스에서 여는 metadata 한 곡.')
SELECTION=obj({'id':IDENT,'ownerId':ACCOUNT,'playlistId':IDENT,'playlistRevision':REV,'currentTrackId':IDENT,'name':s('검토 대상 음악 목록 이름.'),'tracks':arr(TRACK,'소유자 목록의 순서를 유지하는1~100곡.'),'review':ref('Review')},'활성 DJ가 선택한 현재 목록. 수신자는 현재 승인된 projection만 받습니다.')
SNAPSHOT=obj({'revision':R,'canEdit':b('현재 DJ이며 이 호출 주체의 공유 권한을 모두 충족하면 true입니다. Native는 별도 전역 목적과 이 기기의 방별 shareMusic 동의도 필요합니다.'),'selection':nullable(SELECTION)},'방 음악 정본. selection=null은 미선택, 철회, 현재 원권리 불충족 또는 검토 전 등 공유 가능한 목록이 없음을 뜻합니다.')
SHARED_TRACK=obj({'id':IDENT,'track':nullable(TRACK),'artist':nullable(s('검토 대상 아티스트 이름, 최대80자.')),'addedBy':nullable(obj({'id':ACCOUNT,'name':s('현재 추가자 표시 이름.')},'곡을 추가한 현재 참여자.')),'canDelete':b('본인 곡 또는 방장일 때 true.'),'review':nullable(ref('Review'))},'미공개 곡은 삭제 가능한 사람에게만 id와 삭제 권한을 남기고 내용을 숨깁니다.')
SHARED_PLAYLIST=obj({'tracks':arr(SHARED_TRACK,'추가순으로 표시하는 방당 최대200곡. 현재 가입·동의·검토 권한에 따라 숨깁니다.'),'limit':n('방당 최대 곡 수.',const=200),'canAdd':b('현재 방에 추가할 공간이 있는지 나타냅니다.')},'모든 동의한 현재 참여자가 함께 만드는 링크 목록.')
BROWSER_SNAPSHOT=obj({**SNAPSHOT['properties'],'playlist':SHARED_PLAYLIST},'브라우저 방 음악과 공유 플레이리스트 정본. Native 응답에는 playlist가 없습니다.')
DEVICE=obj({'authorizationVersion':n('단일 공개 인증 계약의 정수 1입니다.',const=1),'authority':s('단일 기능 동의 정본의 읽기 투영입니다.',const='native-functional'),'deviceId':IDENT,'revision':n('현재 기능 동의 revision의 읽기 투영입니다. 별도 저장 카운터가 아닙니다.',minimum=0),'functionalRevision':n('현재 기능 동의 revision입니다. revision과 같습니다.',minimum=0),'enabled':b('현재 전역 room-music:read 목적이 승인됐는지 나타냅니다. 방별 수신 동의를 대신하지 않습니다.')},'본인 기기의 전역 기능 동의를 읽기 투영합니다.')
BASE='/v1/social/rooms/{room}/music'
SHARED_BASE=BASE+'/playlist'
SHARED_ACCESS=BROWSER+' 현재 방 멤버이고 music 동의가 필요합니다. 종료·만료·탈퇴·차단 상태와 현재 계정을 transaction에서 재검사합니다. Native에서는 사용할 수 없습니다.'
SHARED_RETRY='rooms invalidate를 받으면 기존 표시를 지우고 GET music을 다시 읽습니다. 실패한 변경을 자동 재전송하지 않습니다.'
add('post',SHARED_BASE,TAG,'여행방 공유 목록에 곡 추가',SHARED_ACCESS,
 'title(120자), artist(80자), url(2048자)와 rightsConfirmed=true를 보냅니다. HTTPS host와443 포트, 인증정보·공백 금지를 확인합니다. 본문은4096바이트 이하입니다.',
 '암호화한 불변 곡을 추가순으로 저장합니다. 방당200곡, 계정당 분당10회입니다. 검토 요청은 별도이며 승인 전에는 추가자만 내용을 봅니다.',SHARED_RETRY,
 created(BROWSER_SNAPSHOT,'곡이 추가된 현재 방 음악입니다.'),['400','401','403','404','409','413','429','503'],example={'title':'함께 가는 길','artist':'아티스트','url':'https://music.example/song','rightsConfirmed':True})
add('delete',SHARED_BASE+'/{track}',TAG,'공유 곡 삭제',SHARED_ACCESS,
 '삭제할 곡ID를 경로에 보냅니다. 본문은 없습니다.',
 '추가자 또는 방장만 삭제합니다. 삭제한 곡이 현재곡이면 선택도 철회하고 rooms를 invalidate합니다. 방장은 비공개 곡도 내용을 보지 않고 삭제할 수 있습니다.',SHARED_RETRY,
 ok(BROWSER_SNAPSHOT),['401','403','404','409','503'])
add('patch',SHARED_BASE+'/{track}/review-request',TAG,'공유 곡 검토 요청·철회',SHARED_ACCESS,
 '추가자만 별도 consent 불리언을 보냅니다. 곡은 수정되지 않으므로ID가 정확 projection을 가리킵니다.',
 '기존 room-music 검토로 아티스트·제목·원곡 링크를 제출하거나 철회합니다. 동의 기본값은false이고 방 만료까지 유효합니다.',SHARED_RETRY,
 ok(ref('Review')),['400','401','403','404','409','413','503'],example={'consent':False})
add('post',SHARED_BASE+'/{track}/reports',TAG,'공유 곡 신고',SHARED_ACCESS,
 '현재 승인된 공유 곡의ID와 reason(harmful/privacy/rights/other)을 보냅니다.',
 '정확한 곡 projection을 기존 검토 경로로 재격리하고 rooms를 invalidate합니다. 선택된 현재곡도 원곡 승인 상태를 다시 검사합니다.',SHARED_RETRY,
 report(),['400','401','403','404','409','413','503'],example={'reason':'rights'})
ACCESS=READ+' Browser는 현재 방 멤버의 계정 music 동의, Native는 rooms:read와 room-music:read 및 해당 기기와 방의 receiveMusic 명시 동의를 모두 요구합니다.'
add('get',BASE,TAG,'여행방 현재곡·목록 조회',ACCESS,
 'Browser는 방의 music 동의, Native는 전역 기능 정본과 GET /v1/native/rooms/{room}/music-permissions를 각각 확인한 뒤 같은 방 음악 GET을 호출합니다.',
 'revision/canEdit/selection을 반환합니다. 현재 DJ의 해당 주체 권한과 역할, 원목록 revision, 콘텐츠 승인을 매번 재검사합니다. 다른 사용자에게는 승인된 metadata만 반환합니다. 음원재생·차량SDK 실행은 없습니다.',
 'snapshot/invalidate의 rooms 또는 devices 수신 시 화면을 지우고 정본을 재조회합니다. 연결 상실·방 만료·계정교체에도 이전 metadata를 지웁니다.',ok(SNAPSHOT),['401','403','404','409','503'])
add('put',BASE,TAG,'DJ가 현재 목록·곡 선택',BROWSER+' 또는 Native mTLS와 Bearer입니다. 현재 DJ이고 Browser는 본인 music 동의, Native는 rooms:read와 room-music:control 및 방별 shareMusic 동의가 필요합니다.',
 'GET music의 revision, 본인 GET playlists의 id/revision 및 그 안의 track id를 보냅니다. Browser는 승인된 방 공유 곡을 playlistId=room ID, playlistRevision=1, 해당 trackId로 선택할 수도 있습니다. Native는 현재 functionalRevision과 roomMusicRevision도 보냅니다. rightsConfirmed=true는 링크·metadata 공유 권리 확인이며 운영자 검토 동의와 별개입니다.',
 '암호화 원목록 또는 승인된 방 공유 곡을 참조해 선택을 저장하고 rooms를 invalidate합니다. 새 목록/버전과 다른 공유 곡 선택은 나만 보기로 시작하여 기존 현재곡 검토를 거칩니다. 같은 개인 목록의 곡만 바꾸면 기존 정확 metadata 검토는 유지됩니다. 다른 계정의 개인 목록/임의 metadata는 입력할 수 없습니다.',
 '409면 music와 본인 playlist를 재조회해 사용자 선택을 다시 받습니다. 응답 유실은 먼저 GET으로 확인하고 같은 오래된 revision을 재송신하지 않습니다.',ok(SNAPSHOT),['400','401','403','404','409','413','429','503'],
 example={'revision':0,'playlistId':'0'*32,'playlistRevision':1,'trackId':'1'*32,'rightsConfirmed':True})
add('delete',BASE,TAG,'음악 공유 중단',BROWSER+' 현재 DJ 또는 방장입니다. Native는 현재 DJ와 전역 rooms:read, room-music:control 및 방별 shareMusic도 필요합니다.',
 'GET music의 revision을 JSON본문으로 보냅니다. Native는 현재 functionalRevision과 roomMusicRevision도 보냅니다.',
 '파생 선택과 검토요청을 철회하고 rooms를 invalidate합니다. 본인 원음악목록은 삭제하지 않습니다. 이후 다시 켜도 이전 선택은 자동 복원되지 않습니다.',
 '응답 유실은 GET music으로 확인합니다.409는 정본을 다시 읽고 현재 대상을 확인합니다.',ok(SNAPSHOT),['400','401','403','404','409','413','503'],example={'revision':1})
add('patch',BASE+'/review-request',TAG,'음악 metadata 검토 요청·철회',BROWSER+' 현재 선택을 소유한 DJ만 요청할 수 있습니다.',
 'GET music의 revision과 별도 consent를 보냅니다. 운영자는 목록 이름·곡 제목·원곡 링크만 볼 수 있으며 제출 기본값은false입니다.',
 'true는 현재 정확 projection을 검토대기로 제출하고 false는 운영자와 다른 참여자 접근을 철회합니다. 공유하려면 실제 admin checksum 승인과 양쪽 음악 동의가 모두 필요합니다.',
 '수정된 revision은409이며 재조회 후 사용자가 제출 여부를 다시 선택합니다.',ok(ref('Review')),['400','401','403','404','409','413','503'],example={'revision':1,'consent':False})
add('post',BASE+'/reports',TAG,'공유 음악 metadata 신고',BROWSER+' 음악에 동의한 현재 수신자가 현재 승인된 selection만 신고할 수 있습니다.',
 '현재 GET music의 selection.id와 harmful/privacy/rights/other 중 reason을 보냅니다.',
 '정확 음악 projection을 검토대기로 재격리하고 방/관리자에게 invalidate합니다. 원음원·본인 원목록은 삭제하지 않습니다.',
 '202는 신고 접수이며 내용 판정 완료가 아닙니다. 응답 유실은 정본 상태를 먼저 확인합니다.',report(),['400','401','403','404','409','413','503'],example={'selectionId':'0'*32,'reason':'rights'})
PATH='/v1/devices/{device}/music-permission'
add('get',PATH,TAG,'본인 기기의 음악 기능 허용 상태',READ,
 '현재 본인 기기를 선택해 전역 기능 동의의 읽기 투영을 확인합니다.',
 'authorizationVersion=1, authority=native-functional과 같은 revision/functionalRevision 및 enabled를 반환합니다. enabled는 room-music:read만의 투영이며 방별 receiveMusic은 별도입니다.',
 '설정 변경은 기존 functional-permissions 정본을 사용하고 방별 동의는 rooms/{room}/music-permissions를 사용합니다.',ok(DEVICE),['400','401','403','404','503'])
add('put',PATH,TAG,'기존 음악 설정 요청의 정본 안내',BROWSER,
 '이전 revision/enabled 형식의 요청은 형식과 소유자를 확인한 뒤 409로 거절합니다.',
 '새 권한은 저장하지 않습니다. 현재 단일 functional-permissions 정본에서 본인이 명시 선택해야 합니다.',
 '409를 새 revision 재전송으로 해결하지 말고 정본 공유 설정으로 이동합니다.',{},['400','401','403','404','409','413','503'],example={'revision':0,'enabled':True})
add('delete',PATH,TAG,'기존 음악 해제 요청의 정본 안내',BROWSER,
 '이전 별도 음악 설정 경로이며 본문은 없습니다.',
 '현재 소유자를 확인한 뒤 409로 거절하며 권한을 바꾸지 않습니다. functional-permissions에서 해당 목적을 명시 해제합니다.',
 '다른 기기나 전역 계정 음악 동의를 대신 해제하지 않습니다.',{},['401','403','404','409','503'])
add('get','/v1/device/music-permission',TAG,'이 기기의 음악 기능 허용 상태',NATIVE,
 '현재 개인 mTLS와 Bearer로 조회합니다. 기기 ID를 따로 보내지 않습니다.',
 '현재 전역 room-music:read 승인 여부의 읽기 투영입니다. 방별 receiveMusic 승인이나 재생 권한을 생성하지 않습니다.',
 'devices invalidate 뒤 전역 및 해당 방별 정본을 다시 읽습니다.',ok(DEVICE),['401','403','404','503'])

TRIP_LINK=obj({'revision':R,'kind':{'const':'playlist-link','description':'DJ가 공유할 플레이리스트 링크 유형입니다. 자동 재생 요청이 아닙니다.'},'provider':{'const':'melon','description':'사용자가 링크를 직접 여는 멜론 음악 서비스입니다.'},'title':s('표시 제목, 최대120자.',maxLength=120),'url':s('검증한 melon.com/www.melon.com/m.melon.com HTTPS 링크. 각 차량에서 직접 엽니다.',format='uri',maxLength=2048),'rightsConfirmed':{'const':True,'description':'링크와 표시 metadata를 공유할 권리가 있음을 본인이 확인합니다. 콘텐츠 검토 동의나 재생 승인을 대신하지 않습니다.'}},'DJ가 공유하는 멜론 플레이리스트 링크. 재생 명령이 아닙니다.')
ROOM_LINKED='여행에 연결된 내부 방을 이 방 경로로 부르면 TRIP_CLIENT_UPDATE_REQUIRED입니다. 같은 동작은 /v1/social/trips/{trip}/music 경로로만 합니다.'
ROOM_CONFLICT={
 ('post',SHARED_BASE):'방 공유 목록이 이미200곡이면 Room playlist limit reached입니다. 곡을 지운 뒤 사용자가 다시 추가합니다. '+ROOM_LINKED,
 ('put',BASE):'Room music changed(revision 불일치), Music list changed(본인 목록 revision 변경), Room playlist entry changed(공유 곡 playlistRevision≠1), Choose a reviewed room track(공유 곡 미승인·차단)입니다. Native는 ROOM_MUSIC_REVISION_CHANGED(roomMusicRevision 불일치)와 FUNCTIONAL_REVISION_CHANGED도 받습니다. '+ROOM_LINKED,
 ('delete',BASE):'Room music changed(revision 불일치)입니다. Native는 ROOM_MUSIC_REVISION_CHANGED와 FUNCTIONAL_REVISION_CHANGED도 받습니다. '+ROOM_LINKED,
 ('patch',BASE+'/review-request'):'Room music changed(revision 불일치)입니다. 재조회 후 사용자가 제출 여부를 다시 선택합니다. '+ROOM_LINKED}
for key,operation in OPS.items():
 if '409' in operation['errors'] and key[1].startswith(BASE):
  operation['errorDescriptions']={'409':ROOM_CONFLICT.get(key,ROOM_LINKED)}

import copy
TRIP_CONTEXT='TRIP_STATE_CONFLICT(계획·진행 중이 아닌 종료·취소 여행), TRIP_CONTEXT_NOT_READY(여행 내부 방 미준비), TRIP_MEMBERSHIP_INCONSISTENT(수락 명단과 방 참여 불일치)입니다. 여행 상세를 다시 읽습니다.'
TRIP_CONFLICT={
 ('post',SHARED_BASE):'여행 공유 목록이 이미200곡이면 Room playlist limit reached입니다. ',
 ('put',BASE):'Room music changed(revision 불일치), Music list changed(본인 목록 revision 변경), Room playlist entry changed, Choose a reviewed room track입니다. ',
 ('delete',BASE):'Room music changed(revision 불일치)입니다. ',
 ('patch',BASE+'/review-request'):'Room music changed(revision 불일치)입니다. '}
TRIP_BROWSER='공개 브라우저 origin의 Access와 개인 세션이 필요하며 변경은 같은 Origin·현재 X-WegoH-CSRF도 필요합니다. 차량 Native 호스트에서는 403입니다. 차량은 GET /v1/social/trips/{trip}/music/saved-playlists와 여행 상세의 음악 요약을 사용합니다.'
for (method,path),operation in list(OPS.items()):
 if path.startswith(BASE):
  trip_path=path.replace('/rooms/{room}/','/trips/{trip}/')
  value=copy.deepcopy(operation)
  value['summary']=value['summary'].replace('여행방','여행')
  if path==BASE:
   value['prerequisites']=TRIP_BROWSER+(' 수락한 여행 멤버이며 본인 여행 music 공유 설정이 켜져 있어야 합니다.' if method=='get' else ' 현재 DJ이고 본인 여행 music 공유 설정이 켜져 있어야 합니다. 공유 중단은 DJ 또는 여행 소유자만 할 수 있습니다.' if method=='delete' else ' 현재 DJ이고 본인 여행 music 공유 설정이 켜져 있어야 합니다.')
  else:
   value['prerequisites']=value['prerequisites'].replace('현재 방 멤버이고 music 동의가 필요합니다.','현재 수락한 여행 멤버이고 본인 여행 music 공유 설정이 필요합니다.').replace(BROWSER+' ',TRIP_BROWSER+' ')
   if path!=SHARED_BASE:value['prerequisites']+=' saved-playlists로 계정 목록에서 가져온 곡에는 music 공유 설정을 요구하지 않습니다. 직접 추가한 링크에만 요구합니다.'
  value['prerequisites']+=' 계획(planned)·진행 중(active) 여행만 허용합니다. 종료·취소 여행은 409입니다.'
  if (method,path)==('get',BASE):
   value['sequence']='여행 상세에서 tripId를 확인한 뒤 이 GET을 호출합니다. playlist는 iPhone·차량의 saved-playlists와 같은 여행 단일 목록이며, 직접 추가한 링크는 music 공유 설정을 켠 사람에게만 보입니다.'
   value['effects']='revision/canEdit/selection/playlist와 tripId/contractVersion=1을 반환합니다. 현재 DJ와 원목록 revision, 콘텐츠 승인을 매번 재검사하고 다른 사람에게는 승인된 metadata만 보여 줍니다. 차단 상대가 추가한 곡과 선택은 숨깁니다.'
  if (method,path)==('put',BASE):
   value['sequence']='GET music의 revision과 함께 본인 GET playlists의 id/revision/trackId를 보내거나, 여행 공유 곡을 playlistId=tripId, playlistRevision=1, trackId로 선택합니다. 또는 kind=playlist-link, provider=melon, title, url(melon.com/www.melon.com/m.melon.com HTTPS)로 멜론 플레이리스트 링크를 공유합니다. rightsConfirmed=true는 공유 권리 확인이며 검토 동의와 별개입니다.'
  value['effects']+=' DJ 교체·공유 철회·재가입·종료는 이전 선택을 되살리지 않습니다. 차단 상대의 음악 자료는 숨깁니다. 이 API는 재생을 시작하거나 동기화하지 않으며 함께 듣기는 별도 listen-together API입니다.'
  value['errorDescriptions']={'409':TRIP_CONFLICT.get((method,path),'')+TRIP_CONTEXT}
  if '409' not in value['errors']:value['errors']=sorted(value['errors']+['409'])
  OPS[(method,trip_path)]=value

TRIP_BASE='/v1/social/trips/{trip}/music'
TRIP_SAVED_SELECTION=obj({'revision':R,'playlistId':IDENT,'playlistRevision':REV,'trackId':IDENT,'rightsConfirmed':{'const':True,'description':'링크와 표시 metadata를 공유할 권리가 있음을 본인이 확인합니다. 콘텐츠 검토 동의나 재생 승인을 대신하지 않습니다.'}},'본인 목록 또는 여행 공유 곡 선택. 공유 곡은 playlistId=tripId, playlistRevision=1입니다.')
BODY={
 ('put',TRIP_BASE):{'oneOf':[TRIP_SAVED_SELECTION,TRIP_LINK]},
 ('delete',TRIP_BASE):obj({'revision':R},'현재 선택 revision으로 공유 중단.'),
 ('post',TRIP_BASE+'/playlist'):obj({'title':s('곡 제목.',maxLength=120),'artist':s('아티스트.',maxLength=80),'url':s('HTTPS 원곡 링크.',maxLength=2048,format='uri'),'rightsConfirmed':{'const':True,'description':'링크와 표시 metadata를 공유할 권리가 있음을 본인이 확인합니다. 콘텐츠 검토 동의나 재생 승인을 대신하지 않습니다.'}},'권리를 확인한 불변 링크 추가.'),
 ('patch',TRIP_BASE+'/playlist/{track}/review-request'):obj({'consent':b('별도 검토 요청·철회.')},'본인 곡의 콘텐츠 검토 동의.'),
 ('post',TRIP_BASE+'/playlist/{track}/reports'):obj({'reason':{'type':'string','enum':['harmful','privacy','rights','other']}},'현재 공개된 곡 신고.'),
 ('patch',TRIP_BASE+'/review-request'):obj({'revision':R,'consent':b('현재 선택의 별도 검토 요청·철회.')},'DJ 선택의 콘텐츠 검토 동의.'),
 ('post',TRIP_BASE+'/reports'):obj({'selectionId':IDENT,'reason':{'type':'string','enum':['harmful','privacy','rights','other']}},'현재 공개된 선택 신고.')}
