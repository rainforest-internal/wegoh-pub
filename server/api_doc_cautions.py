"""Explicit private observation/share contracts; content review is not road truth."""
from api_doc_shared import entry,response,obj,s,n,b,arr,ref,nullable,TIME,READ,BROWSER
from api_doc_models import IDENT,ACCOUNT

def strict(fields,description,required=None):
    return dict(obj(fields,description,required=required),additionalProperties=False)

REV=n('해당 관측 또는 별도 공유 설정의 현재 revision. 수정은 직전 정본을 사용하고 철회 DELETE는 revision 없이 가능합니다.',minimum=1,maximum=2147483647)
KIND=s('급제동을 포함해 사용자가 직접 관측했다고 기록하는 경험 종류. SDK 감지나 현재 도로 상태의 공식 판정이 아닙니다.',enum=['road-surface','construction','visibility','harsh-braking','other'])
PLACE=strict({'id':s('선택 장소의 공급자 ID 또는 본인 저장 방문의 공개 장소명/좌표만으로 만든 독립 장소 ID. 원기록/방문 ID나 그 해시를 쓰지 않습니다.',maxLength=240,minLength=1),'provider':s('명시 선택한 장소의 공급자 식별자. GPS·차량 SDK 검증을 뜻하지 않습니다.',maxLength=40,minLength=1),
    'name':s('사용자가 확인한 공개 장소 이름.',maxLength=80,minLength=1),'address':s('선택 장소의 주소. 없으면 빈 문자열입니다.',maxLength=200),
    'latitude':dict(type='number',minimum=-90,maximum=90,description='선택 장소 객체의 위도. 자동 현재 위치 수집을 하지 않습니다.'),
    'longitude':dict(type='number',minimum=-180,maximum=180,description='선택 장소 객체의 경도. 주행 경로 원본이 아닙니다.')},'명시 확인한 공개 장소 metadata. 소비자에게 좌표 직접 입력을 요구하지 않습니다.')
SOURCE={'oneOf':[
    strict({'kind':dict(type='string',const='selected-place',description='기존 지도/장소 선택기로 명시 선택합니다.'),'place':PLACE},'자동 GPS 전송을 하지 않는 선택 장소.'),
    strict({'kind':dict(type='string',const='own-history-visit',description='본인 소유 기록의 실제 저장 방문을 참조합니다.'),
            'historyId':dict(IDENT,description='본인 소유 기록 ID. 친구 기록 열람 권한으로 대체할 수 없습니다.'),
            'visitId':dict(IDENT,description='그 기록에 실제 존재하는 저장 방문 ID.'),'revision':REV},
           '서버가 본인 현재 기록 revision과 방문을 확인하고 장소만 독립 복사합니다. 사진·후기·평점·경로를 복사하지 않습니다.')],
    'description':'선택 장소 또는 실제 본인 저장 방문 중 하나를 명시합니다. 원래 기록을 자동 수정하거나 친구의 원자료를 재사용하지 않습니다.'}
CONFIRM=dict(type='boolean',const=True,description='사용자가 이번 저장에서 직접 확인한 별도 항목입니다. 유효 문서 예제 true를 자동 동의 또는 UI 기본 선택으로 실행하지 않습니다.')
CREATE_FIELDS={'eventId':dict(IDENT,description='불확실한 동일 저장의 확인에 유지할 클라이언트32hex ID. 다른 내용으로 자동 재사용하지 않습니다.'),
    'kind':KIND,'observedAt':dict(TIME,description='사용자가 명시 입력한 시간대 있는 관측 시각. 서버가 현재 시각을 대신 채우지 않으며 미래5분 초과는 거절합니다.'),
    'placeSource':SOURCE,'publicPlaceConfirmed':dict(CONFIRM,description='선택한 장소가 공유 가능한 공개 장소임을 이번에 확인합니다.'),
    'storageConsent':dict(CONFIRM,description='이번 관측 장소·시각·출처의 개인 암호화 저장을 별도로 허용합니다. 친구 공유가 아닙니다.'),
    'rightsConfirmed':dict(CONFIRM,description='이 장소 metadata를 기록할 본인 권리를 확인합니다. 사진·후기 재사용 권리는 포함하지 않습니다.')}
