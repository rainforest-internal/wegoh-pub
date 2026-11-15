package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import io.wegoh.app.*
import io.wegoh.app.nativeauth.TripSavedPlaylist

@Composable
internal fun TripMusicPage(title: String,state: TripMusicState,enabled: Boolean,onBack: ()->Unit,onRefresh: ()->Unit,
    onSources: ()->Unit,onAdd: (TripMusicSourceItem)->Unit,onPlay: (TripSavedPlaylist)->Unit,onConnection: ()->Unit,
    djName: String?=null,onPlayNext: ()->Unit={},onQueueNext: (TripSavedPlaylist)->Unit={},onDismissAnnouncement: (Int)->Unit={},
    listenTogether: (@Composable (Boolean)->Unit)?=null) {
    val interactive=enabled && !state.refreshing && !state.writing
    var pendingSource by remember {mutableStateOf<TripMusicSourceItem?>(null)}
    var pendingSequence by remember {mutableIntStateOf(state.addedSequence)}
    var confirmed by remember {mutableStateOf(false)}
    val currentState by rememberUpdatedState(state)
    val currentEnabled by rememberUpdatedState(enabled)
    val currentAdd by rememberUpdatedState(onAdd)
    fun canAdd(item: TripMusicSourceItem): Boolean {
        val current=currentState
        return currentEnabled && !current.refreshing && !current.writing &&
            current.status==TripMusicStatus.READY && current.collection?.canAdd==true &&
            current.sourceStatus==TripMusicStatus.READY && item in current.sources
    }
    fun requestAdd(item: TripMusicSourceItem) {
        if(pendingSource==null && canAdd(item)) {
            pendingSequence=currentState.addedSequence;confirmed=false;pendingSource=item
        }
    }
    LaunchedEffect(state.status,state.sourceStatus,state.sources,state.addedSequence) {
        if(state.status!=TripMusicStatus.READY || state.sourceStatus!=TripMusicStatus.READY ||
            pendingSource !in state.sources || state.addedSequence!=pendingSequence)pendingSource=null
    }
    Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading("여행 음악",onBack=onBack,badge=if(state.refreshing)"새로고침 중" else null)
        CarMetadata(listOfNotNull(title,djName?.takeIf {it.isNotBlank()}?.let {"DJ $it"}))
        if(state.notice!=null)TripText(state.notice,secondary=true,maxLines=CarMessageLines)
        TripMusicAnnouncementBanner(state.announcement,onDismissAnnouncement)
        listenTogether?.invoke(enabled)
        BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
            val narrow=maxWidth/LocalDensity.current.fontScale<CarTokens.Breakpoint
            LaunchedEffect(state.sourceStatus,enabled,state.status,state.refreshing) {
                if(enabled && !state.refreshing && state.status==TripMusicStatus.READY && state.sourceStatus==TripMusicStatus.IDLE)onSources()
            }
            val collection: @Composable (Modifier)->Unit={modifier->
                CarCard(modifier,tone=CarCardTone.OUTLINED) {
                    CarMetadata(listOfNotNull("추가한 음악",state.collection?.takeIf {state.status==TripMusicStatus.READY}?.let {"링크 ${it.items.size}개"}),
                        style=CarType.Section,secondary=false)
                    TripMusicCollectionPane(state,interactive,onPlay,onPlayNext,onQueueNext,onRefresh,Modifier.weight(1f))
                }
            }
            val sources: @Composable (Modifier)->Unit={modifier->
                Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    CarCard(Modifier.weight(1f),tone=CarCardTone.OUTLINED) {
                    TripText("내 음악에서 추가",style=CarType.Section,maxLines=2)
                    TripText("검토를 통과한 음악의 제목과 링크는 일행에게 공개돼요",style=CarType.Label,secondary=true,maxLines=3)
                    if(state.status==TripMusicStatus.READY)TripMusicSourcesPane(state,interactive,onSources,::requestAdd,onConnection,Modifier.weight(1f))
                    else CarEmptyState("내 음악",Modifier.weight(1f),symbol=CarSymbol.Music)
                    }
                    CarPhoneHandoff("music-link")
                }
            }
            if(narrow)Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                collection(Modifier.weight(1f).fillMaxWidth());sources(Modifier.weight(1f).fillMaxWidth())
            } else Row(Modifier.fillMaxSize(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                collection(Modifier.weight(1f).fillMaxHeight());sources(Modifier.weight(1f).fillMaxHeight())
            }
        }
    }
    pendingSource?.let {item->
        val busy=state.adding==item.key
        fun dismiss() {if(currentState.adding!=item.key)pendingSource=null}
        CarPopup("여행에 추가할까요?",::dismiss,body={
            TripText(item.title,style=CarType.Section,maxLines=3)
            TripText("제목과 링크를 일행과 공유하고 운영 검토를 요청해요.",style=CarType.DialogBody,maxLines=4)
            TripText("공유할 권리가 있는 음악인지 확인해 주세요.",style=CarType.DialogBody,maxLines=3)
            if(confirmed)state.notice?.let {TripText(it,secondary=true,maxLines=3)}
        },actions={
            CarButton("동의하고 추가",{
                if(pendingSource==item && canAdd(item)) {confirmed=true;currentAdd(item)}
            },Modifier.weight(1f),primary=true,enabled=canAdd(item),busy=busy)
            CarButton("취소",::dismiss,Modifier.weight(1f),enabled=!busy)
        })
    }
}

