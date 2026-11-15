package io.wegoh.app.nativebusiness

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import io.wegoh.app.nativeauth.*
import io.wegoh.app.AccountReadSnapshot
import io.wegoh.app.ui.*
import java.io.Closeable
import java.time.Instant
import java.time.Duration
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

internal fun historyReadFailure(error: Throwable,detail: Boolean=false): String=when((error as? NativeSocialFailure)?.kind) {
    NativeSocialFailure.Kind.CONSENT_REQUIRED->"이 계정의 여행 기록을 열 수 없습니다"
    NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED->"차량 계정을 다시 연결해주세요"
    NativeSocialFailure.Kind.FORBIDDEN->"이 계정에서 볼 수 없는 기록입니다"
    NativeSocialFailure.Kind.NOT_FOUND->if(detail)"삭제되었거나 더 이상 공유되지 않는 기록입니다" else "조회할 여행 기록이 없습니다"
    else->"기록을 불러오지 못했습니다. 다시 시도해주세요"
}

/** Setup-only, no export, automatic sharing or vehicle command execution. */
@Composable
fun NativeHistoryPanel(connection: VehicleConnection, allowed: Boolean, onBack: ()->Unit,embedded: Boolean=false,
    showEmbeddedHeading: Boolean=true) {
    val focused=LocalCarWindowVisibility.current?.state?.focused==true
    val active=allowed && focused
    var rows by remember(connection) {mutableStateOf<List<SocialHistorySummary>>(emptyList())}
    var cursor by remember(connection) {mutableStateOf<SocialHistoryCursor?>(null)}
    var selected by remember(connection) {mutableStateOf<SocialHistorySummary?>(null)}
    var detail by remember(connection) {mutableStateOf<SocialHistoryDetail?>(null)}
    var detailMessage by remember(connection) {mutableStateOf("")}
    var message by remember(connection) {mutableStateOf("불러오는 중입니다.")}
    var retry by remember(connection) {mutableIntStateOf(0)}
    var client by remember(connection) {mutableStateOf<NativeSocialClient?>(null)}
    var ready by remember(connection) {mutableStateOf(false)}
    var more by remember(connection) {mutableStateOf<Closeable?>(null)}
    var loading by remember(connection) {mutableStateOf(false)}
    fun clear() {rows=emptyList();cursor=null;selected=null;detail=null;loading=false;message="연결과 기록 권한을 확인해 주세요"}
    val snapshot=remember(connection) {AccountReadSnapshot(connection) {clear()}}
    DisposableEffect(connection) {
        val observer=connection.observe {if(snapshot.invalidated()){snapshot.forget();clear()}}
        onDispose {observer.close();snapshot.forget()}
    }
    CarChildBackHandler(enabled=!embedded || selected!=null) {if(selected!=null)selected=null else onBack()}
    DisposableEffect(connection,active,retry) {
        if(snapshot.invalidated()){snapshot.forget();clear()}
        loading=false
        ready=false
        var current=true
        val social=if(active)connection.social() else null
        client=social
        var request: Closeable?=null
        if(social!=null) {
            message=if(rows.isEmpty())"불러오는 중입니다." else "기록을 새로고침하는 중입니다"
            social.open(object: NativeSocialObserver {
                override fun onInvalidated() {
                    if(current) {ready=false;snapshot.forget();clear()}
                }
                override fun onConnectionLost() {
                    if(current) {
                        loading=false
                        ready=false
                        detail=null;detailMessage="연결을 확인한 뒤 다시 시도하세요"
                        if(snapshot.canRetain())message="저장된 기록을 표시합니다. 새로고침으로 현재 상태를 확인하세요"
                        else clear()
                    }
                }
            }) {opened->
                if(current)opened.onSuccess {
                    ready=true
                    request=social.historyApi.readHistoryPage {result->if(current)result.onSuccess {
                        val boundary=connection.verifiedDataBoundary()
                        if(boundary==null){snapshot.forget();clear();return@readHistoryPage}
                        snapshot.remember(boundary)
                        rows=it.history.filter {record->record.own};cursor=it.nextCursor
                        message=if(rows.isEmpty())"저장한 여행 기록이 없습니다." else ""
                    }.onFailure {
                        if((it as? NativeSocialFailure)?.kind in setOf(NativeSocialFailure.Kind.CONSENT_REQUIRED,NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,NativeSocialFailure.Kind.FORBIDDEN,NativeSocialFailure.Kind.NOT_FOUND)) {snapshot.forget();clear();message=historyReadFailure(it)}
                        else message=historyReadFailure(it)
                    }}
                }.onFailure {message="연결을 확인해 주세요"}
            }
        }
        onDispose {current=false;ready=false;request?.close();more?.close();more=null;social?.close();client=null}
    }
    DisposableEffect(connection,active,client,ready,selected?.id,retry) {
        var current=true
        detail=null
        val record=selected;val social=client
        var request: Closeable?=null
        if(active && ready && record!=null && social?.status()==NativeSocialClient.State.READY) {
            detailMessage="기록을 불러오는 중입니다"
            request=social.historyApi.readHistoryItem(record.id) {result->
                if(current)result.onSuccess {value->
                    if(snapshot.canRetain()) {detail=value;detailMessage=""}
                }.onFailure {error->
                    detail=null
                    detailMessage=historyReadFailure(error,true)
                }
            }
        } else if(record!=null)detailMessage="연결을 확인한 뒤 다시 시도하세요"
        onDispose {current=false;request?.close()}
    }
    CarScreenScaffold("여행 기록",{if(selected!=null)selected=null else onBack()},embedded=embedded) {
        if(embedded && showEmbeddedHeading)TripHeading("여행 기록","내가 저장한 여정을 다시 살펴봐요",onBack={if(selected!=null)selected=null else onBack()})
        if(!active)CarRestrictedState(modifier=Modifier.weight(1f))
        else BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
            val narrow=maxWidth/LocalDensity.current.fontScale<CarTokens.Breakpoint
            val catalogue: @Composable (Modifier)->Unit = {modifier->
                CarCard(modifier,tone=CarCardTone.OUTLINED) {
                    CarText("여행 기록",style=CarType.Section)
                    LazyColumn(Modifier.weight(1f).fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                        if(message.isNotEmpty())item {CarText(message,style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)}
                        items(rows,key={it.id}) {record->
                            CarListRow(record.title,listOf(historyDate(record.startedAt),"방문 ${record.visitCount}곳"),CarSymbol.Bookmark,
                                selected=record.id==selected?.id,
                                enabled=snapshot.canRetain() && client?.status()==NativeSocialClient.State.READY,onClick={
                                    if(active && snapshot.canRetain())selected=record
                                })
                        }
                        if(cursor!=null)item {CarButton(if(loading)"불러오는 중" else "더 보기",{
                            val next=cursor;val social=client
                            if(active && next!=null && social?.status()==NativeSocialClient.State.READY && !loading) {
                                loading=true;more=social.historyApi.readHistoryPage(next) {result->
                                    loading=false
                                    result.onSuccess {page->
                                        if(!active || !snapshot.canRetain())return@onSuccess
                                        rows=(rows+page.history.filter {it.own}).distinctBy {it.id};cursor=page.nextCursor
                                    }.onFailure {error->
                                        if((error as? NativeSocialFailure)?.kind in setOf(NativeSocialFailure.Kind.CONSENT_REQUIRED,
                                            NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,NativeSocialFailure.Kind.FORBIDDEN,NativeSocialFailure.Kind.NOT_FOUND)) {
                                            snapshot.forget();clear();message=historyReadFailure(error)
                                        } else message="연결을 확인해 주세요"
                                    }
                                }
                            }
                        },Modifier.fillMaxWidth(),enabled=!loading && client?.status()==NativeSocialClient.State.READY)}
                    }
                    CarButton("새로고침",{if(active)retry++},Modifier.fillMaxWidth(),icon=CarSymbol.Refresh)
                }
            }
            val record: @Composable (Modifier)->Unit = {modifier->
                val current=selected
                if(current==null)CarEmptyState("여행 기록을 골라주세요",modifier,detail="들렀던 장소와 저장한 여정을 확인할 수 있어요",symbol=CarSymbol.Bookmark)
                else NativeHistoryRecord(current,detail,detailMessage,modifier) {selected=null}
            }
            if(narrow) {
                if(selected==null)catalogue(Modifier.fillMaxSize())
                else Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    CarButton("목록으로",{selected=null},Modifier.fillMaxWidth(),icon=CarSymbol.Back)
                    record(Modifier.weight(1f).fillMaxWidth())
                }
            } else Row(Modifier.fillMaxSize(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                catalogue(Modifier.weight(1f).fillMaxHeight())
                record(Modifier.weight(1f).fillMaxHeight())
            }
        }
    }
}

