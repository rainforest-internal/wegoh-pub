package io.wegoh.app.ui

import androidx.compose.runtime.Composable

/**
 * Every "do this on the iPhone" hint in the car app, in one form: 'iPhone 앱의 탭 → 화면에서 ~해요'.
 * Paths name the iPhone tab bar (여행·경로·음악·친구·설정) and, when needed, the screen inside it.
 */
internal fun carPhoneHint(view: String): String = when(view) {
    "create"->"iPhone 앱의 경로에서 경로를 만들어요"
    "course-edit"->"iPhone 앱의 경로에서 경로를 만들고 고쳐요"
    "course-feed"->"iPhone 앱의 경로에서 경로를 만들고 구독을 관리해요"
    "course-save"->"iPhone 앱의 경로에서 경로를 만들고 저장해요"
    "profile"->"iPhone 앱의 설정 → 프로필에서 고쳐요"
    "trip-new"->"iPhone 앱의 여행에서 새 여행을 만들어요"
    "trip-info"->"iPhone 앱의 여행에서 이름과 날짜를 바꿔요"
    "trip-route"->"iPhone 앱의 여행에서 경로를 고쳐요"
    "members"->"iPhone 앱의 여행에서 일행을 초대하거나 내보내요"
    "music"->"iPhone 앱의 음악에서 플레이리스트를 추가해요"
    "music-link"->"iPhone 앱의 음악에서 음악 링크를 추가해요"
    "history"->"iPhone 앱의 여행에서 기록을 확인해요"
    "together"->"iPhone 앱의 친구에서 친구를 추가해요"
    "pickup"->"iPhone 앱의 여행에서 타는 곳을 정해요"
    "drop"->"iPhone 앱의 여행에서 내리는 곳을 정해요"
    "stops"->"iPhone 앱의 여행에서 타고 내릴 곳을 정해요"
    "car-and-stops"->"iPhone 앱의 여행에서 탈 차와 타고 내릴 곳을 정해요"
    "passenger-stops"->"iPhone 앱의 여행에서 동승자가 타고 내릴 곳을 정해요"
    "remote"->"iPhone 앱의 여행 → 동승자 리모컨에서 허용 기능을 바꿔요"
    "vehicle"->"iPhone 앱의 설정 → 연결 차량 설정에서 바꿔요"
    "vehicle-link"->"iPhone 앱의 설정 → 연결 차량 설정에서 이 차를 연결해요"
    "vehicle-permission"->"iPhone 앱의 설정 → 연결 차량 설정에서 경로 보기 권한을 확인해요"
    "caution"->"iPhone 앱에서 주의 기록을 고치거나 지워요"
    else->"iPhone 앱의 여행에서 초대하거나 수정해요"
}

@Composable
fun CarPhoneHandoff(view: String) {CarPhoneHint(carPhoneHint(view))}
