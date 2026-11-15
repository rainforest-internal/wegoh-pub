"""Room live-audio controls, described independently from transport implementation."""
from api_doc_shared import *
OPS={}
def add(method,path,*args,**kw):OPS[(method,path)]=entry(*args,**kw)
TAG='13 방 음성'
MEMBER=READ+' 현재 활성 방 멤버여야 하며 차단·탈퇴·만료가 반영됩니다. native 기기에는 개방하지 않습니다.'
add('get','/v1/social/rooms/{room}/voice/filters',TAG,'내 방 음소거 목록 조회',MEMBER,
 '방 상세에서 room id를 확인하고 입장 전 본인 수신 필터를 읽습니다. 송수신 WSS에는 별도 voice 동의와 roomVoice=true가 필요합니다.',
 '본인에게만 적용되는 mutedSpeakerIds를 반환합니다. 마이크·송신 floor를 시작하지 않습니다.',
 '안전한 조회이며 새 연결과 필터 수정 뒤 다시 읽을 수 있습니다.',ok(obj({'mutedSpeakerIds':arr(ACCOUNT,'내가 이 방에서 음소거한 계정 ID, 정렬 순서.')},'본인 방 수신 필터.')),['401','403','404','409','503'])
add('put','/v1/social/rooms/{room}/voice/filters/{speaker}',TAG,'내 수신자 음소거 설정',BROWSER+' 본인과 대상 speaker가 현재 방에 접근할 수 있어야 합니다. 본인 ID는 대상이 될 수 없습니다.',
 '현재 members의 speaker ID와 muted=true 또는 false를 보냅니다. 마이크/공개 공유 동의를 대신하지 않습니다.',
 '암호화된 본인 수신 필터를 교체합니다. 활성 연결의 epoch를 바꾸고 해당 발화자의 소유 미전송 PCM만 버리며 ready/floor 제어 메시지는 보존합니다. 이미 transport에 넘긴 소리는 회수할 수 없습니다.',
 '같은 boolean 재전송은 같은 설정을 만듭니다. 응답 유실은 GET filters로 확인합니다.',ok(obj({'speakerId':ACCOUNT,'muted':b('현재 저장한 본인 음소거 설정.')},'본인 수신 필터 변경 결과.')),['400','401','403','404','409','413','503'],example={'muted':True})
add('post','/v1/social/rooms/{room}/voice/reports',TAG,'실제 수신한 음성 lease 신고',BROWSER+' 현재 방 멤버이며 본인에게 서버가 실제 전달한 다른 발화자의 lease만 신고할 수 있습니다.',
 'floor-started의 speakerId/leaseId를 사용합니다. 적어도 한 frame을 전달받아야 하고 종료 후60초 이내의 최근 metadata가 필요합니다. reason은 harmful/privacy/rights/other 중 하나입니다.',
 '원음·전사문 없이 사유·발화자·신고자·lease metadata만 기존 키로 암호화합니다. 해당 사용자의 현재 floor를 끝내고 미해결 신고가 남은 동안 그 방에서 새 시작을 막습니다. 의미 기반 음성 분류나 과거 내용 검수 완료가 아닙니다.',
 '새 POST마다 별도 신고이며 계정당20회/분 제한입니다. 응답 유실을 중복 제출로 덮지 마세요. 현재 신고 가능한 metadata는 방당 최근20개로 제한됩니다.',{'202':response(obj({'id':IDENT,'status':s('received.'),'audioRetained':{'const':False,'description':'원음·전사문을 보관하지 않습니다.'}},'접수 상태. 내용 판정 완료가 아닙니다.'),'신고 metadata를 저장하고 해당 발화자의 새 시작을 정지합니다.')},['400','401','403','404','409','413','429','503'],example={'speakerId':'team-'+'0'*40,'leaseId':'0'*32,'reason':'privacy'})
add('get','/v1/moderation/voice-reports',TAG,'미해결 음성 신고 metadata 조회',READ+' 현재 admin 개인 세션만 허용됩니다. 공통 운영 key/native 기기 경로는 제공하지 않습니다.',
 '운영자가 신고를 선택해 사유와 최소 metadata를 확인합니다. 현재 createdAt/id 순서의 미해결 최대100건이며 cursor는 없습니다.',
 'id/roomId/reporterId/speakerId/reason/createdAt/audioRetained=false를 반환합니다. 원음 재생·전사·개인 기록/GPS 조회는 제공하지 않습니다.',
 '조회는 안전하게 반복할 수 있으나 목록 열람만으로 신고를 해결하지 않습니다.',ok(obj({'items':arr(obj({'id':IDENT,'roomId':IDENT,'reporterId':ACCOUNT,'speakerId':ACCOUNT,'reason':s('harmful/privacy/rights/other 중 신고자가 선택한 사유.'),'createdAt':dict(TIME,description='신고 metadata가 서버에 저장된 시각.'),'audioRetained':{'const':False,'description':'음성 원본/전사 미보관.'}},'미해결 신고 한 건.'),'오래된 순서, 최대100건.')},'개인 admin용 신고 목록.')),['401','403','503'])
