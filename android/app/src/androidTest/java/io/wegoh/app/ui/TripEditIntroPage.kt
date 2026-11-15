@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
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
internal fun TripEditIntroPage(trip: TripDetail,enabled: Boolean,actions: TripUiActions,onBack: ()->Unit) {
    var title by remember(trip.id) {mutableStateOf(trip.title)}
    var description by remember(trip.id) {mutableStateOf(trip.description)}
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading("여행 소개 고치기","정차 중에만 글자를 입력할 수 있어요",onBack)
        Box(Modifier.weight(1f)) {
            val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
            TripAdaptiveRow(Modifier.fillMaxSize().then(if(narrow)Modifier.verticalScroll(rememberScrollState()) else Modifier),narrow=narrow,gap=CarTokens.Frame) {
                Column(Modifier.weight(1f).then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    TripField("여행 이름",title,{title=it},40,enabled)
                    TripField("소개 (없어도 돼요)",description,{description=it},300,enabled,multiline=true)
                    if(title.isBlank())TripText("여행 이름을 적어 주세요")
                    Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                        CarButton("취소",onBack,Modifier.weight(1f))
                        CarButton("저장",{actions.perform(TripAction.EditIntro(title,description),onBack)},Modifier.weight(1f),primary=true,enabled=enabled && title.isNotBlank())
                    }
                }
                Column(Modifier.weight(1f).then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    CarPhoneHint("iPhone 앱의 여행에서 이름과 소개를 고치면 여기에 바로 보여요.")
                    TripText("만든 사람과 편집 권한이 있는 멤버만 고칠 수 있어요. 이름과 소개는 다른 멤버에게도 바로 보여요.",secondary=true,maxLines=Int.MAX_VALUE)
                }
            }
        }
    }
}
