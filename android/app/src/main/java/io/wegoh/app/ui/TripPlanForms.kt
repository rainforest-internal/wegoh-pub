@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.text.font.FontWeight
import io.wegoh.app.*
import io.wegoh.app.nativeauth.*

@Composable
internal fun TripInvitePage(trip: TripDetail,state: TripsPageState,enabled: Boolean,actions: TripUiActions,onBack: ()->Unit,
    gear: TripGear=TripGear.UNKNOWN,onSelectTab: (TripPlanTab)->Unit={}) {
    val interactive=enabled && gear==TripGear.PARK
    LaunchedEffect(trip.id,trip.canInvite) {if(interactive && trip.canInvite)actions.inviteFriends()}
    TripPreparationFrame(trip,interactive,TripPlanTab.MEMBERS,onBack,actions,gear,onSelectTab) {
        TripPreparationPanels(left={
            CarCard(tone=CarCardTone.OUTLINED) {
                TripText("일행 ${trip.members.size}명",style=CarType.Section,maxLines=2)
                TripText("준비 ${trip.members.count {it.readiness==TripReadiness.READY}}/${trip.members.size}명",style=CarType.Label,secondary=true)
                trip.members.forEachIndexed {index,person->
                    if(index>0)TripDivider()
                    val carIndex=trip.cars.indexOfFirst {it.driverId==person.id || it.passengers.any {rider->rider.id==person.id}}
                    val car=trip.cars.getOrNull(carIndex)
                    val seat=car?.let {(it.ordinal?.let {number->"${number}호차"} ?: it.name)+if(it.driverId==person.id)" 운전" else " 탑승"}
                    PreparationPersonRow(person.name,listOfNotNull("만든 사람".takeIf {person.isOwner},seat,
                        tripReadinessDetail(person.readiness,person.isMe)).joinToString("\n"),driver=car?.driverId==person.id) {
                        TripMemberRole(person)
                        person.readiness?.let {CarStatusPill(it.label,kind=when(it) {
                            TripReadiness.READY->CarStatusTone.SOFT
                            TripReadiness.INVITED->CarStatusTone.PENDING
                            else->CarStatusTone.NEUTRAL
                        })}
                    }
                }
            }
        },right={
            CarCard(tone=CarCardTone.OUTLINED) {
                TripText("친구 초대",style=CarType.Section,maxLines=3)
                if(trip.canInvite)state.inviteFriends?.let {TripText("친구 ${it.size}명",secondary=true)}
                if(!trip.canInvite)CarInfoHint("초대 권한이 없어요")
                else {
                    if(state.inviteFriends==null) {
                        TripText(if(state.busy)"친구 불러오는 중" else "친구를 불러오지 못했어요",secondary=true,maxLines=2)
                        if(!state.busy)CarButton("다시 시도",actions.inviteFriends,Modifier.fillMaxWidth(),enabled=interactive)
                    }
                    state.inviteFriends.orEmpty().forEachIndexed {index,friend->
                        if(index>0)TripDivider()
                        val status=trip.members.firstOrNull {it.id==friend.id}?.let {if(it.accepted)"accepted" else "pending"} ?: friend.state
                        PreparationPersonRow(friend.name,when(status) {
                            "accepted"->if(friend.hasVehicle==true)"차량 연결됨" else ""
                            "pending"->""
                            else->if(friend.hasVehicle==true)"차량 연결됨" else ""
                        }) {
                            when(status) {
                                "accepted"->CarStatusPill("참여 중",kind=CarStatusTone.NEUTRAL)
                                "pending"->{
                                    if(trip.isOwner)CarButton("초대 취소",{actions.perform(TripAction.RemoveMember(friend.id)) {}},
                                        enabled=interactive && !state.busy,accessibility="${friend.name} 초대 취소")
                                    else CarStatusPill("초대 대기",kind=CarStatusTone.PENDING)
                                }
                                else->CarButton("초대",{actions.perform(TripAction.Invite(friend.id)) {}},variant=CarButtonStyle.SOFT,
                                    enabled=interactive && !state.busy && trip.members.size<20,accessibility="${friend.name} 초대")
                            }
                        }
                    }
                    if(state.inviteFriends?.isEmpty()==true)TripText("초대할 친구가 없어요",secondary=true,maxLines=2)
                }
            }
            CarPhoneHandoff("members")
        })
    }
}

