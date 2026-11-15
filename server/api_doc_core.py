"""Auth/device/course/operator operations. Each entry was checked against its handler."""
from api_doc_shared import *
OPS={}
def add(method,path,*args,**kw):OPS[(method,path)]=entry(*args,**kw)
add('get','/v1/auth/session','01 인증','현재 로그인과 CSRF 상태 확인',
 'Access 경계 로그인만 있어도 조회할 수 있습니다. WegoH 개인 세션이 없으면 authenticated=false입니다.',
 '앱 시작·계정 전환·변경 요청 전에 조회합니다. false이면 사용자가 로그인 행동을 선택한 뒤 POST /v1/auth/session을 호출합니다.',
 '데이터 변경 없음. csrfToken은 현재 세션의 비밀값이므로 로그/URL/영구 저장소에 남기지 않습니다.',
 '안전하게 다시 조회할 수 있습니다. 이전 계정의 응답은 현재 화면에 적용하지 마세요.',ok(ref('Session')),['401','403','503'])
add('post','/v1/auth/session','01 인증','Access 계정의 개인 세션 시작',
 '공개 origin의 유효한 Access 계정과 정확한 Origin이 필요합니다. 본문·이메일·비밀번호는 받지 않습니다.',
 '사용자 로그인 행동 → 이 POST → 응답의 authenticated/user/csrfToken 확인 → 필요한 REST 조회 순서입니다.',
 '4시간 Secure HttpOnly SameSite=Strict 개인 쿠키를 설정하고 해당 계정의 이전 쿠키 세션을 교체합니다. 로그인 계정 정보를 암호화 저장합니다.',
 '응답 유실 시 GET /v1/auth/session부터 확인합니다. 반복 POST는 새 세션을 만들며 15회/분 계정 제한이 있습니다.',ok(ref('Session')),['401','403','429','503'])
add('delete','/v1/auth/session','01 인증','현재 개인 세션 로그아웃',BROWSER,
 '현재 세션의 사용자 확인 → 이 DELETE → 화면·메모리 CSRF/개인 데이터를 비웁니다.',
 '현재 세션 DB행과 브라우저 쿠키를 제거합니다. 다른 기기의 연결을 모두 철회하는 API는 아닙니다.',
 '응답 유실 시 GET session으로 확인합니다. 이미 만료되었으면 401일 수 있으며 성공 응답을 꾸미지 마세요.',ok(ref('Session')),['401','403','503'])
add('get','/v1/account','02 기기 연결','native token의 본인 계정 확인',NATIVE+' Authorization: Bearer 개인 access token이 필요합니다.',
 '한 번의 명시 웹 동의와 현재 연결 교환으로 발급된 개인 access token을 받은 기기가 호출합니다.',
 '조회만 수행합니다. 응답 user/deviceId는 요청 토큰의 계정/기기에만 결합됩니다.',
 '401이면 현재 연결 복구·갱신 정본을 따릅니다. 철회·원기한 만료 시 같은 키로 새 명시 동의가 필요합니다.',
 ok(obj({'user':obj({'id':ACCOUNT,'displayName':s('현재 본인 표시 이름.')},'현재 native 계정의 최소 공개 정보.'),'deviceId':IDENT},'현재 native 개인 기기 계정.')),['401','403','404','429','503'])
add('get','/v1/devices','02 기기 연결','내 활성 기기 목록 조회',READ,
 '내가 승인한 기기의 id/name/expiresAt를 확인하고 개별 permissions 또는 revoke를 선택합니다.',
 '철회되지 않고 만료되지 않은 본인 기기를 최신 생성순 최대100개 반환합니다. 다른 계정 기기·token은 반환하지 않습니다.',
 '안전한 조회입니다. WSS devices invalidate 후 다시 읽으세요.',ok(obj({'devices':arr(ref('Device'),'본인 활성 기기.')},'개인 기기 목록.')),['401','403','503'])
add('delete','/v1/devices/{device_id}','02 기기 연결','선택한 내 기기 연결 전체 철회',BROWSER,
 'GET devices에서 현재 id/name을 확인한 뒤 명시 철회합니다. 기기를 유지하며 선택 범위를 줄이려면 GET permissions 정본의 revision/scopes로 PUT합니다.',
 '기기 전체 token을 revoked로 만듭니다. 자동 재승인이나 새 token발급은 없습니다.',
 '이미 철회/다른 소유자는404입니다. 응답 유실이면 devices 목록과 현재 계정에서 확인하세요.',ok(status('revoked')),['401','403','404','503'])
add('delete','/v1/device','02 기기 연결','native 기기가 자기 연결 철회',NATIVE+' 현재 본인의 access token이 필요합니다.',
 '기기 로그아웃을 사용자가 선택하면 호출하고 성공 뒤 모든 로컬 token을 폐기합니다.',
 '요청 token의 기기 하나를 철회합니다. 다른 deviceId를 지정하거나 계정 전체를 삭제하지 않습니다.',
 '재전송은 이미 철회된 token으로401일 수 있습니다. 로컬 token을 계속 사용하지 마세요.',ok(status('revoked')),['401','403','404','429','503'])
add('get','/v1/devices/{device}/permissions','03 기기 읽기 동의','내 기기의 목적별 읽기 설정 조회',READ,
 'GET devices에서 고른 device ID로 조회합니다. revision과 이름을 확인한 뒤 PUT에서 명시 선택을 저장합니다.',
 '기존 pairing은 course/music 범위이며 friends/rooms/history는 기본 false입니다. 사진·쓰기·차량제어 권한은 추가되지 않습니다.',
 '조회 응답이 정본입니다. 다른 계정·철회·만료 기기는404입니다.',ok(ref('DevicePermissions')),['401','403','404','503'])
add('put','/v1/devices/{device}/permissions','03 기기 읽기 동의','내 기기의 세 가지 읽기 목적 명시 저장',BROWSER,
 'permissions GET의 revision을 가져와 friends/rooms/history 세 boolean을 모두 보냅니다. 사용자가 실제 확인한 목적만 true로 선택합니다.',
 '모든 목적값을 교체하고 revision을 증가시킵니다. 변경된 기기 WSS 권한은 재연결 때 정본 snapshot으로 적용됩니다.',
 '409는 GET으로 최신 revision을 읽고 선택을 재확인합니다. 응답이 없으면 GET으로 확인하고 허용 상태를 옛 false로 단정하지 마세요.',ok(ref('DevicePermissions')),['400','401','403','404','409','413','429','503'],example={'revision':1,'permissions':{'friends':False,'rooms':False,'history':False}})
