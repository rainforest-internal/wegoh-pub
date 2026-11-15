"""Consumer social, history and Story contracts; explicit per-operation authoring."""
from api_doc_shared import *
OPS={}
def add(method,path,*args,**kw):OPS[(method,path)]=entry(*args,**kw)
add('get','/v1/playlists','07 음악 링크','내 음악 링크 목록 조회',READ+' 별도 native 개인 token의 본인 목록 읽기도 지원합니다.',
 '목록에서 id/revision을 확인한 뒤 상세 GET 또는 브라우저 수정·삭제를 선택합니다.',
 '최신 수정순 최대100개의 본인 목록을 반환합니다. 방 음악 송출·재생·DJ 제어를 실행하지 않습니다.',
 '조회 재시도 가능. playlists invalidate 후 최신 목록을 읽습니다.',ok(obj({'playlists':arr(ref('Playlist'),'본인 음악 링크 목록.')},'본인 목록.')),['401','403','429','503'])
add('get','/v1/playlists/{playlist_id}','07 음악 링크','내 음악 링크 목록 하나 조회',READ+' native 본인 token 조회도 허용됩니다.',
 '목록에서 받은 id를 사용합니다. 수정 직전 revision을 이 응답에서 확인합니다.',
 '본인 음악 링크 metadata와 순서만 반환합니다. 원격 URL을 서버에서 가져오지 않습니다.',
 '안전한 조회. 다른 소유자/삭제된 목록은404입니다.',ok(ref('Playlist')),['401','403','404','429','503'])
add('post','/v1/playlists','07 음악 링크','내 음악 링크 목록 만들기',BROWSER,
 'name과 tracks를 보냅니다. tracks=[]도 허용하며 최대100곡, 계정당 최대100목록입니다. 각 곡은 title/url과 선택적 id를 가집니다.',
 '암호화된 새 목록을 생성하고 누락한 track id는 서버가 발급합니다. 음악을 업로드·재생·다운로드하지 않습니다.',
 '새 POST마다 별도 목록을 만듭니다. 응답 유실은 목록 조회로 확인하고 무조건 재전송하지 마세요.30회/분 쓰기 제한.',created(ref('Playlist'),'새 개인 음악 링크 목록을 생성했습니다.'),['400','401','403','409','413','429','503'],example={'name':'내 음악','tracks':[]})
add('put','/v1/playlists/{playlist_id}','07 음악 링크','내 음악 링크 목록 전체 교체',BROWSER,
 'GET의 현재 revision과 name/tracks 전체를 보냅니다. 곡 id를 유지하면 같은 항목을 추적할 수 있으며 중복 id는 금지입니다.',
 '전체 목록 내용·순서를 교체하고 revision을1 증가시킵니다. URL은 HTTPS, 자격증명 없음, 포트443만 허용됩니다.',
 '409이면 최신 GET 후 사용자 편집을 재확인합니다. 응답 유실도 GET으로 정본을 확인하며 옛 revision을 자동 증가시켜 재전송하지 마세요.',ok(ref('Playlist')),['400','401','403','404','409','413','429','503'],example={'name':'내 음악','tracks':[],'revision':1})
add('delete','/v1/playlists/{playlist_id}','07 음악 링크','내 음악 링크 목록 삭제',BROWSER,
 'GET에서 이름/id를 확인한 뒤 명시 삭제합니다. 본문과 revision은 없습니다.',
 '목록 하나와 그 링크 metadata를 삭제합니다. 외부 음악 원본은 삭제하지 않습니다.',
 '이미 삭제/다른소유자는404. 응답 유실은 목록조회로 확인하며 자동으로 같은 이름의 새 목록을 만들지 마세요.',ok(status('deleted')),['401','403','404','429','503'])
add('get','/v1/social/friends/search','08 친구','친구 핸들 정확 일치 검색',READ+' 브라우저 전용입니다.',
 'handle query 하나에 선택적 @와 3~20자 ASCII 영숫자·밑줄·점을 보냅니다. 영문·숫자로 시작하고 대소문자는 구별하지 않습니다. 이름·이메일·부분 일치는 지원하지 않습니다.',
 '활성 계정 한 명의 id/name/handle/relationship만 반환합니다. 본인은 self입니다. 없거나 양방향 중 하나라도 차단되었으면 동일한 person:null입니다. 허용 목록과 독립적인 계정 조회입니다.',
 '계정당 20회/분, 접속 IP당 60회/분입니다. 전달된 IP 헤더는 신뢰하지 않으며 프록시 뒤에서는 연결 IP 한도를 공유합니다. 429이면 Retry-After 이후 다시 시도합니다.',
 ok(obj({'person':nullable(obj({'id':ACCOUNT,'name':s('표시 이름.'),'handle':s('소문자 핸들, @ 제외.'),'relationship':s('self/friend/incoming/outgoing/none.')},'정확 일치 계정.'))},'검색 결과 한 명 또는 없음.')),['400','401','403','429','503'])
add('get','/v1/social/friends/{peer}/profile','08 친구','친구 프로필의 이름과 등록 차량 번호 조회',READ+' 브라우저 전용입니다.',
 '친구 목록에서 선택한 상대의 계정 ID를 경로에 넣습니다. 서버는 현재 친구 관계와 양쪽의 차단 여부를 확인합니다.',
 '표시 이름과 현재 연결된 차량에 등록한 번호 목록을 반환합니다. 같은 번호는 한 번만 담으며 등록된 번호가 없으면 빈 배열입니다. 응답은 private, no-store입니다.',
 '친구 프로필을 다시 열 때 최신 정보를 조회합니다. 친구 관계가 종료되거나 한쪽에서 차단하면 404입니다.',
 ok(dict(obj({'name':s('친구의 계정 표시 이름.'),
              'plateNumbers':dict(arr(s('친구가 등록한 차량 번호.',minLength=2,maxLength=16),'등록된 차량 번호 목록.'),uniqueItems=True)},
             '친구 상세에 표시할 이름과 차량 번호.'),additionalProperties=False)),['401','403','404','503'])
add('get','/v1/music/link-preview','07 음악 링크','공유 음악 링크의 제목과 썸네일 미리보기',READ+' 브라우저 개인 세션 전용입니다.',
 'url query 하나로 허용된 음악 서비스의 HTTPS 공유 주소를 보냅니다. 수동 제목 입력과 음악 목록 저장 계약은 바뀌지 않습니다.',
 '공개 페이지 메타데이터만 읽습니다. 썸네일은 150KB 이하 JPEG/PNG/WebP를 data URL로 반환하며 목록에 저장하지 않습니다.',
 '계정당 60회/분. URL별 공개 메타데이터 캐시는 최대 256개/1시간. 미리보기 실패 시 제목을 직접 입력할 수 있습니다.',
 ok(obj({'title':s('추출한 제목. 최대 120자.'),'image':nullable(s('크기가 제한된 이미지 data URL. 없으면 null.')),
 'provider':s('melon/spotify/youtube-music/youtube/link 서비스 분류.')},'저장되지 않는 링크 미리보기.')),['400','401','403','429','502'])
add('get','/v1/social/overview','08 친구','친구·요청·차단·참여 방 현재 목록 조회',READ+' Native는 friends:read, rooms:read, history:read 중 하나 이상이 필요합니다.',
 'people은 호환을 위해 빈 배열로 유지합니다. 검색 결과 id로 요청합니다. incoming 요청은 respond, outgoing은 DELETE friends/{target}로 취소합니다.',
 '현재 활성 계정과 차단/관계를 반영합니다. Native는 승인된 목적에 따른 부분 목록을 반환합니다. 정확한 배열별 범위는 아래 Native 계약을 따릅니다.',
 '조회는 안전합니다. friends/rooms invalidate나 계정 변경 후 다시 읽고 오래된 관계로 공유 권한을 추정하지 마세요.',ok(ref('SocialOverview')),['401','403','404','429','503'])
add('post','/v1/social/friends/requests','08 친구','선택한 활성 계정에 친구 요청 보내기',BROWSER,
 '친구 핸들 검색 결과의 계정 id를 targetId로 보냅니다. requestId가 아닙니다. 활성 계정 상태와 차단 여부를 다시 검사합니다.',
 '관계를 pending으로 저장하고 양쪽 friends 상태를 갱신합니다. 이미 내 outgoing/accepted이면200입니다.',
 '최초요청201, 같은관계200, 상대가보낸incoming이있으면409이며 respond를 사용해야 합니다. 친구 승인은 위치·기록 공유 동의가 아닙니다.',
 {**created(status('pending'),'새 친구 요청을 보냈습니다.'),**ok(status('pending 또는 accepted'),'이미 같은 pending/accepted 관계입니다.')},['400','401','403','404','409','413','429','503'])
add('post','/v1/social/friends/requests/{target}/respond','08 친구','나에게 온 친구 요청 수락 또는 거절',BROWSER,
 'overview.requests의 direction=incoming인 상대 계정 id를 target 경로에 넣고 accept:true/false를 보냅니다.',
 '현재 상대가 보낸 pending만 accepted 또는 none으로 바꿉니다. 내 outgoing을 이 API로 승인할 수 없습니다.',
 '이미 처리/차단/없으면404. 응답 유실 시 overview를 조회하세요. 같은수락을 무한 재전송하지 마세요.',ok(status('accepted 또는 declined')),['400','401','403','404','409','413','429','503'],example={'accept':False})
