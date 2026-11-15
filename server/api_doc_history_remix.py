"""Two explicit itinerary re-creation paths; no implied history/media licence."""
from api_doc_shared import entry,response,obj,s,n,b,arr,ref,nullable,TIME,READ,BROWSER
from api_doc_models import IDENT,ACCOUNT,CHECK

strict=lambda fields,description:dict(obj(fields,description),additionalProperties=False)
REV=n('이 목적/기록의 현재 revision. 미설정 목적은0.',minimum=0,maximum=2147483647)
KIND=s('course=현재 승인 원코스, visits=실제 저장한 방문 장소의 명시 선택.',enum=['course','visits'])
REASON=nullable(s('현재 실행 불가 이유. null은 이 시점 가능이며 물리 방문/법률 권리 인증이 아닙니다.',enum=['no-source-course','source-unavailable','source-reuse-denied','remix-not-allowed','visits-sharing-required','no-saved-visits','creator-required']))
ROOT='/v1/social/history/{item}'
SOURCE='/v1/studio/packs/{pack_id}/versions/{version}'
SOURCE_REF=obj({'courseId':s('불변 승인 원코스 ID.'),'version':n('그 원코스 버전.',minimum=1),'checksum':CHECK,'reuseRevision':REV,'reuseConsent':b('원작성자가 다른 계정의 원코스 재사용을 별도로 허용했는지. 기본false.'),'canManageReuse':b('현재 사용자가 실제 원작성자인지. 기록 소유와 다릅니다.'),'ownSource':b('본인이 원작성자이면 자신의 코스 재창작에 전역 허용을 요구하지 않습니다.')},'원코스의 현재 권한 정본. 실제 생성/게시 때 재검증합니다.')
COURSE_PATH=strict({'kind':{'const':'course','description':'원코스 재창작 경로.'},'allowed':b('현재 계정이 이 경로를 사용할 수 있는지.'),'reason':REASON,'fingerprint':dict(CHECK,description='원기록 revision·원코스 버전/checksum·재사용목적revision의 정본 지문. 권한 자체를 대신하지 않습니다.'),'source':nullable(SOURCE_REF)},'원코스가 없으면source null/allowedfalse이며 방문 경로는 별개입니다.')
VISIT_PATH=strict({'kind':{'const':'visits','description':'저장된 방문 장소 경로.'},'allowed':b('현재 방문 읽기와 별도 일정 재사용 목적/검토/권리가 충족되는지.'),'reason':REASON,'fingerprint':dict(CHECK,description='현재 저장 방문 장소/보고시각/저장순서와 기록 revision의 정본 지문.'),'visits':arr(obj({'id':IDENT,'name':s('현재 읽을 수 있는 실제 저장 장소 이름. 임의 POI를 생성하지 않습니다.'),'visitedAt':dict(TIME,description='이 기록의 사용자 보고 방문시각. 실제 GPS 도착 인증이 아닙니다.'),'ordinal':n('보고방문시각순, 같은시각은 저장순으로 정한 원자료 순번.',minimum=1)},'사진·후기·trace/좌표를 불필요하게 복사하지 않는 선택목록.'),'실제 저장 방문 후보. 자동 첫3개 선택을 하지 않습니다.'),'orderBasis':{'const':'reported-visit-time-then-stored-order','description':'실제 저장된 두 시각에 근거한 순서. 지리적으로 추정하지 않습니다.'}},'원코스가 없어도 명시 선택한1~3장소로 새 편집초안을 만들 수 있습니다.')
PROVENANCE=obj({'kind':KIND,'historyId':IDENT,'courseId':s('course 경로의 원코스 ID.'),'version':n('course 원버전.',minimum=1),'checksum':CHECK,'visitIds':dict(arr(IDENT,'visits 경로에서 실제 명시 선택한 원순서ID.'),minItems=1,maxItems=3,uniqueItems=True)},'개인 편집초안의 원출처. course/visits에 맞는 필드만 존재하며 공개게시 응답에는historyId/visitIds를 노출하지 않습니다.',required=['kind','historyId'])
TRIP_COURSE_SOURCE=strict({'courseId':s('완료 여행에서 고른 공유 원코스 ID.'),'version':n('여행에 고정된 원코스 버전.',minimum=1),'checksum':CHECK},'공유 코스의 불변 원출처.')
TRIP_PROVENANCE=strict({'kind':{'const':'trip','description':'완료 여행의 공유 코스 장소만 선택한 초안.'},'tripId':IDENT,
    'courses':dict(arr(TRIP_COURSE_SOURCE,'선택한 장소의 공유 원코스. 개인 픽업·드랍은 포함하지 않음.'),minItems=1,maxItems=3)},'본인에게만 제공하는 여행 초안 출처. 공개 출처에서는 tripId를 제거합니다.')
