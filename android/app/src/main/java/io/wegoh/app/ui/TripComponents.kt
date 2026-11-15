@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.selection.LocalTextSelectionColors
import androidx.compose.foundation.text.selection.TextSelectionColors
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.layout.ParentDataModifier
import androidx.compose.ui.layout.layout
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.constrainHeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.TextUnit
import io.wegoh.app.TripGear
import io.wegoh.app.TripPlanMenu
import io.wegoh.app.nativeauth.TripCar

internal val LocalTripLayoutWidth=staticCompositionLocalOf {CarTokens.LayoutReferenceWidth}

@Composable
internal fun TripLayoutRoot(modifier: Modifier=Modifier.fillMaxSize(),content: @Composable BoxScope.()->Unit) {
    BoxWithConstraints(modifier) {
        val width=maxWidth
        CompositionLocalProvider(LocalTripLayoutWidth provides width) {
            Box(Modifier.fillMaxSize(),content=content)
        }
    }
}

@Composable
internal fun TripText(text: String,modifier: Modifier=Modifier,style: TextStyle?=null,secondary: Boolean=false,
    maxLines: Int=1,color: Color?=null) {
    val palette=LocalCarPalette.current
    CompositionLocalProvider(LocalCarPalette provides if(color==null)palette else palette.copy(text=color,secondary=color)) {
        CarText(text,modifier,style ?: if(secondary)CarType.Label else CarType.Body,secondary,maxLines)
    }
}

@Composable
internal fun TripSurface(content: @Composable ()->Unit) {
    val palette=LocalCarPalette.current
    CompositionLocalProvider(LocalTextSelectionColors provides TextSelectionColors(palette.accent,palette.accentSoft)) {
        TripLayoutRoot(Modifier.fillMaxSize().background(palette.background)) {content()}
    }
}

internal fun Modifier.tripBorder(width: Dp,color: Color,radius: Dp,dashed: Boolean=false): Modifier =
    if(!dashed)border(width,color,RoundedCornerShape(radius)) else drawWithCache {
        val stroke=width.toPx()
        val effect=Stroke(stroke,pathEffect=PathEffect.dashPathEffect(floatArrayOf(CarTokens.DashedBorderDash.toPx(),CarTokens.DashedBorderGap.toPx())))
        onDrawWithContent {
            drawContent()
            drawRoundRect(color,Offset(stroke/2,stroke/2),Size((size.width-stroke).coerceAtLeast(0f),(size.height-stroke).coerceAtLeast(0f)),
                CornerRadius((radius.toPx()-stroke/2).coerceAtLeast(0f)),style=effect)
        }
    }

internal enum class CarButtonStyle { OUTLINE, FILLED, DARK, SOFT, ON_INK, INK_OUTLINE, DANGER, DASHED, TEXT }
internal enum class CarCardTone { OUTLINED, SURFACE, INK, SOFT, DASHED, SELECTED }

/** Pleos System Popup 그림(7aec76d8d4dff4d00dd0.svg)의 버튼 두 가지. 확인은 진한 채움(Figma Secondary),
 * 취소는 밝은 면(Figma Primary)이고 테두리만 있는 버튼이나 위험색 변형은 없다. 되돌릴 수 없다는 뜻은 제목과 설명이 전한다. */
internal enum class CarPopupButtonRole { CONFIRM, CANCEL }

internal fun carPopupButtonRole(variant: CarButtonStyle): CarPopupButtonRole =
    if(variant in setOf(CarButtonStyle.FILLED,CarButtonStyle.DARK,CarButtonStyle.ON_INK,CarButtonStyle.DANGER))CarPopupButtonRole.CONFIRM
    else CarPopupButtonRole.CANCEL

