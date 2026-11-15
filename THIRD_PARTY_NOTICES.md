# 구성요소와 출처

WegoH의 앱·서버 소스 코드, 화면 디자인, 알림음은 WegoH 개발팀이 직접 만들었습니다. 아래 외부 구성요소는 각 제공처의 이용 조건과 라이선스를 따릅니다.

## 차량 앱 (`android/`)

| 구성요소 | 버전 | 용도 | 라이선스·이용 조건 |
|---|---|---|---|
| Pleos Connect Vehicle SDK | 2.3.2 | 차량 상태 조회·제어 | Pleos Playground 이용 조건 |
| Pleos Connect NaviHelper SDK | 3.0.5 | 차량 내비게이션 경로 요청 | Pleos Playground 이용 조건 |
| Pleos Connect FusedLocation SDK | 1.1.3 | 차량 위치 | Pleos Playground 이용 조건 |
| Kakao Maps SDK for Android | 2.15.2 | 지도 표시 | 카카오 지도 API 이용 약관. 지도 저작자 표시를 유지하며 지도 타일은 저장소에 포함하지 않음 |
| AndroidX (Core, Activity, Lifecycle, Compose, Material3) | build.gradle.kts 참고 | UI·생명주기 | Apache License 2.0 |
| AndroidX Media3 ExoPlayer | 1.4.1 | 함께 듣기 음원 재생 | Apache License 2.0 |
| Kotlin, kotlinx.coroutines | 2.0.0, 1.9.0 | 언어·비동기 처리 | Apache License 2.0 |
| OkHttp | 4.12.0 | HTTPS·WebSocket 통신 | Apache License 2.0 (`android/native-access/src/main/assets/licenses/okhttp-LICENSE.txt`) |
| ZXing core | 3.5.4 | 차량 연결 QR 코드 생성 | Apache License 2.0 |
| Asta Sans | `android/third_party/asta-sans/source.json` 참고 | 앱 글꼴 | SIL Open Font License 1.1 (`android/third_party/asta-sans/OFL.txt`). 원본 글꼴 파일을 변경 없이 포함 |

소스 트리에는 Pleos SDK·Kakao Maps SDK 바이너리를 두지 않고, 빌드할 때 각 Maven 저장소에서 받습니다. `apk/`의 빌드 결과물에는 이 SDK들이 포함됩니다. Kakao Maps SDK가 함께 넣는 리소스(지도 엔진 라이브러리, Twemoji Mozilla 글꼴: Apache License 2.0, 그림은 CC BY 4.0)는 SDK 배포 조건과 각 라이선스를 따릅니다.

위 라이브러리가 함께 가져오는 전이 의존성(Okio, Dagger/Hilt, Gson, Guava, javax.inject, kotlin-reflect, kotlinx.serialization)은 Apache License 2.0을, OkHttp에 포함된 Public Suffix List는 MPL 2.0을 따릅니다. OkHttp·ZXing·Asta Sans의 라이선스 전문은 APK의 `assets/licenses/`에도 들어 있습니다. 시험 전용 도구(JUnit 4.13.2 EPL-1.0, org.json)는 앱 배포물에 포함되지 않습니다.

빌드 도구: Gradle Wrapper(`android/gradlew`, `android/gradle/wrapper/`)는 Apache License 2.0이며 원래 저작권 표시를 스크립트 머리말에 유지합니다. Android Gradle Plugin 8.8.2, Kotlin Gradle Plugin 2.0.0(Apache License 2.0)을 사용합니다.

## iPhone 앱 (`ios/`)

| 구성요소 | 버전 | 용도 | 라이선스·이용 조건 |
|---|---|---|---|
| Kakao Maps SDK for iOS (Swift Package) | 2.12.19 | 지도 표시 | 카카오 지도 API 이용 약관 |

## 서버 (`server/`)