@Composable
private fun TripMusicCollectionPane(state: TripMusicState,interactive: Boolean,onPlay: (TripSavedPlaylist)->Unit,
    onPlayNext: ()->Unit,onQueueNext: (TripSavedPlaylist)->Unit,onRefresh: ()->Unit,modifier: Modifier) {
    Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
        when(state.status) {
            TripMusicStatus.IDLE,TripMusicStatus.LOADING->CarLoadingState("여행 음악 불러오는 중",Modifier.weight(1f))
            TripMusicStatus.READY->{
                val collection=checkNotNull(state.collection)
                if(!collection.canAdd)TripText("음악 목록이 가득 찼어요",secondary=true,maxLines=2)
                if(collection.items.isNotEmpty())Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),
                    verticalAlignment=Alignment.CenterVertically) {
                    val lines=tripMusicPlayingLines(collection)
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        if(lines!=null) {
                            TripText("마지막으로 연 음악",style=CarType.Caption,secondary=true)
                            TripText(lines.first,style=CarType.Label,maxLines=2)
                            CarMetadata(lines.second,style=CarType.Caption)
                        } else TripText("아직 연 음악 링크가 없어요",style=CarType.Label,maxLines=2)
                    }
                    CarButton(if(collection.mine==null)"첫 링크 열기" else "다음 링크 열기",onPlayNext,primary=true,enabled=interactive,
                        icon=CarSymbol.Next)
                }
                if(collection.items.isEmpty())CarEmptyState("추가한 음악 링크가 없어요",Modifier.weight(1f),symbol=CarSymbol.Music)
                else LazyColumn(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    items(collection.items,key={it.id}) {item->
                        val mine=collection.mine?.itemId==item.id
                        CarMusicRow(item.title,listOfNotNull("${item.addedByName} 추가",
                        when(item.reviewState) {"approved"->"일행에게 공개";"quarantined"->"검토 중";"rejected"->"공유 보류";else->null},
                        "나에게만 표시".takeUnless {item.reviewState=="approved"})) {
                        Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                            if(mine)CarStatusPill("마지막으로 연 링크",kind=CarStatusTone.NEUTRAL)
                            else if(collection.canReorder)CarButton(if(state.moving==item.id)"옮기는 중" else if(collection.mine==null)"맨 앞으로" else "다음 순서로",{onQueueNext(item)},
                                enabled=interactive,busy=state.moving==item.id,variant=CarButtonStyle.SOFT,
                                accessibility="${item.title} "+if(collection.mine==null)"맨 앞으로 옮기기" else "다음 순서로 옮기기")
                            CarButton(if(state.playing==item.id)"여는 중" else "열기",{onPlay(item)},enabled=interactive,busy=state.playing==item.id,icon=CarSymbol.Link,
                                accessibility="${item.title} 링크 열기")
                        }
                    }}
                }
            }
            else->CarEmptyState("여행 음악을 불러오지 못했어요",Modifier.weight(1f),symbol=CarSymbol.Music,
                action={CarButton("다시 불러오기",onRefresh,primary=true,enabled=interactive)})
        }
    }
}

@Composable
private fun TripMusicSourcesPane(state: TripMusicState,interactive: Boolean,onSources: ()->Unit,
    onAdd: (TripMusicSourceItem)->Unit,onConnection: ()->Unit,modifier: Modifier) {
    Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
        when(state.sourceStatus) {
            TripMusicStatus.IDLE,TripMusicStatus.LOADING->CarLoadingState("내 음악 불러오는 중",Modifier.weight(1f))
            TripMusicStatus.PERMISSION_REQUIRED->CarEmptyState("내 음악을 열 수 없어요",Modifier.weight(1f),
                detail="연결 관리에서 음악 접근을 허용해 주세요",symbol=CarSymbol.Music,
                action={CarButton("연결 관리",onConnection,primary=true,enabled=interactive)})
            TripMusicStatus.UNAVAILABLE->CarEmptyState("내 음악을 불러오지 못했어요",Modifier.weight(1f),symbol=CarSymbol.Music,
                action={CarButton("다시 불러오기",onSources,primary=true,enabled=interactive)})
            TripMusicStatus.READY->if(state.sources.isEmpty())CarEmptyState("저장한 음악이 없어요",Modifier.weight(1f),
                symbol=CarSymbol.Music,
                action={CarButton("새로고침",onSources,enabled=interactive)})
            else LazyColumn(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                items(state.sources,key={it.key}) {item->CarMusicRow(item.title,listOf(item.provider)) {
                    if(item.url.isNotBlank() && state.collection?.items?.any {it.url==item.url}==true)CarStatusPill("추가됨",kind=CarStatusTone.NEUTRAL)
                    else CarButton(if(state.adding==item.key)"추가 중" else "여행에 추가",{onAdd(item)},busy=state.adding==item.key,
                        enabled=interactive && state.adding==null && state.collection?.canAdd==true,variant=CarButtonStyle.SOFT,
                        accessibility="${item.title} 여행에 추가")
                }}
            }
        }
    }
}