@Composable
internal fun CarButton(label: String,onClick: ()->Unit,modifier: Modifier=Modifier,primary: Boolean=false,
    enabled: Boolean=true,icon: CarSymbol?=null,variant: CarButtonStyle=if(primary)CarButtonStyle.FILLED else CarButtonStyle.OUTLINE,
    large: Boolean=false,textStyle: TextStyle?=null,accessibility: String=label,busy: Boolean=false) {
    val p=LocalCarPalette.current
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    val popupAction=LocalCarLargeAction.current
    val visualHeight=if(popupAction)CarTokens.PopupLargeButtonHeight else if(large)CarTokens.ButtonLarge else CarTokens.ButtonVisualHeight
    val radius=if(popupAction)CarTokens.PopupLargeButtonRadius else CarTokens.ButtonRadius
    val minWidth=if(popupAction)CarTokens.PopupLargeButtonMinWidth else CarTokens.ButtonMinWidth
    val paddingH=if(popupAction)CarTokens.PopupLargeButtonPaddingHorizontal else CarTokens.ButtonPadding
    val paddingV=if(popupAction)CarTokens.PopupLargeButtonPaddingVertical else CarTokens.ButtonPaddingVertical
    val gap=if(popupAction)CarTokens.PopupLargeButtonGap else CarTokens.ButtonGap
    val iconSize=if(popupAction)CarTokens.PopupLargeButtonIcon else CarTokens.ButtonIcon
    val labelStyle=if(popupAction || large)CarType.Section else CarType.Action
    val popupRole=if(popupAction)carPopupButtonRole(variant) else null
    val filled=if(popupRole!=null)popupRole==CarPopupButtonRole.CONFIRM else variant in setOf(CarButtonStyle.FILLED,CarButtonStyle.DARK,CarButtonStyle.ON_INK)
    val background=when {
        popupRole!=null->if(enabled && popupRole==CarPopupButtonRole.CONFIRM)p.button else p.low
        !enabled && filled->p.divider
        variant==CarButtonStyle.DARK->p.ink
        variant==CarButtonStyle.ON_INK->p.routeOnInk
        variant==CarButtonStyle.FILLED->p.accent
        variant==CarButtonStyle.SOFT->p.accentSoft
        variant in setOf(CarButtonStyle.TEXT,CarButtonStyle.INK_OUTLINE)->Color.Transparent
        else->p.background
    }
    val foreground=when {
        !enabled->p.secondary
        popupRole!=null->if(popupRole==CarPopupButtonRole.CONFIRM)p.onButton else p.text
        variant==CarButtonStyle.ON_INK->p.ink
        variant in setOf(CarButtonStyle.DARK,CarButtonStyle.INK_OUTLINE)->p.onInk
        variant==CarButtonStyle.FILLED->p.selectionMark
        variant==CarButtonStyle.SOFT->p.accent
        variant==CarButtonStyle.DANGER->p.danger
        else->p.text
    }
    val edge=if(popupRole==null && variant in setOf(CarButtonStyle.OUTLINE,CarButtonStyle.DASHED,CarButtonStyle.INK_OUTLINE,CarButtonStyle.DANGER))
        Modifier.tripBorder(CarTokens.BorderWidth,when(variant) {
            CarButtonStyle.INK_OUTLINE->p.routeOnInk
            CarButtonStyle.DANGER->p.danger
            else->p.divider
        },radius,variant==CarButtonStyle.DASHED) else Modifier
    Row(modifier.width(IntrinsicSize.Max).widthIn(min=minWidth)
        .carTap(enabled=enabled&&!busy,source=source,onClick=onClick).semantics {contentDescription=accessibility}
        .layout {measurable,constraints ->
            val visual=measurable.measure(constraints)
            // Add touch space around smaller L/W visuals without shrinking a driving
            // action whose caller explicitly supplies a taller minimum/fixed height.
            val height=constraints.constrainHeight(maxOf(CarTokens.Touch.roundToPx(),visual.height))
            layout(visual.width,height) {visual.placeRelative(0,(height-visual.height)/2)}
        }.heightIn(min=visualHeight).clip(RoundedCornerShape(radius))
        .background(if(pressed)p.pressedOverlay.compositeOver(background) else background).then(edge)
        .padding(horizontal=paddingH,vertical=paddingV),
        horizontalArrangement=Arrangement.spacedBy(gap,Alignment.CenterHorizontally),verticalAlignment=Alignment.CenterVertically) {
        if(busy)CarLoading(Modifier.size(iconSize),foreground)
        else icon?.let {CarIcon(it,Modifier.size(iconSize),foreground)}
        TripText(label,style=textStyle ?: labelStyle.copy(fontWeight=if(filled)FontWeight.Bold else FontWeight.Normal),
            color=foreground,maxLines=2)
    }
}

