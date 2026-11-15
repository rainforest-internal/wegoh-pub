package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import io.wegoh.app.nativeauth.TripMusic
import androidx.compose.ui.platform.LocalDensity
import io.wegoh.app.*

@Composable
internal fun AccountMusicScreen(state: AccountPlaylistState,picker: Boolean,onPick: ()->Unit,
    onSelect: (PlaylistSummary)->Unit,onConnection: ()->Unit,onLink: (String,Long,String)->Unit,
    currentTripTitle: String?=null,currentTripMusic: TripMusic?=null,onTripMusic: (()->Unit)?=null,showDetails: Boolean=true) {
    CarChildBackHandler(enabled=showDetails && state.selected!=null && !picker,onBack=onPick)
    val catalogue=rememberLazyListState();val tracks=rememberLazyListState()
    val list=if(picker)catalogue else tracks
    LaunchedEffect(state.selected?.summary?.id,state.selected?.summary?.revision) {tracks.scrollToItem(0)}
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
        if(state.status!=AccountPlaylistStatus.READY) {
            val label=when(state.status) {
                AccountPlaylistStatus.CONNECTION_REQUIRED->"차량을 연결해 주세요"
                AccountPlaylistStatus.PERMISSION_REQUIRED->"이 차에서 음악을 볼 권한이 없어요"
                AccountPlaylistStatus.LOADING->"음악을 불러오는 중"
                else->"음악을 불러오지 못했어요"
            }
            if(state.status==AccountPlaylistStatus.LOADING)CarLoadingState(label,Modifier.weight(1f))
            else CarEmptyState(label,Modifier.weight(1f),symbol=CarSymbol.Music,action={
                if(state.status in setOf(AccountPlaylistStatus.CONNECTION_REQUIRED,AccountPlaylistStatus.PERMISSION_REQUIRED))CarAction("차량 연결",CarSymbol.Link,onConnection)
            })
        } else if(picker || state.selected==null || !showDetails) {
            val cataloguePane: @Composable (Modifier)->Unit={modifier->
                Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                        CarText("내 플레이리스트",Modifier.weight(1f),style=CarType.Section)
                        CarText("${state.items.size}개",secondary=true)
                    }
                    if(state.items.isNotEmpty())CarScrollPosition(catalogue,state.items.size,"음악 목록")
                    if(state.items.isEmpty())CarEmptyState("저장한 플레이리스트가 없어요",Modifier.weight(1f),symbol=CarSymbol.Music)
                    else LazyColumn(Modifier.weight(1f).fillMaxWidth(),state=catalogue,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                        items(state.items,key={it.id}) {item->CarMusicRow(item.name,listOf("링크 ${item.count}개")) {
                            val opening=state.opening==item.id
                            CarButton(if(opening)"불러오는 중" else "선택",{onSelect(item)},
                                enabled=state.isCurrent && (state.opening==null || opening),busy=opening,
                                accessibility="${item.name} ${if(opening)"불러오는 중" else "선택"}")
                        }}
                    }
                    CarPhoneHandoff("music")
                }
            }
            if(!picker && currentTripTitle!=null) {
                val current: @Composable ()->Unit={
                    CarCard(tone=CarCardTone.INK) {
                        TripText("진행 중인 여행",style=CarType.Label,secondary=true)
                        TripText(currentTripTitle,style=CarType.Section,maxLines=2)
                        currentTripMusic?.name?.let {TripText(it,style=CarType.Body,maxLines=2)}
                        currentTripMusic?.djName?.let {TripText("DJ $it",style=CarType.Label,secondary=true,maxLines=2)}
                        if(onTripMusic!=null)CarButton("여행 음악",onTripMusic,Modifier.fillMaxWidth(),
                            variant=CarButtonStyle.INK_OUTLINE,enabled=state.isCurrent)
                    }
                }
                if(LocalTripLayoutWidth.current<CarTokens.Breakpoint) {
                    current();cataloguePane(Modifier.weight(1f))
                } else Row(Modifier.weight(1f).fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
                    Column(Modifier.weight(1f)) {current()}
                    cataloguePane(Modifier.weight(1f).fillMaxHeight())
                }
            } else cataloguePane(Modifier.weight(1f))
        } else {
            val detail=state.selected
            BoxWithConstraints(Modifier.fillMaxWidth()) {
                val title: @Composable (Modifier)->Unit = {modifier->Column(modifier) {CarText(detail?.summary?.name ?: "플레이리스트를 선택해 주세요",style=CarType.Hero,maxLines=2)
                    CarText(detail?.let {"링크 ${it.tracks.size}개"} ?: "내 플레이리스트",secondary=true)}
                }
                if(maxWidth/LocalDensity.current.fontScale<CarTokens.Breakpoint)Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    title(Modifier.fillMaxWidth())
                    CarActionGroup {CarAction("다른 플레이리스트",CarSymbol.Music,onPick)}
                } else Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    title(Modifier.weight(1f));CarAction("다른 플레이리스트",CarSymbol.Music,onPick)
                }
            }
            if(detail==null)CarEmptyState("플레이리스트를 선택해 주세요",Modifier.weight(1f),symbol=CarSymbol.Music)
            if(detail!=null) {
                CarScrollPosition(list,detail.tracks.size,"음악 목록")
                if(detail.tracks.isEmpty())CarEmptyState("저장한 음악 링크가 없어요",Modifier.weight(1f),
                    detail="iPhone 앱에서 음악 링크를 추가해 주세요",symbol=CarSymbol.Music)
                else LazyColumn(Modifier.weight(1f).fillMaxWidth(),state=list,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    items(detail.tracks,key={it.id}) {track ->CarMusicRow(track.title,listOf(track.host)) {
                        CarButton("링크 열기",{onLink(detail.summary.id,detail.summary.revision,track.id)},icon=CarSymbol.Link,
                            enabled=state.isCurrent,accessibility="${track.title} 링크 열기")
                    }}
                }
            }
        }
    }
}
