@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import io.wegoh.app.*
import io.wegoh.app.nativeauth.*

enum class TripSection(val title: String) {ROOMS("여행방"),HISTORY("기록"),VOICE("워키토키")}
enum class CarSection(val title: String) {
    OVERVIEW("리모컨"),COMMANDS("차량 요청");
    companion object {
        fun fromSaved(name: String?)=entries.firstOrNull {it.name==name} ?: OVERVIEW
    }
}

@Composable
fun CarTabs(labels: List<String>,selected: Int,onSelect: (Int)->Unit) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
        labels.forEachIndexed {index,label->
            val chosen=index==selected
            Column(Modifier.width(IntrinsicSize.Max).widthIn(min=CarTokens.ButtonLarge).heightIn(min=CarTokens.Touch).carTap(role=Role.Tab){onSelect(index)}
                .semantics {role=Role.Tab;this.selected=chosen;contentDescription=label}.padding(horizontal=CarTokens.SpaceMedium),
                horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.Center) {
                CarText(label,style=CarType.Action.copy(fontWeight=if(chosen)FontWeight.Bold else FontWeight.Normal))
                Spacer(Modifier.height(CarTokens.SpaceSmall))
                Box(Modifier.fillMaxWidth().height(CarTokens.SelectedBorderWidth).background(if(index==selected)LocalCarPalette.current.text else LocalCarPalette.current.background))
            }
        }
    }
}

@Composable
internal fun VehicleTripsPage(state: SocialPageState,onLoad: ()->Unit,onRefresh: ()->Unit,onRoom: (String)->Unit,
    onCloseRoom: ()->Unit,onSignal: (SocialSignalKind)->Unit,onPhone: ()->Unit,extra: @Composable (TripSection)->Unit) {
    var section by remember {mutableStateOf(TripSection.ROOMS)}
    CarChildBackHandler(enabled=section==TripSection.ROOMS && state.room!=null,onBack=onCloseRoom)
    LaunchedEffect(Unit){onLoad()}
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        val sections=TripSection.entries.filter {it!=TripSection.HISTORY}
        CarTabs(sections.map {it.title},sections.indexOf(section).coerceAtLeast(0),{section=sections[it]})
        Box(Modifier.weight(1f).fillMaxWidth()) {
            if(section!=TripSection.ROOMS)extra(section)
            else if(state.overview==null)SocialPreparation(state,onRefresh,onPhone)
            else if(state.room==null) {
                if(state.overview.rooms.isEmpty())CarEmptyState("참여 중인 여행방이 없어요",Modifier.fillMaxSize(),symbol=CarSymbol.Group,
                    action={CarAction("휴대전화에서 계속",CarSymbol.Link,onPhone)})
                else LazyColumn(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    items(state.overview.rooms,key={it.id}) {room->CarListRow(room.name,listOf("${room.memberCount}명"),CarSymbol.Group,
                        enabled=state.isCurrent && !state.busy,onClick={onRoom(room.id)})}
                }
            } else {
                val room=state.room
                Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    CarText(room.name,style=CarType.Hero,maxLines=2)
                    CarAction("여행방 목록",CarSymbol.Back,onCloseRoom)
                    room.course?.let {CarText(it.title,style=CarType.Section,maxLines=2)}
                    room.members.forEach {CarListRow(it.person.name ?: "일행",symbol=CarSymbol.Person)}
                    CarText("여행방 음악",style=CarType.Section)
                    state.musicNotice?.let {CarText(it,secondary=true,maxLines=2)}
                    state.roomMusic?.selection?.let {selection->
                        CarText(selection.name,style=CarType.Section,maxLines=2)
                        for(track in selection.tracks)CarListRow(track.title,
                            if(track.id==selection.currentTrackId)listOf("선택됨") else emptyList(),CarSymbol.Music)
                    }
                    if(!room.readOnly) {
                        CarAction("휴식 요청",CarSymbol.Clock,{onSignal(SocialSignalKind.REST)},enabled=state.isCurrent && !state.busy)
                        CarAction("도착했어요",CarSymbol.Flag,{onSignal(SocialSignalKind.ARRIVED)},enabled=state.isCurrent && !state.busy)
                    }
                    state.notice?.let {CarText(it,secondary=true,maxLines=2)}
                    CarAction("휴대전화에서 계속",CarSymbol.Link,onPhone)
                }
            }
        }
    }
}