add('delete','/v1/social/friends/{target}','08 친구','내 요청 취소 또는 친구 관계 종료',BROWSER,
 'outgoing 요청 취소 또는 현재친구 종료를 사용자가 선택한 경우 상대 계정 id를 지정합니다. incoming은 respond:false로 거절합니다.',
 '관계를 none으로 만들고 관련 기록grant를 철회합니다. 다시친구가되어도 옛grant가 자동복구되지 않습니다.',
 '현재없음은removed로 종료합니다. incoming취소는403. 응답 유실은 overview/기록공유설정을 재조회하세요.',ok(status('removed')),['400','401','403','404','409','413','429','503'])
add('post','/v1/social/blocks','08 친구','선택 계정을 차단',BROWSER,
 '현재 계정 id를 확인하고 targetId를 보냅니다. 자기 자신은 차단할 수 없습니다.',
 '친구/요청을 종료하고 양쪽 조회를 차단합니다. 관련 기록grant를 철회하고 공동방에서는 방장 관계에 따라 상대 또는 나를 퇴장시킵니다. 원기록을 삭제하지 않습니다.',
 '최초201, 이미내차단이면200. 같은대상재시도는차단상태를유지하며 overview를정본으로확인합니다.',{**created(status('blocked'),'차단하고 기존 공유 접근을 종료했습니다.'),**ok(status('blocked'),'이미 내가 차단한 계정입니다.')},['400','401','403','404','409','413','429','503'])
add('delete','/v1/social/blocks/{target}','08 친구','내 차단 해제',BROWSER,
 'overview.blocks의 대상 계정 id로 명시 해제합니다.',
 '내 blockedBy만 제거합니다. 상대방의 차단·친구관계·방참여·기록grant는 자동복구하지 않습니다.',
 '반복은unblocked로종료합니다. 이후 overview를새로읽고친구요청부터필요하면명시진행하세요.',ok(status('unblocked')),['400','401','403','404','409','413','429','503'])
add('get','/v1/social/invites/{code}','09 여행방','초대 코드의 방 정보와 지원 동의 확인',READ,
 '사용자가 받은8자code로만조회합니다. name/코스/만료/availableConsentKeys를 확인한 후 join을명시선택합니다.',
 '가입전 필요한 방요약을 반환합니다. 이것만으로 멤버정보/신호/위치열람권한이 생기지 않습니다. 미승인방명은고정값입니다.',
 '만료·차단·없는코드는404. code탐색금지;20회/분 제한.',ok(ref('RoomInvite')),['401','403','404','429','503'])
add('post','/v1/social/rooms','09 여행방','기간제 여행방 만들기',BROWSER,
 'name,expiresInHours1~168,courseId/courseVersion을 보냅니다. 코스없음은 두값모두null. preference는선택이며기본balanced입니다.',
 '방과최초방장멤버를생성합니다. 방장의여섯동의도모두false입니다. 현재활성방소유10개/방멤버10명한도입니다. 이름검토제출은별도입니다.',
 'POST재전송은새방을만듭니다.응답유실은overview.rooms를확인하세요.409는코스현재승인/방한도상태를확인합니다.',created(obj({'id':IDENT,'code':s('다른사용자가명시가입할8자초대코드.')},'새방ID와초대코드.'),'방을생성했습니다. 아직상태/장소공유동의는없습니다.'),['400','401','403','409','413','429','503'],example={'name':'함께 가는 여행','courseId':None,'courseVersion':None,'expiresInHours':24,'preference':'balanced'})
add('post','/v1/social/rooms/join','09 여행방','초대 방에 내 목적별 동의로 가입',BROWSER,
 'invite GET으로현재방/만료/지원동의를확인→consents여섯boolean을명시→join. status/location/music 및 현재 availableConsentKeys에 voice가 있을 때 새 true를 허용합니다. music은 별도 기본false이며 visits/control은 false입니다.',
 '본인멤버십을만들거나재가입합니다. 이미현재멤버이면저장된역할/동의를덮지않고기존consents를반환합니다.',
 '중복join은기존멤버값을보존합니다. 동의수정은PATCHconsents를사용하세요.방정원409/차단·만료404입니다.',ok(obj({'id':IDENT,'status':s('joined.'),'consents':ref('Consents')},'가입한현재멤버십.')),['400','401','403','404','409','413','429','503'],example={'code':'ABCD2345','consents':{k:False for k in ('status','location','visits','music','voice','control')}})
add('get','/v1/social/rooms/{room}','09 여행방','현재 내 방 상세·멤버·선택 장소 요청 조회',READ+' Native는 rooms:read 목적이 별도로 필요합니다.',
 'overview/native방목록의id로조회합니다. 방만료시간은serverNow/expiresInSeconds기준으로표시하고신호변경시재조회합니다.',
 '현재멤버십·차단·발신자현재status/location동의를적용합니다. 브라우저의 agreedStop은 요청자 외 현재 참여자가 모두 찬성한 가장 최근 쉼터 제안입니다. 상태·장소 공유와 투표를 매번 다시 확인합니다. Native는 agreedStop, 초대code/consents/availableConsentKeys를 제외하며 현재 rooms:interact에 따라 nativeReadOnly를 계산합니다. destination은명시선택장소이며자동GPS가아닙니다.',
 '조회는안전합니다.404면화면원문·개인위치를폐기합니다.만료가원기록자동삭제를뜻하지않습니다.',ok(ref('Room')),['401','403','404','409','429','503'])
ARCHIVE_SUMMARY=obj({'id':IDENT,'name':s('방장에게는 원래 이름, 다른 구성원에게는 현재 검토 규칙을 적용한 이름 또는 고정 여행방.'),
 'ownerId':ACCOUNT,'state':s('종료된 보관 방.',const='archived'),'readOnly':dict(b('진행 중 기능이나 보관 내용 변경을 허용하지 않습니다.'),const=True),
 'createdAt':TIME,'expiresAt':TIME,'archivedAt':dict(TIME,description='자연 만료의 expires_at 또는 방장 종료의 closed_at. 보관 조회를 한 시각이 아닙니다.'),
 'courseId':nullable(s('보존한 원 코스 ID.')),'courseVersion':nullable(n('보존한 원 코스 버전.')),
 'preference':s('보존한 여행 선호. 내비 경로 적용 결과가 아닙니다.'),'course':nullable(ref('CourseRef')),
 'memberCount':n('퇴장 이력을 포함한 보존된 참여 행 수. 현재 표시 가능한 계정 수와 다를 수 있습니다.')},'본인이 과거 참여한 읽기 전용 보관 방.')
ARCHIVE_DETAIL=obj({**ARCHIVE_SUMMARY['properties'],
 'members':arr(obj({'id':ACCOUNT,'name':s('현재 허용된 계정 표시 이름.'),'role':s('보존된 member/dj/rest/food 역할.'),
     'joinedAt':TIME,'leftAt':nullable(TIME)},'기존 마지막 가입·퇴장 시각을 보존한 참여 행.'),'현재 계정 허용을 충족하는 과거 구성원.'),
 'signals':arr(ref('RoomSignal'),'기존 동의·검토·차단 규칙을 적용한 최근 최대100개 신호. 조회자가 종료 전에 퇴장했다면 빈 배열.'),
 'musicSelection':nullable(obj({'selectionId':IDENT,'ownerId':ACCOUNT,'playlistId':dict(IDENT,description='본인 개인 목록 ID 또는 공유 목록의 방 ID.'),
     'playlistRevision':n('선택 당시 목록 버전. 공유 곡은1.'),'trackId':IDENT},'선택자 본인에게만 반환하는 보존된 마지막 음악 선택 참조. 다른 조회자는 null.'))},'보관 방의 읽기 전용 상세. 초대 코드·URI·동의 grant·원시 위치 보고는 포함하지 않습니다.')
ARCHIVE_ACCESS=READ+' 브라우저 세션 전용이며 Native host/기기 token 경로는 제공하지 않습니다. 해당 방의 당시 구성원으로 보존된 참여 행이 있어야 합니다. 과거 구성원 중 한 명과라도 현재 차단 관계가 있으면 방장 포함 양쪽 조회를 닫습니다.'
add('get','/v1/social/room-archives','09 여행방','내 만료·종료 여행방 보관 목록 조회',ARCHIVE_ACCESS,
 '개인 세션 시작 후 보관 목록을 읽고 반환된 id로 room-archives/{room} 상세를 조회합니다. 활성 방은 overview.rooms를 사용합니다.',
 '종료 시각과 ID 내림차순으로 후보 최대100개에 현재 ACL을 적용합니다. 만료·방장 종료를 보관 상태로 반영하고 진행 중 권한을 회수하되 방 원자료는 삭제하지 않습니다. 원시 위치·방문 보고의 기존 종료 삭제는 유지합니다. 읽기 전용 응답이며 Cache-Control: private, no-store입니다.',
 '동일 GET은 멱등 보관 전이를 적용합니다. 차단되거나 비구성원인 방은 목록에서 제외됩니다. 빈 목록은 다른 계정 자료의 삭제를 뜻하지 않습니다.',
 ok(obj({'rooms':dict(arr(ARCHIVE_SUMMARY,'현재 본인이 조회할 수 있는 종료 방.'),maxItems=100)},'브라우저 전용 보관 목록.')),['401','403','404','503'])