@Composable
internal fun CarCard(modifier: Modifier=Modifier,selected: Boolean=false,outlined: Boolean=false,dashed: Boolean=false,
    background: Color=Color.Unspecified,borderWidth: Dp=if(selected)CarTokens.SelectedBorderWidth else CarTokens.BorderWidth,
    padding: PaddingValues=PaddingValues(CarTokens.CardPadding),radius: Dp=CarTokens.RadiusCard,
    tone: CarCardTone=when {selected->CarCardTone.SELECTED;outlined->CarCardTone.OUTLINED;dashed->CarCardTone.DASHED;else->CarCardTone.SURFACE},
    content: @Composable ColumnScope.()->Unit) {
    val p=LocalCarPalette.current
    val fill=if(background!=Color.Unspecified)background else when(tone) {
        CarCardTone.INK->p.ink
        CarCardTone.SOFT->p.accentSoft
        CarCardTone.SURFACE->p.low
        else->p.background
    }
    val edge=if(tone in setOf(CarCardTone.SELECTED,CarCardTone.OUTLINED,CarCardTone.DASHED,CarCardTone.INK,CarCardTone.SOFT))Modifier.tripBorder(
        if(tone==CarCardTone.SELECTED)CarTokens.SelectedBorderWidth else borderWidth,
        when(tone) {CarCardTone.SELECTED->p.accent;CarCardTone.INK->p.inkBorder;CarCardTone.SOFT->p.softBorder;else->p.divider},radius,tone==CarCardTone.DASHED) else Modifier
    CompositionLocalProvider(LocalCarPalette provides if(tone==CarCardTone.INK)p.copy(text=p.onInk,secondary=p.onInkSecondary) else p) {
        Column(modifier.fillMaxWidth().clip(RoundedCornerShape(radius)).background(fill).then(edge)
            .padding(padding),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),content=content)
    }
}

@LayoutScopeMarker
internal interface TripAdaptiveScope {
    /** 넓은 화면에서 이 열이 나눠 받을 가로 비율. 좁은 화면에서는 모든 열이 전체 폭을 쓴다. */
    fun Modifier.weight(weight: Float): Modifier=then(TripAdaptiveWeight(weight))
}

private class TripAdaptiveWeight(val weight: Float): ParentDataModifier {
    init {require(weight>0f) {"weight must be positive"}}
    override fun Density.modifyParentData(parentData: Any?): Any=this@TripAdaptiveWeight
}

private object TripAdaptiveScopeInstance: TripAdaptiveScope

/**
 * 넓은 화면에서 [weights] 비율로 [width]를 나눈 각 열의 폭. 열 사이 [gap]을 먼저 빼고, 반올림으로 남는 픽셀은 마지막 열이 받는다.
 * 폭은 내용과 무관하게 비율로만 정해진다. 내용의 최소 폭으로 줄을 바꾸면(FlowRow) 내용이 바뀔 때 뒤 열이 높이가 정해진
 * 화면 밖 둘째 줄로 밀려 사라진다.
 */
internal fun tripAdaptiveColumnWidths(width: Int,gap: Int,weights: List<Float>): List<Int> {
    if(weights.isEmpty())return emptyList()
    val room=(width-gap*(weights.size-1)).coerceAtLeast(0)
    val total=weights.sum()
    val widths=weights.dropLast(1).map {(room*it/total).toInt()}
    return widths+(room-widths.sum())
}

/**
 * 좁은 화면([narrow])에서는 열을 위에서 아래로 쌓고, 넓은 화면에서는 모든 열을 한 줄에 비율대로 나란히 둔다.
 * 넓은 화면의 열 배치는 내용 길이·상태와 무관하다.
 */
@Composable
internal fun TripAdaptiveRow(modifier: Modifier=Modifier,narrow: Boolean,gap: Dp=CarTokens.Gap,
    content: @Composable TripAdaptiveScope.()->Unit) {
    Layout({TripAdaptiveScopeInstance.content()},modifier.fillMaxWidth()) {measurables,constraints->
        val space=gap.roundToPx()
        val width=constraints.maxWidth
        val placeables=if(narrow)measurables.map {it.measure(constraints.copy(minWidth=width,minHeight=0))}
            else tripAdaptiveColumnWidths(width,space,measurables.map {(it.parentData as? TripAdaptiveWeight)?.weight ?: 1f})
                .zip(measurables) {columnWidth,measurable->measurable.measure(constraints.copy(minWidth=columnWidth,maxWidth=columnWidth,minHeight=0))}
        val height=if(narrow)placeables.sumOf {it.height}+space*(placeables.size-1).coerceAtLeast(0)
            else placeables.maxOfOrNull {it.height} ?: 0
        layout(width,constraints.constrainHeight(height)) {
            var offset=0
            placeables.forEach {
                if(narrow) {it.placeRelative(0,offset);offset+=it.height+space}
                else {it.placeRelative(offset,0);offset+=it.width+space}
            }
        }
    }
}