@Composable
internal fun SocialPreparation(state: SocialPageState,onRefresh: ()->Unit,onPhone: ()->Unit) {
    if(state.status==AccountReadStatus.LOADING)CarLoadingState("불러오는 중",Modifier.fillMaxSize())
    else {
        val title=when(state.status) {
            AccountReadStatus.PERMISSION_REQUIRED->"여행방을 볼 권한이 없어요"
            AccountReadStatus.CONNECTION_REQUIRED->"차량을 연결해 주세요"
            else->"여행방을 불러오지 못했어요"
        }
        val detail=when(state.status) {
            AccountReadStatus.PERMISSION_REQUIRED->"휴대전화에서 계정을 확인해 주세요"
            AccountReadStatus.CONNECTION_REQUIRED->"휴대전화에서 연결을 완료해 주세요"
            else->"인터넷 연결을 확인해 주세요"
        }
        CarEmptyState(title,Modifier.fillMaxSize(),detail=detail,symbol=CarSymbol.Group,action={
            CarActionGroup {
                if(state.status==AccountReadStatus.UNAVAILABLE) {
                    CarAction("다시 시도",CarSymbol.Refresh,onRefresh,primary=true)
                    CarAction("휴대전화에서 확인",CarSymbol.Link,onPhone)
                } else {
                    CarAction("휴대전화에서 확인",CarSymbol.Link,onPhone,primary=true)
                    CarAction("새로고침",CarSymbol.Refresh,onRefresh)
                }
            }
        })
    }
}

@Composable
internal fun VehicleCarPage(receiving: Boolean,message: String,onClimate: ()->Unit,
    onConnection: ()->Unit,extra: @Composable (CarSection,()->Unit)->Unit,remoteHistory: (@Composable ()->Unit)?=null,
    remotePolicy: TripRemotePolicy?=null,remoteSnapshot: TripRemotePolicySnapshot?=null) {
    val context=LocalContext.current
    val controller=(context.applicationContext as WegoApplication).controller
    val window=LocalCarWindowVisibility.current
    val receiver=rememberVehicleReceiverSettings(context)
    val enabled=receiver.enabled
    val canAdjust=controller.state.setupAllowed && window?.state?.focused==true
    val canToggle=canAdjust && receiver.canToggle && !receiver.busy
    TripSurface {
    Box(Modifier.fillMaxSize()) {
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    TripAdaptiveRow(Modifier.fillMaxSize()
        .padding(horizontal=CarTokens.PagePrimaryPaddingHorizontal,vertical=CarTokens.PagePrimaryPaddingVertical)
        .then(if(narrow)Modifier.verticalScroll(rememberScrollState()) else Modifier),narrow=narrow,gap=CarTokens.Frame) {
        Column(Modifier.weight(1f).then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),
            verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            CarCard(tone=CarCardTone.INK,padding=PaddingValues(CarTokens.Frame),radius=CarTokens.RadiusHero) {
                Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        TripText("리모컨 받기",style=CarType.Title,maxLines=2)
                        TripText(receiver.notice ?: when {
                            !enabled -> "꺼짐"
                            receiving -> "켜짐"
                            else -> "연결 확인 중"
                        },secondary=true,maxLines=3)
                    }
                    CarSwitchControl(checked=enabled,enabled=canToggle,accessibility="리모컨 받기",onChange={next->
                        if(controller.state.setupAllowed && window?.state?.focused==true)receiver.setEnabled(next)
                    })
                }
                if(receiver.retry)CarButton("다시 시도",{
                    if(controller.state.setupAllowed && window?.state?.focused==true)receiver.refresh()
                },Modifier.fillMaxWidth(),enabled=canAdjust && !receiver.busy,icon=CarSymbol.Refresh,variant=CarButtonStyle.INK_OUTLINE)
                TripDivider()
                VehicleRemotePolicySummary(remotePolicyForReceiver(remotePolicy,receiver.deviceId),onInk=true,snapshot=remoteSnapshot)
            }
            CarPhoneHandoff("remote")
            CarInfoHint("시트 열선·통풍과 실내등은 정차 중에만 사용할 수 있어요")
        }
        Column(Modifier.weight(1f).then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),
            verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            if(remoteHistory!=null)remoteHistory() else extra(CarSection.COMMANDS) {}
        }
    }
    }

    }
}

@Composable
internal fun VehicleRemoteHistoryList(entries: List<VehicleRemoteEntry>) {
    var now by remember {mutableLongStateOf(android.os.SystemClock.elapsedRealtime())}
    LaunchedEffect(entries) {
        now=android.os.SystemClock.elapsedRealtime()
        while(entries.isNotEmpty()) {
            kotlinx.coroutines.delay(1_000)
            now=android.os.SystemClock.elapsedRealtime()
        }
    }
    val visible=entries.filter {it.visibleAt(now)}
    val pending=visible.count {it.pending}
    Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
            TripText("받은 조작",Modifier.weight(1f),style=CarType.Section)
            CarMetadata(if(pending>0)listOf("처리 중 ${pending}건","완료 최근 5건") else listOf("최근 5건"))
        }
        CarCard(outlined=true,padding=PaddingValues()) {
            Column {
            if(visible.isEmpty())Box(Modifier.padding(CarTokens.Frame)) {TripText("받은 조작이 없어요",secondary=true,maxLines=2)}
            visible.forEachIndexed {index,entry->
                if(index>0)TripDivider()
                Column(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row)
                    .padding(horizontal=CarTokens.Frame,vertical=CarTokens.SpaceMedium),
                    verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,
                        horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                        TripText(entry.action,Modifier.weight(1f),style=CarType.Body,maxLines=2)
                        TripText(entry.relativeTime(now),style=CarType.Label,secondary=true)
                    }
                    Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,
                        horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                        TripText(entry.sender,Modifier.weight(1f),style=CarType.Label,secondary=true,maxLines=2)
                        CarStatusPill(entry.resultLabel,kind=if(entry.result==VehicleRemoteResult.APPLIED)CarStatusTone.SOFT else CarStatusTone.OUTLINE)
                    }
                }
            }
        }
    }
    }
}