add('get','/v1/social/room-archives/{room}','09 여행방','내 보관 여행방 읽기 전용 상세 조회',ARCHIVE_ACCESS,
 '보관 목록의 id로만 조회합니다. 종료·만료된 방을 진행 중 초대/입장/신호/투표/음성/음악 경로로 다시 열지 않습니다.',
 '방 메타·참여 이력·공개 가능한 신호/투표와 선택자 본인 음악 참조를 반환합니다. 일찍 퇴장한 구성원은 메타·참여 이력만 읽고 신호는 빈 배열입니다. 다른 참여자의 동의 철회·현재 계정 허용·텍스트 검토 마스킹을 유지합니다. 공유 곡 원자료는 보존하지만 목록 본문이나 음원 재생 권한을 추가하지 않습니다. Cache-Control: private, no-store입니다.',
 '안전하게 재조회할 수 있으며 보관 전이는 멱등입니다. 404는 없는/잘못된 ID, 진행 중 방, 비구성원 또는 현재 차단 관계입니다. 오래된 화면을 폐기하고 ID 탐색이나 자동 재가입을 하지 마세요.',
 ok(ARCHIVE_DETAIL),['401','403','404','503'],notes='두 보관 경로는 GET만 제공하며 내용 수정·삭제·다시 여행 만들기 API가 아닙니다. 만료된 방의 기록 보존과 위치 원시 보고 삭제는 구분합니다.')
for archive_path in ('/v1/social/room-archives','/v1/social/room-archives/{room}'):
 OPS[('get',archive_path)]['errorDescriptions']={
  '401':'개인 브라우저 세션이 없거나 만료되었습니다. Access 로그인과 POST /v1/auth/session을 다시 확인합니다.',
  '403':'현재 팀 Access/계정 허용을 충족하지 않습니다. 브라우저 세션이나 과거 참여 이력이 팀 접근 권한을 대신하지 않습니다.',
  '404':'상세는 없는/잘못된 ID·진행 중 방·비구성원·현재 차단 관계입니다. Native 또는 비활성 기능/허용되지 않은 host도 경로를 열지 않습니다. 목록은 접근 불가 방을 제외합니다.',
  '503':'DB·암호화 저장소를 사용할 수 없습니다. 보관 완료나 자료 삭제로 표시하지 말고 복구 후 동일 GET으로 확인합니다.'}
add('patch','/v1/social/rooms/{room}/consents','09 여행방','현재 방에서 내 상태·장소·음성 동의 변경',BROWSER,
 '현재GETconsents와availableConsentKeys를읽고여섯키전체를보냅니다. status/location/music 및 현재 availableConsentKeys의 voice만 새 true를 허용합니다. music은 현재 승인된 음악metadata의 별도 공유이며 visits/control은 미지원입니다. off 전에 저장한 voice 값은 보존할 수 있습니다.',
 '내멤버동의만교체합니다. voice 철회는 다음 재인가에서 송수신을 끝내며 자동 재시작하지 않습니다. status또는location을끄면내선택장소검토제출도철회하고기존신호조회에현재동의를적용합니다.다른멤버를대신변경하지않습니다.',
 '같은명시선택재저장은가능하지만응답유실이면방상세를조회합니다. 옛동의로화면을고정하지마세요.',ok(obj({'consents':ref('Consents')},'저장한본인동의.')),['400','401','403','404','409','413','503'],example={'consents':{k:False for k in ('status','location','visits','music','voice','control')}})
add('patch','/v1/social/rooms/{room}/role','09 여행방','방장이 현재 멤버 역할 지정',BROWSER+' 현재방장만허용됩니다.',
 '방상세members에서accountId를선택하고member/dj/rest/food중역할을보냅니다.',
 '멤버역할을변경하며개인동의는보존합니다. 새 DJ는 한 명만 지정하고 이전 DJ를 member로 되돌리며 이전 음악선택·검토요청을 철회합니다. DJ는 별도 music 동의 후 원곡 metadata를 선택할 수 있으나 음원재생·차량명령은 실행하지 않습니다.',
 '같은역할재설정은가능하지만상세를재조회해확인합니다. 방장아님403/멤버아님404.',ok(status('updated')),['400','401','403','404','409','413','503'])
add('post','/v1/social/rooms/{room}/leave','09 여행방','방에서 나가기 또는 방장이 닫기',BROWSER,
 '사용자가 현재 방 나가기를 확인한 뒤 호출합니다. 브라우저는 본문을 보내지 않고, Native는 functionalRevision 하나만 담은 JSON 본문을 보냅니다.',
 '일반멤버는본인left,방장은방closed로전체접근을종료합니다.관련검토제출을철회하지만과거저장기록을삭제하지않습니다.',
 '이미비활성멤버/방은404, 여행에 연결된 내부 방 ID는409입니다. 응답유실은방목록을재조회하세요.방복제/재가입을자동으로하지마세요.',ok(status('방장 closed, 그 외 left')),['400','401','403','404','409','413','503'])
add('patch','/v1/social/rooms/{room}/review-request','09 여행방','방장이 방 이름 검토 제출 또는 철회',BROWSER+' 현재활성방장만가능합니다.',
 'consent:true는운영자에게방이름만제출합니다. false는철회합니다.방멤버상세/GPS/사진은제출하지않습니다.',
 '정확이름projection을검토대기로두고승인된현재이름만다른사용자에게보여줍니다.방만료/닫힘에제출열람도종료됩니다.',
 '같은내용기존제출은현재상태를유지할수있습니다. 응답유실은방review를재조회하세요.',ok(obj({'review':ref('Review')},'현재이름제출상태.')),['400','401','403','404','409','413','503'],example={'consent':False})
add('post','/v1/social/rooms/{room}/reports','09 여행방','현재 보이는 방 이름 신고',BROWSER,
 '현재멤버는reason만,가입전초대화면수신자는동일방의현재code도보냅니다. 실제승인되어보이는방이름이대상입니다.',
 '현재이름을재격리하고개발자검토metadata를남깁니다.초대code보유가다른방데이터열람을허용하지않습니다.',
 '같은신고자/이유/checksum은같은reportId입니다.404는보이지않는대상·철회·만료;202는접수이며판정완료가아닙니다.',report(),['400','401','403','404','409','413','429','503'])
add('post','/v1/social/rooms/{room}/signals','09 여행방','내 상태 또는 선택 장소 요청 보내기',BROWSER+' 본인status동의true, destination이있으면location동의true도필요합니다.',
 '지원kind와선택적destination을보냅니다.위치자동수집이아니며사용자가확인한{name,latitude,longitude}만입력합니다.',
 '방에새신호를저장합니다. 장소명은별도작성자검토승인후타인에게노출됩니다.현재5000신호한도/20회분.내비경로전송·차량출발명령을수행하지않습니다.',
 'POST재전송은새신호를만듭니다.응답유실은방신호조회로확인합니다.403은현재동의,409는방용량을확인합니다.',created(obj({'id':IDENT,'status':s('sent.')},'저장한방요청.'),'현재동의아래요청신호를저장했습니다.'),['400','401','403','404','409','413','429','503'],example={'kind':'rest','destination':None})
add('patch','/v1/social/rooms/{room}/signals/{identifier}/review-request','09 여행방','내 선택 장소 이름 검토 제출 또는 철회',BROWSER+' 신호의실작성자만가능하며방장이대신제출할수없습니다.',
 '내destination신호id로consent:true/false를보냅니다. 제출때현재status/location동의와멤버십이필요합니다.',
 '장소이름만운영검토투영본에제출하며좌표는이검수자료에포함하지않습니다.동의off/나가기/만료뒤열람종료됩니다.',
 '현재신호/동의없으면404.같은내용제출은현재state를보존할수있고철회는명시false로보냅니다.',ok(obj({'review':ref('Review')},'장소명검토상태.')),['400','401','403','404','409','413','503'],example={'consent':False})
add('post','/v1/social/rooms/{room}/signals/{identifier}/reports','09 여행방','현재 보이는 선택 장소 이름 신고',BROWSER+' 현재활성방멤버이고대상신호의현재destination을볼수있어야합니다.',
 '방신호의id와고정reason을보냅니다.현재승인되어수신한이름을신고하며사라진대상은404입니다.',
 '해당room-place이름만quarantined로재격리합니다.위치삭제/방장대리동의API가아닙니다.',
 '같은대상checksum/신고자/이유는같은reportId를사용합니다.202는접수이며최종판정이아닙니다.',report(),['400','401','403','404','409','413','429','503'])
add('post','/v1/social/rooms/{room}/signals/{identifier}/vote','09 여행방','현재 보이는 장소 요청에 내 응답 저장',BROWSER+' 본인status동의true가필요합니다.',
 '방상세signals에서현재보이는destination있는신호에agree/pass를선택합니다.',
 '내표하나를upsert하고집계를갱신합니다.음성제어/내비ACK/장소예약을수행하지않습니다.',
 '같은선택재전송은내표를같게유지합니다.404는신호가현재보이지않음,409는장소제안이없음입니다.',ok(obj({'status':s('saved.'),'choice':s('agree 또는 pass.')},'현재내표.')),['400','401','403','404','409','413','429','503'],example={'choice':'pass'})
add('delete','/v1/social/rooms/{room}/signals/{identifier}/vote','09 여행방','내 장소 요청 응답 철회',BROWSER+' 현재방접근이필요합니다.',
 '동일방의신호id를지정합니다. 브라우저는 본문이 없고 Native는 functionalRevision만 보냅니다. 다른사람의표를지울수없습니다.',
 '내표만삭제합니다.원신호/장소/다른표는유지합니다.',
 '이미내표가없어도withdrawn.신호/방접근이없으면404.방상세를다시읽어집계확인합니다.',ok(status('withdrawn')),['400','401','403','404','409','413','429','503'])