@Composable
internal fun TripHeading(title: String,subtitle: String?=null,onBack: (() ->Unit)?=null,badge: String?=null,
    activeBadge: Boolean=false,screenTitle: Boolean=false,gear: TripGear?=null,actions: (@Composable RowScope.()->Unit)?=null) {
    Box {
        val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
        Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                if(onBack!=null)Box(Modifier.size(CarTokens.Touch).clip(RoundedCornerShape(CarTokens.ButtonRadius)).carTap(onClick=onBack)
                    .semantics {contentDescription="뒤로"},contentAlignment=Alignment.Center) {CarIcon(CarSymbol.Back,Modifier.size(CarTokens.ButtonIcon))}
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                        TripText(title,Modifier.weight(1f,fill=false),style=if(onBack!=null || screenTitle)CarType.Title else CarType.Section,
                            maxLines=2)
                        badge?.let {CarStatusPill(it,activeBadge,kind=if(activeBadge)CarStatusTone.ACTIVE else CarStatusTone.OUTLINE)}
                    }
                    subtitle?.let {TripText(it,secondary=true,maxLines=3)}
                    if(narrow)gear?.let {CarGearBadge(it)}
                }
                if(!narrow) {gear?.let {CarGearBadge(it)};actions?.invoke(this)}
            }
            if(narrow && actions!=null)Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium,Alignment.End),content=actions)
        }
    }
}

/** P/D shows the gear glyph; other or unconfirmed gears must not look like a confirmed gear. */
internal fun tripGearBadge(gear: TripGear): Pair<String?,String> = when(gear) {
    TripGear.PARK->"P" to "정차 중"
    TripGear.DRIVE->"D" to "주행 중"
    else->null to "차량 상태 확인 중"
}

@Composable
internal fun CarGearBadge(gear: TripGear,onInk: Boolean=false) {
    val p=LocalCarPalette.current
    val (glyph,label)=tripGearBadge(gear)
    if(glyph==null) {
        CarStatusPill(label,kind=if(onInk)CarStatusTone.ON_INK else CarStatusTone.NEUTRAL)
        return
    }
    Row(Modifier.background(if(onInk)p.inkDivider else p.low,RoundedCornerShape(CarTokens.ChipRadius))
        .padding(horizontal=CarTokens.Gap,vertical=CarTokens.SpaceMedium).clearAndSetSemantics {contentDescription=label},
        horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
        Box(Modifier.size(CarTokens.GearSize).background(p.ink,RoundedCornerShape(CarTokens.GearRadius)),contentAlignment=Alignment.Center) {
            TripText(glyph,style=CarType.Label.copy(fontWeight=FontWeight.Bold),color=p.onInk)
        }
        TripText(label,color=if(onInk)p.onInk else p.secondary,maxLines=2)
    }
}

@Composable
internal fun TripField(label: String,value: String,onChange: (String)->Unit,max: Int,enabled: Boolean=true,multiline: Boolean=false) {
    var focused by remember {mutableStateOf(false)}
    val p=LocalCarPalette.current
    Column(verticalArrangement=Arrangement.spacedBy(CarTokens.FieldGap)) {
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.SpaceBetween) {
            TripText(label,style=CarType.Body.copy(fontWeight=FontWeight.Bold));TripText("${value.codePointCount(0,value.length)}/$max",secondary=true)
        }
        BasicTextField(value,{if(it.codePointCount(0,it.length)<=max)onChange(it)},
            Modifier.fillMaxWidth().onFocusChanged {focused=it.isFocused}
                .background(p.background,RoundedCornerShape(CarTokens.FieldRadius))
                .tripBorder(CarTokens.FieldBorderWidth,if(focused)p.accent else p.divider,CarTokens.FieldRadius)
                .semantics {contentDescription=label},
            enabled=enabled,textStyle=(if(multiline)CarType.Body else CarType.Field).copy(color=if(enabled)p.text else p.secondary),
            singleLine=!multiline,minLines=if(multiline)4 else 1,cursorBrush=SolidColor(p.accent),
            decorationBox={inner->
                Box(Modifier.heightIn(min=if(multiline)CarTokens.Row*2 else CarTokens.FieldHeight)
                    .padding(horizontal=CarTokens.FieldPaddingHorizontal),contentAlignment=Alignment.CenterStart) {inner()}
            })
    }
}