internal val remotePolicyFamilies=listOf(
    "공조" to setOf("hvac.temperature","hvac.fan","hvac.power","hvac.ac","hvac.air_cleaner"),
    "조명" to setOf("light.cabin","light.reading","light.ambient"),
    "창문" to setOf("window.position"),
    "시트" to setOf("seat.heat","seat.ventilation"),
)

/** Header refresh count for the remote tab, so its single refresh button also reloads the request list. */
internal val LocalCarRemoteRefresh=compositionLocalOf {0}

/** Read-only allowed-feature summary as text: families with any allowed action, then the ones left off. */
internal fun remotePolicyFamilySummary(policy: TripRemotePolicy): Pair<List<String>,List<String>> {
    val allowed=if(policy.enabled)policy.actions else emptySet()
    val on=mutableListOf<String>();val off=mutableListOf<String>()
    remotePolicyFamilies.forEach {(title,actions)->
        when(val count=actions.count {it in allowed}) {
            0->off+=title
            actions.size->on+=title
            else->on+="$title $count/${actions.size}"
        }
    }
    return on to off
}

internal fun remotePolicyForReceiver(policy: TripRemotePolicy?,deviceId: String?): TripRemotePolicy? =
    policy?.takeIf {!it.enabled || deviceId!=null && it.deviceId==deviceId}

// 리모컨 탭 스냅샷은 탭을 연 뒤에만 읽히고 읽는 동안 LOADING에 머문다. 선택된 진행 중 여행 상세도 같은 서버 값을
// 담고 있으므로 스냅샷이 준비되지 않았으면 상세를 쓴다. 둘 다 같은 여행이면 revision이 큰 쪽을 쓰고,
// 비교할 수 없는데 값이 다르거나 서로 다른 여행을 가리키면 오래된 '허용'을 보이지 않도록 null을 돌려준다.
internal fun currentTripRemotePolicy(state: TripsPageState): TripRemotePolicy? {
    if(state.status!=AccountReadStatus.READY || !state.isCurrent)return null
    val detail=state.detail?.takeIf {state.selectedId==it.id && it.state=="active"}
    val snapshot=state.remotePolicySnapshot
    if(snapshot.status!=AccountReadStatus.READY)return detail?.myCar?.remotePolicy
    if(detail==null)return snapshot.policy
    if(snapshot.tripId!=detail.id)return null
    return newerRemotePolicy(snapshot.policy,detail.myCar?.remotePolicy)
}

private fun newerRemotePolicy(a: TripRemotePolicy?,b: TripRemotePolicy?): TripRemotePolicy? {
    val ra=a?.revision;val rb=b?.revision
    if(ra!=null && rb!=null)return if(rb>ra)b else a
    return a.takeIf {it==b}
}

@Composable
internal fun VehicleRemotePolicySummary(policy: TripRemotePolicy?,onInk: Boolean=false,snapshot: TripRemotePolicySnapshot?=null) {
    val content: @Composable ColumnScope.()->Unit={
        TripText("동승자 허용 기능",style=CarType.Section,maxLines=2)
        snapshot?.tripTitle?.let {TripText(it,style=CarType.Label,secondary=true,maxLines=2)}
        if(snapshot?.status==AccountReadStatus.READY && snapshot.tripId==null) {
            TripText("진행 중인 여행이 없어요",secondary=true,maxLines=2)
        } else if(snapshot?.status==AccountReadStatus.LOADING) {
            TripText("여행 확인 중",secondary=true,maxLines=2)
        } else if(policy==null) {
            TripText("허용 설정을 확인할 수 없어요",secondary=true,maxLines=2)
        } else {
            CarStatusPill(if(policy.enabled)"허용" else "허용 안 함",
                kind=when {policy.enabled && onInk->CarStatusTone.ON_INK;policy.enabled->CarStatusTone.SOFT;else->CarStatusTone.NEUTRAL})
            // 차에서는 바꿀 수 없는 값이므로 선택 칩이 아닌 정적 글자로 보여 준다.
            if(policy.enabled) {
                val (on,off)=remotePolicyFamilySummary(policy)
                if(on.isNotEmpty())CarMetadata(on,style=CarType.Body,secondary=false)
                if(off.isNotEmpty())TripText("꺼둔 기능 · "+off.joinToString(" · "),style=CarType.Label,secondary=true,maxLines=2)
            }
        }
    }
    if(onInk)Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),content=content)
    else CarCard(outlined=true,content=content)
}
