@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.toggleableState
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.unit.Dp
import io.wegoh.app.AccountReadStatus
import java.util.Locale

internal enum class VehicleCourseFeedTab(val label: String) {
    RECOMMENDED("추천"), SUBSCRIPTIONS("구독"), MINE("내 경로"), SAVED("저장한 경로")
}

internal data class VehicleCourseFeedCard(val key: String,val title: String,val author: String,
    val stopCount: Int?=null,val routeSummary: String="",val tags: List<String> = emptyList(),
    val starCount: Int?=null,val isNew: Boolean=false,val canOpen: Boolean=true,val canAdd: Boolean=true,val creatorRank: Int?=null,
    val published: io.wegoh.app.PublishedPack?=null)

internal data class VehicleCourseFeedState(val tab: VehicleCourseFeedTab=VehicleCourseFeedTab.RECOMMENDED,
    val status: AccountReadStatus=AccountReadStatus.CONNECTION_REQUIRED,
    val courses: List<VehicleCourseFeedCard> = emptyList(),val availableTags: List<String> = emptyList(),
    val selectedTags: Set<String> = emptySet(),val unreadCount: Int?=null,
    val followingNames: List<String> = emptyList(),val isCurrent: Boolean=true,val sortLabel: String?=null,
    val followingTags: List<String> = emptyList())

internal fun vehicleCourseTagKey(tag: String)=tag.trim().removePrefix("#").lowercase(Locale.ROOT)

/** Same column rule as GridCells.Adaptive, so a row of cards can share one height. */
internal fun vehicleCourseFeedColumns(width: Dp,narrow: Boolean): Int =
    if(narrow)1 else ((width+CarTokens.Gap)/(CarTokens.CourseCardMinWidth+CarTokens.Gap)).toInt().coerceAtLeast(1)

internal fun vehicleCourseFeedCards(state: VehicleCourseFeedState): List<VehicleCourseFeedCard> {
    val selected=state.selectedTags.map(::vehicleCourseTagKey).toSet()
    return state.courses.filter {course->course.tags.map(::vehicleCourseTagKey).toSet().containsAll(selected)}
}

