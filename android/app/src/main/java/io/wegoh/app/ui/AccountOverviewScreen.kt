package io.wegoh.app.ui

import androidx.compose.ui.text.style.TextAlign
import androidx.compose.foundation.background
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import io.wegoh.app.*
import kotlinx.coroutines.launch

@Composable
internal fun AccountProfileScreen(state: AccountProfileState,onConnection: ()->Unit,onWebInfo: ()->Unit,
    onReload: ()->Unit = {},onBack: (()->Unit)?=null) {
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading("내 정보",onBack=onBack)
        if(state.status!=AccountReadStatus.READY || state.name==null) {
            when(state.status) {
                AccountReadStatus.LOADING->CarLoadingState("프로필을 불러오는 중",Modifier.weight(1f).fillMaxWidth())
                AccountReadStatus.CONNECTION_REQUIRED->CarConnectionState("차량을 연결해 주세요",Modifier.weight(1f).fillMaxWidth(),onConnect=onConnection)
                else->CarFailureState("프로필을 불러오지 못했어요",Modifier.weight(1f).fillMaxWidth(),reportScreen="account.profile",onRetry=onReload)
            }
        } else Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            CarCard(outlined=true,padding=PaddingValues(CarTokens.Frame)) {
                ProfileValueRow("이름",state.name)
                TripDivider()
                val missingVehicle=when {
                    state.vehicleLoading->"불러오는 중"
                    state.vehicleUnavailable->"불러오지 못했어요"
                    else->"차량 정보를 확인할 수 없어요"
                }
                ProfileValueRow("차량 이름",state.vehicle?.displayName ?: missingVehicle)
                TripDivider()
                ProfileValueRow("차량 번호",state.vehicle?.plateNumber?.ifEmpty {"미등록"} ?: missingVehicle)
                if(state.vehicleUnavailable)CarButton("다시 불러오기",onReload,enabled=state.isCurrent,icon=CarSymbol.Refresh)
            }
            CarPhoneHandoff("profile")
        }
    }
}

@Composable
private fun ProfileValueRow(label: String,value: String) {
    // 라벨을 값 위에 두어 짧은 값 앞에 고정 비율 빈 열이 생기지 않게 한다.
    Column(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall,Alignment.CenterVertically)) {
        CarText(label,style=CarType.Label,secondary=true,maxLines=2)
        CarText(value,style=CarType.Body,maxLines=2)
    }
}

@Composable
internal fun AccountDiscoveryScreen(state: AccountDiscoveryState,installed: Set<String>,onDownload: (PublishedPack)->Unit,
    onConnection: (()->Unit)?,canDownload: Boolean) {
    val list=rememberLazyListState()
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
        if(state.status!=AccountReadStatus.READY) {
            val label=when(state.status) {
                AccountReadStatus.CONNECTION_REQUIRED->"차량을 연결해 주세요"
                AccountReadStatus.PERMISSION_REQUIRED->"이 차에서 경로를 볼 권한이 없어요"
                AccountReadStatus.LOADING->"공개 경로를 불러오는 중"
                else->"경로를 불러오지 못했어요"
            }
            if(state.status==AccountReadStatus.LOADING)CarLoadingState(label,Modifier.weight(1f))
            else CarEmptyState(label,Modifier.weight(1f),action={
                if(onConnection!=null && state.status in setOf(AccountReadStatus.CONNECTION_REQUIRED,AccountReadStatus.PERMISSION_REQUIRED))CarAction("차량 연결",CarSymbol.Link,onConnection)
            })
        } else if(state.packs.isEmpty())CarEmptyState("공개 경로가 없어요",Modifier.weight(1f))
        else {
            Row(Modifier.fillMaxWidth()) {CarText("공개 경로",Modifier.weight(1f),style=CarType.Hero);CarScrollPosition(list,state.packs.size,"발견 목록")}
            LazyColumn(Modifier.weight(1f).fillMaxWidth(),state=list,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                items(state.packs,key={it.key}) {pack ->CarListRow(pack.title,listOf(pack.author,"v${pack.version}","${pack.stopCount}곳"),CarSymbol.Route,
                    trailing={val saved=pack.key in installed
                        CarAction(if(saved)"받음" else "받기",if(saved)CarSymbol.Check else CarSymbol.Download,{onDownload(pack)},
                            enabled=state.isCurrent && !saved && canDownload && state.downloading==null,busy=state.downloading==pack.key,
                            accessibility="${pack.title} v${pack.version} ${if(saved)"받음" else "받기"}")})}
            }
        }
    }
}
