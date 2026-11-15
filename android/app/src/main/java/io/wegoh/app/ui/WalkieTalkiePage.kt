package io.wegoh.app.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import kotlin.math.ceil

internal enum class WalkiePhase { LOADING, GUIDE, UNAVAILABLE, CHOOSE, OFF, CONNECTING, LISTENING, HEARING, CALLING, TALKING }

internal data class WalkieRoom(val id: String,val name: String,val canListen: Boolean,val canTalk: Boolean)

internal data class WalkieUi(val phase: WalkiePhase=WalkiePhase.LOADING,val room: WalkieRoom?=null,
    val rooms: List<WalkieRoom> = emptyList(),val hasMore: Boolean=false,val notice: String?=null,
    val locked: Boolean=false,val restricted: Boolean=false)

internal class WalkieActions(val back: ()->Unit,val retry: ()->Unit,val choose: (WalkieRoom)->Unit,val more: ()->Unit,
    val rooms: ()->Unit,val power: ()->Unit,val talk: ()->Unit)

internal const val WalkieTalkSeconds=15

@Composable
internal fun WalkieTalkiePage(ui: WalkieUi,actions: WalkieActions) = TripSurface {
    val palette=LocalCarPalette.current
    Column(Modifier.fillMaxSize().systemBarsPadding()) {
        Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.WalkieHeaderMinHeight).padding(horizontal=CarTokens.SpaceXLarge,vertical=CarTokens.SpaceMedium),
            horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
            CarIconAction("뒤로",CarSymbol.Back,actions.back)
            Column(Modifier.weight(1f)) {
                TripText("워키토키",style=CarType.Title)
                ui.room?.takeIf {ui.phase !in setOf(WalkiePhase.LOADING,WalkiePhase.GUIDE,WalkiePhase.UNAVAILABLE,WalkiePhase.CHOOSE)}
                    ?.let {TripText(it.name,style=CarType.WalkieRoomName,secondary=true)}
            }
            Row(Modifier.background(palette.low,RoundedCornerShape(CarTokens.ChipRadius)).padding(horizontal=CarTokens.SpaceLarge,vertical=CarTokens.SpaceCompact),
                horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceCompact),verticalAlignment=Alignment.CenterVertically) {
                Box(Modifier.size(CarTokens.GearSize).background(palette.text,RoundedCornerShape(CarTokens.GearRadius)),contentAlignment=Alignment.Center) {
                    TripText("P",style=CarType.WalkieGear,color=palette.background)
                }
                TripText("정차 중에만",secondary=true)
            }
        }
        TripDivider()
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when {
                ui.restricted->CarRestrictedState(modifier=Modifier.fillMaxSize(),detail=null)
                ui.phase==WalkiePhase.LOADING->CarLoadingState("워키토키 준비 중",Modifier.fillMaxSize())
                ui.phase==WalkiePhase.GUIDE->WalkieGuide(ui.notice,actions.retry)
                ui.phase==WalkiePhase.UNAVAILABLE->WalkieMessage("지금은 워키토키를 쓸 수 없어요",
                    ui.notice) {CarButton("다시 연결",actions.retry,primary=true,icon=CarSymbol.Refresh)}
                ui.phase==WalkiePhase.CHOOSE->WalkieRooms(ui,actions)
                else->WalkieStage(ui,actions)
            }
        }
    }
}

@Composable
private fun WalkieMessage(title: String,detail: String?,action: @Composable ()->Unit) {
    val palette=LocalCarPalette.current
    CompositionLocalProvider(LocalCarTextAlign provides TextAlign.Center) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(CarTokens.Space3XLarge),
            verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceLarge,Alignment.CenterVertically),horizontalAlignment=Alignment.CenterHorizontally) {
            Box(Modifier.size(CarTokens.WalkieMessageIllustration).background(palette.low,CircleShape),contentAlignment=Alignment.Center) {
                CarIcon(CarSymbol.Microphone,Modifier.size(CarTokens.WalkieMessageIcon),palette.secondary)
            }
            TripText(title,style=CarType.Title,maxLines=3)
            detail?.let {TripText(it,secondary=true,maxLines=CarMessageLines)}
            action()
        }
    }
}

@Composable
private fun WalkieGuide(notice: String?,onRetry: ()->Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal=CarTokens.Space3XLarge,vertical=CarTokens.Space2XLarge),
        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceLarge,Alignment.CenterVertically)) {
        TripText("iPhone에서 워키토키를 켜 주세요",style=CarType.Title,maxLines=3)
        TripText("여행 상세의 ‘차량 워키토키 설정’에서 변경할 수 있어요.",secondary=true,maxLines=3)
        notice?.let {TripText(it,secondary=true,maxLines=CarMessageLines)}
        CarButton("다시 확인",onRetry,Modifier.fillMaxWidth(),primary=true,icon=CarSymbol.Refresh)
    }
}

