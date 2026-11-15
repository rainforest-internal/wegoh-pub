package io.wegoh.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import io.wegoh.app.ui.*

class VehicleClimateActivity: ComponentActivity() {
    private val app get()=application as WegoApplication
    private lateinit var windows: CarWindowVisibility
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        windows=CarWindowVisibility(this) {app.controller.setVisible(it.visible,this,it.focused)}
        setContent {
            BackHandler {finish()}
            ProvideCarWindowVisibility(windows) {WegoCarTheme {
                val allowed=app.controller.state.setupAllowed
                val receiver=rememberVehicleReceiverSettings(this@VehicleClimateActivity)
                val message=receiver.notice ?: if(receiver.enabled)VehicleClimateService.message else "리모컨 수신 꺼짐"
                val retry: ()->Unit={if(app.controller.state.setupAllowed && windows.state.focused)receiver.refresh()}
                CarScreenScaffold("내 차 리모컨",{finish()},{startActivity(Intent(this@VehicleClimateActivity,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP));finish()},showHeader=allowed) {
                    VehicleClimateSettings(allowed,windows.state.focused,receiver.enabled,message,Modifier.weight(1f),
                        canToggle=receiver.canToggle && !receiver.busy,
                        onRetry=retry.takeIf {receiver.retry && !receiver.busy}) {value->
                        if(app.controller.state.setupAllowed && windows.state.focused)receiver.setEnabled(value)
                    }
                }
            }}
        }
    }
    override fun onDestroy() {windows.close();super.onDestroy()}
}

@Composable
internal fun VehicleClimateSettings(allowed: Boolean,focused: Boolean,enabled: Boolean,message: String,modifier: Modifier=Modifier,
    canToggle: Boolean=true,onRetry: (()->Unit)?=null,onEnabled: (Boolean)->Unit) {
    if(!allowed)CarRestrictedState("정차 후 리모컨 수신을 설정하세요",modifier.fillMaxWidth())
    else Column(modifier.fillMaxWidth().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap,Alignment.CenterVertically),horizontalAlignment=Alignment.CenterHorizontally) {
        CarText("내 차 리모컨",style=CarType.Hero)
        CarText(message,secondary=true,maxLines=2)
        CarText("켜면 다른 화면이나 주행 중에도 허용한 조작이 적용돼요",secondary=true,maxLines=2)
        CarText("동승자 권한은 휴대전화의 여행에서 설정하세요",secondary=true,maxLines=2)
        CarActionGroup {
            CarSwitch("리모컨 수신",enabled,enabled=focused && canToggle) {value->
                if(allowed && focused && canToggle)onEnabled(value)
            }
            if(onRetry!=null)CarAction("다시 시도",CarSymbol.Refresh,{if(focused)onRetry()},enabled=focused)
        }
    }
}