add('post','/v1/moderation/voice-reports/{identifier}/resolve',TAG,'음성 신고의 시작 제한 처리',BROWSER+' 현재 admin 개인 세션이 필요합니다. loopback 공통 key로 대체하지 않습니다.',
 '운영 목록의 정확한 신고 id를 사용해 decision=restore 또는 retain을 보냅니다. 보관된 음성이 없으므로 내용 재생에 근거한 판정을 했다고 표시하지 마세요.',
 'restore는 해당 신고 resolved_at을 설정하며 다른 미해결 신고가 없을 때만 새 발화를 허용합니다. retain은 미해결 상태로 유지(이미 해결한 건은 재개방)합니다. 어느 경우도 자동 송신을 시작하지 않습니다.',
 '응답 유실은 미해결 목록으로 확인합니다. 재전송은 같은 상태를 설정하지만 restore 시각은 새로 기록됩니다.',ok(obj({'status':s('restore 또는 retain, 실제 저장한 결정.')},'신고 처리 결과.')),['400','401','403','404','413','503'],example={'decision':'retain'})

ROOM_LINKED='여행에 연결된 내부 방을 이 방 경로로 부르면 TRIP_CLIENT_UPDATE_REQUIRED입니다. 여행은 /v1/social/trips/{room}/voice/ 경로를 사용합니다.'
for (method,path),operation in OPS.items():
 if path.startswith('/v1/social/rooms/{room}/voice/'):operation['errorDescriptions']={'409':ROOM_LINKED}

import copy
TRIP_CONTEXT='TRIP_STATE_CONFLICT(진행 중 active가 아닌 계획·종료·취소 여행), TRIP_CONTEXT_NOT_READY, TRIP_MEMBERSHIP_INCONSISTENT입니다. 여행 상세를 다시 읽습니다.'
for (method,path),operation in list(OPS.items()):
 if path.startswith('/v1/social/rooms/{room}/voice/'):
  trip_path=path.replace('/rooms/','/trips/')
  value=copy.deepcopy(operation)
  value['summary']=value['summary'].replace('내 방','내 여행').replace('음성 lease','여행 음성')
  value['prerequisites']=value['prerequisites'].replace('현재 활성 방 멤버여야 하며','진행 중(active) 여행의 수락 멤버여야 하며').replace('현재 방 멤버이며','진행 중(active) 여행의 수락 멤버이며').replace('현재 방에 접근할 수 있어야','현재 여행 참여자여야')+' 경로의 {room} 자리에는 여행 ID를 보냅니다. 내부 방 ID는 받지 않습니다.'
  value['effects']+=' 차단 당사자 두 명의 여행 음성만 중지하며 나머지 참여자는 유지합니다. 탈퇴·동의 철회·종료 시 미전송 프레임을 폐기합니다.'
  value['errorDescriptions']={'409':TRIP_CONTEXT}
  OPS[(method,trip_path)]=value

BODY={
 ('put','/v1/social/trips/{room}/voice/filters/{speaker}'):obj({'muted':b('이 수신자에게만 적용되는 음소거.')},'현재 여행의 발화자 필터.'),
 ('post','/v1/social/trips/{room}/voice/reports'):obj({'speakerId':ACCOUNT,'leaseId':IDENT,'reason':{'type':'string','enum':['harmful','privacy','rights','other']}},'본인이 실제 수신한 여행 음성 lease의 최소 신고 metadata.')}

CLIP = obj({'id': IDENT, 'speakerId': ACCOUNT, 'sequence': n('프로세스 내 게시 순서.', minimum=1),
    'durationMs': n('PCM 길이에서 계산한 녹음 길이.', minimum=20, maximum=15000)}, '완성된 여행 음성 메시지의 원음 없는 메타데이터.')
CLIP_BODY = obj({'clientMessageId': IDENT, 'pcmBase64': dict(s('PCM16LE mono16kHz 전체 음성의 base64.'), maxLength=640000)},
    '손을 뗀 뒤 전송하는 최대15초 음성. 동일clientMessageId 재시도는 같은 본문에 한정합니다.')