add('get','/v1/social/history','10 여행기록','내 기록과 현재 공유받은 기록 페이지 조회',READ+' 연결된 차량에는 history:read가 적용됩니다.',
 '최신updatedAt/id내림차순50개를읽습니다. 응답nextCursor를그대로다음GET에사용하며null일때끝입니다.권한필터때문에빈history와non-nullcursor도가능합니다.',
 '현재친구/별도grant/검토승인에맞는기록만보입니다. Native는 friends=[], sharedWith=[], permissionRevision=null이며 history:write 승인 여부에 따라 nativeReadOnly를 계산합니다. 사진이나 기록별 수집을 자동 승인하지 않습니다.',
 '같은cursor재조회는가능하지만변경invalidate뒤에는첫페이지부터현재정본을읽습니다. cursor를직접조립하지마세요.',ok(obj({'history':arr(ref('HistorySummary'),'현재허용된최대50개.'),'friends':arr(ref('Person'),'브라우저소유자공유설정선택용현재친구. native는빈배열.'),'nextCursor':nullable(s('다음opaque페이지cursor.')),'capabilities':ref('Capabilities'),'nativeReadOnly':b('Native에서는 현재 history:write 목적이 없을 때 true입니다.')},'기록페이지.',required=['history','friends','nextCursor','capabilities'])),['400','401','403','404','429','503'])
add('post','/v1/social/history','10 여행기록','내 개인 여행기록 만들기',BROWSER,
 '제목/시간/선택코스를입력합니다.끝나지않았으면endedAt:null,코스없으면courseId/courseVersion모두null입니다.',
 '개인암호화기록을만들며collectTrace:false/공유없음/검토미제출입니다.자동GPS수집/실차방문인증은없습니다.계정당500기록.',
 'POST재전송은새기록을만듭니다.응답유실은목록에서확인합니다.409는현재승인코스/용량을확인하세요.',created(obj({'id':IDENT,'revision':REV,'permissionRevision':REV},'새기록revision은각1.'),'내개인기록을생성했습니다.'),['400','401','403','409','413','429','503'],example={'title':'내 여행','startedAt':'2026-01-01T09:00:00+09:00','endedAt':None,'courseId':None,'courseVersion':None})
add('post','/v1/social/rooms/{room}/history','10 여행기록','현재 참여 방의 내 기록 따로 저장',BROWSER+' 현재방멤버이고방이활성이어야합니다.',
 '방이만료되거나나가기전에title만보냅니다.현재서버시각과방의코스참조로개인기록을만듭니다.',
 '방메타/코스참조만복사합니다.다른멤버경로·방신호·사진·위치·동의를자동수집하거나복사하지않습니다.',
 '각POST는새기록을만듭니다.응답유실은내기록목록을확인하세요.만료/퇴장방은404입니다.',created(obj({'id':IDENT,'revision':REV,'permissionRevision':REV},'새개인기록.'),'현재방을출처로개인기록을생성했습니다.'),['400','401','403','404','409','413','429','503'],example={'title':'함께 간 여행'})
add('post','/v1/social/history/from-archive','10 여행기록','종료한 여행방을 내 여행 기록으로 저장',ARCHIVE_ACCESS+' 정확한 Origin과 CSRF가 필요한 브라우저 변경 요청입니다.',
 '보관 목록과 상세를 확인한 뒤 roomId와 title을 보냅니다. 현재 차단 관계와 과거 참여를 저장 시점에 다시 확인합니다.',
 '내 참여 기간과 승인된 코스 참조만 개인 기록으로 저장합니다. 경로·방문지·동료·신호·음악·공유 동의를 복사하지 않습니다. 기간은 주행 측정값이 아닙니다.',
 '최초 201, 같은 계정과 방의 재요청은 기존 기록의 현재 id/revision/permissionRevision을 200으로 반환하며 편집 내용을 덮어쓰지 않습니다. 기록 삭제 후에는 다시 저장할 수 있습니다. 미승인/중단 코스는 409입니다.',
 {'201':created(obj({'id':IDENT,'revision':REV,'permissionRevision':REV},'새 개인 기록.'),'개인 기록을 생성했습니다.')['201'],
  '200':ok(obj({'id':IDENT,'revision':REV,'permissionRevision':REV},'기존 개인 기록.' ))['200']},
 ['400','401','403','404','409','413','429','503'],example={'roomId':'a'*32,'title':'함께 간 여행'})
add('get','/v1/social/history/{item}','10 여행기록','현재 허용된 기록·방문·경로 상세 조회',READ+' Native는 history:read 목적이 필요합니다.',
 '목록id로조회합니다.소유자는revision/permissionRevision/grants를편집의기준으로사용하고수신자는access의목적에따라표시합니다.',
 '친구는현재검토된텍스트와grant교집합만읽습니다. Native는 permissions=null, permissionRevision=null, grants=[], sharedWith=[], visits[].photos=[]이고 source는 kind/actorId/receivedAt만 반환합니다. nativeReadOnly는 history:write 승인 여부만 나타내며 각 쓰기 요청은 현재 목적을 다시 검사합니다.',
 '조회재시도가능.404는현재철회/관계변경도포함하므로원문·사진·경로를화면에서제거합니다.',ok(ref('History')),['401','403','404','429','503'])
add('put','/v1/social/history/{item}','10 여행기록','내 기록 제목·기간·선택 코스 수정',BROWSER+' 기록소유자만가능합니다.',
 '상세GET의revision과제목/시간/코스전체를보냅니다.endedAt는startedAt보다빠를수없고시각에는시간대가필요합니다.',
 '부모revision을증가시키며제출중인내용이바뀌면검토대기로되돌립니다.기존외부파일동의도데이터fingerprint변경으로비활성화됩니다.',
 '409는최신상세를읽고편집을재확인합니다.응답유실도상세정본으로확인하며revision을추정하지마세요.',ok(revresult()),['400','401','403','404','409','413','429','503'])
add('delete','/v1/social/history/{item}','10 여행기록','내 기록과 포함 데이터 삭제',BROWSER+' 소유자만 가능합니다. 브라우저는 본문과 revision을 보내지 않고, Native는 functionalRevision만 보냅니다.',
 '현재제목/id를확인하고명시삭제합니다.방에서나가기를대신하는API가아닙니다.',
 '기록과그방문·경로·사진·관련검토를삭제하고공유수신자에게invalidate합니다.이미외부저장한파일은회수하지못합니다.',
 '이미없는기록은404.응답유실은목록/상세로확인하며같은제목으로자동복원하지마세요.',ok(status('deleted')),['400','401','403','404','409','413','429','503'])
add('patch','/v1/social/history/{item}/review-request','10 여행기록','내 기록 텍스트 운영 검토 제출 또는 철회',BROWSER+' 기록소유자만가능합니다.',
 '현재revision과consent:true를보내면제목·장소이름·후기·경로이름만제출합니다.좌표/시각/경로점/미동의사진은제외됩니다. false는철회입니다.',
 'permissionRevision을증가시키고정확projection만검토합니다. 승인과별도로친구별visits/trace/photosgrant가필요합니다.',
 'true는현재revision불일치409;false철회는옛revision이라도허용합니다.후속상세GET에서review와permissionRevision을확인하세요.',ok(obj({'review':ref('Review'),'permissionRevision':REV},'현재검토상태와공유revision.')),['400','401','403','404','409','413','503'],example={'revision':1,'consent':False})
add('post','/v1/social/history/{item}/reports','10 여행기록','현재 보이는 기록 텍스트 신고',BROWSER+' 본인또는현재공유권한/친구/승인을충족하는수신자여야합니다.',
 '현재보이는기록id와고정reason을보냅니다.사진은사진전용reports로따로신고합니다.',
 '텍스트projection을quarantined로즉재격리하고현재수신자열람을중단합니다.원소유자기록자체를삭제하지않습니다.',
 '동일checksum/신고자/이유는같은reportId.202는접수이며판정완료가아닙니다.',report(),['400','401','403','404','413','429','503'])
add('patch','/v1/social/history/{item}/permissions','10 여행기록','내 기록의 경로 입력 동의 켜기 또는 끄기',BROWSER+' 기록소유자만가능합니다.',
 '현재permissionRevision과collectTrace를보냅니다. true는이후browser-reported배치입력을허용하며자동수집UI/차량GPS권한은별도미구현입니다.',
 '부모permissionRevision을증가시킵니다. false는새수집을중단하지만기존경로점/별도공유grant를삭제하지않습니다.외부동의정본에도영향이있습니다.',
 'true의옛revision은409. false철회는옛revision이어도가능합니다.응답유실은상세permissions를다시읽으세요.',ok(obj({'permissions':obj({'collectTrace':b('저장한입력동의.')},'소유자입력동의.'),'permissionRevision':REV},'변경한수집동의.')),['400','401','403','404','409','413','503'],example={'permissionRevision':1,'collectTrace':False})
add('put','/v1/social/history/{item}/shares/{target}','10 여행기록','현재 친구에게 기록 목적별 공유 설정',BROWSER+' 기록소유자와현재친구target만가능합니다.',
 '현재permissionRevision과visits/trace를명시하고사진은별도photos:true를선택해야합니다. photos는visits:true필수이며visits/trace둘다false이면DELETE로철회하세요.',
 '친구별grant를저장합니다. 검토미승인/차단/친구해제이면grant만으로실열람되지않습니다.자동GPS수집·외부파일동의를포함하지않습니다.',
 '409는현재공유설정을재조회후재확인.응답유실도상세grants로확인합니다.사진키생략은false로저장됩니다.',ok(permission_result()),['400','401','403','404','409','413','503'],example={'permissionRevision':1,'visits':True,'trace':False,'photos':False})
add('delete','/v1/social/history/{item}/shares/{target}','10 여행기록','친구 한 명의 기록 공유 전체 철회',BROWSER+' 기록소유자만가능합니다.',
 '공유 대상 계정 target을 지정합니다. 철회에는 현재 친구 관계가 필요하지 않습니다.본문이나옛permissionRevision이없어즉철회할수있습니다.',
 '해당대상의visits/trace/photosgrant를모두삭제하고permissionRevision을증가시킵니다.다른수신자와원기록은유지합니다.',
 '이미grant가없어도revoked이며revision은증가합니다.응답유실은상세grants를읽고불필요재전송을피합니다.',ok(permission_result()),['400','401','403','404','503'])
