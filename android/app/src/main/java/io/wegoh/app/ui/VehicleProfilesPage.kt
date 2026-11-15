@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.Alignment
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import io.wegoh.app.*

@Composable
internal fun VehicleProfilesPage(profile: AccountProfileState,social: SocialPageState,selected: String?,
    onSelect: (String?)->Unit,
    onManage: (String,Boolean)->Unit,onConnection: ()->Unit,onReload: ()->Unit,onPrivacy: ()->Unit,
    courseCount: Int?=null,tripCount: Int?=null,onBack: (()->Unit)?=null) {
    var friends by rememberSaveable {mutableStateOf(false)}
    var initialFriendChosen by remember {mutableStateOf(false)}
    var logout by rememberSaveable {mutableStateOf(false)}
    val context=androidx.compose.ui.platform.LocalContext.current
    var confirmation by remember {mutableStateOf<Boolean?>(null)}
    var managing by remember(selected) {mutableStateOf(false)}
    val friend=social.overview?.friends?.firstOrNull {it.id==selected}
    LaunchedEffect(selected,social.overview,social.isCurrent,social.busy) {
        if(selected!=null && selected!="self" && social.overview!=null && social.isCurrent && !social.busy && friend==null) {
            confirmation=null;onSelect(null)
        }
    }
    BoxWithConstraints(Modifier.fillMaxSize()) {
    val narrow=maxWidth<CarTokens.Breakpoint
    val backFromFriends: ()->Unit={
        if(selected=="self" || (narrow && friend!=null))onSelect(null)
        else {onSelect(null);friends=false}
    }
    CarChildBackHandler(enabled=friends,onBack=backFromFriends)
    LaunchedEffect(friends,narrow,selected,social.isCurrent,social.overview) {
        if(friends && !narrow && !initialFriendChosen && selected==null && social.isCurrent) {
            social.overview?.friends?.firstOrNull()?.let {initialFriendChosen=true;onSelect(it.id)}
        }
    }
    if(selected=="self")AccountProfileScreen(profile,onConnection,{},onReload,onBack=onBack)
    else if(!friends && friend==null) {
        VehicleProfileOverview(profile,social.overview?.takeIf {social.isCurrent && it.friendsAvailable}?.friends?.size,courseCount,tripCount,
            {initialFriendChosen=false;friends=true},onPrivacy,{logout=true})
    } else Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        TripHeading("친구 관리","프로필 → 친구 관리",backFromFriends)
        Row(Modifier.weight(1f).then(if(narrow && friend!=null)Modifier.verticalScroll(rememberScrollState()) else Modifier),
            horizontalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
            if(!narrow || friend==null)Column(Modifier.weight(1f).fillMaxHeight(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                CarCard(Modifier.weight(1f),outlined=true,padding=PaddingValues(CarTokens.SpaceMedium)) {
                    CarText("나와 친구",style=CarType.Section,maxLines=2)
                    social.overview?.takeIf {social.isCurrent && it.friendsAvailable}?.let {
                        CarText("친구 ${it.friends.size}명",style=CarType.Label,secondary=true,maxLines=2)
                    }
                    LazyColumn(Modifier.fillMaxWidth().weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        item {FriendProfileRow(profile.name ?: "내 프로필",listOfNotNull("내 프로필",profile.vehicle?.plateNumber),
                            selected=="self",true) {onSelect("self")}}
                        items(social.overview?.friends.orEmpty(),key={it.id}) {person->
                            FriendProfileRow(person.name ?: "친구",emptyList(),selected==person.id,false) {onSelect(person.id)}
                        }
                        if(social.overview?.friends.isNullOrEmpty())item {
                            CarText(when(social.status) {
                                AccountReadStatus.LOADING->"친구 불러오는 중"
                                AccountReadStatus.PERMISSION_REQUIRED->"친구 목록을 볼 권한이 없어요"
                                AccountReadStatus.CONNECTION_REQUIRED->"차량을 연결해 주세요"
                                AccountReadStatus.UNAVAILABLE->"친구를 불러오지 못했어요"
                                else->"친구가 없어요"
                            },secondary=true,maxLines=Int.MAX_VALUE)
                        }
                    }
                }
                CarPhoneHandoff("together")
            }
            if(!narrow || friend!=null)Column(Modifier.weight(1f).then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),
                verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                if(friend==null)CarEmptyState("친구를 선택해 주세요",symbol=CarSymbol.People)
                else CarCard(outlined=true,padding=PaddingValues(CarTokens.Frame),radius=CarTokens.RadiusHero) {
                    Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                        CarAvatar(friend.name ?: "친구",large=true)
                        CarText(friend.name ?: "친구",Modifier.weight(1f),style=CarType.Hero,maxLines=Int.MAX_VALUE)
                    }
                    if(managing && social.busy)CarText("처리 중",secondary=true,maxLines=3)
                    else if(managing && social.notice!=null)CarText(social.notice,Modifier.semantics {liveRegion=LiveRegionMode.Polite},secondary=true,maxLines=CarMessageLines)
                    FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                        CarButton("친구 연결 해제",{confirmation=false},Modifier.weight(1f),
                            enabled=social.isCurrent && !social.busy && social.overview?.friendsReadOnly==false)
                        CarButton("차단",{confirmation=true},Modifier.weight(1f),variant=CarButtonStyle.DANGER,
                            enabled=social.isCurrent && !social.busy && social.overview?.friendsReadOnly==false)
                    }
                    if(narrow)CarPhoneHandoff("together")
                }
            }
        }
    }
    }
    if(logout)CarPopup("이 차에서 로그아웃할까요?",{logout=false},description="리모컨 받기도 꺼져요.",actions={
        CarButton("로그아웃",{
            val app=context.applicationContext as WegoApplication
            app.receiverSettings.stopLocally()
            (app.controller.vehicleAccountConnection ?: app.vehicleConnection).disconnect()
            logout=false
        },Modifier.weight(1f),variant=CarButtonStyle.DANGER)
        CarButton("취소",{logout=false},Modifier.weight(1f))
    })
    confirmation?.let {block->CarPopup(if(block)"친구를 차단할까요?" else "친구 연결을 해제할까요?",{confirmation=null},description="여행 중 이 친구에게 허용한 차량 조작도 끝나요.",actions={
        CarButton(if(block)"차단" else "연결 해제",{friend?.let {managing=true;onManage(it.id,block)};confirmation=null},Modifier.weight(1f),variant=CarButtonStyle.DANGER,
            enabled=friend!=null && social.isCurrent && !social.busy && social.overview?.friendsReadOnly==false)
        CarButton("취소",{confirmation=null},Modifier.weight(1f))
    })}
}


@Composable
private fun FriendProfileRow(name: String,detail: List<String>,chosen: Boolean,self: Boolean,onClick: ()->Unit) {
    val palette=LocalCarPalette.current
    Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row).clip(RoundedCornerShape(CarTokens.RadiusCard))
        // 선택은 CarCard SELECTED와 같은 accent 테두리로 표시한다. 면을 accentSoft로 칠하면 같은 색인 SOFT 아바타 원이 사라진다.
        .background(palette.background)
        .then(if(chosen)Modifier.tripBorder(CarTokens.SelectedBorderWidth,palette.accent,CarTokens.RadiusCard) else Modifier)
        .carTap(onClick=onClick)
        .semantics {contentDescription=name;selected=chosen}.padding(CarTokens.SpaceMedium),
        verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        CarAvatar(name,if(self)CarAvatarTone.INK else CarAvatarTone.SOFT)
        Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
            CarText(name,style=CarType.Section,maxLines=Int.MAX_VALUE)
            CarMetadata(detail)
        }
        CarIcon(CarSymbol.Next,Modifier.size(CarTokens.ButtonIcon),palette.secondary)
    }
}