internal enum class CarStatusTone { ACTIVE, OUTLINE, ASSIGNED, UNASSIGNED, PENDING, SOFT, PAST, TEXT, NEUTRAL, INK, LIVE, ON_INK }

@Composable
internal fun CarStatusPill(label: String,active: Boolean=false,kind: CarStatusTone=if(active)CarStatusTone.ACTIVE else CarStatusTone.SOFT) {
    val p=LocalCarPalette.current
    val filled=kind in setOf(CarStatusTone.ACTIVE,CarStatusTone.UNASSIGNED,CarStatusTone.INK,CarStatusTone.LIVE)
    val background=when(kind) {
        CarStatusTone.ACTIVE->p.accent
        CarStatusTone.INK->p.ink
        CarStatusTone.LIVE,CarStatusTone.SOFT->p.accentSoft
        CarStatusTone.UNASSIGNED,CarStatusTone.PAST,CarStatusTone.NEUTRAL->p.low
        CarStatusTone.ASSIGNED->p.background
        else->Color.Transparent
    }
    val color=when(kind) {
        CarStatusTone.ACTIVE->p.selectionMark
        CarStatusTone.INK,CarStatusTone.ON_INK->p.onInk
        CarStatusTone.SOFT,CarStatusTone.LIVE->p.accent
        CarStatusTone.UNASSIGNED->p.text
        else->p.secondary
    }
    val member=kind in setOf(CarStatusTone.ASSIGNED,CarStatusTone.UNASSIGNED,CarStatusTone.PENDING)
    val radius=if(member)CarTokens.Radius else CarTokens.ChipRadius
    val edge=when(kind) {
        CarStatusTone.OUTLINE->Modifier.tripBorder(CarTokens.BorderWidth,p.secondary,radius)
        CarStatusTone.ASSIGNED->Modifier.tripBorder(CarTokens.BorderWidth,p.divider,radius)
        CarStatusTone.PENDING->Modifier.tripBorder(CarTokens.BorderWidth,p.divider,radius,true)
        CarStatusTone.ON_INK->Modifier.tripBorder(CarTokens.BorderWidth,p.routeOnInk,radius)
        else->Modifier
    }
    Row(Modifier.heightIn(min=if(member)CarTokens.PillMemberHeight else CarTokens.PillHeight)
        .background(background,RoundedCornerShape(radius)).then(edge)
        .padding(horizontal=CarTokens.PillPaddingHorizontal,vertical=CarTokens.PillPaddingVertical),
        verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
        if(kind==CarStatusTone.LIVE)Box(Modifier.size(CarTokens.SpaceSmall).background(p.accent,CircleShape))
        TripText(label,style=CarType.Label.copy(fontWeight=if(filled)FontWeight.Bold else FontWeight.Normal),color=color,maxLines=2)
    }
}

/** 이 차가 나와 어떤 관계인지. 준비 개요·차 탭·차 관리·주행 화면이 같은 이름을 쓴다. */
internal fun tripCarRoleLabel(car: TripCar): String? = when {car.isMine->"내 차";car.iRide->"내가 탄 차";else->null}

/** '내 차'·'내가 탄 차' 칩. 어디서나 SOFT 톤으로 차 이름 줄 오른쪽 끝에 둔다. */
@Composable
internal fun TripCarRolePill(car: TripCar) {
    tripCarRoleLabel(car)?.let {CarStatusPill(it,kind=CarStatusTone.SOFT)}
}

