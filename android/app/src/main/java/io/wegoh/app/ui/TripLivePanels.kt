package io.wegoh.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import io.wegoh.app.TripRouteStop
import io.wegoh.app.nativeauth.TripCar
import io.wegoh.app.nativeauth.TripDetail
import io.wegoh.app.nativeauth.TripDisplay
import kotlinx.coroutines.delay

@Composable
internal fun currentTripDisplay(trip: TripDetail): TripDisplay? {
    val display=trip.display
    var now by remember(display) {mutableLongStateOf(android.os.SystemClock.elapsedRealtime())}
    LaunchedEffect(display) {
        while(display!=null && now<maxOf(display.expiresAtElapsedMillis,display.companionsExpiresAtElapsedMillis)) {delay(1000L);now=android.os.SystemClock.elapsedRealtime()}
    }
    return display?.takeIf {now<maxOf(it.expiresAtElapsedMillis,it.companionsExpiresAtElapsedMillis)}?.let {
        it.copy(music=it.music.takeIf {_->now<it.expiresAtElapsedMillis},
            timeline=it.timeline.takeIf {_->now<it.expiresAtElapsedMillis}.orEmpty(),
            visitCount=it.visitCount.takeIf {_->now<it.expiresAtElapsedMillis},metrics=it.metrics.takeIf {_->now<it.expiresAtElapsedMillis},
            companions=it.companions.takeIf {_->now<it.companionsExpiresAtElapsedMillis}.orEmpty())
    }
}

internal fun companionLabel(display: TripDisplay?,carId: String): String? {
    val position=display?.companions?.firstOrNull {it.carId==carId} ?: return null
    val distance=position.distanceMeters
    return if(distance==null)position.label else {
        val label=if(distance>=1000)String.format(java.util.Locale.KOREAN,"%.1fkm",distance/1000) else "${distance.toInt()}m"
        "약 $label ${if(position.direction=="ahead")"앞" else "뒤"}"
    }
}

/** 진행 바 위 상대 차 표시. position은 진행 바 장소 칸 기준 소수 위치(0=첫 장소). */
internal data class TripCompanionMarker(val label: String,val position: Float,val description: String)

private fun carName(car: TripCar)=car.ordinal?.let {"${it}호차"} ?: car.name

/**
 * 공유 코스를 함께 달리는 다른 차를 내 진행 바에 놓는다. 서버 routeStatus.progress의 target과
 * 직전 공유 코스 장소 사이 비율만 쓰며, 내 진행 바에 없는 장소(합류 전·드랍)는 그리지 않는다.
 */
internal fun tripCompanionMarkers(trip: TripDetail,stops: List<TripRouteStop>): List<TripCompanionMarker> =
    trip.cars.filter {it.id!=trip.myCar?.id}.mapNotNull {car->
        val progress=car.routeStatus?.takeIf {it.phase=="shared"}?.progress ?: return@mapNotNull null
        val fraction=progress.legFraction ?: return@mapNotNull null
        val target=stops.indexOfFirst {it.item.key==progress.target.key}
        val previous=(0 until maxOf(target,0)).lastOrNull {stops[it].item.type=="course"} ?: return@mapNotNull null
        TripCompanionMarker(car.ordinal?.toString() ?: car.name.take(1),
            previous+(target-previous)*fraction.toFloat(),"${carName(car)} ${stops[target].name} 가는 중")
    }

private fun approximateDistance(meters: Int): String {
    if(meters<1000)return "직선 1km 이내"
    val rounded=Math.round(meters/500.0)/2.0
    val km=if(rounded%1.0==0.0)"${rounded.toInt()}" else String.format(java.util.Locale.KOREAN,"%.1f",rounded)
    return "직선 약 ${km}km"
}

/**
 * 진행 바 아래 한 줄. 서버가 보낸 상대 차의 구간과 공유 경로 기준 남은 거리(0.5km 단위)를 우선 쓰고,
 * 그 값이 없으면 내 경로 기준 앞/뒤 거리(display.companions)로 보여 준다.
 * 공개된 여행 전체 안전운전 점수가 있으면 숫자 하나만 덧붙인다(순위·승패 없음).
 */
internal fun companionProgressLabels(display: TripDisplay?,car: TripCar,score: Int?=null): List<String> {
    val name=carName(car)
    fun fields(status: String)=listOfNotNull(name,status,score?.let {"${it}점"})
    val status=car.routeStatus
    when(status?.phase) {
        "waiting"->return fields("합류 지점 도착")
        "drop"->return fields("내리는 곳으로 이동 중")
        "done"->return fields("주행 완료")
    }
    status?.progress?.let {progress->
        return fields("${if(status.phase=="pickup")"합류 지점까지" else "다음 장소까지"} ${approximateDistance(progress.remainingMeters)}")
    }
    val position=display?.companions?.firstOrNull {it.carId==car.id}
    val distance=position?.distanceMeters
    val place=when {
        distance==null->"위치 없음"
        distance<1000->"1km 이내"
        else->{
            val rounded=Math.round(distance/500.0)/2.0
            val km=if(rounded%1.0==0.0)"${rounded.toInt()}" else String.format(java.util.Locale.KOREAN,"%.1f",rounded)
            "약 ${km}km ${if(position?.direction=="ahead")"앞" else "뒤"}"
        }
    }
    return fields(place)
}

/** [scores]는 [tripCompanionScores]로 만든 다른 차의 여행 전체 점수다. 점수 패널이 따로 있는 정차 화면은 넘기지 않는다. */
@Composable
internal fun TripCompanionProgress(trip: TripDetail,display: TripDisplay?,scores: Map<String,Int> = emptyMap()) {
    val others=trip.cars.filter {it.id!=trip.myCar?.id}
    if(others.isEmpty())return
    Column(Modifier.fillMaxWidth().semantics(mergeDescendants=true) {
        contentDescription=if(scores.isEmpty())"함께 가는 차 위치" else "함께 가는 차 위치와 안전운전 점수"},
        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
        others.forEach {car->CarMetadata(companionProgressLabels(display,car,scores[car.id]))}
    }
}