BASE='/v1/social/cautions'
BODY={
    ('post',BASE):strict(CREATE_FIELDS,'최초 개인 저장이며 기본 private입니다. 이 확인만으로 친구·방·전체 사용자에게 공개하지 않습니다.'),
    ('put',BASE+'/{item}'):strict({**{k:v for k,v in CREATE_FIELDS.items()if k!='eventId'},'revision':REV},'본인 관측을 명시 수정합니다. 기존 공유는 종료되며 내용 검토와 별도 공유를 다시 확인합니다.'),
    ('put',BASE+'/{item}/shares/{target}'):strict({'revision':REV,'permissionRevision':REV,
        'consent':b('이 관측을 이 친구 한 명에게 공유하는 별도 목적. false는 유효 형식의 오래된 revision이어도 철회합니다.'),
        'expiresInHours':n('공유 기간1~24시간. 공식 도로 정보의 유효기간이나 원관측의 보존기간이 아닙니다.',minimum=1,maximum=24),
        'rightsConfirmed':b('관측 장소 metadata를 이 친구에게 공유할 권리를 명시 확인합니다. true 공유에는 true가 필요합니다.')},'현재 친구·현재 승인 projection·개별 목적의 교집합. 철회만 할 때는 DELETE를 사용하면 revision/기간이 필요 없습니다.'),
    ('patch',BASE+'/{item}/review-request'):strict({'revision':REV,'consent':b('장소·종류·관측 시각 projection을 운영자 내용 검토에 제출하는 별도 목적입니다. false는 오래된 revision이어도 철회합니다.')},'내용 검토의 승인은 도로의 진위·현재 위험·SDK 측정을 인증하지 않습니다.'),
    ('post',BASE+'/{item}/reports'):strict({'reason':s('현재 접근 가능한 관측의 신고 사유.',enum=['harmful','privacy','rights','other'])},'현재 projection을 재격리하며 도로의 진위나 안전 점수를 자동 생성하지 않습니다.')}
