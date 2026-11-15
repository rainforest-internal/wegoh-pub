"""Hand-authored operation metadata helpers; no handler-name documentation fallback."""
from api_doc_models import ref,obj,s,n,b,arr,IDENT,ACCOUNT,REV,TIME,CHECK,nullable
def response(schema,description):return {'description':description,'content':{'application/json':{'schema':schema}}}
def status(value):return obj({'status':s(value)},'실제 handler의 처리 상태.')
def entry(tag,summary,prerequisites,sequence,effects,retry,responses,errors,example=None,notes=None):
    return dict(tag=tag,summary=summary,prerequisites=prerequisites,sequence=sequence,effects=effects,retry=retry,
        responses=responses,errors=errors,example=example,notes=notes or '')
def ok(schema,description='아래 필드는 실제 handler가 반환하는 정본입니다.'):return {'200':response(schema,description)}
def created(schema,description):return {'201':response(schema,description)}
def report():return {'202':response(obj({'reportId':IDENT,'state':s('quarantined')},'신고된 현재 checksum을 즉시 재격리한 결과.'),'신고가 접수되고 해당 공유 콘텐츠가 검토대기로 전환됩니다. 판정 완료가 아닙니다.')}
def revresult():return ref('RevisionResult')
def permission_result():return obj({'status':s('shared 또는 revoked.'),'permissionRevision':REV},'다음 공유 수정에 사용할 부모 permissionRevision.')
BROWSER='공개 브라우저 origin의 Access 로그인 후 POST /v1/auth/session으로 개인 세션을 시작합니다. 변경 요청은 같은 Origin·현재 X-WegoH-CSRF가 필요합니다. Swagger는 현재 세션값을 메모리에서 붙입니다.'
READ='공개 브라우저 origin의 Access와 유효한 개인 세션이 필요합니다.'
ADMIN='현재 admin 계정의 개인 세션이 필요합니다. 변경은 Origin/CSRF도 검증합니다. loopback 운영 key 경로는 운영자 전용이며 웹·APK·문서 예제에 key를 넣지 않습니다.'
NATIVE='별도 native origin의 TLS1.3 및 기기별 개인 mTLS 인증서가 필요합니다. pairing·token교환·refresh와 모든기기조회는 같은 인증서에 결합됩니다. Cloudflare는검증됨·미철회인증서만통과시키고 Managed Transform의4필드를보내며클라이언트가그헤더를직접설정하지않습니다. 실제origin활성화는운영검증후진행하고기기token/개인키를URL·공용서비스key·APK에넣지않습니다.'
ERROR_TEXT={
 '408':'REQUEST_TIMEOUT: 요청 본문을 5초 안에 다 받지 못했습니다. 저장 성공으로 표시하지 말고 정본을 다시 조회한 뒤 사용자가 다시 보냅니다.',
 '410':'GRANT_EXPIRED: 차량 앱의 개인 연결(grant) 원 기한이 지났습니다. 같은 token으로 반복하지 말고 본인 폰에서 명시 재연결합니다.',
 '400':'본문 JSON·필드 조합·값을 handler가 거절했습니다. operation의 필수 키/상한을 고치세요. 같은 요청을 반복하지 마세요.',
 '401':'개인 세션 또는 기기 token이 없거나 만료·철회되었거나 native mTLS 인증서가 누락·불일치합니다. 브라우저는 Access와 개인 세션을 다시 확인하고 native는 본인 refresh/재연결 흐름을 사용합니다.',
 '403':'현재 역할/Origin/CSRF/명시 동의가 부족하거나 팀 권한이 철회되었습니다. 사용자 동의를 추정해 재시도하지 마세요.',
 '404':'현재 계정에서 볼 수 없는 리소스, 비활성 기능/호스트, 만료/철회/다른 소유자입니다. 존재 여부를 추정하거나 ID를 순회하지 마세요.',
 '409':'현재 revision·checksum·상태 또는 용량이 바뀌었습니다. 이 operation 설명의 재조회/정리 절차를 따르세요.',
 '413':'operation별 본문·점·파일 크기 상한을 넘었습니다. 원본을 조용히 잘라 보내지 말고 사용자에게 범위를 선택하게 하세요.',
 '422':'FastAPI가 경로 정수 또는 선언한 헤더 형식을 검증하지 못했습니다. detail의 loc를 확인하세요.',
 '429':'현재 계정 또는 연결 한도를 넘었습니다. Retry-After가 있으면 따르고 없으면 사용자 조작을 중단하고 정본 상태를 확인하세요.',
 '502':'외부 서비스 응답을 읽지 못했습니다. 연결을 확인하고 이후 다시 시도하세요.',
 '503':'DB·암호화 저장소·이미지 격리 처리 등 서비스가 사용 불가합니다. 성공으로 표시하지 말고 이후 조회로 저장 여부를 확인하세요.'}