add('delete','/v1/devices/{device}/permissions/{purpose}','03 기기 읽기 동의','내 기기의 읽기 목적 하나 즉시 철회',BROWSER,
 'friends/rooms/history 중 한 purpose를 지정합니다. 옛 revision 때문에 철회가 막히지 않도록 본문과 revision이 없습니다.',
 '선택 목적만 false로 저장합니다. 나머지 목적과 기기 연결은 유지합니다. 이미 false이면 변경 없이 정본을 반환합니다.',
 '같은 대상의 재철회는 안전합니다. 404이면 현재 기기 목록에서 소유/만료를 확인하세요.',ok(ref('DevicePermissions')),['401','403','404','503'])
add('get','/v1/device/permissions','03 기기 읽기 동의','native 기기가 자기 읽기 동의 확인',NATIVE+' 현재 개인 access token이 필요합니다.',
 '연결 직후와 목적변경 WSS 종료 후 읽습니다. true인 목적만 corresponding GET을 호출합니다.',
 '조회만 수행합니다. 기기 스스로 목적을 허용하거나 browser PUT을 대신할 수 없습니다.',
 '401은 token 재인증,404는 기능/호스트/기기 상태를 확인합니다.',ok(ref('DevicePermissions')),['401','403','404','429','503'])
add('get','/v1/native/rooms','03 기기 읽기 동의','native에서 현재 허용된 내 방 목록 조회',NATIVE+' 개인 token과 기기의 rooms 목적 true가 매 요청 필요합니다.',
 'GET /v1/device/permissions → rooms=true 확인 → 이 목록 → 필요한 방의 /v1/social/rooms/{room} 상세 순서입니다.',
 '현재 멤버/기간/차단에 맞는 요약만 반환합니다. 가입·역할변경·동의수정은 browser 전용입니다.',
 '재조회 가능하며 rooms 목적 철회 시404로 닫힙니다. 이전 목록을 현재 권한으로 재사용하지 마세요.',ok(obj({'rooms':arr(ref('RoomSummary'),'본인 활성 방.'),'nativeReadOnly':b('항상 true.')},'native 읽기 전용 목록.')),['401','403','404','429','503'])
add('post','/v1/packs','04 코스','내 드라이브 코스 새 버전 즉시 게시',BROWSER+' creator 또는 admin 역할이 필요합니다.',
 '코스 편집기에서 장소 1~3개와 선택 대표 이미지를 정하고 권리를 확인합니다. 차량용 Drive Pack 호환성을 위해 편집기가 기존 도착 설정을 유지하거나 기본값을 채웁니다. 새 ID는 버전 1, 기존 ID는 마지막 버전 다음 번호로 게시합니다.',
 '정규 JSON을 checksum주소로 불변 저장합니다. author는 현재 계정 표시 이름으로 대체됩니다. 새 버전은 사전 검토 없이 state=approved로 즉시 공개합니다. 신고 보류·거절 상태인 기존 버전은 동일 요청 재시도로 다시 공개하지 않습니다.',
 '같은 id/version의 정규 원문·태그·대표 이미지가 모두 같으면 200, 새 버전은 201입니다. 이미 게시한 버전의 내용 변경, 다른 소유자 또는 비연속 버전은 409입니다. 응답 유실 시 내 버전의 원문·태그·대표 이미지를 조회합니다.',
 {**created(ref('PublishedCourse'),'새 불변 코스 버전을 저장하고 즉시 공개했습니다.'),**{'200':response(ref('PublishedCourse'),'동일한 원문·태그·대표 이미지로 이미 게시한 버전입니다. 현재 검수상태를 반환합니다.')}},['400','401','403','404','408','409','413','429','503'],notes='서버발급재창작pack ID는본인remixDraftId를함께보내야하며서버가현재기록/별도목적/원출처권리를다시검사합니다. receipt를생략하거나다른ID로붙여known draft검사를우회할수없습니다. 일반직접창작은그대로입니다. rightsConfirmed=true는 사용자 명시 확인 후에만 보냅니다. 대표 이미지는 coverImage 또는 copyCoverFromVersion 중 하나를 지정합니다. 둘 다 생략하면 새 버전은 대표 이미지 없이 게시됩니다. 이미지는 차량 코스 JSON과 체크섬에서 분리해 저장합니다. 아래 본문 기본값 false는 의도적 실행 방지값입니다. 내비 요청/실차 ACK를 수행하는 API는 아닙니다.')
OPS[('post','/v1/packs')]['errorDescriptions']={'408':'코스 게시 본문 수신이 5초를 넘었습니다. 게시되지 않았으므로 내 코스 목록에서 정본을 확인한 뒤 사용자가 다시 게시합니다.',
 '429':'대표 이미지 처리기가 다른 게시를 처리 중입니다. Retry-After: 1 이후 사용자가 다시 게시합니다.'}
add('get','/v1/packs','04 코스','게시 즉시 가용한 공개 코스 목록 조회',
 '공유 운영에서는 공개 browser host의 Access 경계가 필요합니다. handler 자체는 개인 세션을 요구하지 않습니다. native의 현재 개인 token 읽기도 지원됩니다.',
 '목록의 id/version/checksum으로 정확한 버전을 다운로드하고 checksum을 검증합니다.',
 'id당 사후 공개 제한이 없는 최신 게시 버전을 최대100개 반환합니다. 사전 승인 여부로 가리지 않습니다.',
 '조회는 안전합니다. courses invalidate 후 다시 읽으며 과거 조회 성공을 현재 공개 제한 해제로 추정하지 마세요.',ok(obj({'packs':arr(ref('CourseSummary'),'각 id의 최신 가용 게시 버전.')},'현재 가용 게시 목록.')),['401','403','429','503'])
