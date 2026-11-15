package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import io.wegoh.app.nativeauth.TripDetail

@Composable
internal fun TripFinishDialog(incomplete: List<String>,enabled: Boolean,busy: Boolean,onDismiss: ()->Unit,onConfirm: ()->Unit) {
    CarPopup("여행을 완료할까요?",onDismiss,
        description="모든 차의 주행을 끝내고 기록을 저장해요. 완료한 여행은 다시 시작할 수 없어요.",
        body=if(incomplete.isEmpty())null else {{TripPopupTargets("경로가 남은 차",incomplete)}},
        actions={
            CarButton("여행 완료",onConfirm,Modifier.weight(1f),variant=CarButtonStyle.DANGER,enabled=enabled,busy=busy)
            CarButton("취소",onDismiss,Modifier.weight(1f))
        })
}

/** 팝업이 영향을 주는 대상 묶음. 라벨 아래 이름을 굵게 강조해 설명 문장과 나눈다. */
@Composable
internal fun TripPopupTargets(label: String,names: List<String>) {
    CarCard(padding=PaddingValues(CarTokens.Gap),radius=CarTokens.RadiusCard) {
        TripText(label,secondary=true,maxLines=2)
        names.forEach {TripText(it,style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=3)}
    }
}

/** 공유 경로를 마치면 생기는 일. 서버는 모든 차가 주행을 마치면 여행을 자동으로 끝낸다. */
internal enum class TripCourseCompletion { DROP_NEXT, CAR_DONE, TRIP_ENDS }

internal fun tripCourseCompletion(trip: TripDetail): TripCourseCompletion {
    val car=trip.myCar
    val plan=car?.routePlan
    if(plan==null || plan.segments.firstOrNull {it.segment=="drop"}?.items.orEmpty().isNotEmpty())return TripCourseCompletion.DROP_NEXT
    val othersDone=trip.cars.filter {it.id!=car.id}.all {(it.routeStatus?.phase ?: it.routePlan?.phase)=="done"}
    return if(othersDone)TripCourseCompletion.TRIP_ENDS else TripCourseCompletion.CAR_DONE
}

/** "경로 마치기"는 되돌릴 수 없어 운전자가 결과를 확인한 뒤에만 보낸다. */
@Composable
internal fun TripCompleteCourseButton(trip: TripDetail,enabled: Boolean,busy: Boolean,onConfirm: ()->Unit) {
    var confirming by rememberSaveable(trip.id) {mutableStateOf(false)}
    CarButton("경로 마치기",{confirming=true},Modifier.fillMaxWidth(),variant=CarButtonStyle.INK_OUTLINE,enabled=enabled)
    if(confirming && enabled) {
        val outcome=tripCourseCompletion(trip)
        CarPopup(if(outcome==TripCourseCompletion.TRIP_ENDS)"경로를 마치고 여행을 끝낼까요?" else "공유 경로를 마칠까요?",{confirming=false},
            description=when(outcome) {
                TripCourseCompletion.DROP_NEXT->"마치면 내리는 곳으로 안내해요."
                TripCourseCompletion.CAR_DONE->"우리 차는 내리는 곳이 없어 주행이 끝나요."
                TripCourseCompletion.TRIP_ENDS->"마지막 차라서 마치면 여행이 끝나요. 끝난 여행은 다시 시작할 수 없어요."
            },
            actions={
                CarButton("경로 마치기",{confirming=false;onConfirm()},Modifier.weight(1f),
                    variant=if(outcome==TripCourseCompletion.TRIP_ENDS)CarButtonStyle.DANGER else CarButtonStyle.FILLED,busy=busy)
                CarButton("취소",{confirming=false},Modifier.weight(1f))
            })
    }
}
