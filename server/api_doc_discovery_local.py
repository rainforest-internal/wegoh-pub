"""Existing Browser local-road DTOs; no Native purpose or operating activation."""
from copy import deepcopy
from api_doc_shared import entry, response, obj, s, n, arr, ref, nullable, TIME, BROWSER
from api_doc_discovery import BODY as LEGACY_BODY, OPS as LEGACY_OPS, FACILITIES, ROAD_FILTER, SELECTED

REST=('post','/v1/discovery/rest-stops/query')
PLACES=('post','/v1/discovery/places/query')
def closed(fields, description, required=None):
    return dict(obj(fields,description,required),additionalProperties=False)
def numeric(description, low, high):
    return dict(type='number',description=description,minimum=low,maximum=high)
def constant(value, description):
    return dict(const=value,description=description)
BOUNDS=closed({key:numeric('명시 선택한 지도 영역의 '+key+' 경계. 유한 숫자이며 전체 영역이 고정 source 범위 안이어야 합니다.',-180 if key in ('west','east') else -90,180 if key in ('west','east') else 90) for key in ('west','south','east','north')},'west<east 및 south<north. 날짜변경선 감싸기·숨은 전국 범위·위치 추론은 지원하지 않습니다.')
ORDER=s('전체 적격 후보의 도로 거리 또는 추정 주행시간 오름차순. 실시간 교통이나 전역 최단 경로가 아닙니다.',enum=['distance','duration'],default='distance')
LIMIT=n('전체 적격 후보 계산 후 반환할 상한.',minimum=1,maximum=20,default=10)
ANCHOR=deepcopy(LEGACY_BODY['properties']['anchor'])
REST_ROAD=closed({'anchor':ANCHOR,'roadSearch':closed({'bounds':BOUNDS,'order':ORDER},'명시 도로 계산 모드. radiusMeters와 함께 보내지 않습니다.'),'requiredFacilities':deepcopy(LEGACY_BODY['properties']['requiredFacilities']),'roadFilter':ROAD_FILTER,'limit':LIMIT},'공식 휴게소 source 전체 적격 후보에 도로 비용을 계산한 뒤 상한을 적용합니다.',required=['anchor','roadSearch'])
PLACE_BODY=closed({'anchor':ANCHOR,'bounds':BOUNDS,'category':s('고정 OSM에서 이름이 있는 node 분류. ways/relations·완전한 전국 목록·품질·가격·현재 가용성을 뜻하지 않습니다.',enum=['restaurant','cafe','fast_food','food_court','fuel','toilets','charging_station','rest_area']),'order':ORDER,'limit':LIMIT},'현재 선택 지도 영역의 정적 장소. URL·source 지문·계정·Native revision·개인취향 필드는 받지 않습니다.',required=['anchor','bounds','category'])
BODY={REST:{'oneOf':[deepcopy(LEGACY_BODY),REST_ROAD],'description':'roadSearch가 없으면 기존 직선거리 계약, 있으면 명시 도로 계약입니다. 두 모드를 섞거나 자동 전환하지 않습니다.'},PLACES:PLACE_BODY}
DATE=closed({'value':s('원자료의 ISO date 또는 ISO datetime. 조회시각을 원자료 시각으로 바꾸지 않습니다.'),'precision':s('원자료 시각 정밀도.',enum=['date','datetime'])},'원자료 기준일. 개별 좌표 현장 검증·현재 영업 시각이 아닙니다.')
NONNEGATIVE=dict(type='number',minimum=0,description='실제 고정 도로 graph의 auto-costing 결과. 도달 불가면 null.')
REPORTED=closed({'kind':s('원자료 도로 종류.'),'routeNumber':s('원자료 노선번호.'),'routeName':s('원자료 노선명.'),'direction':nullable(s('보고 상하행 라벨. 실제 진입 방향 증명이 아닙니다.',enum=['up','down','both'])),'reportedDirection':nullable(s('원자료 방향 문자열.'))},'공식 휴게소의 보고 metadata. OSM 장소에서는 null입니다.')
HASH=s('원자료 또는 명시된 catalog의 SHA-256.',pattern='^[a-f0-9]{64}$')
MODELS={
 'DiscoveryRoadCandidate':closed({'place':SELECTED,'category':s('official-rest 또는 요청한 OSM 분류.'),'road':closed({'reachable':dict(type='boolean',description='고정 graph에서 보고 좌표까지 도달 가능한지 여부. 실제 입구 확인이 아닙니다.'),'distanceMeters':nullable(NONNEGATIVE),'estimatedDurationSeconds':nullable(NONNEGATIVE)},'reachable=false이면 두 수치는 모두 null입니다. 직선거리로 대체하지 않습니다.'),'facilities':nullable(dict(deepcopy(FACILITIES),additionalProperties=False)),'reportedRoad':nullable(REPORTED),'sourceAsOf':DATE},'도로 계산 후보. 도달 불가 후보는 선택하지 않으며 원자료 이름을 잘라 바꾸지 않습니다.'),
 'DiscoveryRoadSource':closed({'id':s('official-rest-snapshot 또는 osm-named-nodes.',enum=['official-rest-snapshot','osm-named-nodes']),'publisher':s('고정 원자료 발행자.'),'catalogUrl':s('원자료 출처 URL. 입력용 endpoint가 아닙니다.',format='uri'),'license':s('수집된 원자료 이용허락 표시. 마켓·법적 승인 주장이 아닙니다.'),'sourceSha256':HASH,'catalogSha256':HASH,'dataAsOf':DATE,'coverage':closed({'bounds':nullable(BOUNDS),'scope':s('보고 휴게소 또는 이름 있는 OSM node의 실제 자료 범위.'),'excluded':arr(s('제외된 자료·미확인 사항.'),'ways/relations·영업·가격·입구 등 자료 한계.')},'자료 수집 범위. 전국 시설의 완전성 보장이 아닙니다.'),'attribution':closed({'text':s('표시해야 하는 원자료 출처·권리 표시.'),'url':s('원자료 저작권·출처 링크.',format='uri')},'선택 전 기본 화면에 유지하는 원자료 출처.')},'CSV/PBF와 정규화 catalog를 구분한 고정 출처.'),
 'DiscoveryRoadGraph':closed({'sourceId':s('운영자가 고정한 graph source ID.'),'sourceSha256':HASH,'dataAsOf':s('고정 graph 원자료 시각. 조회시각이나 교통 갱신시각이 아닙니다.'),'bounds':BOUNDS,'attribution':s('OSM/Geofabrik 출처 표시.'),'license':s('고정 graph 원자료 이용허락.') ,**{key:constant(False,'항상 false. 현재 교통·전역 최단·현장 진입·방향은 검증하지 않습니다.') for key in ('liveTraffic','globallyShortest','entranceVerified','directionVerified')}},'고정 설정에 결합한 provenance. 원격 engine graph attestation을 뜻하지 않습니다.'),
 'DiscoveryRoadResult':closed({'items':dict(arr(ref('DiscoveryRoadCandidate'),'전체 적격 후보 계산·정렬 후 반환. 도달 불가도 null 지표로 유지합니다.'),maxItems=20),'source':ref('DiscoveryRoadSource'),'graph':ref('DiscoveryRoadGraph'),'basis':constant('valhalla-auto-road-graph-to-reported-coordinate','실제 도로 graph에서 보고 좌표까지의 auto 경로 비용.'),'queriedAt':dict(TIME,description='서버 계산 시각. 원자료·가격·좌표 현장 검증시각이 아닙니다.'),'anchor':deepcopy(__import__('api_doc_discovery').MODELS['DiscoveryResult']['properties']['anchor']),'applied':closed({'bounds':BOUNDS,'order':ORDER,'limit':LIMIT,'category':nullable(s('OSM 요청 분류. 공식 휴게소에서는 null.')),'requiredFacilities':deepcopy(LEGACY_BODY['properties']['requiredFacilities']),'roadFilter':ROAD_FILTER},'실제로 적용한 명시 조건.'),'counts':closed({'eligible':n('상한 적용 전 적격 후보 수.',minimum=0,maximum=1000),'reachable':n('전체 적격 후보 중 graph 도달 가능 수.',minimum=0,maximum=1000),'returned':n('반환 후보 수.',minimum=0,maximum=20)},'eligible 전수를 계산하며 topN 직선거리 사전 절단을 하지 않습니다.'),'unknown':closed({**{key:constant(None,'실시간 자료 미확인. 정적 시설 존재에서 추정하지 않습니다.') for key in ('currentOpen','currentPrice','chargerAvailable')},**{key:constant(False,'현장 진입·주행 방향을 확인하지 않았습니다.') for key in ('physicalEntranceVerified','physicalDirectionVerified')}},'실시간·현장 상태의 미확인을 유지합니다.')},'조회·선택은 저장·게시·방 공유·내비게이션 실행을 하지 않습니다.')}

