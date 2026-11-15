package io.wegoh.app.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.wegoh.app.R

/** WegoH implementation of documented Pleos roles, not an official component SDK. */

data class CarPalette(val background: Color, val low: Color, val selected: Color, val text: Color,
    val secondary: Color, val divider: Color, val button: Color, val onButton: Color, val success: Color, val error: Color, val errorAccent: Color,
    val filledPressed: Color, val pressedOverlay: Color, val switchOn: Color, val switchOff: Color, val switchKnobOn: Color, val switchKnobOff: Color, val switchDisabledTrack: Color, val switchDisabledKnob: Color, val selectionOn: Color, val selectionMark: Color, val accent: Color, val accentSoft: Color, val ink: Color, val onInk: Color,
    val onInkSecondary: Color, val routeOnInk: Color, val inkDivider: Color, val danger: Color, val personalRouteBorder: Color,
    val skeleton: Color, val skeletonOnInk: Color, val skeletonOnInkHighlight: Color,
    /** 탭 밑줄·선택 테두리처럼 선택 상태를 알리는 표시. 야간에는 남색 ink가 배경과 구분되지 않아 역할을 나눈다. */
    val selectionIndicator: Color,
    /** INK 카드 테두리. 야간 INK 면은 그 위 글자·파란 표식 대비 때문에 밝힐 수 없어 SOFT·배경과의 위계를 테두리로 나눈다. 주간은 면과 같은 색이다. */
    val inkBorder: Color,
    /** SOFT 카드 테두리. 야간 SOFT 면은 배경과 1.3:1이라 경계를 테두리가 맡고, INK 테두리보다 약하게 두어 위계를 지킨다. 주간은 면과 같은 색이다. */
    val softBorder: Color)
val LocalCarPalette = staticCompositionLocalOf { PleosPalette.Day }
/** 테마의 원래 팔레트. 카드 톤(예: INK)이 LocalCarPalette 글자색을 바꿔도 팝업처럼 별도 표면은 이 값을 쓴다. */
val LocalCarThemePalette = staticCompositionLocalOf { PleosPalette.Day }

