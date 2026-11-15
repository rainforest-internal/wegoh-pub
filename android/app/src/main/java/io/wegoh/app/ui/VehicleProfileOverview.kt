package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import io.wegoh.app.AccountProfileState
import io.wegoh.app.AccountReadStatus

@Composable
internal fun VehicleProfileOverview(profile: AccountProfileState,friendCount: Int?,courseCount: Int?,tripCount: Int?,
    onFriends: ()->Unit,onPrivacy: ()->Unit,onLogout: ()->Unit) = TripSurface {
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    val connection=when {
        profile.status==AccountReadStatus.READY && profile.isCurrent->"연결됨"
        profile.status==AccountReadStatus.LOADING->"연결 확인 중"
        profile.status==AccountReadStatus.CONNECTION_REQUIRED->"차량 연결 필요"
        else->"연결 확인 필요"
    }
    val identity: @Composable (Modifier)->Unit = {modifier->
        Column(modifier.then(if(narrow)Modifier else Modifier.verticalScroll(rememberScrollState())),
            verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
            ProfileIdentityCard(profile,friendCount,courseCount,tripCount,connection)
            CarPhoneHandoff("profile")
        }
    }
    val menu: @Composable (Modifier)->Unit = {modifier->
        Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
            Column(Modifier.fillMaxWidth().then(if(narrow)Modifier else Modifier.weight(1f).verticalScroll(rememberScrollState())),
                verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                // 이름·차량 이름·차량 번호는 왼쪽 신원 카드가 이미 보여 주므로 같은 값만 다시 여는 단계를 두지 않는다.
                ProfileMenuCard("친구 관리",friendCount?.let {"${it}명"},CarSymbol.People,onFriends)
                ProfileMenuCard("권한 관리",null,CarSymbol.Shield,onPrivacy)
            }
            CarButton("이 차에서 로그아웃",onLogout,Modifier.fillMaxWidth(),
                variant=CarButtonStyle.DANGER)
        }
    }
    val padding=Modifier.padding(horizontal=CarTokens.PagePrimaryPaddingHorizontal,vertical=CarTokens.PagePrimaryPaddingVertical)
    if(narrow)Column(Modifier.fillMaxSize().then(padding).verticalScroll(rememberScrollState()),
        verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        identity(Modifier.fillMaxWidth())
        menu(Modifier.fillMaxWidth())
    } else Row(Modifier.fillMaxSize().then(padding),horizontalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
        identity(Modifier.weight(1f).fillMaxHeight())
        menu(Modifier.weight(1f).fillMaxHeight())
    }
}

@Composable
private fun ProfileIdentityCard(profile: AccountProfileState,friendCount: Int?,courseCount: Int?,tripCount: Int?,
    connection: String) {
    val palette=LocalCarPalette.current
    CarCard(tone=CarCardTone.INK,radius=CarTokens.RadiusHero,padding=PaddingValues(CarTokens.Frame)) {
        Column(Modifier.fillMaxWidth(),
            verticalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
            Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                Box(Modifier.size(CarTokens.ProfileAvatarSize).background(palette.onInk,CircleShape).clearAndSetSemantics {},
                    contentAlignment=Alignment.Center) {
                    TripText(profile.name?.take(2) ?: "나",style=CarType.Hero,color=palette.ink)
                }
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    CarText(profile.name ?: "내 프로필",style=CarType.Hero,maxLines=2)
                    CarText(if(profile.status==AccountReadStatus.READY && profile.isCurrent)"로그인됨" else connection,
                        style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)
                }
            }
            Box(Modifier.fillMaxWidth().height(CarTokens.BorderWidth).background(palette.inkDivider))
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                listOf("여행" to tripCount,"만든 경로" to courseCount,"친구" to friendCount).forEach {(label,count)->
                    Column(Modifier.weight(1f),horizontalAlignment=Alignment.CenterHorizontally,
                        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        CarText(count?.toString() ?: "–",style=CarType.Hero)
                        CarText(label,style=CarType.Label,secondary=true,maxLines=2)
                    }
                }
            }
            Box(Modifier.fillMaxWidth().height(CarTokens.BorderWidth).background(palette.inkDivider))
            Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                CarText("이 차량",style=CarType.Label,secondary=true)
                val vehicle=profile.vehicle
                val (title,plate)=when {
                    profile.status!=AccountReadStatus.READY || !profile.isCurrent->"연결 확인 필요" to null
                    profile.vehicleLoading->"확인 중" to null
                    profile.vehicleUnavailable->"불러오지 못했어요" to null
                    vehicle==null->"차량 정보를 확인할 수 없어요" to null
                    else->vehicle.displayName to vehicle.plateNumber.ifBlank {"등록된 번호가 없어요"}
                }
                CarText(title,style=CarType.Title,maxLines=2)
                plate?.let {CarText(it,style=CarType.Label,secondary=true,maxLines=2)}
            }
        }
    }
}

@Composable
private fun ProfileMenuCard(title: String,description: String?,symbol: CarSymbol,onClick: ()->Unit) {
    val palette=LocalCarPalette.current
    val source=remember {MutableInteractionSource()}
    val pressed by source.collectIsPressedAsState()
    CarCard(Modifier.carTap(source=source,onClick=onClick).semantics {contentDescription=title},outlined=true,
        background=if(pressed)palette.pressedOverlay.compositeOver(palette.background) else palette.background,
        padding=PaddingValues(CarTokens.SpaceLarge)) {
        Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Touch),
            horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
            Box(Modifier.size(CarTokens.Touch).clip(RoundedCornerShape(CarTokens.ButtonRadius))
                .background(if(pressed)palette.pressedOverlay.compositeOver(palette.accentSoft) else palette.accentSoft),
                contentAlignment=Alignment.Center) {CarIcon(symbol,Modifier.size(CarTokens.Icon),palette.accent)}
            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                CarText(title,style=CarType.Section,maxLines=2)
                description?.let {CarText(it,style=CarType.Label,secondary=true,maxLines=2)}
            }
            CarIcon(CarSymbol.Next,Modifier.size(CarTokens.ButtonIcon),palette.secondary)
        }
    }
}