@Composable
internal fun TripMenuItem(menu: TripPlanMenu,selected: Boolean,onClick: ()->Unit) {
    val palette=LocalCarPalette.current
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    val background=if(selected)palette.ink else Color.Transparent
    Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.TripSelectableRowHeight).carTap(role=Role.Tab,source=source,onClick=onClick)
        .clip(RoundedCornerShape(CarTokens.TripListRadius))
        .background(if(pressed)palette.pressedOverlay.compositeOver(background) else background)
        .then(if(selected)Modifier.border(CarTokens.SelectedBorderWidth,palette.selectionIndicator,RoundedCornerShape(CarTokens.TripListRadius)) else Modifier)
        .semantics {this.selected=selected;contentDescription=menu.tab.title}.padding(horizontal=CarTokens.CardPadding,vertical=CarTokens.SpaceMedium),
        horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
        Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceXSmall)) {
            TripText(menu.tab.title,style=CarType.DrivingHeroLabel.copy(fontWeight=if(selected)FontWeight.Bold else FontWeight.Normal),
                color=if(selected)palette.onInk else palette.text,maxLines=2)
            if(menu.subtitle.isNotEmpty())TripText(menu.subtitle,style=CarType.Label,
                color=if(selected)palette.onInkSecondary else palette.secondary,maxLines=2)
        }
        if(menu.count.isNotEmpty())TripText(menu.count,style=CarType.Section,color=if(selected)palette.onInk else palette.text)
    }
}

@Composable
internal fun TripListRow(title: String,subtitle: List<String> = emptyList(),selected: Boolean?=null,enabled: Boolean=true,
    onClick: (() ->Unit)?=null,modifier: Modifier=Modifier,trailing: (@Composable RowScope.()->Unit)?=null) {
    val p=LocalCarPalette.current
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    val background=if(selected==true)p.background else p.low
    val edge=if(selected==true)Modifier.tripBorder(CarTokens.SelectedBorderWidth,p.text,CarTokens.TripListRadius) else Modifier
    val row=modifier.fillMaxWidth().heightIn(min=if(selected==null)CarTokens.TripListMinHeight else CarTokens.TripSelectableRowHeight)
        .then(if(onClick==null)Modifier else Modifier.carTap(enabled=enabled,source=source,onClick=onClick))
        .clip(RoundedCornerShape(CarTokens.TripListRadius))
        .background(if(pressed)p.pressedOverlay.compositeOver(background) else background).then(edge)
        .semantics {contentDescription=title;if(selected!=null)this.selected=selected}.padding(horizontal=CarTokens.CardPadding,vertical=CarTokens.SpaceMedium)
    val text: @Composable (Modifier)->Unit={textModifier->
        Column(textModifier,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceXSmall)) {
            TripText(title,Modifier.fillMaxWidth(),style=CarType.Body.copy(fontWeight=FontWeight.Bold),maxLines=2)
            subtitle.filter {it.isNotEmpty()}.forEach {TripText(it,Modifier.fillMaxWidth(),secondary=true,maxLines=3)}
        }
    }
    androidx.compose.ui.layout.Layout({
        text(Modifier)
        if(trailing!=null)Row(verticalAlignment=Alignment.CenterVertically,content=trailing)
    },row) {measurables,constraints->
        val gap=CarTokens.SpaceMedium.roundToPx()
        val loose=constraints.copy(minWidth=0,minHeight=0)
        val stack=constraints.hasBoundedWidth && constraints.maxWidth<CarTokens.TripListStackWidth.roundToPx()
        val action=measurables.getOrNull(1)?.measure(loose)
        val textWidth=if(stack || action==null || !constraints.hasBoundedWidth)constraints.maxWidth
            else (constraints.maxWidth-action.width-gap).coerceAtLeast(0)
        val label=measurables[0].measure(loose.copy(maxWidth=textWidth))
        val width=if(constraints.hasBoundedWidth)constraints.maxWidth
            else label.width+(action?.let {it.width+gap} ?: 0)
        if(stack) {
            val height=maxOf(constraints.minHeight,label.height+(action?.let {it.height+gap} ?: 0))
            layout(width,height) {
                label.placeRelative(0,0)
                action?.placeRelative(0,label.height+gap)
            }
        } else {
            val height=maxOf(constraints.minHeight,label.height,action?.height ?: 0)
            layout(width,height) {
                label.placeRelative(0,(height-label.height)/2)
                action?.placeRelative(width-action.width,(height-action.height)/2)
            }
        }
    }
}

@Composable
internal fun TripDivider() {Box(Modifier.fillMaxWidth().height(CarTokens.BorderWidth).background(LocalCarPalette.current.divider))}
