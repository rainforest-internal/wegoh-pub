package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.*

internal enum class TripInlineVoicePhase { LOADING, LISTENING, HEARING, REQUESTING, TRANSMITTING, RECORDED, SENDING, OFF, UNAVAILABLE }

// Labels stay one short line and details at most three lines so the half-width driving card never clips them.
internal enum class TripInlineVoiceBlock(val label: String,val detail: String) {
    VEHICLE_STATE("차량 확인","차량 상태를 확인하고 있어요"),
    PARK_REQUIRED("P단에서 이용",CAR_PARK_REQUIRED),
    TRIP_STATE("여행 확인","여행 정보를 확인하고 있어요"),
    SCREEN_INACTIVE("화면 확인","여행 화면으로 돌아오면 다시 연결해요"),
    MICROPHONE_PERMISSION("마이크 확인","권한 요청에 응답해 주세요")
}

/**
 * [microphone] is the current RECORD_AUDIO grant. Hearing never needs it; only recording asks for it.
 * [microphoneBlocked]는 영구 거부되어 Android가 권한 창을 더 띄우지 않는 상태다. 이때는 설정에서만 허용할 수 있다.
 */
internal data class TripInlineVoiceUi(val phase: TripInlineVoicePhase=TripInlineVoicePhase.LOADING,
    val participating: Boolean=true,val permitted: Boolean=true,val notice: String?=null,val block: TripInlineVoiceBlock?=null,
    val microphone: Boolean=true,val microphoneBlocked: Boolean=false)

internal const val TRIP_VOICE_MICROPHONE_DETAIL="말하려면 마이크를 허용해 주세요"
internal const val TRIP_VOICE_MICROPHONE_SETTINGS_DETAIL="설정에서 마이크를 허용해 주세요"

internal data class TripInlineVoiceText(val status: String,val action: String,val detail: String?,
    val off: Boolean,val canStart: Boolean,val canSend: Boolean,val enabled: Boolean,val block: TripInlineVoiceBlock?,
    val side: TripInlineVoiceSide?)

/** 주 버튼 옆 보조 동작. 결과가 주 버튼과 다르므로 아이콘만 두지 않고 워키토키 전용 화면처럼 글자 라벨을 함께 보인다. */
internal enum class TripInlineVoiceSide(val label: String,val symbol: CarSymbol,val accessibility: String) {
    CANCEL("취소",CarSymbol.Close,"녹음 취소"),
    RETRY("다시 연결",CarSymbol.Refresh,"워키토키 다시 연결"),
    OFF("끄기",CarSymbol.Stop,"워키토키 끄기")
}

/** 카드가 무엇의 상태인지 늘 보이도록 동작·상태 위에 두는 대상 라벨. */
internal const val TRIP_VOICE_TARGET="워키토키"