add('delete','/v1/social/history/{item}/share','10 여행기록','내 기록의 모든 친구 공유 철회',BROWSER+' 기록소유자만가능합니다.',
 '사용자가전체공유중단을명시선택한경우호출합니다.본문없음.',
 '이기록의친구grant를모두삭제하고permissionRevision을증가시킵니다.원기록/수집동의는유지하고이미외부저장사본은회수하지못합니다.',
 '반복호출은revoked지만revision증가.응답유실은grants빈배열을정본조회로확인합니다.',ok(permission_result()),['401','403','404','503'])
add('post','/v1/social/history/{item}/visits','10 여행기록','내가 확인한 방문 장소 추가',BROWSER+' 기록소유자만가능합니다.',
 '부모현재revision과명시선택place,visitedAt,후기review,선택rating1~5또는null을보냅니다.빈후기는허용됩니다.',
 '새방문id를발급하고부모revision을증가시킵니다.기록당최대500방문.실차통과/GPS자동인증이아니며사진upload는이visitid후별도입니다.',
 '각POST는새방문.응답유실은상세를조회하세요.409는revision또는방문한도를확인하고원기록을조용히잘라내지마세요.',created(revresult(),'새방문과갱신된부모revision입니다.'),['400','401','403','404','409','413','429','503'])
add('put','/v1/social/history/{item}/visits/{vid}','10 여행기록','내 방문 장소·시각·후기·평점 수정',BROWSER+' 기록소유자만가능합니다.',
 '상세의부모revision과해당방문전체필드를보냅니다.여기revision은방문개별revision이아닙니다.',
 '방문을교체하고부모revision및제출된텍스트검토상태/외부동의유효성에영향을줍니다.',
 '409는부모상세를다시읽고편집을재확인합니다.없는방문/다른소유자는404입니다.',ok(revresult()),['400','401','403','404','409','413','503'])
add('delete','/v1/social/history/{item}/visits/{vid}','10 여행기록','내 방문과 포함 사진 삭제',BROWSER+' 기록소유자만가능합니다.',
 '본문에부모의현재revision을넣어정확한visitid를삭제합니다.',
 '방문과포함사진/사진검토를삭제하고부모revision을증가시킵니다.다른방문은유지합니다.',
 '409는현재부모revision재조회;이미삭제404.응답유실은상세에서해당visit의부재를확인합니다.',ok(obj({'status':s('deleted.'),'revision':REV},'삭제후부모revision.')),['400','401','403','404','409','413','503'],example={'revision':1})
add('post','/v1/social/history/{item}/trace-batches','10 여행기록','동의된 browser-reported 경로 배치 추가',BROWSER+' 소유자와collectTrace:true가필요합니다.',
 '현재revision,클라이언트생성32hex batchId/streamId,label,시각증가points1~200을보냅니다.같은연속경로는streamId를유지하고새불변배치마다batchId를새로생성합니다.',
 '배치와부모revision을저장합니다.출처는browser-reported이며실차nativeGPS증명아님.기록합계100000점상한.자동수집UIcapability는false입니다.',
 '같은batchId와streamId/label/points가정확동일하면200 duplicate:true로재접수하며옛revision도허용합니다.다른내용409.신규201.동의철회403이면추가송신중단/점대기열폐기하세요.',
 {**created(obj({'id':IDENT,'revision':REV,'duplicate':b('신규는false.')},'신규경로배치결과.'),'새불변배치를추가했습니다.'),**ok(obj({'id':IDENT,'revision':REV,'duplicate':b('동일기존배치는true.')},'중복재접수결과.'),'이미저장된정확동일배치입니다.')},['400','401','403','404','409','413','429','503'])
add('post','/v1/social/history/{item}/visits/{visit}/photos','11 사진','내 방문에 권리를 확인한 사진 추가',BROWSER+' 기록소유자·현재visit·historyPhotoUpload:true가필요합니다.',
 '부모revision을읽고Content-Type:image/jpeg또는image/png로rawbytes≤3MiB를전송합니다.권리확인헤더true와현재부모revision헤더가필수.검토제출헤더는별도명시선택이며기본false입니다.',
 '격리decoder가방향적용/metadata제거/최대2048pxJPEG정제후암호화저장합니다.기본private이며방문당6장/소유자100MiB.방문공유만으로사진을열지않습니다.이Swagger JSON실행은차단됩니다.',
 'POST중복은새사진이므로응답유실시상세사진목록을조회합니다.409헤더PHOTO_VISIT_LIMIT/PHOTO_STORAGE_LIMIT는사용자가기존사진정리;revision409는재조회.408은업로드12초초과,503은처리불가입니다.',created(obj({'id':IDENT,'revision':REV,'photo':ref('Photo')},'정제사진metadata와부모revision.'),'사진을개인저장했으며검토요청여부는photo.review로확인합니다.'),['400','401','403','404','408','409','413','429','503'])
OPS[('post','/v1/social/history/{item}/visits/{visit}/photos')].setdefault('errorDescriptions',{})['408']='Image upload timed out: 사진 수신이 12초를 넘었습니다. 저장 성공으로 표시하지 말고 정본 사진 목록을 조회하세요.'
add('get','/v1/social/history/{item}/visits/{visit}/photos/{photo}','11 사진','현재 별도 허용된 사진 JPEG 조회',READ+' 소유자또는현재친구+visits/photosgrant+텍스트/사진현재승인이필요합니다. native는항상닫힘.',
 '기록상세visits[].photos[].url로호출합니다.원사진id를추측하거나다른visit로바꾸지마세요.',
 '매요청현재권한을검사한정제JPEG만반환하며private,no-store입니다.콘텐츠수신은외부파일export동의가아닙니다. Swagger binary실행은차단됩니다.',
 '404는목적철회/신고격리/사진삭제도포함하므로화면이미지와objectURL을폐기하세요.',{'200':{'description':'현재허용된정제JPEG. inline filename/Cache-Control:private,no-store.','content':{'image/jpeg':{'schema':{'type':'string','format':'binary'}}}}},['401','403','404','503'])
add('patch','/v1/social/history/{item}/visits/{visit}/photos/{photo}/review-request','11 사진','내 사진 한 장 검토 제출 또는 철회',BROWSER+' 기록/사진소유자만가능합니다.',
 '현재부모revision과consent:true/false를보냅니다.권리확인과별도의사진운영검토목적입니다.',
 '선택한사진의정제checksum/크기와JPEG만검토가능하게합니다.미동의다른사진/기록좌표를제출하지않습니다.부모revision을증가시킵니다.',
 'true는옛revision409,false철회는옛revision도가능.후속기록상세에서현재review/revision을확인하세요.',ok(obj({'review':ref('Review'),'revision':REV},'사진검토상태와부모revision.')),['400','401','403','404','409','413','503'],example={'revision':1,'consent':False})
add('post','/v1/social/history/{item}/visits/{visit}/photos/{photo}/reports','11 사진','현재 보이는 사진 한 장 신고',BROWSER+' 현재visits/photosgrant와현재사진승인을충족해볼수있는사용자여야합니다.',
 '기록상세의현재사진id와고정reason을보냅니다.다른사진/미승인원본을신고경로로열람할수없습니다.',
 '현재사진checksum을즉재격리해친구열람을중단합니다.현재exportfingerprint도바뀌어기존외부동의가자동복원되지않습니다.',
 '같은checksum/신고자/이유는같은reportId.202접수후기록상세정본을갱신합니다.',report(),['400','401','403','404','413','429','503'])
add('delete','/v1/social/history/{item}/visits/{visit}/photos/{photo}','11 사진','내 사진 한 장 삭제',BROWSER+' 기록소유자만가능합니다.',
 '현재부모revision을본문에넣고사용자명시삭제후호출합니다.',
 '사진bytes와metadata/검토를삭제하고부모revision을증가시킵니다.이미친구/외부파일에저장된사본을회수할수는없습니다.',
 '409는부모기록재조회,이미삭제404.응답유실이면해당사진목록을정본조회하고자동재업로드하지마세요.',ok(obj({'status':s('deleted.'),'revision':REV},'삭제후부모revision.')),['400','401','403','404','409','413','503'],example={'revision':1})
add('get','/v1/social/history/{item}/export-permissions','12 외부 영상','기록의 별도 외부 파일 생성 동의 확인',READ+' 브라우저전용이며소유자/현재기록접근이필요합니다.',
 '기록상세에서historyExportManifest를확인→이GET의historyRevision/대상revision/serverNow→소유자가명시PUT합니다.소유자는저장된대상전체,수신자는자기설정만받습니다.',
 '저장된consent와현재실효active를분리해반환합니다.내부친구공유나사진승인은외부파일동의가아닙니다. auth/session에는이리소스capability키가없을수있습니다.',
 '조회는안전합니다.데이터/공유/검토변경후consent:true라도active:false일수있습니다.',ok(ref('ExportPermissions')),['401','403','404','413','503'])
