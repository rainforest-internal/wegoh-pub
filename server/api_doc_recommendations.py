"""Personal explicit-rules recommendation contracts, not a trained-model claim."""
from copy import deepcopy
from api_doc_shared import entry,response,obj,s,n,b,arr,ref,nullable,TIME,READ,BROWSER
from api_doc_discovery import BODY as DISCOVERY_BODY,MODELS as DISCOVERY_MODELS,FACILITIES,SELECTED
from api_doc_models import CHECK

strict=lambda fields,description:dict(obj(fields,description),additionalProperties=False)
REV=n('이 개인 추천 설정의 현재 revision.',minimum=0,maximum=2147483647)
REV['description']='이 개인 추천 설정의 현재 revision. 미저장0이며 저장·철회·피드백마다 증가합니다.'
PREFS=strict({'coursePriority':s('사용자가 명시한 코스 우선순위. nearby는 첫 장소까지 직선거리, fewStops/manyStops는 실제 장소 수이며 운전시간·난이도 추정이 아닙니다.',enum=['nearby','fewStops','manyStops']),
 'facilities':dict(arr(s('공식 휴게소 시설명.',enum=['toilet','nursing','evCharger','gasStation','lpg']),'명시 선택한 시설의 AND 조건. 코스 자체의 시설을 추정하지 않고 휴게소 후보에만 적용합니다.'),maxItems=5,uniqueItems=True),
 'hideVisited':b('별도 useHistory=true일 때 본인 최근 기록100개에 같은 courseId가 있는 코스를 제외합니다. 미동의 상태에서 true이면 거절합니다.'),
 'maxDistanceKm':dict(type='number',description='선택 기준점에서 첫 코스 장소 또는 휴게소까지 직선거리 상한 km. 실제 도로거리·주행시간이 아닙니다.',minimum=1,maximum=150)},'추정하지 않는 사용자 명시 취향. 요청마다 임시 선택할 수 있습니다.')
PERMISSIONS=strict({'useHistory':b('본인 최근 여행기록100개의 courseId를 추천에 사용하도록 별도 허용합니다. 친구 기록·방문·사진·경로 공유 동의가 아닙니다. 기본 false.'),
 'useFeedback':b('추천의 좋아요/관심없음을 암호화 저장해 다음 규칙 순서·제외에 사용하도록 별도 허용합니다. 모델 학습이 아니며 기본 false. false 저장은 기존 피드백을 지웁니다.')},'추천 전용 개인 목적. 저장하기 전 checkbox 선택만으로 권한이 생기지 않습니다.')
ANCHOR=deepcopy(DISCOVERY_BODY['properties']['anchor'])
BODY={
 ('put','/v1/recommendations/settings'):strict({'revision':REV,'preferences':PREFS,'permissions':PERMISSIONS},'현재 정본 revision으로 명시 취향과 두 별도 목적을 저장합니다.'),
 ('post','/v1/recommendations/query'):strict({'settingsRevision':REV,'anchor':ANCHOR,'preferences':PREFS,
   'dismissed':dict(arr(s('course:코스ID 또는 rest:휴게소ID. 현재 화면에서만 제외할 후보 키.',maxLength=100),'이번 검색에서만 제외합니다. useFeedback=false에서도 서버에 저장하지 않습니다.'),maxItems=200)},'현재 개인 설정 revision과 명시 장소/일회 위치 동의를 사용한 읽기 계산입니다.'),
 ('post','/v1/recommendations/feedback'):strict({'revision':REV,'kind':s('course는 현재 게시 버전, rest는 고정 공식 휴게소입니다.',enum=['course','rest']),
   'id':s('직전 추천 응답의 실제 코스 또는 휴게소 id. 임의 사람·URL·설명은 받지 않습니다.'),
   'version':nullable(n('course이면 현재 가용 코스 버전1~2147483647. rest이면 반드시 null.',minimum=1,maximum=2147483647)),
   'response':s('like는 규칙 우선순위, notInterested는 다음 추천 제외입니다. 같은 후보의 이전 응답을 대체하며 무조건 누적 가산하지 않습니다.',enum=['like','notInterested'])},'저장된 useFeedback=true일 때만 본인 후보 피드백을 기록합니다.')}
