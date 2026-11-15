from api_doc_shared import arr, b, entry, n, nullable, ok, s, IDENT
from api_doc_trips import strict


COURSE = strict(dict(packId=s('시작 시 고정한 공유 코스 ID.'), version=n('고정 코스 버전.', minimum=1),
    state=s('최종 보고 상태.', enum=['pending', 'final', 'unavailable', 'sharing-unavailable']),
    score=nullable(n('완료한 측정 가능 코스의 최종 점수만 공개.', minimum=0, maximum=100))), '원시 자료·사건 횟수 없는 대결 코스 요약.')
CAR = strict(dict(carId=IDENT, name=s('시작 시 저장한 차량 이름.'), participating=b('자동 참가이므로 항상 true.'),
    state=s('자동 참가와 측정·공개 가능 여부는 별개.', enum=['pending', 'ready', 'unavailable', 'withdrawn', 'sharing-unavailable']),
    averageScore=nullable(dict(type='number', minimum=0, maximum=100, description='완료한 측정 가능 final 코스의 평균. 표시만 소수 둘째 자리 반올림.')),
    measuredCourseCount=n('평균에 사용한 측정 가능 코스 수.', minimum=0), courses=arr(COURSE, '시작 순서의 공유 코스.')),
    '현재 멤버·차량·차단·보고 기기의 현재 계정/grant 귀속으로 필터링.')
VERSUS = strict(dict(kind=s('미션 종류.', const='safe-driving-versus'), automatic=b('항상 true. 별도 생성/참가 동의 API 없음.'),
    state=s('집계 중/확정/비교 불가.', enum=['pending', 'final', 'unavailable']),
    reason=nullable(s('확정 전·비교 불가의 실제 이유. 코스 대결: final-reports-pending, contract-unavailable(v2 시작 아님), insufficient-cars, '
        'shared-incomplete, insufficient-measurements, course-unavailable, participant-unavailable, vehicle-connection-required, '
        'report-device-changed, vehicle-authority-unavailable(두 가지 이상). 여행 전체 점수: trip-reports-pending, trip-cancelled, '
        'insufficient-measurements, participant-unavailable, vehicle-connection-required, report-device-changed, vehicle-authority-unavailable. final이면 null.')), cars=arr(CAR, '현재 볼 수 있는 자동 참가 차량.'),
    winnerCarIds=arr(IDENT, '확정하고 모든 기여를 공개할 수 있을 때만 공동 최고 차량 전부.'),
    tied=b('공동 최고 차량이 둘 이상이면 true.')), '같은 차 drivingScores와 별도인 여행 내 명시적 대결 DTO.')
OPS = {('get', '/v1/native/trips/{id}/driving-versus'): entry('여행', '자동 참가 안전운전 대결 조회',
    '현재 native rooms:read 또는 iPhone trips:read. 해당 여행 수락 멤버이면서 참가 차량의 현재 운전자/동승자만.',
    'v2 시작은 전 차량 자동 참가. 같은 여행 참여로 점수 공유하며 별도 점수 동의 없음. pending 동안 집계 중을 표시.',
    '완료한 측정 가능 final 코스만 평균. 현재 운전자 기기의 실제 보고만 별도 암호화 복사. 모든 참가 차 공유 종료 및 final 도착 뒤 확정하며 늦은 final도 허용. 같은 차 직접 drivingScores는 넓히지 않음.',
    '쿼리를 붙이면 400 Invalid driving versus fields. 내가 운전·동승하는 차가 없거나 대결에서 빠진 차, 차단한 운전자의 차면 404 Driving versus unavailable. '
    'v2로 시작하지 않은 여행은 200 contract-unavailable과 빈 cars. 현재 차량 연결 상실·차단·참가 자격 상실이면 점수와 승자를 숨김. 혼자/측정 불가/미완료는 승자를 만들지 않음.',
    ok(VERSUS), ['400', '401', '403', '404', '503'])}

TOTAL_CAR = strict(dict(CAR['properties'], totalScore=nullable(n('여행 전체 누적 점수. 코스 평균 아님.', minimum=0, maximum=100)), final=b('해당 차의 전체 여행 측정 종료.')), '기존 평균/코스 칸은 null/0/빈 배열. 원시 자료와 횟수 공개 없음.')
TOTAL = strict(dict(VERSUS['properties'], scope=s('집계 범위.', const='trip'), cars=arr(TOTAL_CAR, '현재 공개 가능한 여행 전체 점수.')), '픽업·대기·공유·드랍 모두 포함. 기존 코스 평균을 이 점수로 변환하지 않음.')
OPS['get', '/v1/native/trips/{id}/driving-score'] = entry('여행', '여행 전체 안전운전 점수 조회',
    '현재 native rooms:read 또는 iPhone trips:read. 같은 여행의 현재 차 운전자/동승자.',
    '같은 여행 참여 자격과 현재 보고 기기 귀속이 유효한 전체 누적 보고를 조회.',
    '현재 멤버·차단·현재 기기/grant 귀속으로 점수와 승자 필터링. 기능 동의 버전이나 revision 변경으로 숨기지 않음. 픽업부터 드랍까지 차량별 100점에서 누적 차감. '
    '빠지지 않은 모든 차가 final을 보고하고 측정 가능한 차가 2대 이상이면 최고 점수 차를 승자로 확정합니다. 취소한 여행은 trip-cancelled.',
    '조회는 기존 보고를 전체 점수로 변환하거나 새 권한을 승인하지 않음. 쿼리를 붙이면 400 Invalid driving score fields, 내 차가 없거나 대결에서 빠졌거나 차단한 운전자의 차면 404 Driving score unavailable.',
    ok(TOTAL), ['400', '401', '403', '404', '503'])