add('get','/v1/packs/{pack_id}/versions/{version}','04 코스','게시된 정확한 코스 JSON 다운로드',
 '공유 browser Access 또는 별도 native 개인 token이 필요합니다. 사전 승인 없이 사후 공개 제한이 없는 버전을 반환합니다.',
 'catalogue에서 받은 정확 id/version으로 호출 → ETag/checksum과 다운로드 JSON바이트 확인 → 앱 로컬 파싱 순서입니다.',
 '조회만 수행하며 JSON의 chime 계획이 실제 NaviHelper·오디오 실행 성공을 뜻하지 않습니다.',
 '신고/사후 공개 제한 후404일 수 있습니다.503은 저장 무결성 문제이므로 캐시를 새 성공으로 표시하지 마세요.',ok(ref('DrivePack'),'정확한 게시 코스 JSON. 강한 ETag는 SHA-256 checksum이며 Cache-Control은 로컬에서 no-cache, no-transform, 공유 모드에서 private, no-store, no-transform입니다.'),['401','403','404','422','429','503'])
COURSE_COVER_RESPONSE={'200':{'description':'해당 버전의 처리된 JPEG. Cache-Control은 private, no-store, no-transform이며 X-Content-Type-Options는 nosniff입니다.',
    'content':{'image/jpeg':{'schema':{'type':'string','format':'binary'}}}}}
add('get','/v1/packs/{pack_id}/versions/{version}/cover','04 코스','게시된 코스 버전의 대표 이미지 조회',
 '공유 운영에서는 공개 브라우저 호스트의 Access 로그인이 필요합니다.',
 '공개 목록에서 선택한 코스의 ID와 버전으로 대표 이미지를 조회합니다.',
 '현재 가용한 버전에 연결된 대표 JPEG만 반환합니다.',
 '사후 공개 제한 또는 대표 이미지가 없는 버전은 404입니다.',COURSE_COVER_RESPONSE,['401','403','404','422','503'])
COURSE_STAR_SUMMARY=obj({'id':s('코스 ID.'),'version':n('게시 버전.'),'title':s('코스 제목.'),
 'author':s('코스 작성자 표시 이름.'),'description':s('코스 설명.'),'stopCount':n('장소 수.'),
 'starred':b('내 계정의 저장 여부.'),'starCount':n('이 게시 버전에 별표를 남긴 계정 수.'),
 'tags':arr(s('공개 태그.'),'이 게시 버전의 태그.'),
 'canFollow':b('이 창작자를 구독할 수 있는지 여부.'),'followId':nullable(s('내 구독의 식별자.')),
 'creatorRank':nullable(n('공개 코스 별표로 집계한 창작자 순위. 상위 3명에게만 제공.'))},'현재 가용한 코스 요약과 개인 상태.')
COURSE_NEWS_ITEM=obj({**COURSE_STAR_SUMMARY['properties'],'eventId':s('이 코스의 기존 발행 이벤트 ID.'),
 'approvedAt':TIME,'read':b('내 계정이 이 소식을 읽었는지 여부.')},'구독 이후 발행된 코스 소식. approvedAt은 호환 이름이며 발행 시각입니다.')
add('get','/v1/studio/course-library','04 코스','공개·저장 코스와 내 구독 소식 조회',READ+' 브라우저 개인 세션 전용입니다.',
 'public은 코스별 최신 가용 게시 버전이며 선택한 tag로 좁힐 수 있습니다. saved는 내가 저장한 게시 버전입니다. news와 following에서 구독 소식과 관리 목록을 조회합니다.',
 '사전 승인으로 가리지 않습니다. 구독 이후 발행 시각과 현재 사후 공개 제한을 확인하고 최근 소식30개를 반환합니다.',
 '별표·구독 변경 또는 코스 사후 공개 제한 변경 뒤 다시 조회합니다.',
 ok(obj({'public':arr(COURSE_STAR_SUMMARY,'각 코스의 최신 가용 게시 버전.'),'saved':arr(COURSE_STAR_SUMMARY,'내 계정이 저장한 게시 버전.'),
 'news':arr(COURSE_NEWS_ITEM,'내 구독의 현재 공개 소식.'),
 'following':arr(obj({'id':s('내 구독 식별자.'),'name':nullable(s('공개 코스에 표시한 창작자 이름.'))},'내 구독.'),'구독 취소에 사용하는 내 구독 목록.')},
 '공개 코스, 개인 저장과 구독 소식.')),['400','401','403','404','503'])
add('put','/v1/studio/course-stars/{pack_id}/versions/{version}','04 코스','공개 코스 버전에 별표 남기고 저장',BROWSER,
 '공개 코스의 ID와 버전을 선택합니다. 요청 본문은 없습니다.',
 '현재 가용한 버전에만 내 계정의 별표 한 개를 저장합니다.',
 '같은 요청을 반복해도 별표는 늘어나지 않습니다. 404면 공개 코스를 다시 조회합니다.',
 ok(obj({'starred':b('저장됐으면 true.')},'내 별표 상태.')),['401','403','404','422','429','503'])
add('delete','/v1/studio/course-stars/{pack_id}/versions/{version}','04 코스','내 코스 별표 및 저장 해제',BROWSER,
 '저장한 코스 ID와 버전을 선택합니다. 요청 본문은 없습니다.',
 '내 계정의 별표를 해제합니다.',
 '이미 해제된 경우에도 같은 응답을 반환합니다.',
 ok(obj({'starred':b('해제됐으면 false.')},'내 별표 상태.')),['401','403','404','422','429','503'])
add('put','/v1/studio/course-follows/{pack_id}/versions/{version}','04 코스','공개 코스의 창작자 구독',BROWSER,
 '현재 가용한 공개 코스 ID와 버전으로 창작자를 선택합니다. 요청 본문은 없습니다.',
 '내 계정의 구독을 시작합니다. 본인이나 차단 관계의 창작자를 구독할 수 없습니다.',
 '같은 구독을 반복해도 최초 구독 시점과 식별자를 유지합니다.',
 ok(obj({'followId':s('내 구독 식별자.')},'구독 결과.')),['401','403','404','422','429','503'])
add('delete','/v1/studio/course-follows/{follow_id}','04 코스','내 창작자 구독 취소',BROWSER,
 'following에 있는 내 구독 식별자를 보냅니다. 요청 본문은 없습니다.',
 '구독을 취소하고 해당 구독의 소식 읽음 상태를 정리합니다.',
 '이미 취소됐거나 다른 계정의 구독 식별자여도 응답은 같습니다.',
 ok(obj({'following':b('취소 뒤 false.')},'구독 취소 결과.')),['401','403','404','422','429','503'])
