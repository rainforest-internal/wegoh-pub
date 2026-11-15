package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight

@Composable
internal fun CarPrimaryHeader(items: List<CarPageItem>,enabled: Boolean,receiving: Boolean?,onRefresh: ()->Unit,refreshEnabled: Boolean) {
    val palette=LocalCarPalette.current
    CompositionLocalProvider(LocalCarPalette provides palette) {
        TripLayoutRoot(Modifier.fillMaxWidth().height(CarTokens.Header).background(palette.background)) {
            val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
            Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(CarTokens.BorderWidth).background(palette.divider))
            Row(Modifier.fillMaxSize().padding(horizontal=if(narrow)CarTokens.Gap else CarTokens.Frame),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                Row(Modifier.weight(1f).fillMaxHeight().then(if(narrow)Modifier else Modifier.horizontalScroll(rememberScrollState())),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    items.forEach {item->
                        Box((if(narrow)Modifier.weight(1f) else Modifier.width(IntrinsicSize.Max).widthIn(min=CarTokens.Touch)).fillMaxHeight().carTap(enabled=enabled,role=Role.Tab,onClick=item.onSelect)
                            .semantics {selected=item.selected;contentDescription="${item.title} 탭"}) {
                            CarText(item.title,Modifier.align(Alignment.Center).padding(horizontal=if(narrow)CarTokens.SpaceSmall else CarTokens.CardPadding),
                                style=CarType.Section.copy(
                                    fontWeight=if(item.selected)FontWeight.Bold else FontWeight.Normal),secondary=!item.selected)
                            if(item.selected)Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(CarTokens.RouteCurrentBorder).background(palette.selectionIndicator))
                        }
                    }
                }
                if(receiving==true && !narrow)Row(Modifier.background(palette.accentSoft,RoundedCornerShape(CarTokens.ChipRadius)).padding(horizontal=CarTokens.Gap,vertical=CarTokens.SpaceSmall),
                    horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall),verticalAlignment=Alignment.CenterVertically) {
                    Box(Modifier.size(CarTokens.RouteDot).background(palette.accent,CircleShape))
                    CarText("리모컨 받기 켜짐",style=CarType.Label)
                }
                Box(Modifier.size(CarTokens.Touch).clip(RoundedCornerShape(CarTokens.ButtonRadius)).carTap(enabled=enabled && refreshEnabled,onClick=onRefresh)
                    .semantics {contentDescription="새로고침"},contentAlignment=Alignment.Center) {
                    CarIcon(CarSymbol.Refresh,Modifier.size(CarTokens.ButtonIcon),if(enabled && refreshEnabled)palette.text else palette.secondary)
                }
            }
        }
    }
}

@Composable
internal fun CarContentBack(title: String,onBack: ()->Unit) {
    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
        Box(Modifier.size(CarTokens.Touch).clip(RoundedCornerShape(CarTokens.ButtonRadius)).carTap(onClick=onBack)
            .semantics {contentDescription="뒤로"},contentAlignment=Alignment.Center) {CarIcon(CarSymbol.Back,Modifier.size(CarTokens.ButtonIcon))}
        CarText(title,style=CarType.Section,maxLines=2)
    }
}
