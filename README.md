# WegoH (위고 에이치)

> 일행의 대화·음악·경로를 연결하고, 함께 달린 길을 누군가의 다음 여행으로 이어주는 소셜 드라이빙 앱

## APK

| 항목 | 값 |
|---|---|
| 파일 | [`apk/TeslaX_WegoH_release.apk`](apk/TeslaX_WegoH_release.apk) |
| 종류 | release 빌드(팀 서명), 이 저장소 소스로 빌드 |
| 패키지 | `io.wegoh.app` |
| 앱 SDK 범위 | minSdk 28 · targetSdk/compileSdk 35 |

## 테스트 환경

| 항목 | 값 |
|---|---|
| 에뮬레이터 | Pleos Connect 에뮬레이터 v2.1.0 (`RELEASE.release_connect_v2.1.0`) |
| 에뮬레이터 이미지 | arm64-v8a (Apple Silicon macOS에서 개발·시험). APK의 네이티브 라이브러리(카카오 지도 SDK)는 arm64-v8a·armeabi-v7a용입니다 |
| 플랫폼 | Android Automotive OS 14 (API 34) |
| 화면 규격 | 2560 × 1440, 160dpi (mdpi) |
| 차량 상태 시험 | Pleos Connect Virtual Console (기어 P/D 전환 등) |
| 네트워크 | 인터넷 연결 필요 (팀이 운영하는 WegoH 서버에 HTTPS로 접속) |

실제 차량 없이 위 에뮬레이터에서 개발·시험했습니다.

## 실행 방법