add('put','/v1/social/history/{item}/export-permissions/{target}','12 외부 영상','내 기록의 외부 파일 생성 목적을 특정 계정에 허용',BROWSER+' 기록소유자만가능하며target은자기자신또는현재친구입니다.',
 'GET의historyRevision과대상revision(아직설정없으면0)을보냅니다. consent는명시true,visits/trace중하나이상,photos이면visits필수.시간은serverNow기준미래≤24시간입니다.',
 '정확기록/내부공유revision/검수fingerprint에별도목적을묶습니다.반환revision은저장확정일뿐active보증이아니므로후속GET으로실효상태를확인합니다.',
 '409이면현재GET을읽고사용자선택을재확인합니다.단순재승인/재친구화로옛동의를복구하지않습니다.철회는DELETE입니다.저장된외부사본은회수불가.',ok(obj({'revision':REV,'historyRevision':REV},'저장한동의revision. active필드는여기에없습니다.')),['400','401','403','404','409','413','429','503'],notes='정상요청에는consent:true가필수입니다.실행초기본문false는의도적인안전값이며사용자가수신자/목적/기간을확인한뒤직접true로바꿔야합니다.')
add('delete','/v1/social/history/{item}/export-permissions/{target}','12 외부 영상','특정 계정의 외부 파일 생성 동의 철회',BROWSER+' 기록소유자만가능합니다.',
 '정확한exporter계정을지정합니다.옛revision없이즉철회할수있습니다.내부친구공유는별도유지됩니다.',
 '저장consent를false로바꾸고revision을증가시킵니다.이후manifest/사진재조회는현재동의로차단합니다.이미저장한파일을삭제할수는없습니다.',
 '설정이없어도revoked/revision0일수있습니다.설정이있으면반복철회도revision이증가하므로응답유실은GET으로확인하세요.',ok(obj({'status':s('revoked.'),'revision':n('설정이없으면0,있으면증가한동의revision.')},'외부동의철회결과.')),['401','403','404','503'])
add('post','/v1/social/story-manifests','12 외부 영상','현재 허용된 기록으로 단기 영상 입력 manifest 만들기',BROWSER+' 선택기록각각에본인대상별도외부consent와현재내부grant/텍스트·사진승인교집합이필요합니다.',
 'historyIds1~5를중복없이선택한순서로보냅니다.자기기록도명시외부동의가필요합니다.201manifest를받은뒤현재client가실제파일을별도로생성합니다.',
 '최대5분/동의만료중더이른기한의개인JSONsnapshot을저장합니다.경로양끝각200m점/해당방문을제외하고segmentId끊김을보존합니다.전체20000점/8MiB/활성manifest20개상한.',
 'POST마다별도manifest.응답유실은동의상태를확인후사용자재시도를받습니다.404는현재교집합미충족,413은점/크기상한,429는생성한도.완료MP4/외부게시성공응답이아닙니다.',created(ref('StoryManifest'),'개인단기JSON입력snapshot을생성했습니다.영상파일은별도client생성입니다.'),['400','401','403','404','413','429','503'])
add('get','/v1/social/story-manifests/{key}','12 외부 영상','내 manifest를 현재 권한으로 다시 확인',READ+' manifest생성계정만가능하며native/publiclink가아닙니다.',
 '렌더링/저장·공유직전에다시조회합니다.서버는원기록과현재동의/친구/승인/만료로재build한checksum을대조합니다.',
 '조회는동의를연장하지않습니다.보호영역제거·segmentId를그대로유지하고새배치/검토변경을옛snapshot에섞지마세요.',
 '404면준비중/현재파일공유를중단하고개인preview를폐기합니다.이미기기외부에저장된파일회수는불가합니다.',ok(ref('StoryManifest')),['401','403','404','413','503'])
add('delete','/v1/social/story-manifests/{key}','12 외부 영상','내 단기 manifest 폐기',BROWSER,
 '준비취소/화면종료에서자신이만든manifestkey를정리합니다.본문없음.',
 '현재계정의manifest행만삭제합니다.원기록/별도export동의/이미다운로드한외부파일은삭제하지않습니다.',
 '이미없거나다른계정소유여도deleted로종료해존재를드러내지않습니다.안전한반복정리입니다.',ok(status('deleted')),['401','403','404','503'])
add('get','/v1/social/story-manifests/{key}/photos/{item}/{visit}/{photo}','12 외부 영상','현재 manifest에 허용된 사진 한 장 조회',READ+' manifest소유계정과현재외부photos/visits동의·내부grant·사진승인이모두필요합니다.',
 '현재manifest응답의사진url만사용합니다.다른item/visit/photo경로로치환하지마세요. JSONSwagger실행은차단됩니다.',
 '매요청manifest전체checksum/권한을다시확인하고해당JPEG만반환합니다.영구public사진URL이아닙니다.',
 '404는철회/신고/만료/삭제/다른manifest도포함합니다.실패한사진을오래된캐시로대체해외부공유하지마세요.',{'200':{'description':'현재manifest에허용된정제JPEG. private,no-store/nosniff.','content':{'image/jpeg':{'schema':{'type':'string','format':'binary'}}}}},['401','403','404','413','503'])

# Exact causes of the shared 400/409/413 codes, taken from the current handlers.
NATIVE_400='JSON·필드·값이 handler 검사를 통과하지 못했습니다. Native 요청은 JSON 본문의 functionalRevision이 없거나 형식이 틀려도 400(INVALID_FUNCTIONAL_REQUEST)입니다.'
NATIVE_409='Native 요청의 functionalRevision이 현재 기능 동의 revision과 다릅니다(FUNCTIONAL_REVISION_CHANGED). 기능 동의를 다시 읽고 사용자가 다시 확인한 뒤 보냅니다.'
TRIP_ROOM_409='여행에 연결된 내부 방 ID입니다(TRIP_CLIENT_UPDATE_REQUIRED). 이 기간제 방 경로 대신 /v1/social/trips 여행 API를 사용합니다.'
def explain(method,path,**codes):OPS[(method,path)].setdefault('errorDescriptions',{}).update(codes)
for key in (('post','/v1/social/friends/requests/{target}/respond'),('delete','/v1/social/friends/{target}'),('post','/v1/social/blocks'),('delete','/v1/social/blocks/{target}')):
    explain(*key,**{'409':NATIVE_409,'413':'본문이4KiB를 넘었습니다. Native 본문에는 functionalRevision과 정의된 필드만 넣습니다.'})
explain('post','/v1/social/friends/requests',**{'409':'상대가 먼저 보낸 요청이 있어 respond로 수락·거절해야 합니다. '+NATIVE_409})
for key in (('get','/v1/social/rooms/{room}'),('patch','/v1/social/rooms/{room}/review-request'),('post','/v1/social/rooms/{room}/reports'),
            ('patch','/v1/social/rooms/{room}/signals/{identifier}/review-request'),('post','/v1/social/rooms/{room}/signals/{identifier}/reports')):
    explain(*key,**{'409':TRIP_ROOM_409})
for key in (('patch','/v1/social/rooms/{room}/consents'),('patch','/v1/social/rooms/{room}/role'),('post','/v1/social/rooms/{room}/leave'),
            ('delete','/v1/social/rooms/{room}/signals/{identifier}/vote')):
    explain(*key,**{'409':TRIP_ROOM_409+' '+NATIVE_409})
explain('post','/v1/social/rooms',**{'409':'활성 방 소유 한도(10개)이거나 선택 코스가 현재 승인 상태가 아닙니다. '+NATIVE_409})
explain('post','/v1/social/rooms/join',**{'409':'방 정원(10명)이 찼습니다. '+NATIVE_409})
explain('post','/v1/social/rooms/{room}/signals',**{'409':'방 신호 한도(5000개)에 도달했습니다. '+TRIP_ROOM_409+' '+NATIVE_409})
explain('post','/v1/social/rooms/{room}/signals/{identifier}/vote',**{'409':'선택 장소가 없는 신호입니다. '+TRIP_ROOM_409+' '+NATIVE_409})
explain('post','/v1/social/rooms/{room}/history',**{'409':'코스가 현재 승인 상태가 아니거나 기록 한도(500개)에 도달했습니다. '+TRIP_ROOM_409+' '+NATIVE_409})
explain('post','/v1/social/history',**{'409':'코스가 현재 승인 상태가 아니거나 기록 한도(500개)에 도달했습니다. '+NATIVE_409})
explain('put','/v1/social/history/{item}',**{'409':'기록 revision이 바뀌었거나 코스가 현재 승인 상태가 아닙니다. '+NATIVE_409})
explain('delete','/v1/social/history/{item}',**{'409':NATIVE_409})
explain('post','/v1/social/history/{item}/visits',**{'409':'부모 기록 revision이 바뀌었거나 방문 한도(500개)에 도달했습니다. '+NATIVE_409})
explain('put','/v1/social/history/{item}/visits/{vid}',**{'409':'부모 기록 revision이 바뀌었습니다. '+NATIVE_409})
explain('delete','/v1/social/history/{item}/visits/{vid}',**{'409':'부모 기록 revision이 바뀌었습니다. '+NATIVE_409})
explain('post','/v1/social/history/{item}/trace-batches',**{'409':'같은 batchId에 다른 내용을 보냈거나 revision이 바뀌었거나 기록의 점 한도(100000)를 넘습니다. '+NATIVE_409})
for key in (('post','/v1/social/rooms/{room}/leave'),('delete','/v1/social/rooms/{room}/signals/{identifier}/vote'),('delete','/v1/social/history/{item}'),
            ('delete','/v1/social/friends/{target}'),('delete','/v1/social/blocks/{target}')):
    explain(*key,**{'400':NATIVE_400})
explain('post','/v1/social/rooms/{room}/leave',**{'413':'Native 본문이16KiB를 넘었습니다. functionalRevision 하나만 보냅니다.'})
explain('delete','/v1/social/rooms/{room}/signals/{identifier}/vote',**{'413':'Native 본문이16KiB를 넘었습니다. functionalRevision 하나만 보냅니다.'})
explain('delete','/v1/social/history/{item}',**{'413':'Native 본문이256KiB를 넘었습니다. functionalRevision 하나만 보냅니다.'})