OPS[('delete','/v1/studio/course-follows/{follow_id}')]['errorDescriptions']={
 '404':'기기 인증 요청이거나 브라우저 호스트가 아닌 요청입니다. 구독 존재 여부로는 404를 내지 않습니다.',
 '422':'follow_id가 UUID 형식이 아닙니다.'}
add('put','/v1/studio/course-news/{event_id}/read','04 코스','내 구독 소식을 읽음으로 표시',BROWSER,
 'news에서 표시된 eventId를 보냅니다. 요청 본문은 없습니다.',
 '현재 구독과 사후 공개 제한을 확인하고 내 읽음 상태를 저장합니다.',
 '읽은 항목을 다시 요청해도 상태는 유지됩니다. 공개가 철회된 항목은 404를 반환합니다.',
 ok(obj({'read':b('읽음 처리 뒤 true.')},'소식 읽음 결과.')),['401','403','404','422','429','503'])
add('get','/v1/studio/packs','04 코스','내 게시 버전과 공개 상태 목록 조회',READ+' native 본인 기기 token도 courses:read로 읽을 수 있습니다.',
 '게시응답 유실/검수 진행을 확인할 때 호출하고 정확 버전의 내 상세로 이동합니다.',
 '본인 모든상태 버전을 최신생성순 최대1000개 반환합니다. 타인 소유 원본은 포함하지 않습니다.',
 '재조회 가능하며 courses invalidate후 정본을 확인합니다.',ok(obj({'packs':arr(ref('OwnedCourseSummary'),'본인 버전과 현재 검수 상태.')},'작성자 목록.')),['401','403','429','503'])
add('get','/v1/studio/packs/{pack_id}/versions/{version}','04 코스','본인 코스의 정확한 원문 조회',READ+' native는 현재 mTLS·Bearer·courses:read와 소유자 ACL을 모두 요구하며 사후 공개 제한을 확인합니다.',
 '내 catalogue의 id/version/checksum/state를 확인합니다. browser는 본인 편집 원문을 읽고 native는 사전 승인 없이 현재 사후 공개 제한을 확인합니다. 응답 직전 잠금 안에서 현재 계정·grant·scope·slot·credential epoch·기한을 다시 확인합니다.',
 '256 KiB 이하 DrivePack JSON만 반환하며 관리자 정보·검토자·검토 메모·재사용 권한·개인 출처는 포함하지 않습니다. 상태는 본인 목록의 state이며 읽기 성공은 권리 부여나 차량 실행 승인이 아닙니다. 크기·SHA-256·id/version·스키마·1~3개 지점 검사를 유지합니다.',
 '다른 소유자/없는 버전 및 native의 실제 사후 거절·신고 격리는404입니다. 사전 승인 없는 코스 게시와 원본 접근 권한은 구분합니다. 잠금/철회/epoch 변경은 거절하며 익명 공개 경로로 재시도하지 않습니다.',ok(ref('DrivePack'),'본인 원문 JSON. native ETag는 SHA-256이며 private, no-store, no-transform입니다(browser 응답도 no-transform).'),['400','401','403','404','410','422','429','503'])
OPS[('get','/v1/studio/packs/{pack_id}/versions/{version}')]['errorDescriptions']={'410':'현재 개인 grant의 원 연결 기한이 만료됐습니다. 원문이나 캐시를 사용할 권한으로 해석하지 말고 명시 재연결 흐름을 따릅니다.'}
add('get','/v1/studio/packs/{pack_id}/versions/{version}/cover','04 코스','본인 코스 버전의 대표 이미지 조회',READ,
 '내 코스 목록에서 선택한 버전의 ID와 버전으로 대표 이미지를 조회합니다.',
 '승인 상태와 관계없이 현재 브라우저 계정이 소유한 버전의 대표 JPEG를 반환합니다.',
 '다른 소유자, 없는 버전 또는 대표 이미지가 없는 버전은 404입니다.',COURSE_COVER_RESPONSE,['401','403','404','422','503'])
add('get','/v1/moderation/packs','05 운영 검수','코스 검수 대상 버전 목록 조회',ADMIN,
 '목록 → 버전 원문 GET → 전체콘텐츠/권리 판단 → checksum을 묶은 review POST 순서입니다.',
 '최대1000개 버전의 id/version/checksum/state/title/tags를 반환합니다. title은 게시 메타데이터의 최대100자 표시용 제목입니다. 목록 조회가 검수 완료를 뜻하지 않습니다.',
 '안전한 재조회. 현재 역할이 바뀌면403.',ok(obj({'packs':arr(obj({'id':s('코스 안정 ID.'),'version':n('게시 버전.'),'checksum':CHECK,'state':s('quarantined/approved/rejected 현재 상태.'),'title':s('게시 메타데이터의 표시용 코스 제목.',maxLength=100),'tags':arr(s('공개 태그.'),'이 버전의 검수 대상 태그.')},'게시 버전별 검수 상태, 제목 및 태그.'),'검수 대상 버전.')},'검수자 코스 목록.')),['401','403','503'])
add('get','/v1/moderation/packs/{pack_id}/versions/{version}','05 운영 검수','검수할 정확한 코스 원문 조회',ADMIN,
 '수신 원문 바이트의 SHA-256을 queue checksum과 대조하고 본문 전체를 실제 검토한 뒤 같은 checksum으로 결정합니다. ETag 형식이나 유무가 바이트 검증을 대체하지 않습니다.',
 '미승인코스도 검수권한으로 읽습니다. Cache-Control은 로컬에서 no-store, no-transform, 공유 모드에서 private, no-store, no-transform으로 원문 변형을 금지하며 강한 ETag는 원문 checksum입니다. 파일 무결성 실패는503이며 다른자료로 대체판정하지 않습니다.',
 '조회 재시도 가능. 결정 전 현재원문을 다시 확인합니다.',ok(ref('DrivePack'),'검수용 코스 JSON. ETag는 실제 checksum.'),['401','403','404','422','503'])