PROVENANCE=dict(oneOf=[PROVENANCE,TRIP_PROVENANCE],description='개인 기록 재창작 또는 완료 여행 공유 코스의 현재 출처.')
MODELS={
 'HistoryRemixGrant':obj({'accountId':ACCOUNT,'kind':KIND,'revision':REV,'consent':b('저장된 별도 재창작 허용. 읽기 동의가 대신하지 않습니다.'),'active':b('현재 원자료·친구·공유 등 조건에서 허용이 유효한지. 저장consent와 구분합니다.')},'기록 소유자는 대상별, 수신자는 본인 목적만 봅니다.'),
 'HistoryRemixPermissions':obj({'revision':n('현재 원기록 데이터revision.',minimum=1),'permissionRevision':n('현재 원기록 공유/목적revision. 친구 생성 요청도 정본값이 필요합니다.',minimum=1),'own':b('본인 기록인지.'),'paths':{'type':'array','description':'두 경로를 별도로 판단하며 원코스없음이 저장방문경로를 막지 않습니다.','minItems':2,'maxItems':2,'items':{'oneOf':[COURSE_PATH,VISIT_PATH]}},'grants':arr(ref('HistoryRemixGrant'),'별도 재창작 목적. 사진/trace/후기 읽기를 복제하지 않습니다.'),'serverNow':dict(TIME,description='이 권한 정본을 계산한 서버 시각.')},'현재 읽기/원권리와 분리된 itinerary 재사용 상태. 실제 실행에서 다시 검사합니다.'),
 'CourseReusePermission':obj({'revision':REV,'checksum':CHECK,'consent':b('다른 사용자의 원코스 재사용을 명시 허용했는지.'),'active':b('현재 승인 원코스/원작성자/권리확인에서 유효한지.'),'serverNow':TIME},'원작성자 본인만 설정하며 기록 소유자는 타인의 원코스를 허가할 수 없습니다.'),
 'HistoryRemixPermissionSaved':obj({'accountId':ACCOUNT,'kind':KIND,'revision':REV,'consent':b('저장된 별도 목적.'),'permissionRevision':n('변경 후 부모 기록 목적revision.',minimum=1)},'false철회는stale요청으로막지않습니다. 이후새GET을읽습니다.'),
 'HistoryRemixDraft':obj({'draft':ref('DrivePack'),'remixDraftId':dict(IDENT,description='현재 사용자/원기록/현재권리/새코스ID에 묶인 서버 저장 receipt. 기기토큰이 아닙니다.'),'source':PROVENANCE},'새 ID/version1의 편집초안. 게시/검토/내비출발 성공이 아닙니다. 좌표는 허용 원자료만 사용합니다.'),
 'HistoryRemixSource':obj({'remixDraftId':IDENT,'source':PROVENANCE},'본인 게시 재창작 코스를 다시 편집할 때 필요한 현재 receipt/출처. 일반코스404,권리철회403/409.'),
 'RemixPublicationSource':obj({'kind':KIND,'courseId':s('course 경로의 공개 원코스 ID.'),'version':n('공개 원버전.',minimum=1),'checksum':CHECK,'placeCount':n('visits 경로의 명시 선택 장소 수.',minimum=1,maximum=3)},'공개 응답용 최소출처. 개인historyId/visitIds·후기·사진·trace는 노출하지 않습니다.',required=['kind'])}
MODELS['RemixPublicationSource']['properties']['kind']=s('course / visits / trip 공유 장소 출처.',enum=['course','visits','trip'])
MODELS['RemixPublicationSource']['properties']['courses']=dict(arr(TRIP_COURSE_SOURCE,'trip 경로의 공개 공유 코스 출처. tripId는 공개하지 않음.'),minItems=1,maxItems=3)
BODY={
 ('put',SOURCE+'/reuse-permission'):strict({'revision':REV,'checksum':CHECK,'consent':b('원작성자 본인의 다른 계정 재사용 허용.'),'rightsConfirmed':b('true허용일 때 원콘텐츠를 재사용하도록 허가할 권리가 있음을 직접 확인. 서버는 법적 소유권을 독립 인증하지 않습니다.')},'false철회는stale revision으로차단하지않으며 미승인 원코스에서도 본인철회는가능합니다.'),
 ('put',ROOT+'/remix-permissions/{target}'):strict({'revision':REV,'historyRevision':n('현재 원기록revision.',minimum=1),'permissionRevision':n('현재 원기록목적revision.',minimum=1),'kind':KIND,'sourceFingerprint':nullable(CHECK),'consent':b('선택 경로의 일정재사용 별도 허용.'),'rightsConfirmed':b('true허용은 실제 저장 장소metadata를 재사용하도록 허가할 권리까지 본인이 명시확인해야합니다. 사진/후기/trace 권리가 아닙니다.')},'현재 친구/읽기공유/검토/원권리 교집합. false철회는stale revision/fingerprint로막지않습니다.'),
 ('post',ROOT+'/remix'):strict({'revision':n('원기록 정본revision.',minimum=1),'permissionRevision':n('원기록 목적 정본revision.',minimum=1),'kind':KIND,'sourceFingerprint':CHECK,'visitIds':dict(arr(IDENT,'course는빈배열,visits는실존1~3개명시선택이며원자료순서를지켜야합니다.'),maxItems=3,uniqueItems=True),'rightsConfirmed':{'const':True,'description':'선택 콘텐츠의 새 편집·게시 권리를 사용자가 확인. 예제/읽기동의로 추정하지 않습니다.'}},'서버가현재상태를다시검사해GCM편집초안과예약된새코스ID를저장합니다.')}
