package io.wegoh.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.semantics.*
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

@Composable
fun CarDivider() {Box(Modifier.fillMaxWidth().height(CarTokens.HairlineWidth).background(LocalCarPalette.current.divider))}

@Composable
fun CarScreenScaffold(title: String,onBack: ()->Unit,onHome: ()->Unit=onBack,
    items: List<CarPageItem> = emptyList(),showHeader: Boolean=true,menuEnabled: Boolean=true,
    suffix: @Composable RowScope.()->Unit={},embedded: Boolean=false,primaryTabs: Boolean=false,receiving: Boolean?=null,
    onRefresh: ()->Unit={},refreshEnabled: Boolean=true,content: @Composable ColumnScope.()->Unit) {
    val tabs=primaryTabs && !embedded
    val frame=if(embedded)Modifier.fillMaxSize() else Modifier.fillMaxSize().background(LocalCarPalette.current.background).systemBarsPadding()
        .then(if(tabs)Modifier else Modifier.padding(horizontal=CarTokens.Frame))
    Column(frame) {
        if(showHeader && !embedded) {
            if(tabs)CarPrimaryHeader(items,menuEnabled,receiving,onRefresh,refreshEnabled)
            else CarPageHeader(title,onBack,onHome,items,menuEnabled,suffix)
        }
        if(!embedded && !tabs)CarDivider()
        Column(Modifier.weight(1f).fillMaxWidth().padding(horizontal=if(tabs)CarTokens.Frame else 0.dp,
            vertical=if(embedded)0.dp else CarTokens.Gap),content=content)
    }
}

@Composable
fun CarLoadingState(label: String,modifier: Modifier=Modifier) {
    CarStateContent(label,CarSymbol.Clock,modifier,loading=true) {}
}

@Composable
fun CarEmptyState(label: String,modifier: Modifier=Modifier,detail: String?=null,symbol: CarSymbol=CarSymbol.Route,
    action: (@Composable ()->Unit)?=null) {
    CarStateContent(label,symbol,modifier) {detail?.let {CarText(it,secondary=true,maxLines=3)};action?.invoke()}
}

/** 주행 제한 화면이 알려 주는 해제 조건. Pleos는 N단 0km/h도 비주차 제한으로 보므로 '정차 후'가 아니라 P단을 말한다. */
const val CAR_PARK_REQUIRED="P단에서 이용할 수 있어요"

@Composable
fun CarRestrictedState(label: String=CAR_PARK_REQUIRED,modifier: Modifier=Modifier,detail: String?=null,progress: String?=null,onStop: (()->Unit)?=null) {
    CarStateContent(label,CarSymbol.Lock,modifier) {detail?.let {CarText(it,style=CarType.Hero,maxLines=2)}
        progress?.let {CarText(it,secondary=true)};onStop?.let {CarAction("종료",CarSymbol.Stop,it)}}
}

@Composable
fun CarFailureState(label: String,modifier: Modifier=Modifier,detail: String?=null,reportScreen: String?=null,onRetry: ()->Unit) {
    CarStateContent(label,CarSymbol.Refresh,modifier) {
        detail?.let {CarText(it,secondary=true,maxLines=Int.MAX_VALUE)}
        CarButton("다시 불러오기",onRetry,Modifier.fillMaxWidth(),icon=CarSymbol.Refresh)
        reportScreen?.let {CarErrorReport(it)}
    }
}

@Composable
fun CarConnectionState(label: String,modifier: Modifier=Modifier,detail: String?=null,onConnect: ()->Unit) {
    CarStateContent(label,CarSymbol.Car,modifier) {
        detail?.let {CarText(it,secondary=true,maxLines=Int.MAX_VALUE)}
        CarButton("차량 연결",onConnect,Modifier.fillMaxWidth(),icon=CarSymbol.Link)
    }
}