internal fun tripReadinessDetail(readiness: TripReadiness?,isMe: Boolean): String? = when(readiness) {
    TripReadiness.INVITED->"초대 수락 전"
    TripReadiness.NEEDS_CAR->if(isMe)"탈 차를 선택해 주세요" else "탈 차 미정"
    TripReadiness.NEEDS_VEHICLE->if(isMe)"차량을 연결해 주세요" else "운전할 차 연결 전"
    TripReadiness.NEEDS_PLACES->if(isMe)"iPhone에서 타고 내릴 곳을 정해 주세요" else "타고 내릴 곳 미정"
    TripReadiness.READY,null->null
}

@Composable
internal fun TripPhoneHandoff(route: String="home") {CarPhoneHint(carPhoneHint(route))}

private fun validPreparationName(value: String,max: Int)=value.trim().let {
    it.codePointCount(0,it.length) in 1..max && it.none {character->character.isISOControl()}
}

@Composable
internal fun TripCarCreatePage(trip: TripDetail,car: TripCar?,enabled: Boolean,actions: TripUiActions,onBack: ()->Unit,
    gear: TripGear=TripGear.UNKNOWN) {
    var name by rememberSaveable(trip.id,car?.id) {mutableStateOf(car?.name ?: "${trip.me?.name.orEmpty()} 차")}
    var seats by rememberSaveable(trip.id,car?.id) {mutableStateOf(car?.seats ?: 4)}
    var delete by remember(trip.id,car?.id) {mutableStateOf(false)}
    val interactive=enabled && gear==TripGear.PARK
    val p=LocalCarPalette.current
    val action=if(car==null)TripAction.CreateCar(name,seats) else TripAction.EditCar(car.id,name,seats)
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading(if(car==null)"여행에 차 추가" else "차 설정",onBack=onBack) {
            if(gear==TripGear.PARK || gear==TripGear.DRIVE)CarGearBadge(gear)
        }
        Box(Modifier.weight(1f)) {TripPreparationPanels(left={
            CarCard(tone=CarCardTone.SOFT) {
                Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                    CarIcon(CarSymbol.Car,color=p.accent)
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        TripText("연결된 차량",style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=2)
                        TripText("운전자 ${trip.me?.name.orEmpty()}",secondary=true,maxLines=2)
                    }
                }
            }
            TripField("차 이름",name,{name=it},20,interactive)
            TripText("동승자 좌석 수",style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=2)
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                CarButton("−",{seats--},Modifier.size(CarTokens.StepperSize),enabled=interactive && seats>maxOf(1,car?.passengers?.size ?: 0),
                    textStyle=CarType.Hero,accessibility="좌석 수 줄이기")
                Box(Modifier.weight(1f).height(CarTokens.StepperSize).background(p.low,RoundedCornerShape(CarTokens.RadiusCard)),contentAlignment=Alignment.Center) {
                    TripText("${seats}석",style=CarType.Hero)
                }
                CarButton("+",{seats++},Modifier.size(CarTokens.StepperSize),enabled=interactive && seats<8,
                    textStyle=CarType.Hero,accessibility="좌석 수 늘리기")
            }
            if(car==null && trip.myCar!=null)TripText("차를 추가하면 기존 탑승은 취소돼요",secondary=true,maxLines=3)
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                CarButton("취소",onBack,Modifier.weight(1f))
                CarButton(if(car==null)"차 추가" else "저장",{actions.perform(action,onBack)},Modifier.weight(1f),primary=true,
                    enabled=interactive && validPreparationName(name,20) && canPerformTripAction(trip,action))
            }
            if(car!=null)CarButton("차 삭제",{delete=true},Modifier.fillMaxWidth(),enabled=interactive && car.isMine,variant=CarButtonStyle.DANGER)
        },right={
            CarCard(tone=CarCardTone.OUTLINED) {
                TripText("일행에게 보이는 정보",style=CarType.Section,maxLines=2)
                TripPreparationGroupCard(trip,(car ?: TripCar("preview",name,trip.me?.id.orEmpty(),trip.me?.name.orEmpty(),seats,true,false,emptyList()))
                    .copy(name=name.trim().ifEmpty {"이름 없음"},seats=seats),false,TripUiActions(),{},showActions=false)
            }
            CarPhoneHandoff("remote")
        })}
    }
    if(delete && car!=null)CarPopup("여행에서 차를 삭제할까요?",{delete=false},body={
        TripText("동승자는 탈 차를 다시 골라야 해요",maxLines=3)
    },actions={
        CarButton("차 삭제",{actions.perform(TripAction.DeleteCar(car.id),onBack)},Modifier.weight(1f),enabled=interactive && car.isMine,variant=CarButtonStyle.DANGER)
        CarButton("취소",{delete=false},Modifier.weight(1f))
    })
}

