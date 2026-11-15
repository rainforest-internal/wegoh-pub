@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import io.wegoh.app.*
import io.wegoh.app.nativeauth.*

@Composable
internal fun TripPlanPage(trip: TripDetail,enabled: Boolean,onBack: ()->Unit,actions: TripUiActions,
    onEdit: (() ->Unit)?,onInvite: ()->Unit,onCreateCar: ()->Unit,onManageCar: ()->Unit,courses: AccountCourseState,onCoursesLoad: ()->Unit,
    roomTabs: @Composable ()->Unit = {},gear: TripGear?=null,onPickupOrder: (() ->Unit)?=null,onGroups: ()->Unit={},onMembers: ()->Unit=onInvite,onRoute: ()->Unit={}) {
    var showPhone by remember(trip.id) {mutableStateOf(false)}
    val overview=tripPlanOverview(trip)
    val p=LocalCarPalette.current
    val car=trip.myCar
    val stops=tripMyStops(trip)
    val checks=tripPreparationChecks(trip)
    val next=checks.indexOfFirst {!it.done}
    val details=listOf(
        when {overview.pending>0->"초대 대기 ${overview.pending}명";checks[0].notApplicable->"나만 참여";else->"준비 ${overview.ready}/${trip.members.size}명"},
        car?.numberedName ?: "iPhone에서 탈 차를 선택해 주세요",
        if(stops.driving)"" else "타는 곳: ${stops.label("pickup")}\n내리는 곳: ${stops.label("drop")}",
        "저장 경로 ${trip.courses.orEmpty().size}개")
    TripPreparationFrame(trip,enabled,TripPlanTab.OVERVIEW,onBack,actions,gear,{tab->
        when(tab) {TripPlanTab.OVERVIEW->Unit;TripPlanTab.GROUPS->onGroups();TripPlanTab.MEMBERS->onMembers();TripPlanTab.ROUTE->onRoute()}
    }) {
        TripPreparationPanels(left={
            CarCard(tone=CarCardTone.OUTLINED) {
                Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    TripText("여행 준비",Modifier.weight(1f),style=CarType.Section,maxLines=2)
                    TripText("${checks.count {it.done}}/${checks.size}",style=CarType.Label,color=p.accent)
                }
                checks.forEachIndexed {index,(label,done,notApplicable)->
                    if(index>0)TripDivider()
                    Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                        Box(Modifier.size(CarTokens.Touch).background(if(done)p.accent else p.background,CircleShape)
                            .border(CarTokens.BorderWidth,if(done || index==next)p.accent else p.divider,CircleShape),contentAlignment=Alignment.Center) {
                            if(done)CarIcon(CarSymbol.Check,color=p.onInk)
                            else TripText((index+1).toString(),style=CarType.Section,color=if(index==next)p.accent else p.secondary)
                        }
                        Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                            TripText(label,style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=2)
                            if(details[index].isNotEmpty())TripText(details[index],style=CarType.Label,secondary=true,maxLines=3)
                        }
                        if(notApplicable)CarStatusPill("해당 없음",kind=CarStatusTone.NEUTRAL)
                        else CarButton(when(index) {0->"일행";1->"차";2->"설정 안내";else->"경로"},{
                            when(index) {0->onMembers();1->onGroups();2->{showPhone=true};else->onRoute()}
                        },enabled=enabled,variant=if(index==next)CarButtonStyle.SOFT else CarButtonStyle.OUTLINE,
                            accessibility=if(index==2)"타고 내릴 곳 설정 안내" else "$label 보기")
                    }
                }
            }
            CarPhoneHandoff("trip-info")
            if(trip.description.isNotBlank())CarCard {TripText(trip.description,secondary=true,maxLines=3)}
        },right={
            if(car!=null)PreparationCarCard(trip,car,enabled,actions,onManageCar,onPickupOrder)
            else CarCard(tone=CarCardTone.DASHED) {
                TripText("탈 차 미정",style=CarType.Section,maxLines=3)
                TripText("iPhone의 여행에서 탈 차를 선택해 주세요",secondary=true,maxLines=3)
                CarButton("차와 일행",onGroups,enabled=enabled)
            }
            CarCard(tone=CarCardTone.OUTLINED) {
                Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                    TripText("이동 경로",Modifier.weight(1f),style=CarType.Section)
                    CarButton("자세히",onPickupOrder.takeIf {car?.isMine==true} ?: onRoute,enabled=enabled)
                }
                if(trip.courses.orEmpty().isEmpty())TripText("추가한 경로가 없어요",secondary=true,maxLines=3)
                else TripSegmentBand(trip,null)
            }
        })
    }
    if(showPhone)CarPopup("타고 내릴 곳",{showPhone=false},body={CarPhoneHandoff("stops")},actions={CarButton("닫기",{showPhone=false})})
}

@Composable
private fun PreparationCarCard(trip: TripDetail,car: TripCar,enabled: Boolean,actions: TripUiActions,onManage: ()->Unit,onPickupOrder: (() ->Unit)?) {
    CarCard(tone=if(car.isMine || car.iRide)CarCardTone.SELECTED else CarCardTone.OUTLINED) {
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
            TripText(car.numberedName,Modifier.weight(1f),style=CarType.Section,maxLines=2)
            TripCarRolePill(car)
        }
        CarMetadata(listOf("운전자 ${car.driverName}","탑승 ${car.passengers.size+1}/${car.seats+1}명",
            if(car.seats>car.passengers.size)"빈자리 ${car.seats-car.passengers.size}석" else "빈자리 없음"))
        FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
            CarAvatar(car.driverName,CarAvatarTone.INK)
            car.passengers.forEach {person->CarAvatar(person.name)}
        }
        TripCarRoles(trip,car)
        if(car.isMine)TripText(tripRemotePolicyLabel(car.remotePolicy),style=CarType.Label,secondary=true,maxLines=3)
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
            if(car.isMine)CarButton("차와 일행",onManage,Modifier.weight(1f),enabled=enabled)
            if((car.isMine || car.iRide) && onPickupOrder!=null)
                CarButton("탑승 순서",onPickupOrder,Modifier.weight(1f),enabled=enabled)
        }
    }
}