add('get','/v1/moderation/packs/{pack_id}/versions/{version}/cover','05 운영 검수','검수할 코스 버전의 대표 이미지 조회',ADMIN,
 '검수 목록의 코스 ID와 버전으로 대표 이미지를 조회하고 해당 버전의 원문과 함께 검토합니다.',
 '승인 상태와 관계없이 해당 버전에 저장된 대표 JPEG를 조회합니다.',
 '없는 버전 또는 대표 이미지가 없는 버전은 404입니다.',COURSE_COVER_RESPONSE,['401','403','404','422','503'])
add('post','/v1/moderation/packs/{pack_id}/versions/{version}','05 운영 검수','검토한 코스 checksum 승인 또는 거절',ADMIN,
 '직전 inspect의 checksum과 전체 검토 근거를 넣습니다. 웹 reviewer는 현재계정 표시이름으로 대체됩니다.',
 '현재 checksum의 검수 상태를 변경하고 감사event를 추가합니다. approved만 catalogue/download에 노출됩니다. 자동어휘필터나 마켓승인이 아닙니다.',
 '응답 유실 시 목록 재조회 후 결정합니다. 같은POST도 감사event를 추가하므로 무조건재전송 금지;409는 원문/체크섬 재검토.',ok(obj({'checksum':CHECK,'state':s('approved 또는 rejected.')},'결정한 현재코스 상태.')),['400','401','403','404','409','413','422','503'])
add('get','/v1/moderation/reports','05 운영 검수','코스 신고 목록 조회',ADMIN,
 '신고 내용은 기존4개 reason과 정확 checksum을 기준으로 코스원문을 따로 확인합니다.',
 '최근 최대1000개 코스신고 metadata를 반환합니다. 일반 history/photo 신고전문을 모두 보여주는 API가 아닙니다.',
 '안전한 조회. 신고된코스의 현재state는 코스검수목록에서 확인합니다.',ok(obj({'reports':arr(obj({'id':IDENT,'packId':s('신고 코스id.'),'version':n('신고버전.'),'checksum':CHECK,'reason':s('harmful/privacy/rights/other.'),'createdAt':TIME},'코스신고metadata.'),'최근 신고.')},'코스 전용 신고 목록.')),['401','403','503'])
add('post','/v1/packs/{pack_id}/versions/{version}/reports','04 코스','정확한 코스 버전 신고',BROWSER,
 '사용자가 본 코스의 id/version과 reason을 선택해 신고합니다. 임의 자유본문은 받지 않습니다.',
 'checksum+신고자+reason 중복신고는 같은 reportId를 사용하고 현재코스상태를 quarantined로 바꿉니다. 이후 전체검토가 필요합니다.',
 '응답 유실 시 동일대상/이유재전송은 같은신고ID이지만 재격리감사event는 추가될 수 있습니다. 다른 버전으로 자동변경하지 마세요.',report(),['400','401','403','404','413','422','503'])
add('get','/v1/moderation/content','05 운영 검수','명시 제출된 콘텐츠 검토대기 목록 조회',ADMIN,
 '100건 metadata를 페이지로 읽고 선택한 한 건만 detailUrl로 inspect합니다. nextCursor가 null이면 끝입니다.',
 '현재quarantined이고 제출·계정·기간·투영checksum이 유효한 항목만 반환합니다. projection본문/사진을 목록에서 일괄반환하지 않습니다.',
 '동일cursor재조회 가능하나 새변경이 있으면 첫페이지부터읽습니다. cursor를 직접조립하지 마세요.',ok(obj({'items':arr(ref('ContentItem'),'projection을 제외한 metadata.'),'nextCursor':nullable(s('다음페이지 opaque cursor.'))},'검토대기 metadata 목록.')),['400','401','403','503'])
add('get','/v1/moderation/content/{kind}/{key}','05 운영 검수','선택한 한 콘텐츠의 제출 투영본 확인',ADMIN,
 'queue item의 kind/key로 호출하고 현재review.checksum 및 projection을 실제읽습니다. photo일 때만 선택된 mediaUrl을 읽습니다.',
 'history는제목/장소명/후기/경로명,room과room-place는이름,photo는정제JPEGmetadata만입니다. 미제출원본·GPS·다른사진열람권한이 아닙니다.',
 '철회/만료는404,변경은409. 그런 경우 원문/폼을 비우고 재조회하며 이전checksum으로 결정하지 마세요.',ok(ref('ContentItem')),['401','403','404','409','503'])
add('get','/v1/moderation/content/{kind}/{key}/media','05 운영 검수','선택한 제출 사진의 정제 JPEG 확인',ADMIN,
 'kind=photo인 현재 inspect결과의 mediaUrl만 호출합니다. JSON Try it out은 binary를실행하지않으므로 제품 검토 UI를 사용합니다.',
 '현재제출·checksum·기간을다시검사하고private,no-store JPEG를 반환합니다. 개인미제출사진은404입니다.',
 '재조회때도현재권한이필요합니다.철회후저장한사본을서버가회수한다고약속하지않습니다.',{'200':{'description':'현재 선택된 제출 JPEG. Cache-Control: private, no-store.','content':{'image/jpeg':{'schema':{'type':'string','format':'binary'}}}}},['401','403','404','409','503'])
add('post','/v1/moderation/content/{kind}/{key}','05 운영 검수','검토대기 투영 checksum 승인 또는 거절',ADMIN,
 'inspect의review.state=quarantined와checksum을확인하고projection전체를실제검토한뒤decision/reviewNote를보냅니다.',
 'typed투영승인과암호화감사event를저장합니다. 친구grant·외부export동의를대신하지않습니다. 웹reviewer는현재계정이름을사용합니다.',
 '409는상태/checksum변경입니다. 재조회·재검토하고자동재승인하지마세요. 응답유실은상세조회로확인하며같은결정재전송은409일수있습니다.',ok(ref('Review')),['400','401','403','404','409','413','503'])
