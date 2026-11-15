# WegoH iPhone 앱

여행 만들기, 코스·음악 편집, 친구, 동승자 리모컨, 차량 연결 승인을 맡는 SwiftUI 앱입니다. 차량 앱(`android/`)과 같은 WegoH 서버를 사용합니다.

## 빌드

- macOS, Xcode, iOS 17 이상 시뮬레이터 또는 기기
- `ios/WegoH.xcodeproj`를 열고 `WegoH` 스킴으로 빌드합니다.
- 서명 팀(`DEVELOPMENT_TEAM`)은 비워 두었습니다. 기기에 설치하려면 Xcode의 Signing & Capabilities에서 본인 팀을 선택하세요. 시뮬레이터는 서명 없이 실행할 수 있습니다.
- 지도 키는 선택입니다. 필요하면 `ios/api_keys.swift.example`을 `ios/WegoH/api_keys.swift`로 복사해 카카오 지도 키를 넣습니다. 이 파일은 Git에서 제외됩니다. 키가 없어도 빌드·실행됩니다.

## 구조

```text
WegoH/
├── App/          # 앱 진입점, 세션 주입, 탭 구성
├── Tabs/
│   ├── Trips/    # 여행 목록·준비·진행·완료
│   ├── Courses/  # 코스 탐색·내 코스·편집·지도
│   ├── Music/    # 플레이리스트 링크
│   ├── Friends/  # 친구 목록·요청·코드 검색
│   └── Settings/ # 프로필·권한·차량 연결(QR·8자리 코드)
├── Flows/        # 로그인, 첫 실행 안내·권한
├── Shared/       # 디자인 토큰, 세션·인증, 권한, 공통 UI
└── Testing/      # DEBUG 전용 화면 시험 데이터
```

`WegoHTests`는 단위 테스트, `WegoHUITests`는 화면 시험입니다. DEBUG 전용 시험 모드는 메모리 데이터만 쓰며 실제 계정·네트워크에 접속하지 않습니다.
