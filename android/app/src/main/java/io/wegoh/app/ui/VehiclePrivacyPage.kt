@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import android.content.pm.PackageManager
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.wegoh.app.VehicleRuntimePermissions
import io.wegoh.app.readVehicleRuntimePermissions

@Composable
internal fun VehiclePrivacyPage(locationConsented: Boolean,onSuspend: ()->Unit,onWithdraw: ()->Unit,
    onSettings: ()->Unit,onDisclosure: ()->Unit,onPrivacyPolicy: (()->Unit)?=null,onLocationTerms: (()->Unit)?=null,
    onBack: (()->Unit)?=null,permissionRefresh: Int=0) {
    val permissions=rememberVehicleRuntimePermissions(permissionRefresh)
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val narrow=maxWidth<CarTokens.Breakpoint
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            TripHeading("권한 관리","프로필 → 권한 관리",onBack)
            TripAdaptiveRow(narrow=narrow,gap=CarTokens.Gap) {
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    DevicePermissionCard("위치",when {
                        permissions.preciseLocation->"정확한 위치"
                        permissions.approximateLocation->"대략적인 위치"
                        else->"방문 장소 확인"
                    },CarSymbol.Pin,permissions.preciseLocation || permissions.approximateLocation,
                        if(!permissions.preciseLocation && permissions.approximateLocation)"부분 허용" else null)
                    DevicePermissionCard("차량 위치","현재 위치 확인",
                        CarSymbol.Car,permissions.vehicleLocation)
                }
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    DevicePermissionCard("마이크","워키토키 음성 전송",CarSymbol.Microphone,permissions.microphone)
                    DevicePermissionCard("차량 속도","안전운전 점수 계산",CarSymbol.Speed,permissions.vehicleSpeed)
                }
            }
            CarButton("기기 설정",onSettings,Modifier.fillMaxWidth(),icon=CarSymbol.Settings)
            Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                CarCard(outlined=true,padding=PaddingValues(CarTokens.Frame)) {
                    CarButton("위치 사용 일시중지",onSuspend,Modifier.fillMaxWidth(),icon=CarSymbol.Pause,enabled=locationConsented)
                    VehicleSecondaryNavigationRow("위치 정보 사용 안내",CarSymbol.Info,onDisclosure)
                    onPrivacyPolicy?.let {VehicleSecondaryNavigationRow("개인정보처리방침",CarSymbol.Shield,it)}
                    onLocationTerms?.let {VehicleSecondaryNavigationRow("위치 이용약관",CarSymbol.Pin,it)}
                }
                CarButton("동의 철회 및 기록 삭제",onWithdraw,Modifier.fillMaxWidth(),variant=CarButtonStyle.DANGER,icon=CarSymbol.Delete)
            }
        }
    }
}

@Composable
private fun DevicePermissionCard(title: String,detail: String,symbol: CarSymbol,granted: Boolean,status: String?=null) {
    CarCard(outlined=true,padding=PaddingValues(CarTokens.Gap)) {
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
            CarIcon(symbol,Modifier.size(CarTokens.Icon))
            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                CarText(title,style=CarType.Section,maxLines=2)
                CarText(detail,style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)
            }
            val (label,tone)=devicePermissionStatus(granted,status)
            CarStatusPill(label,kind=tone)
        }
    }
}

/** Granted is the quiet normal state; missing or partial permission is what the driver may need to act on,
 *  so it gets the accent. Neither is a filled button-like chip. */
internal fun devicePermissionStatus(granted: Boolean,status: String?): Pair<String,CarStatusTone> = when {
    status!=null->status to CarStatusTone.SOFT
    granted->"허용됨" to CarStatusTone.NEUTRAL
    else->"허용 안 됨" to CarStatusTone.SOFT
}

@Composable
private fun rememberVehicleRuntimePermissions(refresh: Int): VehicleRuntimePermissions {
    val context=LocalContext.current
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    val view=LocalView.current
    fun read()=readVehicleRuntimePermissions {context.checkSelfPermission(it)==PackageManager.PERMISSION_GRANTED}
    var permissions by remember(context,refresh) {mutableStateOf(read())}
    DisposableEffect(context,lifecycle,view,refresh) {
        val observer=LifecycleEventObserver {_,event->if(event==Lifecycle.Event.ON_RESUME)permissions=read()}
        val focus=android.view.ViewTreeObserver.OnWindowFocusChangeListener {if(it)permissions=read()}
        val tree=view.viewTreeObserver
        lifecycle.addObserver(observer)
        tree.addOnWindowFocusChangeListener(focus)
        onDispose {
            lifecycle.removeObserver(observer)
            if(tree.isAlive)tree.removeOnWindowFocusChangeListener(focus)
        }
    }
    return permissions
}
