# WegoH 서버

차량 앱과 iPhone 앱이 함께 쓰는 FastAPI API와 PostgreSQL 저장소입니다. 앱이 서버와 어떻게 연결되는지 이해하는 참고용으로 포함했습니다. 앱은 팀이 운영하는 서버에 접속하므로 심사를 위해 이 서버를 실행할 필요는 없습니다. 운영 배포 스크립트와 비밀값은 저장소에 포함하지 않았습니다.

## 구성

모듈은 이 디렉터리에 평탄하게 두고, 각 모듈의 테스트(`test_*.py`)를 같은 디렉터리에 둡니다. 일부 테스트는 이 저장소에 포함하지 않은 운영 스크립트가 있어야 실행됩니다.

| 경로 | 역할 |
| --- | --- |
| `app.py`, `api_application.py` | API 진입점과 라우터 구성 |
| `api_doc_*.py`, `team_api_docs.py` | Swagger/OpenAPI 계약 |
| `iphone_*.py` | iPhone 앱 API (로그인, 여행, 코스, 친구, 리모컨) |
| `native_*.py` | 차량 앱 API (기기 인증서 연결, 여행 진행, 음성, 차량 제어) |
| `team_*.py` | 여행방·코스·기록 공용 로직 |
| `enrollment*.py` | 차량 연결(QR·8자리 코드) 승인 |
| `migrations/`, `schema.sql`, `*_schema.sql` | DB 스키마와 마이그레이션 |
| `native_access_wire.json` | 차량 앱과 공유하는 연결 규약 (차량 앱 빌드에도 사용) |
| `web/` | Swagger API 문서 화면, iPhone 로그인 화면 스타일 |

## 보안 설계

- 차량 앱은 기기마다 발급한 클라이언트 인증서(mTLS)로 접속하고, 사용자가 iPhone 앱에서 승인한 범위만 쓸 수 있습니다.
- 위치·음성·리모컨·점수 공유는 기능별로 따로 동의받고, 철회하면 즉시 공유를 멈춥니다.
- 개인 기록과 민감한 값은 서버에서 암호화해 저장합니다.

## 의존성

Python 3.12 이상, PostgreSQL. 패키지 목록은 `requirements.txt`, 고정 버전은 `requirements.lock.txt`에 있습니다.