# These five current handlers share Browser and Native URLs, not credentials or
# projection contracts. Keep the Browser schemas unchanged in their own branch.
NATIVE_SOCIAL_OPERATIONS = (
    ('get', '/v1/social/overview'),
    ('get', '/v1/social/rooms/{room}'),
    ('get', '/v1/social/history'),
    ('post', '/v1/social/rooms/{room}/signals'),
    ('post', '/v1/social/history'),
)

# The remaining current functional routes of this area keep the Browser response
# DTO for Native. Each entry names its Native request model; None means a GET.
# Photo bytes stay out: that handler accepts only the Browser session.
NATIVE_SOCIAL_SHARED_OPERATIONS = (
    ('post', '/v1/social/friends/requests', 'NativeSocialFriendRequestBody'),
    ('post', '/v1/social/friends/requests/{target}/respond', 'NativeSocialFriendRespondBody'),
    ('delete', '/v1/social/friends/{target}', 'NativeSocialRevisionOnlyBody'),
    ('post', '/v1/social/blocks', 'NativeSocialBlockBody'),
    ('delete', '/v1/social/blocks/{target}', 'NativeSocialRevisionOnlyBody'),
    ('get', '/v1/social/invites/{code}', None),
    ('post', '/v1/social/rooms', 'NativeSocialRoomCreateBody'),
    ('post', '/v1/social/rooms/join', 'NativeSocialRoomJoinBody'),
    ('post', '/v1/social/rooms/{room}/leave', 'NativeSocialRevisionOnlyBody'),
    ('patch', '/v1/social/rooms/{room}/role', 'NativeSocialRoomRoleBody'),
    ('patch', '/v1/social/rooms/{room}/consents', 'NativeSocialRoomConsentsBody'),
    ('post', '/v1/social/rooms/{room}/signals/{identifier}/vote', 'NativeSocialVoteBody'),
    ('delete', '/v1/social/rooms/{room}/signals/{identifier}/vote', 'NativeSocialRevisionOnlyBody'),
    ('get', '/v1/social/history/{item}', None),
    ('post', '/v1/social/rooms/{room}/history', 'NativeSocialRoomHistoryBody'),
    ('put', '/v1/social/history/{item}', 'NativeSocialHistoryUpdateBody'),
    ('delete', '/v1/social/history/{item}', 'NativeSocialRevisionOnlyBody'),
    ('post', '/v1/social/history/{item}/visits', 'NativeSocialVisitBody'),
    ('put', '/v1/social/history/{item}/visits/{vid}', 'NativeSocialVisitUpdateBody'),
    ('delete', '/v1/social/history/{item}/visits/{vid}', 'NativeSocialVisitDeleteBody'),
    ('post', '/v1/social/history/{item}/trace-batches', 'NativeSocialTraceBatchBody'),
)
BROWSER_ONLY_FUNCTIONAL = {('get', '/v1/social/history/{item}/visits/{visit}/photos/{photo}')}
SOCIAL_PREFIXES = ('/v1/social/overview', '/v1/social/friends', '/v1/social/blocks', '/v1/social/invites',
                   '/v1/social/rooms', '/v1/social/history')
OTHER_OVERLAYS = ('/music', '/device-requests', '/device-command-access')


def native_note(method, path):
    if path.startswith(('/v1/social/friends', '/v1/social/blocks')):
        return ' 친구 요청·응답·취소·차단·해제는 friends:read와 friends:manage가 모두 필요하며 브라우저와 같은 계정 존재·차단·관계 검사를 거칩니다.'
    if path == '/v1/social/invites/{code}':
        return ' Native 응답도 브라우저와 같은 초대 요약 필드이며 요청에 쓴 code를 그대로 돌려줍니다. 조회만으로 가입하지 않습니다.'
    if path == '/v1/social/history/{item}':
        return ' Native 응답은 아래 NativeSocialHistory projection입니다. 공유 설정·수집 동의·사진 목록은 비우며 nativeReadOnly는 history:write 승인 여부입니다.'
    if path.startswith('/v1/social/history') or path.endswith('/history'):
        extra = ' 경로 배치는 history:write와 기록별 collectTrace 동의가 모두 필요합니다.' if path.endswith('/trace-batches') else ''
        source = (' Native로 저장한 방문·경로의 source.kind는 device-reported입니다.' if method != 'delete' and ('/visits' in path or path.endswith('/trace-batches'))
                  else ' 방에서 만든 기록의 source.kind는 room-confirmed입니다.' if path.endswith('/{room}/history') else '')
        return ' 연결한 본인 계정의 개인 기록을 history:read 목적으로 쓰며 소유자·revision 검사는 브라우저와 같습니다.' + source + extra
    return ' 방 생성·가입·나가기·역할·동의·투표는 rooms:read와 rooms:interact가 모두 필요하며 현재 멤버십·차단·동의 검사는 브라우저와 같습니다.'