@Composable
private fun CarStateContent(label: String,symbol: CarSymbol,modifier: Modifier,loading: Boolean=false,content: @Composable ()->Unit) {
    val palette=LocalCarPalette.current
    CompositionLocalProvider(LocalCarTextAlign provides TextAlign.Center) {
        BoxWithConstraints(modifier.fillMaxWidth(),contentAlignment=Alignment.Center) {
            val body=if(constraints.hasBoundedHeight)Modifier.verticalScroll(rememberScrollState()).heightIn(min=maxHeight) else Modifier
            Column(body.fillMaxWidth().padding(CarTokens.Gap),horizontalAlignment=Alignment.CenterHorizontally,
                verticalArrangement=Arrangement.Center) {
                CarCard(Modifier.widthIn(max=CarTokens.PopupMaxWidth),outlined=true,padding=PaddingValues(CarTokens.Frame)) {
                    Column(Modifier.fillMaxWidth(),horizontalAlignment=Alignment.CenterHorizontally,
                        verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                        Box(Modifier.size(CarTokens.Touch).background(palette.accentSoft,RoundedCornerShape(CarTokens.ButtonRadius)),
                            contentAlignment=Alignment.Center) {
                            if(loading)CarLoading(Modifier.size(CarTokens.Icon),palette.accent)
                            else CarIcon(symbol,Modifier.size(CarTokens.Icon),palette.accent)
                        }
                        CarText(label,style=CarType.Title,maxLines=Int.MAX_VALUE)
                        content()
                    }
                }
            }
        }
    }
}

@Composable
fun CarListRow(title: String,subtitle: List<String> = emptyList(),symbol: CarSymbol?=null,
    selected: Boolean?=null,enabled: Boolean=true,onClick: (()->Unit)?=null,modifier: Modifier=Modifier,
    trailing: (@Composable RowScope.()->Unit)?=null) {
    val p=LocalCarPalette.current
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    val chosen=selected==true
    val role=if(selected==null)Role.Button else Role.RadioButton
    val background=if(chosen)p.selected else p.low
    val activate=onClick
    val semantics=if(selected!=null)Modifier.clearAndSetSemantics {
        this.role=Role.RadioButton;this.selected=chosen;toggleableState=ToggleableState(chosen)
        contentDescription=title;text=androidx.compose.ui.text.AnnotatedString(subtitle.joinToString("\n"))
        stateDescription=if(chosen)"선택됨" else "선택 안 됨"
        if(!enabled)disabled() else if(activate!=null)onClick {activate();true}
    } else Modifier.semantics(mergeDescendants=true) {if(!enabled)disabled()}
    BoxWithConstraints(modifier.fillMaxWidth().heightIn(min=CarTokens.Row)
        .then(if(activate!=null)Modifier.carTap(enabled=enabled,role=role,source=source,onClick=activate) else Modifier)
        .clip(RoundedCornerShape(CarTokens.Radius))
        .background(if(pressed)p.pressedOverlay.compositeOver(background) else background)
        .border(if(chosen)CarTokens.BorderWidth else CarTokens.HairlineWidth,if(chosen)p.text else p.divider,RoundedCornerShape(CarTokens.Radius))
        .then(semantics).padding(CarTokens.Gap)) {
        val stack=trailing!=null && maxWidth/LocalDensity.current.fontScale<CarTokens.ListTrailingBreakpoint
        Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        symbol?.let {CarIcon(it,Modifier.size(CarTokens.IconLarge))}
        Column(Modifier.weight(1f)) {CarText(title,style=CarType.Section,maxLines=2);if(subtitle.isNotEmpty())CarMetadata(subtitle)}
        if(trailing!=null && !stack)trailing() else if(trailing==null && chosen)CarIcon(CarSymbol.Check) else if(trailing==null && selected==null && onClick!=null)CarIcon(CarSymbol.Next)
        }
        if(stack)CompositionLocalProvider(LocalCarActionGroup provides true) {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.End) {trailing?.invoke(this)}
        }
        }
    }
}