@Composable
internal fun VehicleCourseFeed(state: VehicleCourseFeedState,onTab: (VehicleCourseFeedTab)->Unit,
    onTag: (String?)->Unit,onRetry: ()->Unit,onConnection: ()->Unit,
    onOpen: (String)->Unit,onAdd: (String)->Unit,openingKey: String?=null) {
    val cards=vehicleCourseFeedCards(state)
    val readable=state.status==AccountReadStatus.READY
    val current=readable && state.isCurrent
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    val tags=(state.availableTags+state.selectedTags).distinctBy(::vehicleCourseTagKey)
    val followedTags=state.followingTags.distinctBy(::vehicleCourseTagKey)
    BoxWithConstraints(Modifier.fillMaxSize()) {
    val columns=vehicleCourseFeedColumns(maxWidth-CarTokens.PagePrimaryPaddingHorizontal*2,narrow)
    // Cards are laid out a row at a time: each row takes its tallest card's height and every card pins its
    // actions to the bottom, so buttons in one row share a line even when one card has tags or a rank.
    LazyVerticalGrid(GridCells.Fixed(1),Modifier.fillMaxSize(),
        contentPadding=PaddingValues(horizontal=CarTokens.PagePrimaryPaddingHorizontal,vertical=CarTokens.PagePrimaryPaddingVertical),
        horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        item(span={GridItemSpan(maxLineSpan)}) {
            FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),
                verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                VehicleCourseFeedTab.entries.forEach {tab->
                    val hasNew=tab==VehicleCourseFeedTab.SUBSCRIPTIONS && state.unreadCount?.let {it>0}==true
                    val label=if(hasNew)"${tab.label} (${state.unreadCount})" else tab.label
                    CourseFeedChoice(label,state.tab==tab,Role.Tab,true,
                        accessibility=if(hasNew)"${tab.label}, 새 경로 ${state.unreadCount}개" else tab.label) {onTab(tab)}
                }
            }
        }
        if(readable && tags.isNotEmpty())item(span={GridItemSpan(maxLineSpan)}) {
            Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                TripText(if(state.selectedTags.size>1)"선택한 태그 모두 포함" else "태그",style=CarType.Label,secondary=true,maxLines=2)
                FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),
                    verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    CourseFeedChoice("전체",state.selectedTags.isEmpty(),Role.Checkbox,current) {onTag(null)}
                    tags.forEach {tag->
                        val selected=state.selectedTags.any {vehicleCourseTagKey(it)==vehicleCourseTagKey(tag)}
                        CourseFeedChoice("#${tag.trim().removePrefix("#")}",selected,Role.Checkbox,current) {onTag(tag)}
                    }
                }
            }
        }
        if(readable && state.tab==VehicleCourseFeedTab.SUBSCRIPTIONS && state.followingNames.isNotEmpty())
            item(span={GridItemSpan(maxLineSpan)}) {
                CarCard(tone=CarCardTone.SOFT) {
                    TripText("구독한 창작자",style=CarType.Section,maxLines=2)
                    CarMetadata(state.followingNames.take(8),style=CarType.Body,secondary=false)
                    if(state.followingNames.size>8)TripText("외 ${state.followingNames.size-8}명",
                        style=CarType.Label,secondary=true,maxLines=2)
                }
            }
        if(readable && state.tab==VehicleCourseFeedTab.SUBSCRIPTIONS && followedTags.isNotEmpty())
            item(span={GridItemSpan(maxLineSpan)}) {
                CarCard(tone=CarCardTone.SOFT) {
                    TripText("구독한 태그",style=CarType.Section,maxLines=2)
                    FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),
                        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        followedTags.take(8).forEach {tag->
                            val chosen=state.selectedTags.any {vehicleCourseTagKey(it)==vehicleCourseTagKey(tag)}
                            CourseFeedChoice("#${tag.trim().removePrefix("#")}",chosen,Role.Checkbox,current,
                                accessibility="구독한 태그 #${tag.trim().removePrefix("#")}") {onTag(tag)}
                        }
                    }
                    if(followedTags.size>8)TripText("외 ${followedTags.size-8}개",
                        style=CarType.Label,secondary=true,maxLines=2)
                }
            }
        if(readable && !state.isCurrent)item(span={GridItemSpan(maxLineSpan)}) {
            CarCard(tone=CarCardTone.SOFT) {
                TripText("경로를 다시 불러와 주세요",secondary=true,maxLines=CarMessageLines)
            }
        }
        // 정렬 기준은 상태 알림이 아니므로 목록 머리의 보조 라벨로만 둔다.
        if(readable && state.isCurrent && cards.isNotEmpty())state.sortLabel?.let {label->
            item(span={GridItemSpan(maxLineSpan)}) {TripText(label,style=CarType.Label,secondary=true,maxLines=1)}
        }
        if(!readable)item(span={GridItemSpan(maxLineSpan)}) {
            when(state.status) {
                AccountReadStatus.LOADING->CarLoadingState("경로를 불러오는 중",Modifier.heightIn(min=CarTokens.ButtonDriving))
                AccountReadStatus.CONNECTION_REQUIRED->CarConnectionState("차량을 연결해 주세요",onConnect=onConnection)
                AccountReadStatus.PERMISSION_REQUIRED->CarConnectionState("이 차에서 경로를 볼 권한이 없어요",
                    onConnect=onConnection)
                else->CarFailureState("경로를 불러오지 못했어요",reportScreen="course.feed",onRetry=onRetry)
            }
        } else if(cards.isEmpty())item(span={GridItemSpan(maxLineSpan)}) {
            CarEmptyState(if(state.selectedTags.isNotEmpty())"선택한 태그에 맞는 경로가 없어요" else when(state.tab) {
                VehicleCourseFeedTab.RECOMMENDED->"추천 경로가 없어요"
                VehicleCourseFeedTab.SUBSCRIPTIONS->"새 경로가 없어요"
                VehicleCourseFeedTab.MINE->"내가 만든 경로가 없어요"
                VehicleCourseFeedTab.SAVED->"저장한 경로가 없어요"
            },detail=if(state.selectedTags.isNotEmpty())"다른 태그를 선택해 주세요" else null)
        } else items(cards.chunked(columns),key={row->row.first().key}) {row->
            Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                row.forEach {course->
                    CourseFeedCard(course,current,state.selectedTags,onTag,onOpen,onAdd,Modifier.weight(1f).fillMaxHeight(),opening=course.key==openingKey,busy=openingKey!=null)
                }
                repeat(columns-row.size) {Spacer(Modifier.weight(1f))}
            }
        }
        item(span={GridItemSpan(maxLineSpan)}) {
            CarPhoneHandoff("course-feed")
        }
    }
    }
}