add('get','/v1/places/search','06 호환·개발','Studio에서 이름 또는 주소로 장소 검색',READ+' 웹 전용이며 Native 호스트와 기기 권한에는 열지 않습니다.',
 'q에 trim 후 2~60자 이름·주소를 보냅니다. 지도 중심 경도 x와 위도 y는 함께 생략하거나 함께 전달합니다. 결과를 골라 기존 확인·저장 흐름으로 이어갑니다.',
 '카카오 키워드·주소 API를 각각 한 번 호출하고 ID 또는 같은 좌표·주소의 중복을 제거해 키워드 우선 최대 15개를 반환합니다. 서버 캐시나 장소 DB를 만들지 않습니다.',
 '계정당 최근 60초 30회 제한입니다. 키 미설정은 503, 외부 실패는 502, 전체 3초 제한 초과는 504입니다. 검색 자동 재시도는 하지 않습니다.',
 ok(obj({'places':dict(arr(obj({'id':s('공급자 구분을 포함한 검색 결과 ID.'),'name':s('장소명. 주소 결과는 도로명 또는 지번 주소.'),
    'address':s('지번 주소. 빈 값일 수 있습니다.'),'roadAddress':s('도로명 주소. 빈 값일 수 있습니다.'),'category':s('장소 분류 또는 주소.'),
    'lat':dict(type='number',minimum=-90,maximum=90,description='위도.'),'lng':dict(type='number',minimum=-180,maximum=180,description='경도.'),
    'source':s('항상 kakao.',enum=['kakao']),'placeUrl':s('새 탭으로 여는 카카오맵 HTTPS 링크.')},'현재 검색 결과.'),'캐시하지 않은 검색 결과.'),maxItems=15)},'웹 장소 검색 응답. Cache-Control: private, no-store.')),
 ['400','401','403','404','429','502','503','504'],notes='REST 키는 서버 전용 0600 파일에서 읽습니다.')
OPS[('get','/v1/places/search')]['errorDescriptions']={
 '400':'PLACE_SEARCH_QUERY_INVALID: q 문자수·제어문자, x/y 조합·유한 범위, 알 수 없는 또는 중복 파라미터를 확인하세요.',
 '404':'기기 인증 요청이거나 Native 호스트의 요청입니다. 차량 앱은 이 웹 검색을 사용하지 않습니다.',
 '429':'PLACE_SEARCH_RATE_LIMITED: 계정당 최근 60초 30회를 넘었습니다. Retry-After: 60 이후 다시 검색합니다.',
 '502':'PLACE_SEARCH_PROVIDER_UNAVAILABLE: 외부 인증·쿼터·리다이렉트·잘못된 응답은 외부 본문 없이 같은 오류로 반환합니다.',
 '503':'PLACE_SEARCH_UNAVAILABLE: REST 키 파일이 없거나 소유자·0600 권한·내용이 안전하지 않아 검색만 비활성입니다. PLACE_SEARCH_BUSY: 프로세스 전체 검색 작업 4개가 실행 중입니다. 잠시 후 다시 검색합니다.',
 '504':'PLACE_SEARCH_TIMEOUT: 검색 전체 3초 제한을 넘었습니다. 늦은 결과는 버립니다.'}
add('post','/v1/routes/preview','04 코스','Studio 코스 도로 경로 미리보기',BROWSER+' 웹 전용이며 Native에는 열지 않습니다.',
 'points에 순서대로 1~3개 좌표를 보냅니다. origin은 선택이며 생략/null이면 첫 장소에서 마지막 장소까지 계산합니다. 좌표는 lat 32~39, lng 124~132의 유한 숫자입니다.',
 '카카오모빌리티 자동차 길찾기를 한 번 호출합니다. 거리(m), 시간(s), 최대 2000개 [lat,lng] 도로 좌표만 반환하며 서버 캐시·DB·코스에 저장하지 않습니다. 출발지 없는 한 장소는 외부 호출 없이 0/0/빈 path입니다.',
 '계정당 최근 60초 20회, 프로세스 전체 동시 작업 4개, 전체 4초 제한입니다. 자동 재시도는 없습니다. 응답 Cache-Control: private, no-store.',
 ok(obj({'distanceMeters':dict(type='number',minimum=0,description='총 도로 거리(m).'),
         'durationSeconds':dict(type='number',minimum=0,description='총 예상 소요 시간(s).'),
         'path':dict(type='array',maxItems=2000,items=dict(type='array',minItems=2,maxItems=2,items={'type':'number'}),description='지도용 [lat,lng] 도로 경로. 첫 점과 마지막 점을 보존해 축약합니다.')},'저장하지 않는 경로 미리보기.')),
 ['400','401','403','404','413','422','429','502','503','504'],example={'points':[{'lat':37.544,'lng':127.037},{'lat':37.55,'lng':127.05}]})
OPS[('post','/v1/routes/preview')]['errorDescriptions']={
 '400':'ROUTE_INPUT_INVALID: 알 수 없는 필드·좌표 범위·숫자 형식·장소 1~3개를 확인하세요.',
 '404':'기기 인증 요청이거나 Native 호스트의 요청입니다. 차량 앱은 공개 코스별 route-preview 경로를 사용합니다.',
 '422':'ROUTE_NOT_FOUND: 공급자가 경로를 찾지 못했습니다. 마커만 표시하고 위치를 다시 확인합니다.',
 '429':'ROUTE_RATE_LIMITED: 최근 60초 20회 초과. Retry-After: 60.',
 '502':'ROUTE_PROVIDER_UNAVAILABLE: 외부 인증·쿼터·리다이렉트·응답 오류. 외부 본문이나 키는 반환하지 않습니다.',
 '503':'ROUTE_UNAVAILABLE: 기존 REST 키 파일이 없습니다. ROUTE_BUSY: 전체 동시 작업 4개가 실행 중입니다.',
 '504':'ROUTE_TIMEOUT: 전체 4초 제한을 넘었습니다. 늦은 결과를 버립니다.'}
add('get','/v1/places/visited','06 호환·개발','본인 legacy 방문 장소 목록 조회',READ,
 '이경로는visited_places호환저장소를읽습니다. 새로운여행기록방문은 /v1/social/history/{item}에서조회합니다.',
 '장소id별가장최근visitedAt만최대100개반환합니다. 공유서버에는이legacy표의정상신규입력API가없어목록이비어있을수있습니다.',
 '조회재시도가능. 빈목록을차량방문수집완료로표시하지마세요.',ok(obj({'places':arr(ref('LegacyPlace'),'장소별최근방문.')},'legacy호환목록.')),['401','403','503'])
