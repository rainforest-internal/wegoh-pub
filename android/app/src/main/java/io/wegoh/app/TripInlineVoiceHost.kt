package io.wegoh.app

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.wegoh.app.nativeauth.NativeTripVoiceController
import io.wegoh.app.nativeauth.NativeVoiceAudioSafety
import io.wegoh.app.nativeauth.TripDetail
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.ui.*

@Composable
internal fun TripInlineVoiceHost(connection: VehicleConnection,trip: TripDetail,allowed: Boolean,modifier: Modifier=Modifier) {
    val context=LocalContext.current
    val view=LocalView.current
    val window=LocalCarWindowVisibility.current
    val currentAllowed by rememberUpdatedState(allowed)
    var state by remember(connection,trip.id) {mutableStateOf(TripInlineVoiceUi())}
    var audioSafety by remember(connection,trip.id) {mutableStateOf(NativeVoiceAudioSafety())}
    val owner=remember(connection,trip.id) {TripInlineVoiceOwner(connection,trip) {value->state=value}}
    val safety=remember(owner,context) {NativeVoiceCarSafety(context,drivingOptimized=true) {value->
        audioSafety=value
        if(!value.permits())owner.cancel()
        owner.updateSafety(value.foreground,value.carUxAllowed)
    }}
    DisposableEffect(owner,safety,window,view) {
        var last: CarWindowState?=null
        fun foreground() {safety.setForeground(tripVoiceForeground(window?.state,view.isShown))}
        val observation=window?.observe {next->
            if(tripVoiceFocusLost(last,next))owner.cancel()
            last=next;foreground()
        }
        foreground();owner.start()
        onDispose {owner.cancel();observation?.close();safety.close();owner.close()}
    }
    SideEffect {
        safety.setForeground(tripVoiceForeground(window?.state,view.isShown))
        // 여행 다시 읽기·손들기 결정은 연결을 끊지 않고 녹음·재생만 멈춘다. 끊으면 매번 '준비 중'부터 다시 시작하고
        // 그 사이 음성 조회 위치를 잃는다. 계정·여행 변경은 이 화면의 owner(connection, trip.id)가 바뀌어 새로 연결한다.
        owner.setTripReady(allowed)
    }
    key(owner) {
        TripInlineVoiceWithMicrophone(state.withSafety(audioSafety,allowed),onPress={owner.press()},onRelease=owner::release,
            onParticipation=owner::setParticipation,onRetry=owner::retry,modifier=modifier,canRequest={audioSafety.permits() && currentAllowed},onCancel=owner::cancel)
    }
}

/**
 * 연결·수신의 화면 조건은 창이 보이고 RESUMED인지(CarWindowState.visible)로만 정한다.
 * Pleos 멀티 윈도우에서는 내비 옆 창의 WegoH가 보이는 채로 포커스를 잃으므로 포커스를 조건에 넣지 않는다.
 * 여행 확인 상태(isCurrent 등)는 연결 조건이 아니다. 그 동안은 [NativeTripVoiceController.setTripReady]로 조작만 막는다.
 */
internal fun tripVoiceForeground(window: CarWindowState?,shown: Boolean)=
    window?.visible==true && shown

/** 포커스가 다른 창·시스템 화면으로 옮겨 가는 순간 진행 중 녹음만 끝낸다. 연결과 수신은 유지한다. */
internal fun tripVoiceFocusLost(previous: CarWindowState?,next: CarWindowState)=
    previous?.focused==true && !next.focused

internal fun TripInlineVoiceUi.withSafety(safety: NativeVoiceAudioSafety,tripAllowed: Boolean): TripInlineVoiceUi = copy(
    permitted=safety.permits() && tripAllowed,
    block=when {
        safety.carUxAllowed==null->TripInlineVoiceBlock.VEHICLE_STATE
        safety.carUxAllowed==false->TripInlineVoiceBlock.PARK_REQUIRED
        !tripAllowed->TripInlineVoiceBlock.TRIP_STATE
        !safety.foreground->TripInlineVoiceBlock.SCREEN_INACTIVE
        else->null
    })