@Composable
internal fun TripCarManagePage(trip: TripDetail,enabled: Boolean,actions: TripUiActions,onBack: ()->Unit,onSettings: ()->Unit,
    onDeparture: ()->Unit,parked: Boolean,gear: TripGear=TripGear.UNKNOWN,onRemote: (()->Unit)?=null) {
    val car=trip.myCar?.takeIf {it.isMine}
    if(car==null) {CarEmptyState("여행에 추가한 차가 없어요",action={CarButton("뒤로",onBack)});return}
    val interactive=enabled && parked
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading(car.numberedName,onBack=onBack) {
            TripCarRolePill(car)
            if(gear==TripGear.PARK || gear==TripGear.DRIVE)CarGearBadge(gear)
            CarButton("차 설정",onSettings,enabled=interactive)
        }
        CarMetadata(listOf("탑승 ${car.passengers.size+1}/${car.seats+1}명","빈자리 ${car.seats-car.passengers.size}석"))
        Box(Modifier.weight(1f)) {TripPreparationPanels(left={
            TripText("운전자",style=CarType.Label,secondary=true)
            CarCard {
                PreparationPersonRow(car.driverName,if(trip.members.firstOrNull {it.id==car.driverId}?.isOwner==true)"여행 만든 사람" else "",driver=true) {
                    CarStatusPill("운전",kind=CarStatusTone.INK)
                }
            }
            TripText("동승자 ${car.passengers.size}명",style=CarType.Label,secondary=true)
            car.passengers.forEach {person->CarCard(tone=CarCardTone.OUTLINED) {
                PreparationPersonRow(person.name,trip.members.firstOrNull {it.id==person.id}?.role?.let(::tripRoleLabel) ?: "동승자")
                FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    listOf("pickup","drop").forEach {kind->
                        val place=car.places.orEmpty().firstOrNull {it.kind==kind && person.id in it.selectedBy.orEmpty()}
                        CarStatusPill("${if(kind=="pickup")"타는 곳" else "내리는 곳"}: ${place?.name ?: "미정"}",
                            kind=if(place==null)CarStatusTone.OUTLINE else CarStatusTone.SOFT)
                    }
                }
            }}
            CarCard(tone=CarCardTone.DASHED) {
                TripText("빈자리 ${car.seats-car.passengers.size}석",style=CarType.Section)
                TripText("일행은 iPhone에서 탈 차를 골라요",secondary=true,maxLines=3)
            }
        },right={
            listOf("pickup","drop").forEach {kind->
                val label=if(kind=="pickup")"타는 곳" else "내리는 곳"
                CarCard(tone=CarCardTone.OUTLINED) {
                    TripText(label,style=CarType.Section,maxLines=2)
                    val places=car.places.orEmpty().filter {it.kind==kind}
                    if(places.isEmpty())TripText("선택한 장소가 없어요",secondary=true,maxLines=2)
                    places.forEachIndexed {index,place->
                        if(index>0)TripDivider()
                        Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                            CarIcon(CarSymbol.Pin,color=LocalCarPalette.current.accent)
                            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                                TripText(place.name,style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=3)
                                val people=place.selectedBy.orEmpty().mapNotNull {id->trip.members.firstOrNull {it.id==id}?.name}
                                TripText(if(people.isEmpty())"선택한 일행 없음" else people.joinToString(", "),secondary=true,maxLines=3)
                            }

                        }
                    }
                }
            }
            CarPhoneHandoff("passenger-stops")
            CarCard(tone=CarCardTone.OUTLINED) {
                TripText("동승자 리모컨",style=CarType.Section)
                TripText(tripRemotePolicyLabel(car.remotePolicy),style=CarType.Label,secondary=true,maxLines=3)
                if(onRemote!=null)CarButton("리모컨",onRemote,Modifier.fillMaxWidth(),enabled=enabled)
            }
            CarButton("탑승 순서",onDeparture,Modifier.fillMaxWidth(),primary=true,enabled=interactive)
        })}
    }
}