MODELS={
    'CautionReviewProjection':strict({'kind':KIND,'observedAt':dict(TIME,description='사용자가 보고한 명시 관측 시각. 검토자의 현장 확인 시각이 아닙니다.'),'place':PLACE},'별도 제출한 관측 종류·시각·공개 장소만 검토합니다. 원기록 ID·사진·후기·경로는 제외하며 도로 진위를 인증하지 않습니다.'),
    'Caution':obj({'id':IDENT,'own':b('현재 조회자가 이 관측의 소유자인지 여부.'),'revision':REV,
        'permissionRevision':nullable(dict(REV,description='소유자에게만 보이는 별도 공유 설정 revision. 수신자는 null입니다.')),
        'kind':KIND,'place':PLACE,'observedAt':dict(TIME,description='작성자가 명시 보고한 관측 시각. 서버 확인 시각이나 현재 도로 상태의 보장이 아닙니다.'),
        'source':strict({'kind':dict(type='string',const='user-observed',description='사용자 본인 관측이라는 출처 표시.'),
            'physicalMeasurementVerified':dict(type='boolean',const=False,description='물리 GPS·차량 SDK로 관측을 인증하지 않았습니다.')},'서버가 정하는 출처 구분.'),
        'ownerId':ACCOUNT,'ownerName':nullable(s('현재 허용된 작성자 표시 이름.')),
        'shareExpiresAt':nullable(dict(TIME,description='수신자에게 허용된 공유 종료 시각. 소유자에게는 null이며 관측 자체를 삭제하지 않습니다.')),
        'review':ref('Review'),'serverNow':dict(TIME,description='이 응답의 서버 시각. 현장 확인 시각이 아닙니다.'),
        'currentRoadConditionVerified':dict(type='boolean',const=False,description='현재 도로 상태를 검증하거나 안전을 보장하지 않습니다.'),'placeSource':SOURCE},
        '본인 또는 개별 허용 친구만 읽는 관측. placeSource는 소유자 전용이며 수신자에게 원기록·방문 ID를 공개하지 않습니다.',
        required=['id','own','revision','permissionRevision','kind','place','observedAt','source','ownerId','ownerName','shareExpiresAt','review','serverNow','currentRoadConditionVerified']),
    'CautionList':obj({'items':arr(ref('Caution'),'현재 허용된 본인/친구 관측. 권한 필터 때문에 빈 page에도 nextCursor가 있을 수 있습니다.'),
        'nextCursor':nullable(s('다음 페이지의 불투명 cursor. 해석·수정·시각 보완을 하지 않습니다.')),'serverNow':TIME},'최대50개 관측 목록. 공개 교통 위험 feed나 자동 주변 위험 탐지가 아닙니다.'),
    'CautionCreated':obj({'id':IDENT,'revision':REV,'permissionRevision':REV,'visibility':dict(type='string',const='private',description='최초 저장 또는 수정 뒤 기본 비공개입니다.')},'개인 저장 정본. 공유·현장 검증 성공을 뜻하지 않습니다.'),
    'CautionDuplicate':obj({'id':IDENT,'revision':REV,'permissionRevision':REV,'duplicate':dict(type='boolean',const=True,description='동일 owner/eventId/정규화 본문의 기존 결과입니다.')},'불확실 저장의 기존 결과200. 관측을 중복 생성하지 않습니다.'),
    'CautionSharing':obj({'revision':REV,'permissionRevision':REV,'friends':arr(ref('Person'),'현재 사용 가능하며 차단되지 않은 친구.'),
        'grants':arr(obj({'accountId':ACCOUNT,'consent':b('저장된 개별 공유 목적.'),'active':b('현재 친구·기록 revision·검토 세대·기간이 모두 유효한지 여부.'),'expiresAt':TIME},'개별 목적의 정본. consent만으로 열람 가능하다고 판단하지 않습니다.'),'현재 저장된 공유 설정.'),'serverNow':TIME},'관측 소유자만 관리하는 개별 공유 정본.'),
    'CautionGrantSaved':obj({'accountId':ACCOUNT,'consent':b('저장한 공유 목적.'),'permissionRevision':REV,
        'expiresAt':TIME,'serverNow':TIME},'true 공유 저장에는 만료/서버 시각을 추가하며 철회는 앞3필드만 반환합니다.',required=['accountId','consent','permissionRevision']),
    'CautionReviewRequested':obj({'review':ref('Review'),'permissionRevision':REV},'검토 제출/철회 정본. 친구 공유는 별도입니다.'),
    'CautionDeleted':strict({'status':dict(type='string',const='deleted',description='이 관측과 공유를 삭제했습니다.')},'원기록과 방문은 보존합니다.'),
    'CautionReported':strict({'reportId':IDENT,'state':dict(type='string',const='quarantined',description='현재 projection을 재격리했습니다.')},'신고 접수202. 도로의 진위 판정이 아닙니다.')}
OPS={}
def operation(method,path,title,sequence,effects,model,errors,code='200',example=None):
    value=entry('18 주의 구간 경험',title,(READ if method=='get'else BROWSER)+' Native는 미공개이며 운영 Bearer가 개인 권한을 대신하지 않습니다.',sequence,effects,
        '409는 현재 정본을 다시 읽고 사용자가 재선택합니다. 저장 응답이 불확실하면 eventId를 유지해 목록에서 확인하고 자동 새 저장·본문 변경 재전송을 하지 않습니다.429는 Retry-After를 따릅니다.',
        {code:response(ref(model),title+'의 현재 결과. 도로의 안전·진위를 인증하지 않습니다.')},errors,example=example,
        notes='공유 만료는 열람만 종료하고 원관측·원기록을 삭제하지 않습니다. 사진·후기·경로·친구 기록의 권한을 전용하지 않습니다.')
    value['errorDescriptions']={key:text for key,text in {'408':'본문 수신5초 초과입니다. 성공으로 표시하지 말고 정본을 확인합니다.','413':'본문8KiB 초과입니다. 원정보를 조용히 잘라내지 않습니다.'}.items()if key in errors}
    OPS[(method,path)]=value
