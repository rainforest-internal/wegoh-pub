package io.wegoh.app

import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.unit.dp
import io.wegoh.app.ui.*

internal class FirstRunGuide(context: Context) {
    private val preferences=context.getSharedPreferences("first_run_guide",Context.MODE_PRIVATE)
    var completed by mutableStateOf(preferences.getBoolean("completed",false))
        private set
    fun complete() {
        preferences.edit().putBoolean("completed",true).apply()
        completed=true
    }
}

@Composable
internal fun FirstRunWalkthrough(allowed: Boolean,canInteract: ()->Boolean,onComplete: ()->Unit) {
    var page by rememberSaveable {mutableIntStateOf(0)}
    if(!allowed) {
        CarRestrictedState()
        return
    }
    val (title,description)=when(page) {
        0->"경로를 차에서 시작해요" to "휴대전화에서 준비한 경로를 불러와\n내비게이션으로 출발하세요"
        1->"내 음악을 차에서" to "저장한 음악 링크를 차에서 열어요"
        else->"휴대전화로 차량 연결" to "iPhone에서 QR 코드를 스캔하거나\n연결 코드를 입력하세요"
    }
    VehicleOnboardingLayout(
        onSkip={if(allowed && canInteract())onComplete()},
        artwork={VehicleOnboardingArtwork(page)},
        actions={
            if(page>0)VehicleOnboardingButton("이전",{if(allowed && canInteract())page--},Modifier.weight(1f),icon=CarSymbol.Back)
            else Spacer(Modifier.weight(1f))
            VehicleOnboardingButton(if(page==2)"계속" else "다음",
                {if(allowed && canInteract()) {if(page==2)onComplete() else page++}},Modifier.weight(1f),primary=true,icon=CarSymbol.Next)
        }) {
        VehicleOnboardingSteps(page)
        CarText(title,style=CarType.Hero,maxLines=3)
        CarText(description,secondary=true,maxLines=3)
    }
}
