package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight

@Composable
internal fun CarMusicRow(title: String,metadata: List<String>,modifier: Modifier=Modifier,
    trailing: @Composable ()->Unit) {
    val p=LocalCarPalette.current
    Column(modifier.fillMaxWidth().heightIn(min=CarTokens.Row),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
        BoxWithConstraints(Modifier.fillMaxWidth().padding(vertical=CarTokens.SpaceMedium)) {
            val narrow=maxWidth/LocalDensity.current.fontScale<CarTokens.CourseCardMinWidth
            val label: @Composable (Modifier)->Unit={textModifier->
                Row(textModifier,horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                    Box(Modifier.size(CarTokens.IconLarge).background(p.accentSoft,RoundedCornerShape(CarTokens.Radius)),contentAlignment=Alignment.Center) {
                        CarIcon(CarSymbol.Music,Modifier.size(CarTokens.Icon),p.accent)
                    }
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        CarText(title,style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=Int.MAX_VALUE)
                        metadata.filter {it.isNotBlank()}.forEach {CarText(it,style=CarType.Label,secondary=true,maxLines=Int.MAX_VALUE)}
                    }
                }
            }
            if(narrow)Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                label(Modifier.fillMaxWidth());trailing()
            } else Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                label(Modifier.weight(1f));trailing()
            }
        }
        Spacer(Modifier.fillMaxWidth().height(CarTokens.BorderWidth).background(p.divider))
    }
}