@Composable
internal fun TripInlineVoiceWithMicrophone(ui: TripInlineVoiceUi,onPress: ()->Boolean,onRelease: ()->Unit,
    onParticipation: (Boolean)->Unit,onRetry: ()->Unit,modifier: Modifier=Modifier,canRequest: ()->Boolean={ui.permitted},onCancel: ()->Unit) {
    val context=LocalContext.current
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    fun granted()=context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED
    var permissionNotice by remember {mutableStateOf<String?>(null)}
    var permissionPending by remember {mutableStateOf(false)}
    // Re-read on resume: the grant can change in system settings while this screen is away.
    var microphoneGranted by remember {mutableStateOf(granted())}
    // 영구 거부를 알게 되면 권한 창 대신 앱 설정을 연다. 설정에서 허용하고 돌아오면 풀린다.
    var microphoneBlocked by rememberSaveable {mutableStateOf(false)}
    DisposableEffect(lifecycle,context) {
        val observer=LifecycleEventObserver {_,event-> if(event==Lifecycle.Event.ON_RESUME) {
            microphoneGranted=granted()
            if(microphoneGranted)microphoneBlocked=false
        }}
        lifecycle.addObserver(observer)
        onDispose {lifecycle.removeObserver(observer)}
    }
    val microphone=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {granted->
        permissionPending=false
        microphoneGranted=granted
        val blocked=!granted && context.activity()?.shouldShowRequestPermissionRationale(Manifest.permission.RECORD_AUDIO)==false
        microphoneBlocked=blocked
        permissionNotice=microphonePermissionNotice(granted,blocked)
    }
    val shown=ui.copy(notice=permissionNotice ?: ui.notice,microphone=microphoneGranted,microphoneBlocked=microphoneBlocked).let {
        if(permissionPending && ui.block !in setOf(TripInlineVoiceBlock.PARK_REQUIRED,TripInlineVoiceBlock.VEHICLE_STATE))
            it.copy(permitted=false,block=TripInlineVoiceBlock.MICROPHONE_PERMISSION) else it
    }
    TripInlineVoiceControl(shown,onPress={
        if(canRequest()) {
            permissionNotice=null
            when(tripMicrophoneRequest(granted(),microphoneBlocked)) {
                TripMicrophoneRequest.RECORD->onPress()
                TripMicrophoneRequest.ASK-> {permissionPending=true;microphone.launch(Manifest.permission.RECORD_AUDIO);false}
                TripMicrophoneRequest.SETTINGS-> {
                    if(!context.openAppDetailsSettings())permissionNotice=TRIP_VOICE_SETTINGS_FAILED
                    false
                }
            }
        } else false
    },onRelease=onRelease,onParticipation={permissionNotice=null;onParticipation(it)},
        onRetry={permissionNotice=null;onRetry()},modifier=modifier,onCancel=onCancel)
}

/** After a denial, no rationale means Android will not show the dialog again; only settings can grant it. */
internal fun microphonePermissionNotice(granted: Boolean,blocked: Boolean)=when {
    granted->"다시 눌러 말해 주세요"
    blocked->TRIP_VOICE_MICROPHONE_SETTINGS_DETAIL
    else->TRIP_VOICE_MICROPHONE_DETAIL
}

internal enum class TripMicrophoneRequest { RECORD, ASK, SETTINGS }

/** 영구 거부 뒤의 권한 요청은 창 없이 바로 거부로 끝나므로, 그때는 앱 설정으로 보낸다. */
internal fun tripMicrophoneRequest(granted: Boolean,blocked: Boolean)=when {
    granted->TripMicrophoneRequest.RECORD
    blocked->TripMicrophoneRequest.SETTINGS
    else->TripMicrophoneRequest.ASK
}

internal const val TRIP_VOICE_SETTINGS_FAILED="기기 설정을 열지 못했어요"

private fun Context.openAppDetailsSettings(): Boolean {
    val intent=Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,android.net.Uri.fromParts("package",packageName,null))
    val host=activity() ?: this.also {intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)}
    return runCatching {host.startActivity(intent)}.isSuccess
}

private tailrec fun Context.activity(): Activity?=when(this) {
    is Activity->this
    is ContextWrapper->baseContext.activity()
    else->null
}

private class TripInlineVoiceOwner(connection: VehicleConnection,trip: TripDetail,
    private val changed: (TripInlineVoiceUi)->Unit) {
    private var closed=false
    private val voice=NativeTripVoiceController(connection,trip.id,trip.title) {value->
        if(!closed)changed(TripInlineVoiceUi(TripInlineVoicePhase.valueOf(value.phase.name),value.participating,notice=value.notice))
    }
    fun start()=voice.start()
    fun retry()=voice.retry()
    fun press()=voice.press()
    fun release()=voice.release()
    fun cancel()=voice.cancel()
    fun setParticipation(value: Boolean)=voice.setParticipation(value)
    fun updateSafety(foreground: Boolean,allowed: Boolean?)=voice.updateSafety(foreground,allowed)
    fun setTripReady(value: Boolean)=voice.setTripReady(value)
    fun close(){closed=true;voice.close()}
}
