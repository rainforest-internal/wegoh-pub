package io.wegoh.app

import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.wegoh.app.ui.*

internal class FirstRunPermissionState(completed: Boolean,private val saveCompleted: ()->Unit) {
    var completed by mutableStateOf(completed)
        private set

    fun eligible(walkthroughCompleted: Boolean,connected: Boolean)=!completed && (walkthroughCompleted || connected)

    fun shouldShow(walkthroughCompleted: Boolean,connected: Boolean,allGranted: Boolean)=
        eligible(walkthroughCompleted,connected) && !allGranted

    fun skipGranted(walkthroughCompleted: Boolean,connected: Boolean,allGranted: Boolean) {
        if(eligible(walkthroughCompleted,connected) && allGranted)complete()
    }

    fun complete() {
        if(completed)return
        saveCompleted()
        completed=true
    }
}

@Composable
internal fun FirstRunPermissionEntry(walkthroughCompleted: Boolean,connected: Boolean,setupAllowed: Boolean,
    foreground: Boolean,canRequest: ()->Boolean,content: @Composable ()->Unit) {
    val context=LocalContext.current
    val state=remember(context) {
        val preferences=context.getSharedPreferences(VehicleAppDependencies.preferenceName("first_run_permissions"),Context.MODE_PRIVATE)
        FirstRunPermissionState(preferences.getBoolean("completed",false)) {
            preferences.edit().putBoolean("completed",true).apply()
        }
    }
    val permissions=remember {WegoController.PERMISSIONS+"android.car.permission.CAR_SPEED"}
    val allGranted=permissions.all {context.checkSelfPermission(it)==PackageManager.PERMISSION_GRANTED}
    LaunchedEffect(walkthroughCompleted,connected,allGranted) {
        state.skipGranted(walkthroughCompleted,connected,allGranted)
    }
    if(!setupAllowed || !state.shouldShow(walkthroughCompleted,connected,allGranted)) {
        content()
        return
    }
    if(LocalActivityResultRegistryOwner.current==null) {
        ConnectionEntry(fullScreen=true) {
            FirstRunPermissionScreen(foreground,false,onRequest={},
                onLater={if(canRequest())state.complete()},requestAvailable=false)
        }
        return
    }
    FirstRunPermissionRequest(state,permissions,foreground,canRequest)
}

@Composable
private fun FirstRunPermissionRequest(state: FirstRunPermissionState,permissions: Array<String>,
    foreground: Boolean,canRequest: ()->Boolean) {
    var requesting by rememberSaveable {mutableStateOf(false)}
    var requestGeneration by remember {mutableIntStateOf(0)}
    val launcher=rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        requesting=false
        state.complete()
    }
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    val view=LocalView.current
    DisposableEffect(lifecycle,view) {
        var recovery: Runnable?=null
        fun recoverReturnedRequest() {
            if(!requesting)return
            recovery?.let(view::removeCallbacks)
            val generation=requestGeneration
            recovery=Runnable {
                if(requesting && requestGeneration==generation &&
                    lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) && view.hasWindowFocus())requesting=false
            }.also(view::postOnAnimation)
        }
        val observer=LifecycleEventObserver {_,event->if(event==Lifecycle.Event.ON_RESUME)recoverReturnedRequest()}
        val focus=android.view.ViewTreeObserver.OnWindowFocusChangeListener {if(it)recoverReturnedRequest()}
        val tree=view.viewTreeObserver
        lifecycle.addObserver(observer);tree.addOnWindowFocusChangeListener(focus);recoverReturnedRequest()
        onDispose {
            lifecycle.removeObserver(observer)
            if(tree.isAlive)tree.removeOnWindowFocusChangeListener(focus)
            recovery?.let(view::removeCallbacks)
        }
    }
    ConnectionEntry(fullScreen=true) {
        FirstRunPermissionScreen(foreground,requesting,
            onRequest={
                if(canRequest() && !requesting) {
                    requestGeneration++
                    requesting=true
                    launcher.launch(permissions)
                }
            },onLater={if(canRequest() && !requesting)state.complete()})
    }
}

@Composable
internal fun FirstRunPermissionScreen(interactive: Boolean,requesting: Boolean,onRequest: ()->Unit,onLater: ()->Unit,
    requestAvailable: Boolean=true) {
    VehicleOnboardingLayout(artwork={VehiclePermissionArtwork()},permission=true,
        actions={
            VehicleOnboardingButton("나중에",onLater,Modifier.weight(1f),enabled=interactive && !requesting)
            VehicleOnboardingButton("권한 설정",onRequest,Modifier.weight(1f),primary=true,icon=CarSymbol.Check,
                enabled=requestAvailable && interactive && !requesting)
        }) {
        CarText("앱 권한",style=CarType.Hero,maxLines=3)
        VehiclePermissionRow(CarSymbol.Pin,"위치","경로 진행을 확인하고 여행 일행에게 위치를 공유해요")
        VehiclePermissionRow(CarSymbol.Car,"차량 속도","안전운전 점수를 계산해요")
        CarText("탑승부터 하차까지 모든 차의 점수를 일행과 비교해요",style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)
        CarText("점수를 보낼 때 속도, 위치 등 원본 데이터는 보내지 않아요",style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)
        CarText("차량 위치 서비스 권한은 '알 수 없는 작업'으로 표시될 수 있어요.",style=CarType.Label,secondary=true,maxLines=3)
        CarText("나중에 허용해도 앱을 사용할 수 있어요.",style=CarType.Label,secondary=true,maxLines=2)
    }
}