| 구성요소 | 용도 | 라이선스 |
|---|---|---|
| FastAPI, Uvicorn | API 서버 | MIT, BSD-3-Clause |
| psycopg | PostgreSQL 연결 | LGPL-3.0 |
| cryptography, PyJWT, websockets, httpcore | 암호화·인증·실시간 통신 | Apache-2.0/BSD, MIT, BSD-3-Clause, BSD-3-Clause |
| OpenTelemetry SDK·OTLP exporter | 서버 관측 | Apache License 2.0 |
| Pillow | 여행 사진 변환 | MIT-CMU (HPND) |
| Starlette, Pydantic (FastAPI 구성요소) | 요청 처리·검증 | BSD-3-Clause, MIT |
| 카카오 로컬 API(장소 검색), 카카오모빌리티 길찾기 API | 장소 검색·경로 미리보기·손들기 경유 계산 | 각 서비스 이용약관. API 키는 저장소에 포함하지 않음 |
| Swagger UI | 5.34.0 · API 문서 화면 | Apache License 2.0 (`server/web/vendor/swagger-ui/licenses.html`) |

정확한 버전은 `server/requirements.txt`와 `server/requirements.lock.txt`에 있습니다. 전이 의존성은 MIT·BSD·Apache-2.0·MPL-2.0(certifi)·PSF 라이선스를 따르며, 서버 패키지는 저장소에 재배포하지 않고 설치할 때 받습니다. 서버 화면 시험 도구(Playwright, Apache License 2.0)는 배포물에 포함되지 않습니다.

## 이미지·아이콘

| 대상 | 출처 | 비고 |
|---|---|---|
| 앱 아이콘·로고: Android `res/mipmap-anydpi-v26/ic_launcher.xml`·`res/drawable/wegoh_launcher_foreground.xml`·`res/drawable/wegoh_icon_brand.xml`, iOS `Assets.xcassets`의 `AppIcon`·`BrandMark`·`BrandWordmark` | 팀이 생성형 AI 도구로 제작 | 외부 이미지·상표를 가져다 쓰지 않았습니다 |
| Android `res/drawable/pleos_icon_*.xml` 10종(alert, check, close, down, info, microphone, pause, person, plus, up) | Pleos Connect 공식 디자인 에셋(Figma, Pleos Connect design assets 2.1.5)에서 추출한 벡터 | Pleos 앱 UI 가이드에 맞추기 위해 사용. 권리는 제공처에 있으며 Pleos Playground 이용 조건을 따릅니다 |
| 그 밖의 UI 아이콘 `res/drawable/wegoh_icon_*.xml`, 알림 아이콘 `res/drawable/ic_wegoh.xml`, 웹 `server/web/favicon.svg` | WegoH 자체 제작 벡터(Pleos 48dp 격자에 맞춰 작성) | 외부 아이콘 폰트·이미지 미사용 |
| iPhone 앱 UI 아이콘 | iOS 시스템이 제공하는 SF Symbols | 앱에 아이콘 파일을 따로 포함하지 않음 |

## 음원과 데이터

- `android/app/src/main/res/raw/arrival.wav`: 팀이 PCM 파형으로 직접 만든 0.5초 알림음입니다.
- `android/app/src/debug/assets/listen-together/wegoh-demo-01.wav`: 함께 듣기 시연용으로 팀이 음표 표에서 직접 합성한 음원입니다. debug 빌드에만 포함되며 외부 음원·샘플을 사용하지 않았습니다.
- 음악 기능은 음악 링크만 공유하며, 외부 음원을 저장소나 앱에 포함하지 않습니다.
- `server/rest_stop_data.py`: 공공데이터포털 「전국휴게소정보표준데이터」(한국도로공사, data.go.kr 15025446, 2026-09-17 기준, 이용허락범위 제한 없음)를 손들기의 휴게소 후보로 쓰기 위해 정리해 포함했습니다.
- 서버에는 OpenStreetMap 데이터(© OpenStreetMap contributors, ODbL 1.0)와 Valhalla(MIT)를 쓰는 주변 탐색 코드가 있습니다. 지도 데이터 파일은 저장소에 포함하지 않습니다.
- 앱 안의 기본 코스·시험 장소 좌표는 에뮬레이터 시험용입니다.