@Composable
private fun WalkieRooms(ui: WalkieUi,actions: WalkieActions) {
    val palette=LocalCarPalette.current
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal=CarTokens.Space3XLarge,vertical=CarTokens.Space2XLarge),
        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
        TripText("여행 선택",style=CarType.Title,maxLines=3)
        ui.notice?.let {TripText(it,secondary=true,maxLines=CarMessageLines)}
        ui.rooms.forEach {room->
            Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row).clip(RoundedCornerShape(CarTokens.RadiusCard)).background(palette.low)
                .carTap {actions.choose(room)}.semantics {contentDescription=room.name}.padding(horizontal=CarTokens.SpaceXLarge,vertical=CarTokens.SpaceComfortable),
                horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceComfortable),verticalAlignment=Alignment.CenterVertically) {
                CarIcon(CarSymbol.Group,Modifier.size(CarTokens.WalkieRoomIcon),palette.text)
                Column(Modifier.weight(1f)) {
                    TripText(room.name,style=CarType.Section,maxLines=2)
                    TripText(when {room.canListen && room.canTalk->"듣기와 말하기";room.canTalk->"말하기만";else->"듣기만"},secondary=true)
                }
                CarIcon(CarSymbol.Next,Modifier.size(CarTokens.WalkieNextIcon),palette.secondary)
            }
        }
        if(ui.hasMore)CarButton("더 보기",actions.more,Modifier.fillMaxWidth())
    }
}

private data class WalkieCopy(val title: String,val detail: String?,val label: String,val action: String)

private fun walkieCopy(ui: WalkieUi): WalkieCopy {
    val room=ui.room
    return when(ui.phase) {
        WalkiePhase.OFF->WalkieCopy("워키토키가 꺼져 있어요",if(room?.canListen==false)"켜면 일행에게 말할 수 있어요" else "켜면 일행의 대화가 들려요","켜기","워키토키 켜기")
        WalkiePhase.CONNECTING->WalkieCopy("연결 중",null,"연결 중","연결 중")
        WalkiePhase.HEARING->WalkieCopy("일행이 말하는 중",null,"듣는 중","일행이 말하는 중")
        WalkiePhase.CALLING->WalkieCopy("말하기 준비 중",null,"준비 중","말하기 준비 중")
        WalkiePhase.TALKING->WalkieCopy("말하는 중","다시 누르면 끝나요","끝내기","말하기 끝내기")
        else->when {
            room==null || !room.canTalk->WalkieCopy("듣는 중","이 차는 듣기만 할 수 있어요","듣기 전용","듣기 전용")
            !room.canListen->WalkieCopy("말할 수 있어요","이 차는 말하기만 할 수 있어요","말하기","말하기")
            else->WalkieCopy("듣는 중","버튼을 한 번 누르고 말하세요","말하기","말하기")
        }
    }
}

