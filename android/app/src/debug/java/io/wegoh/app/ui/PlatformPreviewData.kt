package io.wegoh.app.ui

/** Fictional design fixtures. No accounts, visits, locations or actual music rights. */
object PlatformPreviewData {
    const val available=true
    val packs=listOf(
        PreviewPack("간월호 한 바퀴","사용자A",listOf("간월호","간월암"),"약 40분","호수",listOf(20,20)),
        PreviewPack("서해안 해안도로 코스","사용자A",listOf("간월암","꽃지해수욕장","대천해수욕장"),"약 80분","해안",listOf(25,35,20)),
        PreviewPack("보령 해안도로","사용자B",listOf("대천항","무창포해수욕장"),"약 50분","해안",listOf(25,25)))
    val friends=listOf(PreviewFriend("사용자C","1호차 · 사용자A의 차","다음 장소로",1),PreviewFriend("사용자D","1호차 · 사용자A의 차","합류 준비",0),PreviewFriend("사용자E","2호차 · 사용자B의 차","첫 장소 도착",1))
}
