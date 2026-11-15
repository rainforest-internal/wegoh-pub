package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import io.wegoh.app.nativeauth.TripDrivingVersus
import java.util.Locale

@Composable
internal fun TripDrivingVersusSummary(versus: TripDrivingVersus?,loading: Boolean=false,
    notice: String?=null,onRefresh: (() ->Unit)?=null,compact: Boolean=false) {
    CarCard(tone=if(compact)CarCardTone.SOFT else CarCardTone.INK,radius=CarTokens.RadiusHero) {
        TripText("안전운전 대결",style=CarType.Section,maxLines=2)
        CarStatusPill(when {
            loading->"불러오는 중"
            versus?.state=="pending"->"집계 중"
            versus?.state=="final"->"결과 확정"
            versus?.state=="unavailable"->"비교 불가"
            else->"결과 확인"
        },kind=if(compact)CarStatusTone.SOFT else CarStatusTone.ON_INK)
        if(versus==null) {
            if(!loading)TripText(notice ?: "대결 결과를 불러오지 못했어요",secondary=true,maxLines=CarMessageLines)
        } else {
            if(versus.state=="final") {
                val names=versus.cars.filter {it.carId in versus.winnerCarIds}.map {it.name}
                if(names.isNotEmpty())CarMetadata(listOf(if(versus.tied)"공동 1위" else "1위")+names,style=CarType.Title,secondary=false)
            }
            TripText(versusReasonLabel(versus),secondary=true,maxLines=3)
            versus.cars.forEach {car->
                Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    TripDivider()
                    TripText(car.name,style=CarType.Section,maxLines=2)
                    val score=car.totalScore?.toDouble().takeIf {car.state in setOf("pending","ready")}
                    if(score!=null) {
                        TripText("${versusScoreLabel(score)}점",style=if(compact)CarType.Title else CarType.Hero)
                        TripText(if(car.final)"여행 최종 점수" else "여행 누적 점수",secondary=true,maxLines=2)
                    } else TripText(versusCarStateLabel(car.state,versus.reason),style=CarType.Label,secondary=true,maxLines=3)
                }
            }
            if(notice!=null)TripText(notice,secondary=true,maxLines=CarMessageLines)
        }
        if(onRefresh!=null)CarButton("대결 새로고침",onRefresh,Modifier.fillMaxWidth(),enabled=!loading,
            icon=CarSymbol.Refresh,variant=if(compact)CarButtonStyle.SOFT else CarButtonStyle.ON_INK)
    }
}

private fun versusScoreLabel(score: Double): String = String.format(Locale.KOREAN,"%.2f",score).trimEnd('0').trimEnd('.')

internal fun versusCarStateLabel(state: String,reason: String?=null): String = when(state) {
    "pending"->"점수 전송 대기"
    "unavailable"->"측정 불가"
    "withdrawn"->"참가 종료"
    "sharing-unavailable"->when(reason) {
        "course-unavailable"->"경로 공개 확인 필요"
        "report-authorization-changed","report-device-changed"->"점수 전송 확인 필요"
        "vehicle-connection-required"->"차량 연결 확인 필요"
        "participant-unavailable"->"여행 참가 상태 확인 필요"
        "vehicle-authority-unavailable"->"차량 연결과 참가 상태 확인 필요"
        else->"공유 상태 확인 필요"
    }
    else->"측정 결과 없음"
}

internal fun versusReasonLabel(versus: TripDrivingVersus): String = when(versus.reason) {
    "trip-reports-pending","final-reports-pending"->"모든 차의 주행과 점수 전송이 끝나면 확정돼요"
    "insufficient-cars"->"참가 차량이 두 대 이상이어야 비교할 수 있어요"
    "insufficient-measurements"->"점수가 있는 차가 두 대 이상이어야 비교할 수 있어요"
    "shared-incomplete"->"공유 경로를 마치지 않아 비교할 수 없어요"
    "sharing-unavailable"->"공개할 수 없는 점수가 있어 비교할 수 없어요"
    "course-unavailable"->"경로를 확인할 수 없어 점수를 숨겼어요. 경로 공개 상태를 확인해 주세요"
    "report-authorization-changed"->"공유 설정이 바뀌어 점수를 숨겼어요. 차량에서 공유 설정과 점수 전송을 확인해 주세요"
    "vehicle-connection-required"->"점수를 보낸 차량의 연결과 로그인을 확인해 주세요"
    "report-device-changed"->"차량 연결이 바뀌었어요. 현재 차량에서 점수 전송을 확인해 주세요"
    "participant-unavailable"->"참가 상태가 바뀐 차가 있어 비교할 수 없어요"
    "vehicle-authority-unavailable"->"차량 연결과 여행 참가 상태를 확인해 주세요"
    "contract-unavailable"->"안전운전 대결 기록이 없어요"
    else->if(versus.state=="final")"여행 전체의 점수를 비교한 결과예요"
        else "대결 결과를 확인할 수 없어요"
}