def apply_native_social_documentation(original, auth):
    from copy import deepcopy
    from native_functional_policy import WIRE
    schema = deepcopy(original)
    models = schema['components']['schemas']
    native_security = {'NativeMTLS': [], 'DeviceBearer': []}
    rules = {(row['method'].lower(), row['path']): row for row in WIRE['nativeRoutes']}

    overview = deepcopy(models['SocialOverview'])
    overview['additionalProperties'] = False
    overview['properties']['history']['maxItems'] = 0
    overview['properties']['capabilities'] = dict(type='object', additionalProperties=False,
        description='이 Native 응답의 현재 기능 목적과 읽기 전용 projection 상태입니다. 각 실제 요청의 현재 권위 재검사를 대신하지 않습니다.',
        properties={key: dict(type='boolean', description=description) for key, description in {
            'friends': '현재 friends:read 목적입니다.', 'rooms': '현재 rooms:read 목적입니다.',
            'history': '현재 history:read 목적입니다.',
            'nativeReadOnly': 'friends:read와 friends:manage가 모두 승인된 경우에만 false입니다.'}.items()},
        required=['friends', 'rooms', 'history', 'nativeReadOnly'])
    overview['description'] = '하나 이상의 읽기 목적에 따른 부분 projection입니다. friends는 friends:read, rooms는 rooms:read일 때만 채웁니다. people/requests/blocks는 friends:read와 friends:manage가 모두 필요하며 history는 항상 빈 배열입니다.'
    models['NativeSocialOverview'] = overview

    room = deepcopy(models['Room'])
    for key in ('code', 'consents', 'availableConsentKeys', 'agreedStop'):
        room['properties'].pop(key, None)
    room['additionalProperties'] = False
    room['required'] = list(dict.fromkeys(list(room['properties']) + ['nativeReadOnly']))
    room['properties']['nativeReadOnly'] = dict(type='boolean', description='rooms:read와 rooms:interact가 모두 승인되면 false, rooms:read만 있으면 true입니다. false도 현재 방 멤버십과 요청별 권한을 대신하지 않습니다.')
    models['NativeSocialRoom'] = room

    summary = deepcopy(models['HistorySummary'])
    summary['additionalProperties'] = False
    summary['properties']['permissionRevision'] = dict(type='null', description='Native 목록은 소유자여도 공유 설정 revision을 노출하지 않습니다.')
    summary['properties']['sharedWith']['maxItems'] = 0
    models['NativeSocialHistorySummary'] = summary
    history_operation = schema['paths']['/v1/social/history']['get']
    history = deepcopy(history_operation['responses']['200']['content']['application/json']['schema'])
    history['additionalProperties'] = False
    history['required'] = list(dict.fromkeys(history['required'] + ['nativeReadOnly']))
    history['properties']['history']['items'] = ref('NativeSocialHistorySummary')
    history['properties']['friends']['maxItems'] = 0
    history['properties']['nativeReadOnly'] = dict(type='boolean', description='기존 차량 화면용 필드입니다. history:write가 꺼져 있으면 true입니다. 연결한 계정으로 직접 입력하는 개인 기록과 방문은 수정할 수 있고, 경로 업로드에는 history:write와 기록별 수집 동의가 모두 필요합니다.')
    caps = dict(history=True, historyRemix=False, historyTraceIngest=None, historyPhotos=False,
        historyPhotoUpload=False, historyReplay=True, historyExport=False, cautions=False)
    history['properties']['capabilities'] = dict(type='object', additionalProperties=False,
        description='현재 Native 기록 목록이 제공하는 기능의 고정/권한별 표시입니다. 기록별 수집·사진·외부 공유 동의나 실제 쓰기 승인을 만들지 않습니다.',
        required=list(caps), properties={key: dict(type='boolean', **({} if value is None else {'const': value}),
            description='historyTraceIngest는 현재 history:write 승인 여부이며 기록별 collectTrace 동의를 대신하지 않습니다.' if value is None else '현재 Native 기록 목록의 capability 값입니다.') for key, value in caps.items()})
    models['NativeSocialHistoryPage'] = history

    covered = set(NATIVE_SOCIAL_OPERATIONS) | {(method, path) for method, path, _ in NATIVE_SOCIAL_SHARED_OPERATIONS}
    expected = {key for key in rules if key[1].startswith(SOCIAL_PREFIXES) and not any(part in key[1] for part in OTHER_OVERLAYS)} - BROWSER_ONLY_FUNCTIONAL
    if covered != expected:
        raise RuntimeError('Native social documentation differs from wire: missing=%r orphan=%r' % (sorted(expected - covered), sorted(covered - expected)))

    def mark(method, path):
        operation = schema['paths'][path][method]
        rule = rules[(method, path)]
        browser_security = {'CloudflareAccess': [], 'TeamSession': []}
        if method != 'get': browser_security['CurrentSessionCSRF'] = []
        operation['security'] = [browser_security] + ([deepcopy(native_security)] if auth.native_origin else [])
        operation['servers'] = [dict(url=auth.public_origin, description='기존 웹 로그인과 변경 요청의 현재 CSRF')]
        if auth.native_origin:
            operation['servers'].append(dict(url=auth.native_origin, description='별도 Native 호스트: TLS1.3 개인 mTLS AND 같은 인증서의 현재 Bearer'))
        operation['x-wegoh-native-access'] = True
        operation['x-wegoh-native-functional-purposes'] = dict(all=rule['all'], any=rule['any'])
        operation['x-wegoh-surface'] = 'browser-and-native'
        operation['x-wegoh-executable'] = True  # explorer remains Browser-only
        feature = getattr(auth, 'functional_access', None)
        operation['x-wegoh-feature-enabled'] = bool(feature and feature.enabled and feature.base.enabled)
        operation['description'] += '\n\n### 현재 Native 계약\n별도 Native 호스트의 같은 개인 인증서와 Bearer로 확인된 단일 NativePrincipal을 사용합니다. 현재 연결과 기기, 만료 시각, 사용할 수 있는 기능을 같은 트랜잭션에서 확인합니다. 친구·여행·기록 조회와 사용자가 직접 하는 계정 작업은 차량 로그인으로 열립니다. Swagger 실행은 기존 Browser 세션만 사용합니다. 필요한 모든 목적: ' + (', '.join(rule['all']) or '없음') + '; 하나 이상 필요한 목적: ' + (', '.join(rule['any']) or '없음') + '.'
        return operation

    def functional_revision():
        return dict(type='integer', minimum=1, maximum=WIRE['revisionMaximum'], description='직전 기능 동의 정본의 revision을 JSON 본문에 넣습니다. 헤더나 업무 데이터 revision이 아닙니다. 같은 transaction에서 현재 revision과 일치해야 합니다.')

    def native_model(operation, name):
        native = deepcopy(operation['requestBody']['content']['application/json']['schema'])
        native['properties']['functionalRevision'] = functional_revision()
        native['required'].append('functionalRevision')
        if 'examples' in native:
            native['examples'] = [dict(value, functionalRevision=1) for value in native['examples']]
        models[name] = native

    def native_body(operation, name):
        content = operation['requestBody']['content']['application/json']
        browser = deepcopy(content['schema'])
        native_model(operation, name)
        content['schema'] = dict(oneOf=[browser, ref(name)], description='Browser는 기존 closed DTO, Native는 같은 DTO에 필수 functionalRevision을 추가합니다.')
        example = content.pop('example', None)
        if example is not None:
            content['examples'] = dict(browser=dict(value=example), native=dict(value=dict(example, functionalRevision=1)))

    response_models = {'/v1/social/overview': ('SocialOverview', 'NativeSocialOverview'),
        '/v1/social/rooms/{room}': ('Room', 'NativeSocialRoom')}
    for method, path in NATIVE_SOCIAL_OPERATIONS:
        operation = mark(method, path)
        if method == 'get':
            if path == '/v1/social/overview':
                browser = dict(allOf=[ref('SocialOverview'), dict(properties={'capabilities': {'description': 'Browser 응답의 capability에는 Native 전용 nativeReadOnly 필드가 없습니다.', 'not': {'required': ['nativeReadOnly']}}})])
            elif path == '/v1/social/history':
                browser = dict(allOf=[deepcopy(operation['responses']['200']['content']['application/json']['schema']), {'not': {'required': ['nativeReadOnly']}}])
            else:
                browser = dict(allOf=[ref(response_models[path][0]), {'not': {'required': ['nativeReadOnly']}}])
            model = 'NativeSocialHistoryPage' if path.endswith('/history') else response_models[path][1]
            operation['responses']['200']['content']['application/json']['schema'] = dict(oneOf=[browser, ref(model)], description='Browser와 Native의 projection을 구분합니다. Native의 nativeReadOnly는 현재 쓰기 목적에 따라 true 또는 false입니다.')
            operation['description'] += ' Native 응답은 위 Native 전용 schema의 부분 projection과 nullable 값을 따릅니다. 읽기 전용 여부는 항상 true가 아니며 현재 목적에서 계산합니다.'
        else:
            native_body(operation, 'NativeSocialSignalBody' if path.endswith('/signals') else 'NativeSocialHistoryBody')
            operation['description'] += ' Native도 성공은 HTTP201입니다. functionalRevision은 JSON 본문 필수이며 누락/잘못된 값은 400, 현재 동의 revision 불일치는 409입니다. operationId나 idempotency key는 받지 않습니다. 같은 POST를 반복하면 별도 항목이 생길 수 있습니다. 응답이 불확실하면 정본을 확인하며 새 revision으로 자동 재전송하지 않습니다.'
            operation['description'] += (' 신호는 kind와 현재 revision만으로도 보낼 수 있습니다. 반환 id는 방 GET의 signals에서 확인합니다. destination은 명시 선택이며 현재 위치 관련 조건도 적용합니다.' if path.endswith('/signals') else ' 기록은 개인 암호화 원본이며 collectTrace=false, 공유 없음, device-reported 출처입니다. 응답 유실은 기록 목록으로 확인하며 기록별 수집이나 공유를 자동 승인하지 않습니다.')

    models['NativeSocialRevisionOnlyBody'] = dict(type='object', additionalProperties=False, required=['functionalRevision'],
        properties={'functionalRevision': functional_revision()},
        description='Native 전용 본문입니다. 브라우저는 이 요청에 본문을 보내지 않습니다.')
    detail = models['History']['allOf'][1]['properties']
    detail['nativeReadOnly'] = dict(type='boolean', description='브라우저 응답에는 없습니다. Native 응답의 값은 NativeSocialHistory를 따릅니다.')
    models['NativeSocialHistory'] = dict(allOf=[ref('History'), dict(type='object',
        description='Native 기록 상세 projection입니다. 공유 설정·수집 동의·사진 목록은 비우고 source는 kind/actorId/receivedAt만 반환합니다.',
        required=['nativeReadOnly'], properties={
            'permissions': dict(type='null', description='Native는 소유자여도 수집 동의를 반환하지 않습니다.'),
            'permissionRevision': dict(type='null', description='Native는 공유 설정 revision을 반환하지 않습니다.'),
            'grants': dict(type='array', maxItems=0, description='Native는 공유 설정을 반환하지 않습니다.'),
            'sharedWith': dict(type='array', maxItems=0, description='Native는 공유 대상을 반환하지 않습니다.'),
            'visits': dict(type='array', items=dict(type='object', properties={'photos': dict(type='array', maxItems=0, description='Native는 사진 목록을 반환하지 않습니다.')}), description='현재 허용된 방문. 사진은 항상 빈 배열입니다.'),
            'nativeReadOnly': dict(type='boolean', description='history:write가 승인되지 않았으면 true입니다. 기록·방문 수정은 history:read로 허용되며 각 쓰기 요청이 현재 목적을 다시 검사합니다.'),
            'capabilities': deepcopy(history['properties']['capabilities'])})])
    for method, path, name in NATIVE_SOCIAL_SHARED_OPERATIONS:
        operation = mark(method, path)
        operation['description'] += native_note(method, path)
        if method == 'get':
            if path == '/v1/social/history/{item}':
                operation['responses']['200']['content']['application/json']['schema'] = dict(oneOf=[
                    dict(allOf=[ref('History'), {'not': {'required': ['nativeReadOnly']}}]), ref('NativeSocialHistory')],
                    description='Browser와 Native의 기록 상세 projection을 구분합니다.')
            continue
        if name == 'NativeSocialRevisionOnlyBody':
            operation['requestBody'] = dict(required=False, description='브라우저는 본문을 생략합니다. Native는 functionalRevision만 담은 JSON 본문이 필수입니다.',
                content={'application/json': dict(schema=ref(name), examples=dict(native=dict(value=dict(functionalRevision=1))))})
        else:
            # Browser request schema/example stay the explorer contract; the
            # Native DTO is the same closed body plus functionalRevision.
            native_model(operation, name)
            operation['x-wegoh-native-request-body'] = ref(name)
            operation['description'] += ' Native 본문 schema는 ' + name + '입니다(브라우저 본문 + functionalRevision).'
        operation['description'] += ' Native 본문에는 현재 functionalRevision이 필수입니다. 누락·형식 오류는 400, 현재 기능 동의 revision 불일치는 409입니다. 응답이 불확실하면 정본을 먼저 읽으며 새 revision으로 자동 재전송하지 않습니다.'

    # Browser-only archive save: the handler reads exactly roomId and title.
    archive = schema['paths']['/v1/social/history/from-archive']['post']
    archive_example = {'roomId': 'a' * 32, 'title': '함께 간 여행'}
    archive['requestBody'] = dict(required=True, content={'application/json': dict(example=archive_example, schema=dict(
        type='object', additionalProperties=False, required=['roomId', 'title'], examples=[archive_example],
        description='보관 방 ID와 새 개인 기록 제목만 받습니다. 다른 필드는 400입니다.',
        properties={'roomId': dict(type='string', pattern='^[a-f0-9]{32}$', description='GET /v1/social/room-archives 목록의32hex 보관 방 ID. 형식이 틀리면404입니다.'),
                    'title': dict(type='string', minLength=1, maxLength=100, description='새 개인 기록 제목. 1~100자이며 공백만 있거나 제어 문자가 있으면400입니다. 이미 저장한 방이면 무시하고 기존 기록을 반환합니다.')}))})
    archive['x-wegoh-try-example'] = archive_example
    archive.pop('x-wegoh-body-contract', None)
    archive['x-wegoh-executable'] = True
    return schema
