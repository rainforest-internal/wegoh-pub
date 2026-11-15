package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import io.wegoh.app.ListenTogetherAudio
import io.wegoh.app.ListenTogetherRepository
import io.wegoh.app.ListenTogetherUiState
import io.wegoh.app.nativeauth.ListenTogetherPhase

/** Status text shown to every vehicle; the playing label comes only from this vehicle's player events. */
internal fun listenTogetherStatus(state: ListenTogetherUiState): Pair<String,CarStatusTone> = when {
    state.joined->when(state.audio) {
        ListenTogetherAudio.PLAYING->"재생 중" to CarStatusTone.LIVE
        ListenTogetherAudio.COUNTDOWN->"${state.countdownSeconds ?: 0}초 뒤 시작" to CarStatusTone.ACTIVE
        ListenTogetherAudio.SUSPENDED->"잠시 멈춤" to CarStatusTone.PENDING
        ListenTogetherAudio.FINISHED->"곡 종료" to CarStatusTone.PAST
        else->if(state.active?.phase==ListenTogetherPhase.PLAYING)"맞추는 중" to CarStatusTone.PENDING else "참여 준비됨" to CarStatusTone.ACTIVE
    }
    state.session?.phase==ListenTogetherPhase.ENDED->ListenTogetherRepository.endNotice(state.session.endedReason) to CarStatusTone.PAST
    state.active?.phase==ListenTogetherPhase.PLAYING->"다른 차에서 재생 중" to CarStatusTone.SOFT
    state.active!=null->"준비 모집 중" to CarStatusTone.SOFT
    else->"참여 전" to CarStatusTone.NEUTRAL
}

internal fun listenTogetherDetail(state: ListenTogetherUiState): String {
    val session=state.active
    return when {
        session==null->"같은 시연 곡을 각 차 스피커로 함께 들어요. 참여를 누르면 이번 세션에서 방장이 시작할 때 이 차에서 재생돼요"
        session.phase==ListenTogetherPhase.PREPARING->"준비된 차량 ${session.deviceCount}대 · 방장 차량 포함 ${state.minimumDevices}대부터 시작할 수 있어요"
        else->"함께 듣는 차량 ${session.deviceCount}대"+if(state.joined)"" else " · 참여하면 지금 위치부터 들어요"
    }
}

@Composable
internal fun ListenTogetherCard(state: ListenTogetherUiState,enabled: Boolean,onJoin: ()->Unit,onLeave: ()->Unit,
    onStart: ()->Unit,onEnd: ()->Unit) {
    val ready=enabled && state.blocked==null && !state.busy
    val (status,tone)=listenTogetherStatus(state)
    CarCard(Modifier.fillMaxWidth(),tone=CarCardTone.OUTLINED) {
        Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                TripText("함께 듣기 (시연)",Modifier.weight(1f),style=CarType.Section,maxLines=1)
                CarStatusPill(status,kind=tone)
            }
            TripText(listenTogetherDetail(state),style=CarType.Label,secondary=true,maxLines=2)
            (state.blocked ?: state.notice)?.let {TripText(it,style=CarType.Label,maxLines=2)}
            Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                val session=state.active
                if(state.joined)CarButton("나가기",onLeave,enabled=enabled && !state.busy,icon=CarSymbol.Stop,accessibility="이 차만 함께 듣기에서 나가기")
                else CarButton(if(session?.phase==ListenTogetherPhase.PLAYING)"지금 위치부터 듣기" else "참여 준비",onJoin,primary=true,
                    enabled=ready,icon=CarSymbol.Music,accessibility="이번 함께 듣기 세션의 예약 재생에 동의하고 참여")
                if(state.host && session?.phase==ListenTogetherPhase.PREPARING)CarButton("함께 재생",onStart,primary=state.joined,
                    enabled=ready && state.canStart,icon=CarSymbol.Play,accessibility="준비된 차량 ${session.deviceCount}대에서 함께 재생")
                if(state.host && session!=null)CarButton("모두 종료",onEnd,enabled=enabled && !state.busy,variant=CarButtonStyle.DANGER,
                    accessibility="모든 차량의 함께 듣기 종료")
            }
        }
    }
}