private fun historyDate(value: Instant): String = DateTimeFormatter.ofPattern("yyyy.MM.dd HH:mm",Locale.KOREAN)
    .withZone(ZoneId.systemDefault()).format(value)

private fun historyDuration(record: SocialHistorySummary): String? {
    val ended=record.endedAt ?: return null
    if(ended.isBefore(record.startedAt))return null
    val seconds=Duration.between(record.startedAt,ended).seconds
    return when {
        seconds>=3600->"${seconds/3600}시간 ${seconds%3600/60}분"
        seconds>=60->"${seconds/60}분"
        else->"${seconds}초"
    }
}

@Composable
internal fun NativeHistoryRecord(record: SocialHistorySummary,detail: SocialHistoryDetail?,message: String,
    modifier: Modifier=Modifier,onClose: ()->Unit) {
    LazyColumn(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        item {
            CarCard(tone=CarCardTone.INK,radius=CarTokens.RadiusHero) {
                CarText("저장한 여행",style=CarType.Label,secondary=true)
                CarText(detail?.summary?.title ?: record.title,style=CarType.Hero,maxLines=Int.MAX_VALUE)
                historyDuration(detail?.summary ?: record)?.let {duration->
                    CarText(duration,style=CarType.Hero,maxLines=Int.MAX_VALUE)
                    CarText("여행 시간",style=CarType.Label,secondary=true)
                }
                detail?.let {value->
                    CarText("방문 ${value.summary.visitCount}곳",style=CarType.Section)
                    CarText("시작 ${historyDate(value.summary.startedAt)}",style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)
                    value.summary.endedAt?.let {CarText("종료 ${historyDate(it)}",style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)}
                    value.course?.let {CarText(it.title,style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)}
                }
            }
        }
        if(message.isNotEmpty())item {CarText(message,style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)}
        if(detail!=null) {
            item {CarText("들른 곳",style=CarType.Section)}
            if(detail.visits.isEmpty())item {CarText("보고한 방문 장소가 없어요",style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)}
            items(detail.visits,key={it.id}) {visit->
                CarListRow(visit.place.name,listOf(historyDate(visit.visitedAt),"사용자가 보고한 방문 기록"),CarSymbol.Pin)
            }
        }
        item {CarPhoneHint("여행 기록은 iPhone 앱의 여행에서 확인해 주세요.")}
        item {CarButton("취소",onClose,Modifier.fillMaxWidth(),icon=CarSymbol.Close)}
    }
}