EXAMPLE=dict(eventId='0'*32,kind='road-surface',observedAt='2026-01-02T02:00:00Z',placeSource=dict(kind='selected-place',place=dict(id='synthetic-doc-place',provider='map',name='문서용 가상 공개 장소',address='',latitude=0,longitude=0)),publicPlaceConfirmed=True,storageConsent=True,rightsConfirmed=True)
operation('post',BASE,'직접 관측한 공개 장소를 비공개 저장','장소·종류·시간대 있는 관측 시각을 직접 선택→공개 장소/저장/권리 확인→새 eventId로 저장.','원기록을 수정하지 않는 암호화 독립 snapshot입니다. 동일 event/body는 기존200, 다른 본문은409, 삭제된 event는 자동 복원하지 않습니다.','CautionCreated',['400','401','403','404','408','409','413','429','503'],'201',EXAMPLE)
OPS[('post',BASE)]['responses']['200']=response(ref('CautionDuplicate'),'동일 owner/eventId/body의 현재 기존 결과입니다.')
operation('get',BASE,'본인과 개별 허용 친구의 관측 목록 읽기','첫 GET→nextCursor 그대로 다음 GET. eventId 단독 지정은 본인의 불확실 저장만 확인합니다.','현재 권한으로 최대50개를 읽습니다. cursor와 eventId는 함께 사용하지 않습니다. 공개 위험 feed를 생성하지 않습니다.','CautionList',['400','401','403','503'])
operation('get',BASE+'/{item}','현재 허용된 관측 상세 읽기','목록의 id→현재 친구/개별 목적/검토/기간을 다시 확인합니다.','수신자에게는 승인 projection만 반환하고 원기록 ID·사진·후기·경로를 포함하지 않습니다.','Caution',['401','403','404','503'])
operation('put',BASE+'/{item}','본인 관측을 명시 수정','본인 상세 revision→장소/종류/시각과 확인→저장.','기존 공유를 종료합니다. 변경 projection은 검토/개별 공유를 다시 확인하며 원기록·방문은 수정하지 않습니다.','CautionCreated',['400','401','403','404','408','409','413','429','503'])
operation('delete',BASE+'/{item}','본인 관측만 삭제','사용자 확인→이 DELETE.','관측/공유를 지우고 최소 암호화 event 표식으로 불확실 재전송의 복원을 막습니다. 원기록/방문은 지우지 않습니다.','CautionDeleted',['401','403','404','503'])
operation('get',BASE+'/{item}/shares','본인 관측의 공유 상대·기간 읽기','본인 상세→현재 친구와 개별 grant 정본→새 선택.','저장된 consent와 실효 active를 구분하고 타인에게 다른 공유 대상을 공개하지 않습니다.','CautionSharing',['401','403','404','503'])
operation('put',BASE+'/{item}/shares/{target}','현재 친구 한 명에게 별도 목적으로 공유','현재 revision/permissionRevision→현재 승인 projection→친구와1~24시간을 명시합니다.','true는 현재 검토 세대와 기록 revision에 결합합니다. false는 유효 형식의 오래된 revision이어도 철회하며 다른 공유 목적을 변경하지 않습니다.','CautionGrantSaved',['400','401','403','404','408','409','413','429','503'])
operation('delete',BASE+'/{item}/shares/{target}','대상 계정의 관측 공유 철회','소유자→공유 대상 accountId→DELETE.','현재 친구가 아니거나 revision이 오래돼도 철회합니다. 원관측은 소유자에게 남습니다.','CautionGrantSaved',['400','401','403','404','503'])
operation('patch',BASE+'/{item}/review-request','장소·종류·시각의 내용 검토 요청 또는 철회','현재 revision→제출 projection 확인→별도 consent. false는 오래된 revision이어도 철회합니다.','내용 검토 승인으로 현재 도로·SDK 측정을 인증하지 않습니다. 재검토/재승인으로 옛 공유를 복구하지 않습니다.','CautionReviewRequested',['400','401','403','404','408','409','413','429','503'])
operation('post',BASE+'/{item}/reports','현재 접근 가능한 관측 신고','현재 상세 확인→harmful/privacy/rights/other 명시.','해당 projection을 재격리하고 도로의 진위·위험 점수를 자동 생성하지 않습니다.','CautionReported',['400','401','403','404','408','413','429','503'],'202')

# The edit example keeps the same exact selected-place object as creation.
OPS[('put',BASE+'/{item}')]['example']={**{key:value for key,value in EXAMPLE.items()if key!='eventId'},'revision':1}