@Composable
private fun CourseFeedChoice(label: String,chosen: Boolean,role: Role,enabled: Boolean,
    accessibility: String=label,onClick: ()->Unit) {
    val palette=LocalCarPalette.current
    Box(Modifier.heightIn(min=CarTokens.Touch).clip(CircleShape)
        .background(if(chosen)palette.ink else palette.background)
        .then(if(chosen)Modifier else Modifier.tripBorder(CarTokens.BorderWidth,palette.divider,CarTokens.ChipRadius))
        .carTap(enabled=enabled,role=role,onClick=onClick)
        .semantics {
            selected=chosen;contentDescription=accessibility
            if(role==Role.Checkbox)toggleableState=if(chosen)ToggleableState.On else ToggleableState.Off
        }
        .padding(horizontal=CarTokens.Frame,vertical=CarTokens.SpaceMedium),contentAlignment=Alignment.Center) {
        TripText(label,style=CarType.Action.copy(fontWeight=if(chosen)CarType.Section.fontWeight else CarType.Action.fontWeight),
            color=if(chosen)palette.onInk else if(enabled)palette.text else palette.secondary,maxLines=2)
    }
}

@Composable
private fun CourseFeedCard(course: VehicleCourseFeedCard,current: Boolean,selectedTags: Set<String>,onTag: (String?)->Unit,
    onOpen: (String)->Unit,onAdd: (String)->Unit,modifier: Modifier=Modifier,opening: Boolean=false,busy: Boolean=false) {
    val palette=LocalCarPalette.current
    CarCard(modifier.heightIn(min=CarTokens.CourseCardHeight),tone=CarCardTone.OUTLINED,radius=CarTokens.RadiusCard) {
        Box(Modifier.fillMaxWidth().height(CarTokens.CourseCoverHeight).clip(RoundedCornerShape(CarTokens.RadiusCard))
            .background(palette.accentSoft),contentAlignment=Alignment.Center) {
            CourseRoadMap(course.published,Modifier.fillMaxSize(),enabled=current,numbersOnly=true)
        }
        Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
            if(course.isNew)CarStatusPill("새 경로",kind=CarStatusTone.SOFT)
            TripText(course.title,style=CarType.Section,maxLines=2)
            course.stopCount?.let {TripText("장소 ${it}곳",secondary=true,maxLines=1)}
            if(course.routeSummary.isNotBlank())TripText(course.routeSummary,style=CarType.Label,secondary=true,maxLines=2)
            if(course.tags.isNotEmpty())Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                course.tags.distinctBy(::vehicleCourseTagKey).forEach {tag->
                    val label="#${tag.trim().removePrefix("#")}"
                    CourseFeedChoice(label,selectedTags.any {vehicleCourseTagKey(it)==vehicleCourseTagKey(tag)},Role.Checkbox,current,
                        accessibility="${course.title} $label") {onTag(tag)}
                }
            }
            Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                CarAvatar(course.author)
                TripText(course.author,Modifier.weight(1f),style=CarType.Label,secondary=true,maxLines=2)
                course.starCount?.let {TripText("별표 $it",style=CarType.Label,secondary=true,maxLines=1)}
            }
            course.creatorRank?.takeIf {it in 1..3}?.let {CarMetadata(listOf("드라이브 셀럽","${it}위"))}
        }
        Spacer(Modifier.weight(1f))
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
        // Opening downloads and verifies the course first; keep the press visible while it runs.
        CarButton(if(opening)"불러오는 중" else "경로 보기",{onOpen(course.key)},Modifier.weight(1f),enabled=current && course.canOpen && !busy,
            accessibility="${course.title} 경로 보기")
        CarButton("여행에 추가",{onAdd(course.key)},Modifier.weight(1f),enabled=current && course.canAdd,
            variant=CarButtonStyle.SOFT,accessibility="${course.title} 여행에 추가")
        }
    }
}
