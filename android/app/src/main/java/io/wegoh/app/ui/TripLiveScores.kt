package io.wegoh.app.ui

import io.wegoh.app.TripsPageState
import io.wegoh.app.nativeauth.TripDetail

internal data class TripLiveScoreRow(val carId: String,val name: String,val own: Boolean,val score: Int?,val status: String)

internal fun tripLiveScoreRows(trip: TripDetail,state: TripsPageState): List<TripLiveScoreRow> {
    val versus=state.drivingVersus?.takeIf {it.scope=="trip"}
    val current=state.isCurrent && state.detail?.id==trip.id
    return trip.cars.sortedBy {if(it.id==trip.myCar?.id)0 else 1}.map {car->
        val reported=versus?.cars?.firstOrNull {it.carId==car.id}
        val blocked=reported!=null && (!reported.participating || reported.state !in setOf("pending","ready"))
        val local=state.liveCourseScore?.takeIf {
            current && car.isMine && state.liveCourseId=="trip-total-v1" && !blocked && it.score!=null
        }
        val score=if(current && !blocked)local?.score ?: reported?.totalScore else null
        val status=when {
            !current->"연결 확인 중"
            reported?.participating==false->"참가 종료"
            blocked->versusCarStateLabel(requireNotNull(reported).state,versus?.reason)
            score!=null->if(local?.completed==true || local==null && reported?.final==true)"최종 점수" else "현재 점수"
            state.drivingVersusLoading->"불러오는 중"
            state.drivingVersusNotice!=null->"점수 확인 필요"
            state.drivingVersus!=null && versus==null->"여행 점수 확인 필요"
            else->"측정 대기"
        }
        TripLiveScoreRow(car.id,car.numberedName,car.id==trip.myCar?.id,score,status)
    }
}

/** 주행(D) 화면의 함께 가는 차 줄에 붙일 다른 차의 여행 전체 점수. 정차 화면 점수 행과 같은 공개·숨김 규칙을 따른다. */
internal fun tripCompanionScores(trip: TripDetail,state: TripsPageState): Map<String,Int> =
    tripLiveScoreRows(trip,state).filter {!it.own}.mapNotNull {row->row.score?.let {row.carId to it}}.toMap()