add('delete','/v1/places/visited','06 호환·개발','본인 legacy 방문 저장소 전체 비우기',BROWSER,
 'GETlegacy목록을확인한뒤사용자가전체제거를명시선택한경우만호출합니다.',
 '현재계정visited_places행전체를삭제합니다. 새TeamHistory기록은삭제하지않습니다. 복구API는없습니다.',
 '반복호출은cleared를반환합니다.네트워크유실후GET으로확인합니다.',ok(status('cleared')),['401','403','503'])
add('post','/v1/local/packs/{pack_id}/versions/{version}/reports','06 호환·개발','로컬 에뮬레이터에서 받은 코스 checksum 신고',
 '공유서비스에서는404. WEGOH_LOCAL_STUDIO=1의loopback개인워크스페이스·정확Origin·X-WegoH-Local-Report:1만허용됩니다.',
 '에뮬레이터가다운로드한정확checksum과reason을명시합니다. 개인외부로그인·실차인증대체가아닙니다.',
 '로컬코스checksum을재격리합니다. 운영key/사용자GPS를APK에넣지않습니다.',
 '다른checksum이면409. 같은코스/이유는중복신고ID를재사용합니다.',report(),['400','403','404','409','413','422','503'])
add('post','/v1/local/visits','06 호환·개발','로컬에서 선택한 방문만 명시 저장',
 '공유서비스에서는404. opt-inloopback워크스페이스·정확Origin·X-WegoH-Local-Visit:1이필요합니다.',
 '사용자가완료장소만선택→consent:true→최대100visit전송합니다.백그라운드위치수집API가아닙니다.',
 'legacy개인저장소에암호화저장하며같은visitid는덮어쓰지않습니다. accepted는입력개수이며신규행개수와다를수있습니다.최대1000행.',
 '같은id재전송은기존행을보존합니다.409는용량을사용자가정리해야합니다.',ok(obj({'accepted':n('검증한 입력 visit 수. 신규삽입수와다를수있음.')},'로컬선택방문접수.')),['400','403','404','409','413','503'])
for method,title in [('post','로컬 창작 세션 시작 (공유 서버 비활성)'),('delete','로컬 창작 세션 종료 (공유 서버 비활성)')]:
 add(method,'/v1/studio/session','06 호환·개발',title,
  '공유서비스에서는404입니다. 공유 로그인은/v1/auth/session을 사용합니다. 로컬 POST 시작은 WEGOH_LOCAL_STUDIO=1과 loopback이 필요합니다. 로컬 DELETE는 opt-in/loopback을 별도로 검사하지 않고 정확 Origin과 현재 로컬 쿠키를 정리합니다.',
  '로컬개인창작모드에서만정확Origin으로호출합니다.본문은없습니다.',
  'POST는4시간로컬창작cookie,DELETE는현재로컬cookie제거.외부개인인증/차량기기동의가아닙니다.',
  '공유host의404를우회하려고key를추가하지마세요.',ok(obj({'creator':s('POST의고정로컬창작자이름.'),'mode':s('POST:local-workspace.'),'status':s('DELETE:signed-out.')},'alias별응답.',required=[])),['403','404','503'])
add('get','/v1/dev/status','06 호환·개발','로컬 자산 개발 모드 정보 (공유 기능 아님)',
 '일반개발서버의운영Bearer key경로입니다.public host는 Access와 운영 Bearer를 함께 검증합니다. native와 공유 loopback 경계에서는404입니다.',
 '자산호환도구에서만호출합니다.웹Swagger는이경로를실행하지않습니다.',
 'stage/asset상한은legacy개발설명이며현재여행방지원여부의정본은auth/resourcecapabilities입니다.',
 '안전조회지만운영key를브라우저/APK에입력하지마세요.',ok(obj({'stage':s('pack-studio.'),'pack_publishing':b('legacy코스게시지원값.'),'trip_rooms':b('legacy상태필드false;현재방capability대체가아님.'),'asset_limit_bytes':n('실제설정한자산byte상한.'),'allowed_media_types':arr(s('허용MIME.'),'실제자산MIME목록.')},'개발전용legacy상태.')),['401','403','404'])
add('post','/v1/assets','06 호환·개발','개발용 raw 자산 업로드 (공유 기능 아님)',
 '일반개발서버운영Bearer key가필요합니다.public host는 Access+운영 Bearer가 필요합니다. native와 공유 loopback에서는404입니다.',
 '개발도구에서실MIMEContent-Type과rawbinary를전송합니다.사진방문upload와다른저장소이며Swagger실행은차단됩니다.',
 '실제checksum주소로완료파일을원자저장합니다.업로드bytes한도는개발설정값입니다.',
 '동일bytes는동일id를재사용합니다.빈파일400/미지원MIME415/크기413.응답유실은checksumGET으로확인합니다.',created(obj({'id':CHECK,'media_type':s('처음저장한MIME.'),'byte_size':n('실제저장byte수.')},'개발자산metadata.'),'자산을저장하거나동일checksum기존자산을확인했습니다.'),['400','401','404','413','415','503'])