EXAMPLE={'anchor':{'kind':'selected-place','place':{'id':'selected-public-example','provider':'map','name':'선택한 장소','address':'','latitude':37.5618896,'longitude':126.97622}},'bounds':{'west':126.975,'south':37.565,'east':126.98,'north':37.57},'category':'restaurant','order':'distance','limit':3}
ERRORS={'400':'DISCOVERY_QUERY_INVALID 등 닫힌 입력·영역·분류·상한 오류입니다. 명시 영역을 줄이거나 올바른 선택을 다시 하세요. upstream 본문은 노출하지 않습니다.','408':'본문 수신이5초를 초과했습니다. 저장 성공으로 표시하지 마세요.','429':'계정60회/분 또는 같은 API process의 도로 계산 사용 중입니다. rate 응답의 Retry-After를 따르며 busy에 헤더가 없으면 재조작을 기다립니다.','502':'DISCOVERY_ENGINE_RESULT_INVALID 또는 DISCOVERY_RESULT_TOO_LARGE 등 engine 결과를 거절했습니다. 일부 후보·직선거리로 성공을 꾸미지 않습니다.','504':'DISCOVERY_ENGINE_TIMEOUT. 고정3초 transport 또는8초 전체 계산 제한으로 결과를 버렸습니다. 더 작은 명시 영역을 선택하세요.'}
def operation(summary, schema, example):
    doc=entry('14 시설 후보',summary,BROWSER+' 두 discovery POST는 Native 호스트에서404입니다. 별도 Native 목적·권한을 추가하지 않습니다.',
        '기존 지도에서 기준 장소와 보이는 검색 영역을 명시 선택합니다. 현재위치는 별도 브라우저 권한과 이번 검색의 전송 동의 후에만 보냅니다. 고정 source의 모든 적격 후보를 계산한 뒤 선택 조건과 상한을 적용합니다.',
        '좌표·검색 본문·결과를 DB·개인 이력·WSS에 저장하거나 새 외부 서비스로 보내지 않습니다. 운영자 고정 loopback engine만 호출하며 세션과 현재 계정을 반환 전에 다시 확인합니다. source/date/권리/미확인은 선택 전에 표시합니다.',
        '빈 결과는 실제 빈 목록입니다. 도달 불가는 수치 null이며 선택하지 않습니다. 공급원403·연결 실패는503, timeout은504로 끝나며 자동 재시도·직선거리 fallback은 없습니다.',
        {'200':response(schema,'고정 자료와 실제 도로 graph의 계산 결과. 실시간 교통·가격·영업·충전 가용성·현장 입구 보장이 아닙니다.'),'503':response({'oneOf':[closed({'code':constant('PREPARATION','운영자 고정 자료가 아직 연결되지 않았습니다.')},'공통 준비 응답.'),ref('ApiError')]},'미연결은 {code:PREPARATION}, 공급원 사용 불가는 detail 오류입니다. 준비 중입니다로 처리하고 성공 목록을 만들지 마세요.')},
        ['400','401','403','404','408','413','429','502','504'],example=example,
        notes='후보 선택은 place6 로컬 선택뿐입니다. 이후 별도로 현재 방·status/location 동의를 확인하고 기존 signals POST의 실제201와 정본 GET을 확인합니다. 투표는 별도 vote 요청입니다. 기존 방 DTO는 provider provenance를 보존하지 않으므로 출처 보존 export라고 표현하지 않습니다. 내비게이션 실행·국도우선·실차 위치 인증이 아닙니다.')
    doc['errorDescriptions']=ERRORS
    return doc
OPS={PLACES:operation('명시 지도 영역의 정적 장소를 도로 거리·추정시간으로 찾기',ref('DiscoveryRoadResult'),EXAMPLE),REST:operation('선택 장소 주변 공식 휴게소의 직선·도로 후보 찾기',{'oneOf':[ref('DiscoveryResult'),ref('DiscoveryRoadResult')]},{'anchor':deepcopy(EXAMPLE['anchor']),'roadSearch':{'bounds':deepcopy(EXAMPLE['bounds']),'order':'distance'},'requiredFacilities':['toilet'],'limit':3})}