@OptIn(ExperimentalTextApi::class)
private val Asta = FontFamily(
    Font(R.font.asta_sans, FontWeight.Normal, variationSettings = FontVariation.Settings(FontVariation.weight(400))),
    Font(R.font.asta_sans, FontWeight.Bold, variationSettings = FontVariation.Settings(FontVariation.weight(700))),
    Font(R.font.asta_sans, FontWeight.ExtraBold, variationSettings = FontVariation.Settings(FontVariation.weight(800))),
)
object CarType {
    val Field = TextStyle(fontFamily = Asta, fontWeight = PleosType.FieldWeight, fontSize = PleosType.FieldSize, lineHeight = PleosType.FieldLine)
    val ArrivalAction = TextStyle(fontFamily = Asta, fontWeight = PleosType.ArrivalActionWeight, fontSize = PleosType.ArrivalActionSize, lineHeight = PleosType.ArrivalActionLine)
    val DepartureRemove = TextStyle(fontFamily = Asta, fontWeight = PleosType.DepartureRemoveWeight, fontSize = PleosType.DepartureRemoveSize, lineHeight = PleosType.DepartureRemoveLine)
    val DepartureTitle = TextStyle(fontFamily = Asta, fontWeight = PleosType.DepartureTitleWeight, fontSize = PleosType.DepartureTitleSize, lineHeight = PleosType.DepartureTitleLine)
    val DrivingHeroLabel = TextStyle(fontFamily = Asta, fontWeight = PleosType.DrivingHeroLabelWeight, fontSize = PleosType.DrivingHeroLabelSize, lineHeight = PleosType.DrivingHeroLabelLine)
    val DrivingPromptCaption = TextStyle(fontFamily = Asta, fontWeight = PleosType.DrivingPromptCaptionWeight, fontSize = PleosType.DrivingPromptCaptionSize, lineHeight = PleosType.DrivingPromptCaptionLine)
    val WalkieGear = TextStyle(fontFamily = Asta, fontWeight = PleosType.WalkieGearWeight, fontSize = PleosType.WalkieGearSize, lineHeight = PleosType.WalkieGearLine)
    val WalkieStep = TextStyle(fontFamily = Asta, fontWeight = PleosType.WalkieStepWeight, fontSize = PleosType.WalkieStepSize, lineHeight = PleosType.WalkieStepLine)
    val WalkieDetail = TextStyle(fontFamily = Asta, fontWeight = PleosType.WalkieDetailWeight, fontSize = PleosType.WalkieDetailSize, lineHeight = PleosType.WalkieDetailLine)
    val DrivingHeroCompact = TextStyle(fontFamily = Asta, fontWeight = PleosType.DrivingHeroCompactWeight, fontSize = PleosType.DrivingHeroCompactSize, lineHeight = PleosType.DrivingHeroCompactLine)
    val WalkieRoomName = TextStyle(fontFamily = Asta, fontWeight = PleosType.WalkieRoomNameWeight, fontSize = PleosType.WalkieRoomNameSize, lineHeight = PleosType.WalkieRoomNameLine)
    val WalkieStatus = TextStyle(fontFamily = Asta, fontWeight = PleosType.WalkieStatusWeight, fontSize = PleosType.WalkieStatusSize, lineHeight = PleosType.WalkieStatusLine)
    val WalkieCountdown = TextStyle(fontFamily = Asta, fontWeight = PleosType.WalkieCountdownWeight, fontSize = PleosType.WalkieCountdownSize, lineHeight = PleosType.WalkieCountdownLine)
    val DialogBody = TextStyle(fontFamily = Asta, fontWeight = PleosType.DialogBodyWeight, fontSize = PleosType.DialogBodySize, lineHeight = PleosType.DialogBodyLine)
    val SignalAction = TextStyle(fontFamily = Asta, fontWeight = PleosType.SignalActionWeight, fontSize = PleosType.SignalActionSize, lineHeight = PleosType.SignalActionLine)
    val SignalPlace = TextStyle(fontFamily = Asta, fontWeight = PleosType.SignalPlaceWeight, fontSize = PleosType.SignalPlaceSize, lineHeight = PleosType.SignalPlaceLine)
    val DrivingHero = TextStyle(fontFamily = Asta, fontWeight = PleosType.DrivingHeroWeight, fontSize = PleosType.DrivingHeroSize, lineHeight = PleosType.DrivingHeroLine)
    val DrivingScore = TextStyle(fontFamily = Asta, fontWeight = PleosType.DrivingScoreWeight, fontSize = PleosType.DrivingScoreSize, lineHeight = PleosType.DrivingScoreLine)
    val Action = TextStyle(fontFamily = Asta, fontWeight = PleosType.ActionWeight, fontSize = PleosType.ActionSize, lineHeight = PleosType.ActionLine)
    val Hero = TextStyle(fontFamily = Asta, fontWeight = PleosType.HeroWeight, fontSize = PleosType.HeroSize, lineHeight = PleosType.HeroLine)
    val Title = TextStyle(fontFamily = Asta, fontWeight = PleosType.TitleWeight, fontSize = PleosType.TitleSize, lineHeight = PleosType.TitleLine)
    val Section = TextStyle(fontFamily = Asta, fontWeight = PleosType.SectionWeight, fontSize = PleosType.SectionSize, lineHeight = PleosType.SectionLine)
    val Body = TextStyle(fontFamily = Asta, fontWeight = PleosType.BodyWeight, fontSize = PleosType.BodySize, lineHeight = PleosType.BodyLine)
    val Label = TextStyle(fontFamily = Asta, fontWeight = PleosType.LabelWeight, fontSize = PleosType.LabelSize, lineHeight = PleosType.LabelLine)
    val Caption = TextStyle(fontFamily = Asta, fontWeight = PleosType.CaptionWeight, fontSize = PleosType.CaptionSize, lineHeight = PleosType.CaptionLine)
}

@Composable
fun WegoCarTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val p = if (dark) PleosPalette.Night else PleosPalette.Day
    val scheme = if (dark) darkColorScheme(primary = p.text, background = p.background, surface = p.background,
        onSurface = p.text, onBackground = p.text, onPrimary = p.background)
    else lightColorScheme(primary = p.text, background = p.background, surface = p.background,
        onSurface = p.text, onBackground = p.text, onPrimary = p.background)
    CompositionLocalProvider(LocalCarPalette provides p, LocalCarThemePalette provides p) {
        MaterialTheme(colorScheme = scheme, typography = Typography(
            displaySmall = CarType.Hero, titleLarge = CarType.Title, titleMedium = CarType.Section,
            bodyLarge = CarType.Body, bodyMedium = CarType.Label, labelLarge = CarType.Label, bodySmall = CarType.Caption), content = content)
    }
}