/** Pure state decision for the inline control. A missing microphone grant is never shown as a connection problem. */
internal fun tripInlineVoiceText(ui: TripInlineVoiceUi,recordingRequested: Boolean): TripInlineVoiceText {
    val off=ui.phase==TripInlineVoicePhase.OFF && !ui.participating
    val canStart=ui.permitted && ui.participating && ui.phase==TripInlineVoicePhase.LISTENING && !recordingRequested
    val canSend=ui.permitted && ui.participating && recordingRequested &&
        ui.phase in setOf(TripInlineVoicePhase.TRANSMITTING,TripInlineVoicePhase.RECORDED)
    val enabled=ui.permitted && (off || canStart || recordingRequested)
    val block=if(!ui.permitted)ui.block ?: TripInlineVoiceBlock.SCREEN_INACTIVE else null
    val needsMicrophone=canStart && !ui.microphone
    val status=block?.label ?: when {
        ui.phase==TripInlineVoicePhase.LOADING->"준비 중"
        off || !ui.participating || ui.phase==TripInlineVoicePhase.OFF->"워키토키 꺼짐"
        ui.phase==TripInlineVoicePhase.RECORDED->"녹음 완료"
        ui.phase==TripInlineVoicePhase.TRANSMITTING->"녹음 중"
        ui.phase==TripInlineVoicePhase.SENDING->"보내는 중"
        recordingRequested || ui.phase==TripInlineVoicePhase.REQUESTING->"녹음 준비 중"
        ui.phase==TripInlineVoicePhase.HEARING->"음성 재생 중"
        ui.phase==TripInlineVoicePhase.UNAVAILABLE->"연결 확인"
        needsMicrophone->"마이크 꺼짐"
        else->"녹음 가능"
    }
    val action=when {
        !ui.permitted->status
        off->"켜기"
        canSend->"보내기"
        recordingRequested->"취소"
        needsMicrophone->if(ui.microphoneBlocked)"설정 열기" else "마이크 허용"
        canStart->"녹음"
        else->status
    }
    val detail=block?.detail ?: ui.notice ?: when {
        ui.phase==TripInlineVoicePhase.LOADING->"음성 연결을 준비하고 있어요"
        ui.phase==TripInlineVoicePhase.RECORDED->"15초 녹음 완료"
        ui.phase==TripInlineVoicePhase.TRANSMITTING->"녹음 중 (최대 15초)"
        recordingRequested->"녹음 준비 중"
        ui.phase==TripInlineVoicePhase.HEARING->"받은 음성을 순서대로 재생해요"
        ui.phase==TripInlineVoicePhase.UNAVAILABLE->"연결을 다시 확인해 주세요"
        needsMicrophone->if(ui.microphoneBlocked)TRIP_VOICE_MICROPHONE_SETTINGS_DETAIL else TRIP_VOICE_MICROPHONE_DETAIL
        else->null
    }
    // 녹음을 준비하는 동안에는 주 버튼이 이미 '취소'라 같은 동작을 옆에 겹쳐 두지 않는다.
    val side=when {
        recordingRequested->TripInlineVoiceSide.CANCEL.takeIf {canSend}
        ui.phase==TripInlineVoicePhase.UNAVAILABLE->TripInlineVoiceSide.RETRY
        !off->TripInlineVoiceSide.OFF
        else->null
    }
    return TripInlineVoiceText(status,action,detail,off,canStart,canSend,enabled,block,side)
}