1. Pleos Playground 개발 문서의 [에뮬레이터 설정 가이드](https://document.pleos.ai/docs/connect/guide/getting-started/application-development/setup-connect-sdk-emulator)에 따라 Pleos Connect 에뮬레이터를 실행합니다.
2. APK를 설치하고 실행합니다.

   ```sh
   adb install -r apk/TeslaX_WegoH_release.apk
   adb shell am start -n io.wegoh.app/.MainActivity
   ```

3. 처음 실행하면 앱 권한 화면에서 위치와 차량 속도 권한을 안내합니다. **권한 설정**을 눌러 허용하면 코스 도착 확인, 위치 공유, 안전운전 점수를 쓸 수 있고, **나중에**를 눌러도 앱을 둘러볼 수 있습니다. 마이크 권한은 워키토키로 처음 녹음할 때 묻습니다.
4. 계정 기능(여행, 코스, 친구, 리모컨)은 **차량 연결** 후에 열립니다. 차량 화면에서 **차량 연결**을 누르면 QR 코드와 8자리 연결 코드가 표시됩니다(5분 동안 유효). 이 코드를 WegoH iPhone 앱에서 승인하면 연결됩니다.

### 필요한 설정과 참고 사항

- **심사용 접속**: iPhone 앱 없이 차량 연결을 승인하는 방법은 접수양식(기획서)에 적었습니다.
- **iPhone 앱**: 여행 만들기, 코스·음악 편집, 동승자 리모컨, 차량 연결 승인은 iPhone 앱이 맡습니다(소스: [`ios/`](ios/)). iPhone 앱은 공개 배포하지 않았으므로, 연결 이후의 전체 흐름은 함께 제출한 **시연 영상**에서 확인할 수 있습니다.
- **주행 상태**: Virtual Console에서 기어를 P(정차)와 D(주행)로 바꾸면 차량 화면이 주행 제한(CarUxRestrictions)에 맞춰 바뀝니다. 주행 중에는 한 번의 터치로 끝나는 응답만 남깁니다.
- **도착 확인**: 코스 장소 도착은 FusedLocation 위치로 판단합니다. 에뮬레이터에서는 가상 위치를 바꿔 시험합니다.
  ```sh
  adb emu geo fix <경도> <위도>
  ```

## 소스에서 빌드

### 차량 앱 (`android/`)

필요: Android SDK(API 35), JDK 17 또는 21 (Gradle 8.10.2는 JDK 24 이상에서 실행되지 않습니다. 최신 Android Studio 내장 JDK가 이에 해당하면 `JAVA_HOME`을 JDK 21로 지정하세요). Gradle 8.10.2는 Wrapper에 포함되어 있습니다. Pleos SDK는 Pleos Playground Maven 저장소에서 자동으로 받습니다.

```sh
cd android
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

API 키와 서명 정보는 저장소에 넣지 않았습니다. 필요한 값은 다음과 같이 지정합니다.

| 값 | 용도 | 지정 방법 |
|---|---|---|
| 카카오 지도 Native 앱 키 | 차량 화면 지도 표시 (없으면 지도 대신 안내 문구가 보이고 나머지 기능은 동작) | `android/local.properties`의 `wegohKakaoNativeAppKey=` 또는 환경 변수 `WEGOH_KAKAO_NATIVE_APP_KEY` ([예시](android/local.properties.example)) |
| 서비스 주소 | release 빌드의 서비스 HTTPS 주소 | Gradle 속성 `-PwegohApiUrl=https://…` |
| release 서명 | release 빌드 서명 | 환경 변수 `WEGOH_RELEASE_STORE_FILE`, `WEGOH_RELEASE_STORE_PASSWORD`, `WEGOH_RELEASE_KEY_ALIAS`, `WEGOH_RELEASE_KEY_PASSWORD` |

release 빌드는 서비스 주소와 서명이 없으면 의도적으로 실패합니다. debug 빌드는 일부 주소(공개 코스 목록, 앱 업데이트 확인)가 로컬 개발 서버를 가리킵니다. 실행에는 저장소의 APK를 사용하면 됩니다.

단위 테스트:

```sh
cd android
./gradlew testDebugUnitTest
```

### iPhone 앱 (`ios/`)

macOS의 Xcode에서 `ios/WegoH.xcodeproj`를 열고 `WegoH` 스킴으로 빌드합니다(iOS 17 이상). 지도 키는 `ios/api_keys.swift.example`을 `ios/WegoH/api_keys.swift`로 복사해 지정합니다(자세한 내용은 [ios/README.md](ios/README.md)).

### 서버 (`server/`)

FastAPI·PostgreSQL 서버 소스입니다. 앱 동작을 이해하는 참고용으로 포함했습니다. 차량 앱과 iPhone 앱은 팀이 운영하는 서버에 접속하므로 심사를 위해 서버를 직접 실행할 필요는 없습니다. 자세한 구성은 [server/README.md](server/README.md)에 있습니다.

## 사용한 Pleos Connect SDK

Pleos Connect SDK 5종 중 **Vehicle·NaviHelper·FusedLocation** 3종을 사용합니다(TextToSpeech·SpeechToText는 사용하지 않음). 아래 목록은 차량 앱(debug 빌드)을 컴파일한 클래스 2,097개에서 Pleos SDK 참조를 모두 추출해 대조한 것으로, 앱이 호출하는 SDK API와 구현한 콜백을 빠짐없이 적었습니다.

| SDK | 버전 | 의존성 | 매니페스트 권한 |
|---|---|---|---|
| Vehicle SDK | 2.3.2 | `ai.pleos.playground:Vehicle` (`android/vehicle-hardware`) | `pleos.car.permission.CAR_CLIMATE`·`CONTROL_CAR_CLIMATE`, `CAR_SEATS`·`CONTROL_CAR_SEATS`, `CAR_WINDOWS`·`CONTROL_CAR_WINDOWS`, `CAR_LIGHTS`·`CONTROL_CAR_LIGHTS` |
| NaviHelper SDK | 3.0.5 | `ai.pleos.playground:NaviHelper` (`android/app`) | `pleos.car.permission.NAVI_ROUTE`, `NAVI_ROUTE_SEARCH` |
| FusedLocation SDK | 1.1.3 | `ai.pleos.playground:FusedLocation` (`android/app`) | `pleos.car.permission.FUSED_LOCATION` |

### Vehicle SDK — 동승자 리모컨

운전자가 허용한 범위에서 동승자가 iPhone으로 보낸 조작을 차량에서 실행합니다. 모든 항목은 실행 전에 `check…Capabilities`로 지원 여부·접근 권한(`AccessType`)·범위(`AreaBounds`, 온도는 `HvacTemperatureConfigArray`)를 확인하고, 지원하지 않거나 범위를 벗어나면 실행하지 않습니다. 실행 뒤에는 getter로 실제 상태를 다시 읽어 결과를 보고합니다.

| 리모컨 항목 | 사용한 API | 단위 |
|---|---|---|
| 공조 전원 | `HVAC.checkHvacPowerCapabilities` · `getHvacPowerState` · `setHvacPower` | 차량 전체 |
| 목표 온도 | `HVAC.checkHvacTemperatureCapabilities` · `getHvacTemperature` · `setHvacTemperature` (`TemperatureUnit.CELSIUS`) | 좌석 구역 |
| 풍량 | `HVAC.checkHvacFanSpeedCapabilities` · `getHvacFanSpeed` · `setHvacFanSpeed` | 좌석 구역 |
| 냉방(A/C) | `HVAC.checkHvacAcCapabilities` · `getHvacAcState` · `setHvacAc` | 좌석 구역 |
| 공기청정 | `HVAC.checkHvacAirCleanerCapabilities` · `getHvacAirCleanerState` · `setHvacAirCleaner` | 좌석 구역 |
| 시트 열선 | `Seat.checkSeatTemperatureCapabilities` · `getHvacSeatTemperature` · `setHvacSeatTemperature` | 좌석별(`SeatArea`) |
| 시트 통풍 | `Seat.checkSeatVentilationCapabilities` · `getHvacSeatVentilationState` · `setHvacSeatVentilation` | 좌석별(`SeatArea`) |
| 창문 위치 | `Window.checkWindowPositionCapabilities` · `getCurrentWindowPosition` · `setWindowPosition` | 창문별(`WindowArea`) |
| 실내등 | `Light.checkCabinLightSwitchCapabilities` · `getCabinLightSwitch` · `setCabinLightSwitch` (`LightSwitch.ON/OFF`) | 차량 |
| 독서등 | `Light.checkReadingLightSwitchCapabilities` · `getReadingLightSwitch` · `setReadingLightSwitch` | 좌석별 |
| 앰비언트 라이트 | `Light.checkAmbientLightSwitchCapabilities` · `getAmbientLightSwitch` · `setAmbientLightSwitch` | 좌석별 |

- 세션: `Vehicle(context)` → `initialize` → 도메인 객체(`getHVAC`·`getSeat`·`getWindow`·`getLight`)로 사용 → `release`. 리모컨 수신 서비스가 세션을 소유합니다. 좌석·창문 구역은 `SeatArea`·`WindowArea`(`SeatValue`·`WindowValue`)로 지정합니다.
- 소스: [`VehicleHardwareSdkAdapter.kt`](android/vehicle-hardware/src/main/java/io/wegoh/app/VehicleHardwareSdkAdapter.kt)(SDK 호출), [`VehicleClimateService.kt`](android/app/src/main/java/io/wegoh/app/VehicleClimateService.kt)·[`VehicleClimateHost.kt`](android/app/src/main/java/io/wegoh/app/VehicleClimateHost.kt)(수신·실행), [`VehicleControlSupport.kt`](android/app/src/main/java/io/wegoh/app/VehicleControlSupport.kt)(지원 항목 보고).
- 같은 어댑터에 연료(`Fuel.getFuelPercent`)·주행 거리(`Odometer.getCurrentDistanceDriven`)·브레이크(`Brake.getCurrentBrakePedalStatus`) 읽기가 있지만, 이는 루트 빌드에 포함되지 않는 별도 진단 프로젝트 [`android/vehicle-readonly-smoke`](android/vehicle-readonly-smoke/)(어댑터 소스를 가져다 빌드하는 읽기 전용 Vehicle SDK 확인용 시험 앱)에서만 호출합니다. WegoH 앱은 이를 호출하지 않고 필요한 권한(`pleos.car.permission.CAR_DRIVE`·`CAR_ENERGY`)도 선언하지 않습니다.

### NaviHelper SDK — 차량 기본 내비게이션 연동

별도 내비 앱을 만들지 않고 차량 기본 내비게이션을 사용합니다. 세 곳에서 씁니다. 모두 `NaviHelper(context)` → `initialize` → `addListener` → 사용 → `removeListener` · `release` 순서입니다.

1. **코스·여행 출발**: [`PleosClients.kt`](android/app/src/main/java/io/wegoh/app/PleosClients.kt)의 `NavigationClient`
   - 목적지만 있으면 `requestRoute(RouteInfo)`, 경유지가 있으면 `requestRouteWithWaypoints(RouteWithWaypointsRequest)`(`RequestWaypointInfo`, `WaypointIndex.FIRST`·`SECOND`, 경유지 최대 2개).
   - 요청을 보낸 것만으로 성공 처리하지 않습니다. `getRouteStateInfo`·`getDestinationInfo`·`getWaypointInfo`로 내비에 실제 설정된 목적지와 경유지 순서를 다시 읽어 일치할 때만 "안내 중"으로 표시합니다.
   - 구현한 콜백: `onRouteStarted`, `onRoutingCompleted`, `onNavigationStatus`(`NavigationStatus.ROUTE_DRIVE`), `onRouteStateInfo`(`NaviMode.ROUTE_GUIDING`, `TrafficStatus` 혼잡 구간 → 코스 상세의 장소별 교통 표시), `onDrivingInfo`(남은 거리·시간), `onTBTInfo`(재확인 시점으로만 사용), `onDestinationInfo`, `onWayPointInfo`, `onDestinationChanged`, `onRouteCancelled`, `onDestinationArrived`, `onError`(`NaviErrorCode`).
2. **여행 진행**: [`TripVehicleIntegration.kt`](android/app/src/main/java/io/wegoh/app/TripVehicleIntegration.kt)의 `TripNavigationSession`
   - `onWayPointArrived`(`WaypointArrivedInfo`)·`onDestinationArrived`로 픽업·장소·도착을 진행에 반영합니다.
   - `onCurrentLocationInfo`·`getCurrentLocationInfo`(위치·진행 방향)와 `getDestinationInfo`·`getWaypointInfo`(남은 거리·시간)로 진행 바와 지도의 내 차 위치를 갱신합니다(일행에게 공유하는 위치는 FusedLocation 값). 그 밖에 `onDestinationInfo`, `onWayPointInfo`, `onDrivingInfo`, `onDestinationChanged`, `onError`를 구현합니다.
3. **손들기**: [`TripSignalNavigation.kt`](android/app/src/main/java/io/wegoh/app/TripSignalNavigation.kt)
   - `getCurrentLocationInfo`·`getDestinationInfo`로 현재 위치와 목적지를 읽어 앞쪽 휴게소·쉼터 후보를 찾습니다(내비 정보가 없으면 FusedLocation 위치 사용).
   - 구현한 콜백: `onCurrentLocationInfo`, `onDestinationInfo`.
   - 요청한 차를 뺀 다른 차가 모두 동의하면 서버가 합의한 장소를 각 차의 여행 경로 다음 순서에 넣습니다. 운전자가 차량 화면에서 **길 안내**를 누르면 그 장소를 `NavigationClient`의 `requestRoute`로 차량 내비의 목적지로 설정합니다.

### FusedLocation SDK — 차량 위치

[`PleosClients.kt`](android/app/src/main/java/io/wegoh/app/PleosClients.kt)의 `LocationClient`: `FusedLocation(context)` → `isSupported` → `initialize` → `getLastKnownLocation`·`registerFusedLocationCallback`(`FusedLocationListener.onChanged`·`onError`) → `unregisterFusedLocationCallback` · `release`. `LocationData`의 위도·경도·진행 방향·시각을 사용합니다.

| 사용처 | 용도 |
|---|---|
| [`JourneyExecutionManager.kt`](android/app/src/main/java/io/wegoh/app/JourneyExecutionManager.kt) | 코스 장소 도착 확인(반경 안 진입, 오래된 위치 제외) |
| [`TripLocationObservation.kt`](android/app/src/main/java/io/wegoh/app/TripLocationObservation.kt) | 여행 중 동의한 일행에게 내 차 위치 공유 |
| `TripVehicleIntegration.kt` | 여행 진행 위치(NaviHelper 위치와 함께 받고, 오래됐거나 직전 값보다 새롭지 않은 값은 버림) |
| `TripSignalNavigation.kt` | 손들기 위치 보완 |

<details>
<summary>SDK 참조 전체 목록 (컴파일된 클래스에서 추출, 클래스·멤버·사용 파일)</summary>

`ai.pleos.playground.` 아래 패키지 기준입니다. 생성자와 리스너 구현을 포함한 전체 목록입니다. `Brake`·`Fuel`·`Odometer`는 `android/vehicle-hardware` 어댑터에 있어 함께 컴파일되지만 진단 프로젝트에서만 호출합니다. SDK 라이브러리가 병합하는 권한 `ai.pleos.playground.service.vehicle.VEHICLE_BINDING`·`ai.pleos.playground.service.location.fused.FUSED_LOCATION_BINDING`은 앱이 직접 선언하지 않습니다.

| SDK | 클래스 | 사용한 멤버 | 사용 파일 |
|---|---|---|---|
| FusedLocation SDK | `location.fused.FusedLocation` | (생성자), `getLastKnownLocation`, `initialize`, `isSupported`, `registerFusedLocationCallback`, `release`, `unregisterFusedLocationCallback` | PleosClients |
| FusedLocation SDK | `location.fused.model.LocationData` | `getHeading`, `getLatitude`, `getLongitude`, `getTimestampMillis` | JourneyExecutionManager, LocationSampleLog(debug 빌드 진단 로그), TripLocationObservation, TripSignalNavigation, TripVehicleIntegration |
| NaviHelper SDK | `navi.constants.NaviErrorCode` | `name` | PleosClients |
| NaviHelper SDK | `navi.constants.NaviMode` | `ROUTE_GUIDING`, `hashCode`, `name` | PleosClients |
| NaviHelper SDK | `navi.constants.NavigationStatus` | `ROUTE_DRIVE`, `hashCode`, `name` | PleosClients |
| NaviHelper SDK | `navi.constants.TrafficCongestionType` | `name` | PleosClients |
| NaviHelper SDK | `navi.constants.WaypointIndex` | `FIRST`, `SECOND` | PleosClients, TripVehicleIntegration |
| NaviHelper SDK | `navi.data.CurrentLocationInfo` | `getHeading`, `getLatitude`, `getLongitude` | TripSignalNavigation, TripVehicleIntegration |
| NaviHelper SDK | `navi.data.DestinationInfo` | `getLatitude`, `getLongitude`, `getRemainDistance`, `getRemainTime` | PleosClients, TripSignalNavigation, TripVehicleIntegration |
| NaviHelper SDK | `navi.data.DrivingInfo` | `getDestination` | PleosClients |
| NaviHelper SDK | `navi.data.DrivingState` | `getDistance`, `getDuration` | PleosClients |
| NaviHelper SDK | `navi.data.RequestWaypointInfo` | (타입·생성자) | PleosClients |
| NaviHelper SDK | `navi.data.RouteInfo` | (타입·생성자) | PleosClients |
| NaviHelper SDK | `navi.data.RouteStateInfo` | `getNaviMode`, `getTrafficStatus`, `isRouting` | PleosClients |
| NaviHelper SDK | `navi.data.RouteWithWaypointsRequest` | (타입·생성자) | PleosClients |
| NaviHelper SDK | `navi.data.TrafficCongestionInfo` | `getDistance`, `getOffset`, `getTrafficCongestionType` | PleosClients |
| NaviHelper SDK | `navi.data.TrafficStatus` | `getCongestionItemList` | PleosClients |
| NaviHelper SDK | `navi.data.WaypointArrivedInfo` | `getIndex` | TripVehicleIntegration |
| NaviHelper SDK | `navi.data.WaypointInfo` | `getLatitude`, `getLongitude`, `getRemainDistance`, `getRemainTime` | PleosClients, TripVehicleIntegration |
| NaviHelper SDK | `navi.helper.NaviHelper` | (생성자), `addListener`, `getCurrentLocationInfo`, `getDestinationInfo`, `getRouteStateInfo`, `getWaypointInfo`, `initialize`, `release`, `removeListener`, `requestRoute`, `requestRouteWithWaypoints` | PleosClients, TripSignalNavigation, TripVehicleIntegration |
| Vehicle SDK | `vehicle.Vehicle` | (생성자), `getBrake`, `getFuel`, `getHVAC`, `getLight`, `getOdometer`, `getSeat`, `getWindow`, `initialize`, `release` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.Brake` | `checkBrakePedalStatusCapabilities`, `getCurrentBrakePedalStatus` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.Fuel` | `checkFuelPercentCapabilities`, `getFuelPercent` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.HVAC` | `checkHvacAcCapabilities`, `checkHvacAirCleanerCapabilities`, `checkHvacFanSpeedCapabilities`, `checkHvacPowerCapabilities`, `checkHvacTemperatureCapabilities`, `getHvacAcState`, `getHvacAirCleanerState`, `getHvacFanSpeed`, `getHvacPowerState`, `getHvacTemperature`, `setHvacAc`, `setHvacAirCleaner`, `setHvacFanSpeed`, `setHvacPower`, `setHvacTemperature` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.Light` | `checkAmbientLightSwitchCapabilities`, `checkCabinLightSwitchCapabilities`, `checkReadingLightSwitchCapabilities`, `getAmbientLightSwitch`, `getCabinLightSwitch`, `getReadingLightSwitch`, `setAmbientLightSwitch`, `setCabinLightSwitch`, `setReadingLightSwitch` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.Odometer` | `checkCurrentDistanceDrivenCapabilities`, `getCurrentDistanceDriven` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.Seat` | `checkSeatTemperatureCapabilities`, `checkSeatVentilationCapabilities`, `getHvacSeatTemperature`, `getHvacSeatVentilationState`, `setHvacSeatTemperature`, `setHvacSeatVentilation` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.Window` | `checkWindowPositionCapabilities`, `getCurrentWindowPosition`, `setWindowPosition` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.model.area.SeatArea` | `getValues` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.model.area.WindowArea` | (생성자), `getValues` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.model.capability.AccessType` | `NONE`, `READ`, `READ_WRITE`, `WRITE`, `ordinal`, `values` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.model.capability.AreaBounds` | `getMaxValue`, `getMinValue` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.model.capability.CapabilityConfig` | `getAccessType` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.api.model.capability.HvacTemperatureConfigArray` | `getIncrementCelsius`, `getMaxCelsius`, `getMinCelsius` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.constant.area.SeatValue` | `name` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.constant.area.WindowValue` | `name`, `valueOf` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.constant.control.LightSwitch` | `OFF`, `ON`, `name` | VehicleHardwareSdkAdapter |
| Vehicle SDK | `vehicle.constant.unit.TemperatureUnit` | `CELSIUS` | VehicleHardwareSdkAdapter |
| NaviHelper SDK | `navi.helper.listener.NaviHelperEventListener` (구현) | `onCurrentLocationInfo`, `onDestinationArrived`, `onDestinationChanged`, `onDestinationInfo`, `onDrivingInfo`, `onError`, `onNavigationStatus`, `onRouteCancelled`, `onRouteStarted`, `onRouteStateInfo`, `onRoutingCompleted`, `onTBTInfo`, `onWayPointArrived`, `onWayPointInfo` | PleosClients, TripSignalNavigation, TripVehicleIntegration |
| FusedLocation SDK | `location.fused.listener.FusedLocationListener` (구현) | `onChanged`, `onError` | PleosClients |

</details>


### 함께 사용한 Android Automotive 기능

| 기능 | API | 사용처 |
|---|---|---|
| 주행 제한 | `CarUxRestrictionsManager`(`getCurrentCarUxRestrictions`·`registerListener`), `CarUxRestrictions.isRequiresDistractionOptimization`·`getActiveRestrictions` | 주행 중 설정·조작 잠금(`PleosClients.kt`의 `DrivingPolicy`), 리모컨·함께 듣기 실행 조건(`ClimateCarSafety.kt`), 워키토키 조작 조건(`NativeVoiceCarSafety.kt`) |
| 기어(P/D) | `CarPropertyManager` `VehiclePropertyIds.GEAR_SELECTION`(`VehicleGear.GEAR_PARK`·`GEAR_DRIVE`), 권한 `android.car.permission.CAR_POWERTRAIN` | 정차 확인(`ClimateCarSafety.kt`. 리모컨 수신과 함께 듣기 `ListenTogetherHost.kt`가 이 결과를 사용), 여행 주행 상태(`TripVehicleIntegration.kt`의 `TripGearObserver`) |
| 차량 속도 | `CarPropertyManager` `VehiclePropertyIds.PERF_VEHICLE_SPEED`, 권한 `android.car.permission.CAR_SPEED` | 안전운전 점수의 급가속·급감속 계산(`CourseSpeedObserver.kt`) |
| 매니페스트 | `distractionOptimized`(주행 중 사용 화면 표시), `com.hmg.rotary.ROTARY_SUPPORTED=false`(로터리 컨트롤러 미지원 선언) | `AndroidManifest.xml` |

그 밖에 일반 Android 권한으로 인터넷, 위치(대략·정확), 마이크(워키토키), 포그라운드 서비스(위치·데이터 동기화)를 선언합니다.

## 주요 기능

| 기능 | 차량 화면 | iPhone |
|---|---|---|
| 여행방·코스 출발 | 여행 선택, 차량 내비로 출발, 일행 차 위치·진행 표시 | 여행 만들기, 친구 초대, 차·역할·픽업 지정 |
| 손들기 | 화장실·휴식 등 이유와 앞쪽 휴게소 후보로 정차 제안, 한 번 눌러 응답(주행 중 축소 화면). 다른 차가 모두 동의하면 각 차의 여행 경로에 다음 들를 곳으로 추가(길 안내를 누르면 차량 내비로 전달) | 같은 기능 |
| 워키토키 | 누르는 동안 최대 15초 녹음 → 일행 차에서 차례로 재생 | 같은 기능 |
| 동승자 리모컨 | 허용 범위 표시, 요청을 검사한 뒤 실행 | 운전자의 사전 허용, 같은 차 동승자의 공조·시트·창문·조명 조작 |
| 안전운전 대결 | 여행 전체 급가속·급감속 점수 비교 (점수·횟수만 공유) | 결과 확인 |
| 음악 | 일행이 공유한 음악 링크 목록, 정차 중 음악 앱으로 열기 | 음악 링크 추가, DJ·방장의 순서 변경 |
| 기록·코스 공유 | 기록·코스 조회 | 여행 기록(들른 곳), 기록을 코스로 다듬어 공개, 코스 저장·구독 |

## 저장소 구성

| 경로 | 내용 |
|---|---|
| `android/` | Kotlin·Jetpack Compose 차량 앱 (`app`), Vehicle SDK 연동 모듈 (`vehicle-hardware`), 차량 연결 인증 모듈 (`native-access`) |
| `ios/` | SwiftUI iPhone 앱 |
| `server/` | FastAPI·PostgreSQL 서버 (참고용) |
| `apk/` | 제출용 release APK |

## 구성요소와 권리

외부 라이브러리·글꼴·아이콘·음원의 출처와 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 있습니다. Pleos 공식 디자인 에셋에서 가져온 아이콘 10종 등 그 문서에 적은 외부 구성요소를 제외한 WegoH 소스 코드와 디자인의 저작권은 WegoH 개발팀에 있습니다. 이 저장소는 열람용으로 공개한 것이며 별도의 이용 허락(라이선스)을 부여하지 않습니다. 허락 없이 복제·수정·배포하거나 다른 서비스에 이용할 수 없습니다. 앱 아이콘·로고는 생성형 AI 도구로 제작했습니다.
