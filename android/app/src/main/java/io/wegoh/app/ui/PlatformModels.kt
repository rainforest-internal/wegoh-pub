package io.wegoh.app.ui

data class PreviewPack(val title: String,val creator: String,val places: List<String>,val duration: String,val theme: String,val legMinutes: List<Int> = listOf(25,35,20))
data class PreviewFriend(val name: String,val car: String,val status: String,val completed: Int)

object PlatformRoutes {
    val primary=listOf("trips","car","courses","music","profile")
    val titles=linkedMapOf(
        "trips" to "여행","courses" to "경로",
        "discover" to "발견","pack" to "경로 상세","creator" to "창작자","rooms" to "여행방",
        "room-create" to "방 만들기","room-join" to "초대로 참여","room" to "함께 달리기","room-plan" to "방문 계획",
        "sharing" to "공유 설정","messages" to "상태 전하기","music" to "음악","room-ended" to "여행방 종료",
        "car" to "리모컨","friends" to "친구","friend" to "친구 프로필","pair" to "차량 연결","create" to "만들기","editor" to "경로 편집",
        "place" to "장소 고르기","event" to "도착 이벤트","publish" to "게시 확인","remix" to "재창작",
        "results" to "여행 기록","result" to "여행 결과","result-save" to "결과 저장","profile" to "프로필",
        "voice" to "안내 프로필","safety" to "운전 습관","nearby" to "주변 소식","settings" to "연결과 개인정보",
        "states" to "연결 상태","journeys" to "경로",
        "location-map" to "함께 있는 곳","music-picker" to "음악 고르기","challenge" to "출발 전 약속","challenge-result" to "함께한 결과","nearby-detail" to "방문지 정보","nearby-vote" to "함께 고르기","operations" to "콘텐츠 관리","pack-manage" to "게시 상태","community" to "함께 남긴 길","group-call" to "음성 대화","voice-create" to "내 안내 만들기","recording-import" to "기록에서 만들기","music-sync" to "함께 듣기","cleanliness" to "시설 후기")
    fun symbol(route: String)=when(route){
        "trips"->CarSymbol.Group;"discover"->CarSymbol.Discover;"rooms","room"->CarSymbol.Group;"friends","friend"->CarSymbol.People
        "create","editor"->CarSymbol.Edit;"profile"->CarSymbol.Person;"music"->CarSymbol.Music
        "car"->CarSymbol.Car;"results","result"->CarSymbol.Bookmark;"settings","sharing"->CarSymbol.Settings
        else->CarSymbol.Route
    }
}