ALGORITHM={'const':'explicit-rules-v1','description':'사용자 명시 선택·실제 거리/장소 수·동의된 피드백의 결정적 규칙. 학습 모델이 아닙니다.'}
AI={'const':False,'description':'이 버전은 모델 추론·학습을 사용하지 않습니다. AI 완료로 표시하지 마세요.'}
COURSE_REASONS=arr(s('nearbyStart=첫 장소 가까움, fewerPlaces/morePlaces=실제 장소 수, notInPermittedHistory=허용한100개 기록에없음, likedByYou=동의해저장한좋아요.',enum=['nearbyStart','fewerPlaces','morePlaces','notInPermittedHistory','likedByYou']),'현재 계산에 실제 사용된 추천 근거 코드입니다.')
MODELS={
 'RecommendationPreferences':PREFS,'RecommendationPermissions':PERMISSIONS,
 'RecommendationSettings':obj({'revision':REV,'configured':b('사용자가 설정을 저장했으면 true. DELETE 뒤 false이며 revision은 재사용하지 않습니다.'),'preferences':PREFS,'permissions':PERMISSIONS,
   'feedbackCount':n('현재 암호화 저장된 본인 후보 피드백 수. 미동의/철회 뒤0.',minimum=0,maximum=200),'algorithm':ALGORITHM,'aiUsed':AI},'현재 개인 추천 정본. 위치·타인 기록·피드백 후보ID는 응답하지 않습니다.'),
 'RecommendedCourse':obj({'id':s('실제 게시 코스 ID.'),'version':n('이 조회의 최신 승인 버전.',minimum=1),'title':s('게시된 코스의 사용자 제목.'),'author':s('게시시 정본 작성자 이름.'),'description':s('게시 코스의 실제 설명.'),'checksum':CHECK,
   'placeCount':n('실제 코스 장소 수.',minimum=1,maximum=3),'straightLineMeters':n('기준점에서 코스 첫 장소까지 반올림한 직선거리 m. 코스 전체 길이·도로거리·ETA가 아닙니다.',minimum=0),
   'visitedBefore':nullable(b('useHistory=true일 때 본인 최근100기록의 courseId 포함 여부. 미동의이면 null이며 미방문으로 추정하지 않습니다.')),'reasons':COURSE_REASONS},'가용 코스 최대100개 중 명시 규칙으로 선정한 후보. 공개 상세 조회도 현재 공개 제한을 다시 확인합니다.'),
 'RecommendedRestStop':obj({'id':s('고정 공식 CSV 행의 안정 ID.'),'place':SELECTED,'facilities':FACILITIES,
   'road':obj({'routeName':s('공식 보고 노선명.'),'reportedDirection':nullable(s('원본 보고 방향. 없으면 null.')),'direction':nullable(s('정규화 up/down/both 또는 null. 차량 진행방향이 아닙니다.'))},'현재 차량의 경로·진입가능성을 추론하지 않는 source 라벨.'),
   'dataAsOf':s('이 행의 실제 시설 데이터 기준일. 조회/현장 확인일과 다릅니다.',format='date'),
   'straightLineMeters':n('보고 좌표 사이 대권 직선거리 m. 반대방향 고속도로 진입을 보장하지 않습니다.',minimum=0),
   **{key:{'type':'null','description':description}for key,description in {'routeDistanceMeters':'실제 도로 경로거리 미제공.','travelSeconds':'도로·교통시간 미제공.','currentOpen':'실시간 영업상태 미확인.','price':'주유·충전·음식 실시간 가격 미제공.','chargerAvailable':'현재 충전기 가용 여부 미확인.','coordinateVerifiedAt':'좌표의 별도 현장검증 시각 미제공.'}.items()},
   'reasons':arr(s('nearbyFacilities=가까운공식시설, requiredFacilities=명시시설AND충족, likedByYou=저장좋아요.',enum=['nearbyFacilities','requiredFacilities','likedByYou']),'실제 적용한 후보 근거.')},'공식215행 고정 source의 시설 후보. 음식점/쉼터 존재가 맛집/졸음쉼터 이름이나 안전정차 승인을 뜻하지 않습니다.'),
 'RecommendationResult':obj({'settingsRevision':REV,'courses':dict(arr(ref('RecommendedCourse'),'현재 규칙 코스 순서.'),maxItems=12),'restStops':dict(arr(ref('RecommendedRestStop'),'좋아요 우선, 그다음 직선거리·ID 순서.'),maxItems=12),
   'source':ref('DiscoverySource'),'preferences':PREFS,'anchor':deepcopy(DISCOVERY_MODELS['DiscoveryResult']['properties']['anchor']),
   'queriedAt':dict(TIME,description='이 규칙 계산의 서버 시각. 시설/좌표 현장갱신 시각이 아닙니다.'),'algorithm':ALGORITHM,'aiUsed':AI,
   'historyUsed':b('저장된 별도 본인 기록 사용 목적이 현재 true인지.'),'historyLimit':{'const':100,'description':'본인 기록 조회 상한. 전체 생애/타인 기록을 뜻하지 않습니다.'},
   'historyConsidered':n('이번 계산에서 실제 읽은 본인 최근 기록 수.',minimum=0,maximum=100),'feedbackUsed':b('저장된 별도 피드백 목적이 현재 true인지.'),'courseCatalogLimit':{'const':100,'description':'코스ID순 최신 가용 코스 최대100개. 전국 코스 최적화 보장이 아닙니다.'},
   'unsupported':obj({key:{'const':True,'description':description}for key,description in {'roadRouting':'도로 경로·국도 우선 SDK ACK 미연결.','routeTime':'실제 도로시간 미제공.','livePrice':'실시간 가격 미제공.','fuelHabitInference':'차량 연료습관 추론 없음.','namedFood':'대표음식/맛집 데이터 없음.','modelTraining':'이 버전 실제 모델 학습 없음; 전체 AI 취향 완료 조건은 후속.'}.items()},'true는 미지원이며 가상 값으로 채우지 않습니다.')},'현재 공개 제한·개인 동의와 명시 기준점의 결정적 추천. 조회 위치/결과를 계정 기록에 저장하지 않습니다.')}