/** "first–last / total" only while the list overflows the screen; a list that fits shows no position. */
internal fun carScrollPositionRange(firstVisible: Int,lastVisible: Int?,total: Int,scrollable: Boolean): Pair<Int,Int>? {
    if(!scrollable || total==0)return null
    val first=firstVisible+1
    return first to (lastVisible?.plus(1)?.coerceAtMost(total) ?: first)
}

@Composable
fun CarScrollPosition(state: LazyListState,total: Int,label: String="목록") {
    val (first,last)=carScrollPositionRange(state.firstVisibleItemIndex,state.layoutInfo.visibleItemsInfo.lastOrNull()?.index,
        total,state.canScrollForward || state.canScrollBackward) ?: return
    CarText("$first–$last / $total",style=CarType.Label,secondary=true,
        modifier=Modifier.semantics {contentDescription="$label 현재 위치 $first–$last, 전체 $total"})
}

@Composable
fun CarSwitch(title: String,checked: Boolean,enabled: Boolean=true,onChange: (Boolean)->Unit) {
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Touch).carTap(enabled,Role.Switch,source){onChange(!checked)}
        .semantics {role=Role.Switch;toggleableState=ToggleableState(checked);if(!enabled)disabled()},
        verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        CarText(title,Modifier.weight(1f),secondary=!enabled,maxLines=2)
        CarSwitchVisual(checked,enabled,pressed)
    }
}

@Composable
fun CarSwitchControl(checked: Boolean,onChange: (Boolean)->Unit,modifier: Modifier=Modifier,
    enabled: Boolean=true,accessibility: String="") {
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    Box(modifier.size(width=maxOf(CarTokens.Touch,CarTokens.SwitchWidth),height=maxOf(CarTokens.Touch,CarTokens.SwitchHeight))
        .carTap(enabled,Role.Switch,source){onChange(!checked)}
        .semantics {role=Role.Switch;toggleableState=ToggleableState(checked);contentDescription=accessibility;if(!enabled)disabled()},
        contentAlignment=Alignment.Center) {
        CarSwitchVisual(checked,enabled,pressed)
    }
}

@Composable
private fun CarSwitchVisual(checked: Boolean,enabled: Boolean,pressed: Boolean) {
    val p=LocalCarPalette.current
    // Keep the adopted high-contrast control palette; low-alpha source disabled fills
    // do not meet this app's contrast contract. Position retains the checked state.
    val track=if(!enabled)p.switchDisabledTrack else if(checked)p.switchOn else p.switchOff
    val knob=if(!enabled)p.switchDisabledKnob else if(checked)p.switchKnobOn else p.switchKnobOff
    Box(Modifier.size(CarTokens.SwitchWidth,CarTokens.SwitchHeight).clip(RoundedCornerShape(CarTokens.SwitchRadius))
        .background(if(pressed)p.pressedOverlay.compositeOver(track) else track)
        .border(CarTokens.HairlineWidth,if(enabled)p.text else p.switchDisabledTrack,RoundedCornerShape(CarTokens.SwitchRadius))
        .padding(CarTokens.SwitchPadding),contentAlignment=if(checked)Alignment.CenterEnd else Alignment.CenterStart) {
        Box(Modifier.size(CarTokens.SwitchKnob).clip(RoundedCornerShape(CarTokens.SwitchKnobRadius)).background(knob))
    }
}

@Composable
fun CarErrorNotice(message: String) {
    val p=LocalCarPalette.current
    Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
        CarIcon(CarSymbol.Alert,Modifier.size(CarTokens.IconLarge),p.errorAccent)
        androidx.compose.material3.Text(message,color=p.error,style=CarType.Body,modifier=Modifier.weight(1f))
    }
}

@Composable
fun CarActionGroup(content: @Composable ColumnScope.()->Unit) {
    CompositionLocalProvider(LocalCarActionGroup provides true) {
        Column(Modifier.widthIn(max=CarTokens.ActionGroupMaxWidth).fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),content=content)
    }
}
