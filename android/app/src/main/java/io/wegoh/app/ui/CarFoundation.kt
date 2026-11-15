package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.semantics.*
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.text.font.FontWeight

internal enum class CarAvatarTone { INK, SOFT }

@Composable
internal fun CarPhoneHint(text: String,modifier: Modifier=Modifier) {
    CarHint(text,CarSymbol.Phone,modifier)
}

@Composable
internal fun CarInfoHint(text: String,modifier: Modifier=Modifier) {
    CarHint(text,CarSymbol.Info,modifier)
}

@Composable
private fun CarHint(text: String,symbol: CarSymbol,modifier: Modifier) {
    val p=LocalCarPalette.current
    Row(modifier.fillMaxWidth().background(p.low,RoundedCornerShape(CarTokens.RadiusCard))
        .padding(CarTokens.Gap).semantics(mergeDescendants=true) {},
        horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
        Box(Modifier.size(CarTokens.PhoneHintIcon).background(p.accentSoft,RoundedCornerShape(CarTokens.Radius)),contentAlignment=Alignment.Center) {
            CarIcon(symbol,Modifier.size(CarTokens.Icon),p.accent)
        }
        CarText(text,Modifier.weight(1f),style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)
    }
}

@Composable
internal fun CarAvatar(name: String,tone: CarAvatarTone=CarAvatarTone.SOFT,modifier: Modifier=Modifier,large: Boolean=false) {
    val p=LocalCarPalette.current
    Box(modifier.size(if(large)CarTokens.ProfileAvatarSize else CarTokens.AvatarSize).background(if(tone==CarAvatarTone.INK)p.ink else p.accentSoft,CircleShape),contentAlignment=Alignment.Center) {
        TripText(name.take(2),style=(if(large)CarType.Hero else CarType.Label).copy(fontWeight=FontWeight.Bold),color=if(tone==CarAvatarTone.INK)p.onInk else p.accent)
    }
}

@Composable
internal fun CarChoiceTile(title: String,checked: Boolean,symbol: CarSymbol,modifier: Modifier=Modifier,
    enabled: Boolean=true,iconContent: (@Composable ()->Unit)?=null,onClick: ()->Unit) {
    val p=LocalCarPalette.current
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    val background=if(checked)p.ink else p.low
    Column(modifier.heightIn(min=CarTokens.ButtonLarge)
        .carTap(enabled=enabled,role=Role.RadioButton,source=source,onClick=onClick)
        .clip(RoundedCornerShape(CarTokens.RadiusCard))
        .background(if(pressed)p.pressedOverlay.compositeOver(background) else background)
        .then(if(checked)Modifier.border(CarTokens.SelectedBorderWidth,p.selectionIndicator,RoundedCornerShape(CarTokens.RadiusCard)) else Modifier)
        .clearAndSetSemantics {
            contentDescription=title;role=Role.RadioButton;selected=checked
            stateDescription=if(checked)"선택됨" else "선택 안 됨"
            if(!enabled)disabled() else onClick {onClick();true}
        }.padding(CarTokens.Gap),horizontalAlignment=Alignment.CenterHorizontally,
        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall,Alignment.CenterVertically)) {
        if(iconContent!=null)iconContent() else CarIcon(symbol,color=if(checked)p.onInk else p.text)
        TripText(title,style=CarType.Label,color=if(checked)p.onInk else p.text,maxLines=2)
    }
}

@Composable
internal fun CarFilterChip(title: String,checked: Boolean,onClick: ()->Unit,modifier: Modifier=Modifier,enabled: Boolean=true) {
    val p=LocalCarPalette.current
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    val background=if(checked)p.ink else p.background
    Row(modifier.heightIn(min=CarTokens.Touch)
        .carTap(enabled=enabled,role=Role.Checkbox,source=source,onClick=onClick)
        .clip(RoundedCornerShape(CarTokens.ChipRadius))
        .background(if(pressed)p.pressedOverlay.compositeOver(background) else background)
        .border(CarTokens.BorderWidth,if(checked)p.selectionIndicator else p.divider,RoundedCornerShape(CarTokens.ChipRadius))
        .clearAndSetSemantics {
            contentDescription=title;role=Role.Checkbox;toggleableState=ToggleableState(checked);selected=checked
            if(!enabled)disabled() else onClick {onClick();true}
        }.padding(horizontal=CarTokens.Gap,vertical=CarTokens.SpaceMedium),
        verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
        if(checked)CarIcon(CarSymbol.Check,Modifier.size(CarTokens.ButtonIcon),p.onInk)
        TripText(title,style=CarType.Action,color=if(checked)p.onInk else p.text,maxLines=2)
    }
}
