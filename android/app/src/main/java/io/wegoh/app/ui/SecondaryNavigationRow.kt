package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics

@Composable
internal fun VehicleSecondaryNavigationRow(label: String,symbol: CarSymbol,onClick: ()->Unit) {
    val palette=LocalCarPalette.current
    val source=remember {MutableInteractionSource()}
    val pressed by source.collectIsPressedAsState()
    Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row).carTap(source=source,onClick=onClick)
        .background(if(pressed)palette.pressedOverlay else Color.Transparent)
        .semantics {contentDescription=label}.padding(vertical=CarTokens.SpaceMedium),
        verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        Box(Modifier.size(CarTokens.Touch).background(if(pressed)palette.pressedOverlay.compositeOver(palette.low) else palette.low,
            RoundedCornerShape(CarTokens.ButtonRadius)),
            contentAlignment=Alignment.Center) {CarIcon(symbol,Modifier.size(CarTokens.Icon))}
        CarText(label,Modifier.weight(1f),style=CarType.Action,maxLines=2)
        CarIcon(CarSymbol.Next,Modifier.size(CarTokens.ButtonIcon),palette.secondary)
    }
}