add('get','/v1/assets/{checksum}','06 호환·개발','checksum 개발 자산 다운로드 (공유 기능 아님)',
 '운영 Bearer key 전용이며 public host에서는 Access도 필요합니다. native와 공유 loopback은404입니다. 개인 사진 URL 대체가 아닙니다.',
 '개발upload응답의checksum으로만조회합니다.웹Swagger는binary실행을차단합니다.',
 '저장MIME그대로raw파일을반환하며private,no-store입니다.',
 '재조회가능.404는없는checksum,503은저장소불가입니다.',{'200':{'description':'저장한media_type의raw파일. MIME은upload응답을참조하세요.','content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}}},['401','404','503'])

add('get','/v1/app-release','06 호환·개발','검증된 서명 APK 배포 식별자 조회',
 '공유 browser host의 Access 경계가 필요합니다. 개인세션은 handler가 요구하지 않으며 native host는 허용하지 않습니다. 운영자가 검증한 catalog를 명시 설정하지 않으면404입니다.',
 '앱 업데이트 확인에서 packageName/versionCode와 다운로드한 APK·서명 지문을 비교하는 metadata로만 사용합니다. 다운로드URL이나설치행동을생성하지않습니다.',
 'handler는 설정된 catalog의 형식·식별 필드만 검증합니다. APK bytes/서명 자체 검증은 별도 생산 절차입니다. debug APK·준비중파일을 실제 서명 release로 표시하지 않습니다.',
 '조회는안전합니다.404는미설정,503은파일/형식/지문필드검증불가입니다.다른APK로자동대체하지마세요.',
 ok(obj({'schemaVersion':n('현재1.'),'packageName':s('io.wegoh.app.'),'versionCode':n('서명release의양의정수버전.'),'versionName':s('검증한release표시버전.'),'apkSha256':CHECK,'signingCertificatesSha256':arr(CHECK,'현재검증된서명인증서SHA256,1~8개.')},'서명release식별metadata.')),
 ['401','403','404','503'])

add('put','/v1/profile/handle','01 인증','본인 친구 핸들 변경',BROWSER,
 'session.user.handle을 expectedHandle로, 원하는 핸들을 handle로 보냅니다. 선택적 @ 뒤 ASCII 영문·숫자로 시작하는 3~20자, 밑줄·점만 허용합니다.',
 '소문자로 저장하며 모든 계정 사이에서 대소문자를 무시한 유일성을 보장합니다. 이름·인증 권한·기존 관계는 유지합니다.',
 '5회/분 시도 제한, 성공 변경은 24시간에 한 번입니다. 409는 사용 중 또는 이전 값 충돌입니다. session을 다시 읽고 재입력합니다.',
 ok(obj({'handle':s('저장된 소문자 핸들. @ 제외.')},'본인 핸들.')),['400','401','403','409','413','429','503'])

for path in ('/v1/profile','/v1/account'):
 add('put',path,'01 인증','본인 계정 이름 변경',
  BROWSER if path=='/v1/profile' else NATIVE+' 현재 로그인한 본인의 이름을 변경합니다. 별도 휴대전화 승인은 필요하지 않습니다.',
  '현재 session 또는 account의 displayName을 expectedDisplayName에 넣고 직접 입력한 displayName을 보냅니다. 이름은 웹과 다른 연결 기기에도 적용됩니다.',
  '본인 encrypted identity의 표시 이름만 저장합니다. ID·이메일·역할·allowlist·다른 계정·콘텐츠 작성자 기록은 바꾸지 않습니다.',
  '409 PROFILE_CHANGED 또는 응답 유실 시 현재 계정을 다시 조회하고 사용자가 다시 저장을 선택해야 합니다. 자동 재전송하지 않습니다.',
  ok(obj({'user':obj({'id':ACCOUNT,'displayName':s('저장된 본인 계정 이름.')},'현재 이름 정본.')},'이름 변경 결과.')),['400','401','403','408','409','413','429','503'])

for verb in ('get','put'):
 add(verb,'/v1/device/vehicle-profile','02 기기 연결','이 차량의 이름·수동 번호판 '+('조회' if verb=='get' else '저장'),NATIVE,
  '현재 인증한 차량 앱 설치의 이름과 번호판만 취급합니다. Pleos 자동 조회나 차량 소유권 인증 결과가 아닙니다.',
  '계정+설치 식별자에 묶인 encrypted identity에 저장합니다. 다른 차량·계정과 분리되며 새 설치에서는 재등록합니다. 빈 번호판은 등록 해제, 빈 이름은 기본 이름입니다. 이름은 연결 차량 목록·리모컨·방 명령 대상에 표시됩니다.',
  '409이면 정본 revision을 다시 읽고 직접 저장합니다. 만료·철회된 기기는 조회·수정할 수 없습니다.',
  ok(obj({'deviceId':IDENT,'plateNumber':s('수동 입력 번호판. 미등록은 빈 문자열.',maxLength=16),
          'name':s('소유자가 정한 차량 이름. 정하지 않았으면 빈 문자열이며 defaultName을 표시합니다.',maxLength=20),
          'defaultName':s('이름을 정하지 않았을 때 쓰는 "{계정 이름}의 차". 계정 이름을 바꾸면 함께 바뀝니다.'),
          'revision':n('미등록 0, 저장할 때마다 증가하는 revision.',minimum=0,maximum=2147483647)},'현재 설치의 차량 프로필.')),
  ['400','401','403','404','410','429','503']+(['408','409','413'] if verb=='put' else []))

for verb in ('get','put'):
 add(verb,'/v1/devices/{device}/vehicle-profile','02 기기 연결','내 기기의 차량 이름·번호 '+('조회' if verb=='get' else '수정'),BROWSER,
  '기기 목록에서 현재 본인이 소유한 기기만 선택합니다. 수정은 CSRF와 현재 브라우저 세션이 필요합니다.',
  'native 차량 프로필과 동일한 암호화 정본이며 설치별로 분리합니다. 빈 번호는 등록 해제, 빈 이름은 기본 이름입니다.',
  '409이면 새 revision을 조회하고 직접 저장합니다. 다른 소유자·철회·만료 기기는 변경하지 않습니다.',
  ok(obj({'deviceId':IDENT,'plateNumber':s('수동 입력 번호판 또는 미등록 빈 값.',maxLength=16),
          'name':s('소유자가 정한 차량 이름 또는 기본 이름을 따르는 빈 값.',maxLength=20),
          'defaultName':s('이름을 정하지 않았을 때 쓰는 "{계정 이름}의 차".'),
          'revision':n('저장 시 비교하는 현재 revision.',minimum=0,maximum=2147483647)},'차량 프로필.')),
  ['400','401','403','404','410','429','503']+(['408','409','413'] if verb=='put' else []))
 OPS[(verb,'/v1/devices/{device}/vehicle-profile')]['errorDescriptions']={
  '410':'GRANT_EXPIRED: 이 기기 연결(grant)의 원 기한이 지났습니다. 철회된 연결은 403 CONSENT_REVOKED입니다. 차량에서 새로 연결합니다.'}

# Operations whose handler reads no request body; the explorer may run them without a JSON editor.
NO_BODY={('post','/v1/studio/session'),('put','/v1/studio/course-stars/{pack_id}/versions/{version}'),
 ('put','/v1/studio/course-follows/{pack_id}/versions/{version}'),('put','/v1/studio/course-news/{event_id}/read')}