@Composable
internal fun TripInlineVoiceControl(ui: TripInlineVoiceUi,onPress: ()->Boolean,onRelease: ()->Unit,
    onParticipation: (Boolean)->Unit,onRetry: ()->Unit,modifier: Modifier=Modifier,onCancel: ()->Unit) {
    val presentation=LocalTripVoicePresentation.current
    SideEffect {presentation?.ui=ui}
    DisposableEffect(presentation) {onDispose {presentation?.ui=null}}
    val currentUi by rememberUpdatedState(ui)
    val currentPress by rememberUpdatedState(onPress)
    val currentRelease by rememberUpdatedState(onRelease)
    val currentCancel by rememberUpdatedState(onCancel)
    val currentParticipation by rememberUpdatedState(onParticipation)
    var recordingRequested by remember {mutableStateOf(false)}
    var recordingObserved by remember {mutableStateOf(false)}
    var hadFocus by remember {mutableStateOf(false)}
    fun cancelRecording() {
        if(recordingRequested) {
            recordingRequested=false
            recordingObserved=false
            currentCancel()
        }
    }
    // Starting, sending and cancelling are separate clicks. Releasing a finger,
    // losing focus or reaching the recording limit must never send a clip.
    fun activate() {
        val current=currentUi
        if(!current.permitted) {cancelRecording();return}
        if(current.phase==TripInlineVoicePhase.OFF && !current.participating) {
            currentParticipation(true)
        } else if(recordingRequested) {
            if(current.participating && current.phase in setOf(TripInlineVoicePhase.TRANSMITTING,TripInlineVoicePhase.RECORDED)) {
                recordingRequested=false
                recordingObserved=false
                currentRelease()
            } else cancelRecording()
        } else if(current.participating && current.phase==TripInlineVoicePhase.LISTENING) {
            recordingRequested=true
            recordingObserved=false
            if(!currentPress()) {
                recordingRequested=false
                recordingObserved=false
            }
        }
    }
    DisposableEffect(ui.permitted) {
        if(!ui.permitted)cancelRecording()
        onDispose {cancelRecording()}
    }
    LaunchedEffect(ui.phase,ui.participating,ui.permitted,ui.notice) {
        if(recordingRequested)when {
            !ui.permitted || !ui.participating->cancelRecording()
            ui.phase in setOf(TripInlineVoicePhase.REQUESTING,TripInlineVoicePhase.TRANSMITTING,TripInlineVoicePhase.RECORDED)->recordingObserved=true
            ui.phase==TripInlineVoicePhase.LISTENING && (recordingObserved || ui.notice!=null)->cancelRecording()
            ui.phase!=TripInlineVoicePhase.LISTENING->cancelRecording()
        }
    }
    val text=tripInlineVoiceText(ui,recordingRequested)
    val off=text.off
    val canStart=text.canStart
    val canSend=text.canSend
    val enabled=text.enabled
    val status=text.status
    val action=text.action
    val detail=text.detail
    val palette=LocalCarPalette.current
    val onInk=ui.permitted && (canSend || ui.phase==TripInlineVoicePhase.HEARING)
    val color=if(onInk)palette.ink else if(canStart)palette.accent else palette.low
    val ink=if(onInk)palette.onInk else if(canStart)palette.selectionMark else palette.text
    val secondary=if(onInk)palette.onInkSecondary else if(canStart)palette.selectionMark else palette.secondary
    // 주 버튼은 행 높이를 끝까지 채운다. 같은 줄 손들기 버튼과 높이가 달라 위아래 띠가 남지 않게 한다.
    Row(modifier.heightIn(min=CarTokens.ButtonDrivingCompact),
        horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
        Row(Modifier.weight(1f).fillMaxHeight().heightIn(min=CarTokens.ButtonDrivingCompact)
            .onFocusChanged {
                if(hadFocus && !it.hasFocus)cancelRecording()
                hadFocus=it.hasFocus
            }
            .carTap(enabled=enabled,onClick=::activate)
            .clearAndSetSemantics {
                role=Role.Button
                contentDescription="워키토키 $action"
                testTag="trip-inline-voice-control"
                stateDescription=status
                onClick(label=action) {if(enabled) {activate();true} else false}
                if(!enabled)disabled()
            }
            .clip(RoundedCornerShape(CarTokens.RadiusCard)).background(color)
            .padding(horizontal=CarTokens.Gap,vertical=CarTokens.SpaceSmall),
            horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
            // Drop the decorative icon before any text when the half-width card is too narrow for the label.
            // Measured after layout instead of BoxWithConstraints: driving rows ask for intrinsic sizes, which subcomposition cannot answer.
            val density=LocalDensity.current
            val labelRoom=CarTokens.Icon+CarTokens.Gap+with(density) {CarType.Section.fontSize.toDp()}*TRIP_VOICE_LABEL_CHARS
            var roomy by remember {mutableStateOf(true)}
            Row(Modifier.weight(1f).onSizeChanged {roomy=with(density) {it.width.toDp()}>=labelRoom},
                horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                if(roomy)CarIcon(CarSymbol.Microphone,Modifier.size(CarTokens.Icon),ink)
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    TripText(TRIP_VOICE_TARGET,style=CarType.Caption,color=secondary,maxLines=1)
                    TripText(action,style=CarType.Section,color=ink,maxLines=1)
                    detail?.let {TripText(it,style=CarType.Caption,color=secondary,maxLines=3)}
                }
            }
        }
        text.side?.let {side->
            CarButton(side.label,when(side) {
                TripInlineVoiceSide.CANCEL->::cancelRecording
                TripInlineVoiceSide.RETRY->onRetry
                TripInlineVoiceSide.OFF->{{cancelRecording();onParticipation(false)}}
            },Modifier.fillMaxHeight(),icon=side.symbol,accessibility=side.accessibility,
                enabled=ui.permitted && (side!=TripInlineVoiceSide.OFF || ui.phase !in setOf(TripInlineVoicePhase.LOADING,TripInlineVoicePhase.SENDING)))
        }
    }
}

/** Longest one-line action label, in characters; tripInlineVoiceText keeps every label within it. */
internal const val TRIP_VOICE_LABEL_CHARS=7