for method, suffix, title, schema in (
    ('get', '', '새 여행 음성 메시지 목록', obj({'cursor': s('프로세스와 마지막 게시 번호.', pattern='^[a-f0-9]{32}:(0|[1-9][0-9]{0,15})$'),
        'clips': arr(CLIP, '현재 수신할 수 있는 새 메시지, 게시 순서.')}, '최초/재시작 조회는 현재cursor와 빈 목록입니다.')),
    ('post', '', '완성된 여행 음성 보내기', CLIP),
    ('get', '/{identifier}', '여행 음성 전체 내려받기', obj(dict(CLIP['properties'], pcmBase64=CLIP_BODY['properties']['pcmBase64']), '재생 전 현재 송수신 자격을 다시 확인한 전체 음성.'))):
    path = '/v1/social/trips/{trip}/voice-clips' + suffix
    OPS[(method, path)] = entry(TAG, title,
        NATIVE + ' 진행 중인 여행의 수락 멤버이며 현재 워키토키 참여와 rooms:read가 필요합니다. 송신에는 rooms:interact도 필요합니다.',
        'GET 목록은 최초cursor를 받은 뒤 새cursor로 폴링하고 각id를 내려받아 순서대로 재생합니다. POST는 녹음을 마친 뒤 전체PCM을 한 번 전송합니다.',
        '원음은90초·전체32MiB·최대64건·여행20건의 프로세스RAM에서만 일시 보관하며 파일·DB에 저장하지 않습니다. 현재계정·grant·참여가입세대·차단·음소거·신고 상태를 다시 확인합니다. 이미 내려받은 음성은 회수할 수 없습니다.',
        '응답 유실은90초 안에 같은clientMessageId와 동일PCM으로 재시도합니다. 원음 축출 후에도 최대2048건의 원음 없는 영수증을 유지합니다. 가득 차면 새ID를429로 거절하며 기존 영수증을 축출하지 않습니다. 본문 변경은409입니다. 만료·재시작·용량정리된 음성은404이며 과거목록 재생을 보장하지 않습니다.',
        ok(schema), ['400','401','403','404','408','409','413','429','503'] if method == 'post' else ['400','401','403','404','409','429','503'],
        notes='구형실시간WSS와 혼합재생은 지원하지 않습니다. 앱·차량을 함께 전환해야 합니다. JSON본문최대700000바이트; 원음·Bearer를 로그에 쓰지 않습니다.')
    OPS[(method, path)]['errorDescriptions'] = {
        '400': 'GET 목록은 cursor 하나만, 내려받기는 query 없이 보냅니다. POST는 Content-Type application/json, 중복 없는 정확한 필드, 640바이트 배수인 20ms~15초 PCM이어야 합니다. Native POST는 functionalRevision도 필요합니다.',
        '403': 'PARTICIPATION_REQUIRED(여행 voice 참여 꺼짐), DIRECTION_REQUIRED(Native rooms:read 또는 송신 rooms:interact 없음), SPEAKER_SUSPENDED(미해결 신고로 송신 정지), TRIP_VOICE_UNAVAILABLE입니다. 사용자 설정 없이 재시도하지 않습니다.',
        '404': '음성 기능 꺼짐, Native 호스트가 아님, 차단 관계, 만료·재시작·용량 정리된 음성(VOICE_CLIP_UNAVAILABLE)입니다.',
        '409': ('VOICE_CLIP_MESSAGE_CONFLICT(같은 clientMessageId에 다른 PCM), FUNCTIONAL_REVISION_CHANGED(Native), ' if method == 'post' else '') + TRIP_CONTEXT,
        **({'408': '음성 JSON 본문 수신5초를 초과했습니다. 같은clientMessageId와 동일PCM만 재시도합니다.',
            '413': '본문은 최대700000바이트입니다.',
            '429': '계정당 분당60회 업로드 한도 또는 원음 없는 영수증 2048건이 가득 찬 VOICE_CLIP_CAPACITY입니다. 기존 영수증은 축출하지 않습니다.'} if method == 'post' else {})}
BODY[('post', '/v1/social/trips/{trip}/voice-clips')] = CLIP_BODY

OPS[('get', '/v1/social/trips/{room}/voice/filters')]['notes'] += ' Native는 rooms:read와 이 여행의 voice 참여로 같은 필터를 조회할 수 있습니다. 필터 변경과 신고는 웹과 iPhone에서만 합니다.'
OPS[('post', '/v1/social/trips/{room}/voice/reports')]['sequence'] += ' 완성 음성 모드에서는 실제 전체 다운로드를 마친clip.id를 leaseId로 전달합니다. 현재 가입 세대의 다운로드 영수증이 있어야 합니다.'
OPS[('get', '/v1/social/trips/{room}/voice/filters')]['prerequisites'] = OPS[('get', '/v1/social/trips/{room}/voice/filters')]['prerequisites'].replace('native 기기에는 개방하지 않습니다.', 'Native는 현재 rooms:read와 이 여행의 voice 참여가 필요합니다.')
OPS[('get', '/v1/social/trips/{room}/voice/filters')]['errors'] = ['400','401','403','404','409','503']
OPS[('get', '/v1/social/trips/{room}/voice/filters')]['errorDescriptions']['400'] = 'Native 조회에 query를 붙이면 거절합니다. query 없이 다시 요청합니다.'