OPS={}
def add(method,path,title,sequence,schema,effects,example=None,created=False):
 errors=['401','403','404','503'] if method=='get' else ['400','401','403','404','408','409','413','429','503']
 if method=='get' and ('remix-drafts/' in path or path.endswith('/remix-source')):errors.append('409')
 if '{version}' in path:errors.append('422')
 OPS[(method,path)]=entry('17 기록 재창작',title,(READ if method=='get'else BROWSER)+' Native 새조회/쓰기는열지않습니다. 생성·게시에는현재creator/admin계정이필요합니다.',sequence,effects,'409는새권한/원자료정본을다시읽고사용자가재선택합니다. 자동동의/임의좌표채움/원본잘라내기/receipt누락재게시로우회하지않습니다.',{'201'if created else'200':response(ref(schema),'현재개인정본. 실제방문/법적권리/게시검토완료를인증하지않습니다.')},errors,example=example,notes='원기록·승인원코스와공유목적을매번재검증합니다. 이미다운로드한사본이나공개된과거코스의외부회수를보장하지않습니다. 알려진서버발급draft코스ID는receipt를생략해도게시검사를벗어나지못합니다.')
 if method!='get':OPS[(method,path)]['errorDescriptions']={'408':'본문 전송을 5초 안에 마치지 못했습니다. 초안/권한 저장 성공으로 표시하지 말고 현재 권한 또는 내 초안을 다시 조회하세요.','413':'재창작 JSON 본문은 8KiB 이하여야 합니다. 장소/권리 필드를 조용히 잘라 보내지 마세요.'}
add('get',ROOT+'/remix-permissions','현재 기록의 코스·저장 방문 재창작 권한 확인','현재기록상세→이GET→두경로의원자료/권리/이유를확인합니다.','HistoryRemixPermissions','원기록·원코스의현재상태만읽고목적/초안을자동생성하지않습니다.')
add('put',ROOT+'/remix-permissions/{target}','친구에게 경로별 일정 재사용을 별도 허용·철회','기록소유자가현재친구·읽기공유·원권리를확인→course/visits와현재지문→명시허용. false는철회만수행합니다.','HistoryRemixPermissionSaved','기존방문/사진/trace읽기권한은확대하지않습니다. 부모목적revision과history무효화만갱신합니다.',{'revision':0,'historyRevision':1,'permissionRevision':1,'kind':'visits','sourceFingerprint':'0'*64,'consent':True,'rightsConfirmed':True})
add('get',SOURCE+'/reuse-permission','원작성자가 코스의 별도 재사용 목적 읽기','원작성자본인의게시코스→원version/checksum과현재재사용상태확인.','CourseReusePermission','다른기록소유자가남의원코스에권한을부여할수없습니다.')
add('put',SOURCE+'/reuse-permission','원작성자가 다른 계정의 코스 재사용을 허용·철회','원작성자본인→현재revision/checksum→권리확인후명시허용. false는stale로차단하지않습니다.','CourseReusePermission','원코스의불변파일/검토상태는변경하지않고암호화된별도목적만저장합니다. 기존draft의새게시도현재권리를재확인합니다.',{'revision':0,'checksum':'0'*64,'consent':True,'rightsConfirmed':True})
add('post',ROOT+'/remix','승인 원코스 또는 실제 저장 방문으로 편집초안 생성','두경로중하나를명시선택. course는현재승인원코스/원권리,visits는실제1~3장소를원순서로명시선택합니다. 친구는읽기와별도재창작허용/검토가모두필요합니다.','HistoryRemixDraft','새ID/version1과개인receipt를저장합니다. 사진·후기·trace·타인계정정보를복제하지않고새GPS/방문을생성하지않습니다. 장소확인반경100m/chime는새편집기기본값이며원측정값이아닙니다.',{'revision':1,'permissionRevision':1,'kind':'visits','sourceFingerprint':'0'*64,'visitIds':['1'*32],'rightsConfirmed':True},created=True)
add('get','/v1/social/remix-drafts/{draft_id}','본인 편집초안의 현재 권리와 원출처 복원','본인receipt→현재기록/권리재검증→편집원본을다시엽니다.','HistoryRemixDraft','권리철회/삭제/버전변경을새허용으로해석하지않고미허용이면닫습니다.')
add('get',SOURCE+'/remix-source','본인 재창작 게시코스의 현재 출처와 receipt 읽기','본인게시코스를편집할때이GET. 일반코스404,권리철회403/409는일반코스재게시로우회하지않습니다.','HistoryRemixSource','개인출처를publicDrivePackJSON에추가하지않고별도개인응답으로보존합니다.')