OPS={}
def add(method,path,summary,sequence,schema,effects,example=None,errors=None):
 OPS[(method,path)]=entry('16 내 취향 추천',summary,(READ if method=='get' else BROWSER)+' 추천은 브라우저 개인 기능이며 Native 호스트 허용목록은 열지 않습니다.',sequence,effects,
  '409는 설정 GET을 새로 읽고 사용자가 다시 선택합니다. 변경 요청 응답 유실은 먼저 설정 정본을 확인하고 자동 동의·자동 재전송하지 마세요. 429는 Retry-After,408은 본문 수신5초,413은16KiB 상한입니다.',
  {'200':response(ref(schema),'이 계정의 현재 추천 정본. 모델 학습/실차/내비 실행 성공이 아닙니다.')},errors or ['400','401','403','404','408','409','413','429','503'],example=example,
  notes='실제 명시 취향 세로 흐름의 첫 단위입니다. 규칙만으로 전체 LIVE10 AI 취향 요구를 완료 처리하지 않습니다. 외부 모델/POI fetch, 연료·의학·가격·교통 추정이 없습니다.')
BASE='/v1/recommendations'
add('get',BASE+'/settings','본인 추천 설정과 별도 사용 목적 읽기','개인 로그인→이 GET→revision과 두 목적 기본false 확인. 실패한 GET을 동의된 기본값으로 대체하지 마세요.','RecommendationSettings','조회만 하며 설정/동의/피드백을 자동 생성하지 않습니다.',errors=['401','403','404','409','429','503'])
EXAMPLE_PREF={'coursePriority':'nearby','facilities':['toilet'],'hideVisited':False,'maxDistanceKm':50}
add('put',BASE+'/settings','명시 취향과 본인 기록·피드백 사용 목적 저장','GET→선호 선택→각 별도 목적 사용자가 확인→현재 revision으로 저장. hideVisited는 useHistory가 필요합니다.','RecommendationSettings','본인 암호화 설정만 갱신합니다. useFeedback=false는 저장 피드백을 지우며 useHistory=false는 원래 여행기록을 삭제하지 않습니다.',{'revision':0,'preferences':EXAMPLE_PREF,'permissions':{'useHistory':False,'useFeedback':False}})
add('delete',BASE+'/settings','추천 설정과 별도 사용 목적 철회','사용자가 추천 설정 삭제→목적둘다false·기본선호·피드백0의 새 revision 확인. 원래 코스/여행기록은 보존됩니다.','RecommendationSettings','기존 개인 설정/피드백 내용을 암호화 tombstone으로 대체합니다. revision을0으로 되돌리지 않아 늦은 이전 요청을 차단합니다.',errors=['401','403','404','429','503'])
add('post',BASE+'/query','선택 장소와 명시 취향으로 코스·휴게소 추천 계산','settings GET→지도/기록 장소 객체 선택 또는 현재 위치의 이번 서버 전송 명시동의→선호·현재 revision POST. 좌표 직접입력/묵시 GPS 전송을 요구하지 않습니다.','RecommendationResult','현재 가용 코스와 공식215행을 읽어 계산합니다. 별도 목적false이면 본인 기록/저장피드백을 읽지 않습니다. anchor·검색결과·dismissed는 DB/WSS·외부모델에 저장/전송하지 않습니다.',{'settingsRevision':0,'anchor':{'kind':'selected-place','place':{'id':'synthetic-doc-place','provider':'map','name':'문서용 가상 선택 장소','address':'','latitude':0,'longitude':0}},'preferences':EXAMPLE_PREF,'dismissed':[]})
add('post',BASE+'/feedback','본인 추천의 좋아요 또는 관심없음 저장','설정 useFeedback=true를 별도로 저장→현재 추천 후보 선택→현재 설정 revision과 id/version·응답을 POST. 미동의의 화면 제외는 로컬만 처리합니다.','RecommendationSettings','동일 후보의 피드백을 대체하며 최대200개입니다. 좋아요 우선/관심없음 제외라는 명시 규칙에만 사용하고 학습/AI라고 표시하지 않습니다.',{'revision':1,'kind':'rest','id':'응답에서 받은 실제 휴게소 ID','version':None,'response':'notInterested'})
for item in OPS.values():
 if '408' in item['errors']:item['errorDescriptions']={'408':'추천 요청 본문 수신이5초를 초과했습니다. 성공으로 표시하지 말고 설정 정본을 확인한 뒤 사용자가 다시 선택하세요.'}
OPS[('get',BASE+'/settings')]['errorDescriptions']={
 '409':'Native 조회 중 기기의 기능 목적 정본 revision이 바뀌었습니다(FUNCTIONAL_REVISION_CHANGED). 기능 목적을 다시 확인한 뒤 조회합니다. 브라우저 조회는 409를 내지 않습니다.',
 '429':'Native 호스트 전체 인증 요청 한도(분당600회)를 넘었습니다. Retry-After: 60 이후 다시 조회합니다. 브라우저 조회에는 별도 한도가 없습니다.'}