@Composable
private fun WalkieStage(ui: WalkieUi,actions: WalkieActions) {
    val palette=LocalCarPalette.current
    val copy=walkieCopy(ui)
    val on=ui.phase!=WalkiePhase.OFF
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val side=maxWidth>=CarTokens.Breakpoint || maxHeight<CarTokens.WalkieStageShortBreakpoint
        val diameter=(if(side)maxHeight-CarTokens.WalkieStageReservedHeight else maxHeight*CarTokens.WalkieButtonHeightFraction).coerceIn(CarTokens.WalkieButtonMin,CarTokens.WalkieButtonMax)
        val status: @Composable (Modifier,Alignment.Horizontal)->Unit={modifier,align->
            CompositionLocalProvider(LocalCarTextAlign provides if(align==Alignment.Start)TextAlign.Start else TextAlign.Center) {
                Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceCompact),horizontalAlignment=align) {
                    TripText(copy.title,style=CarType.WalkieStatus,maxLines=2)
                    copy.detail?.let {TripText(it,style=CarType.WalkieDetail,secondary=true,maxLines=3)}
                    ui.notice?.let {
                        Box(Modifier.padding(top=CarTokens.SpaceSmall).background(palette.low,RoundedCornerShape(CarTokens.WalkieNoticeRadius)).padding(horizontal=CarTokens.SpaceLarge,vertical=CarTokens.WalkieNoticePaddingVertical)) {
                            TripText(it,style=CarType.Label,maxLines=3)
                        }
                    }
                }
            }
        }
        val rule: @Composable ()->Unit={TripText("최대 ${WalkieTalkSeconds}초 동안 말할 수 있어요. 녹음하지 않아요.",secondary=true,maxLines=2)}
        Column(Modifier.fillMaxSize()) {
            if(side)Row(Modifier.weight(1f).fillMaxWidth().padding(horizontal=CarTokens.Space4XLarge),
                horizontalArrangement=Arrangement.spacedBy(CarTokens.Space4XLarge),verticalAlignment=Alignment.CenterVertically) {
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceLarge)) {status(Modifier.fillMaxWidth(),Alignment.Start);rule()}
                WalkieTalkButton(ui,copy,diameter,actions)
            } else Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal=CarTokens.Space3XLarge,vertical=CarTokens.SpaceXLarge),
                verticalArrangement=Arrangement.spacedBy(CarTokens.Space2XLarge,Alignment.CenterVertically),horizontalAlignment=Alignment.CenterHorizontally) {
                status(Modifier.fillMaxWidth(),Alignment.CenterHorizontally)
                WalkieTalkButton(ui,copy,diameter,actions)
                CompositionLocalProvider(LocalCarTextAlign provides TextAlign.Center) {rule()}
            }
            TripDivider()
            Row(Modifier.fillMaxWidth().padding(horizontal=CarTokens.SpaceXLarge,vertical=CarTokens.SpaceComfortable),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                if(on)CarButton("끄기",actions.power,Modifier.weight(1f),icon=CarSymbol.Stop,accessibility="워키토키 끄기")
                else if(ui.rooms.size>1)CarButton("다른 여행",actions.rooms,Modifier.weight(1f),icon=CarSymbol.Group)
                else CarButton("나가기",actions.back,Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun WalkieTalkButton(ui: WalkieUi,copy: WalkieCopy,diameter: Dp,actions: WalkieActions) {
    val palette=LocalCarPalette.current
    val phase=ui.phase
    val talking=phase==WalkiePhase.TALKING
    val hearing=phase==WalkiePhase.HEARING
    val waiting=phase in setOf(WalkiePhase.CONNECTING,WalkiePhase.CALLING)
    val canTalk=ui.room?.canTalk==true
    val enabled=!ui.locked && when(phase) {
        WalkiePhase.OFF,WalkiePhase.TALKING->true
        WalkiePhase.LISTENING->canTalk
        else->false
    }
    val fill by animateColorAsState(when {
        talking->palette.accent
        phase==WalkiePhase.LISTENING && canTalk->palette.text
        phase==WalkiePhase.OFF->palette.background
        else->palette.low
    },tween(CarTokens.WalkieTransitionMs),label="walkie-fill")
    val ink by animateColorAsState(when {
        talking || phase==WalkiePhase.LISTENING && canTalk->palette.background
        phase==WalkiePhase.OFF->palette.text
        hearing->palette.accent
        else->palette.secondary
    },tween(CarTokens.WalkieTransitionMs),label="walkie-ink")
    var remaining by remember {mutableFloatStateOf(1f)}
    LaunchedEffect(talking) {
        remaining=1f
        if(talking) {
            val start=withFrameNanos {it}
            while(remaining>0f)withFrameNanos {now->remaining=(1f-(now-start)/(WalkieTalkSeconds*1_000_000_000f)).coerceIn(0f,1f)}
        }
    }
    val ring by animateFloatAsState(if(talking)1f else 0f,tween(CarTokens.WalkieTransitionMs),label="walkie-ring")
    val wave=if(hearing) {
        val progress by rememberInfiniteTransition(label="walkie-wave").animateFloat(0f,1f,
            infiniteRepeatable(tween(CarTokens.WalkieWaveMs,easing=LinearEasing),RepeatMode.Restart),label="walkie-wave-progress")
        progress
    } else 0f
    val halo=CarTokens.WalkieHalo
    Box(Modifier.size(diameter+halo*2),contentAlignment=Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val inner=diameter.toPx()/2
            if(hearing)listOf(wave,(wave+0.5f)%1f).forEach {step->
                drawCircle(palette.accent.copy(alpha=(1f-step)*CarTokens.WalkieWaveAlpha),inner+halo.toPx()*step,style=Stroke(CarTokens.WalkieWaveStroke.toPx()))
            }
            if(ring>0f) {
                val stroke=CarTokens.WalkieRingStroke.toPx()
                val radius=inner+halo.toPx()/2
                val corner=Offset(center.x-radius,center.y-radius)
                drawCircle(palette.divider.copy(alpha=ring),radius,style=Stroke(stroke))
                drawArc(palette.accent.copy(alpha=ring),-90f,360f*remaining,false,corner,Size(radius*2,radius*2),
                    style=Stroke(stroke,cap=StrokeCap.Round))
            }
        }
        Column(Modifier.size(diameter).clip(CircleShape).background(fill)
            .then(if(phase==WalkiePhase.OFF)Modifier.border(CarTokens.WalkieOffBorder,palette.text,CircleShape) else Modifier)
            .carTap(enabled=enabled) {if(phase==WalkiePhase.OFF)actions.power() else actions.talk()}
            .semantics {contentDescription=copy.action;stateDescription=copy.title},
            verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall,Alignment.CenterVertically),horizontalAlignment=Alignment.CenterHorizontally) {
            val icon=Modifier.size(diameter*CarTokens.WalkieButtonIconFraction)
            when {
                waiting->CarLoading(icon,ink)
                talking->TripText("${ceil(remaining*WalkieTalkSeconds).toInt().coerceAtLeast(1)}",
                    style=CarType.WalkieCountdown,color=ink)
                hearing->CarIcon(CarSymbol.Group,icon,ink)
                else->CarIcon(CarSymbol.Microphone,icon,ink)
            }
            TripText(copy.label,style=CarType.Title,color=ink)
        }
    }
}
