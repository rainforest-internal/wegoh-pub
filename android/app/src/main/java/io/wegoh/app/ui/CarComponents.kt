package io.wegoh.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.Icon
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.graphics.StrokeJoin
import io.wegoh.app.R
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.semantics.*
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.LineBreak
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.DialogWindowProvider
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import android.os.Build
import android.view.WindowInsets
import android.view.WindowManager

enum class CarSymbol { Route, Discover, Play, Pause, Stop, Navigate, Back, More, Refresh, Download, Check, Lock, Pin, Share, File, Info, Close, Alert,
    Brand, Home, People, Group, Person, Edit, Music, Clock, Settings, Down, Next, Plus, Car, Shield, Link, Bookmark, Remix, Up, Message, Flag, Map, Microphone, Phone, SkipNext, Delete, Speed }

private val LocalCarBodyStyle=staticCompositionLocalOf {CarType.Body}
internal val LocalCarLargeAction=staticCompositionLocalOf {false}
internal val LocalCarActionGroup=staticCompositionLocalOf {false}

@Composable
fun CarIcon(symbol: CarSymbol, modifier: Modifier = Modifier.size(CarTokens.Icon), color: Color = LocalCarPalette.current.text) {
    val official=when(symbol) {
        CarSymbol.Person -> R.drawable.pleos_icon_person
        CarSymbol.Plus -> R.drawable.pleos_icon_plus
        CarSymbol.Microphone -> R.drawable.pleos_icon_microphone
        CarSymbol.Close -> R.drawable.pleos_icon_close
        CarSymbol.Info -> R.drawable.pleos_icon_info
        CarSymbol.Alert -> R.drawable.pleos_icon_alert
        CarSymbol.Check -> R.drawable.pleos_icon_check
        CarSymbol.Down -> R.drawable.pleos_icon_down
        CarSymbol.Up -> R.drawable.pleos_icon_up
        CarSymbol.Pause -> R.drawable.pleos_icon_pause
        else -> 0
    }
    if(official!=0) {Icon(painterResource(official),contentDescription=null,modifier=modifier,tint=color);return}
    val product=when(symbol) {
        CarSymbol.Phone -> R.drawable.wegoh_icon_phone
        CarSymbol.Route -> R.drawable.wegoh_icon_route
        CarSymbol.Discover -> R.drawable.wegoh_icon_discover
        CarSymbol.Play -> R.drawable.wegoh_icon_play
        CarSymbol.Pause -> R.drawable.pleos_icon_pause
        CarSymbol.Stop -> R.drawable.wegoh_icon_stop
        CarSymbol.Navigate -> R.drawable.wegoh_icon_navigate
        CarSymbol.Back -> R.drawable.wegoh_icon_back
        CarSymbol.More -> R.drawable.wegoh_icon_more
        CarSymbol.Refresh -> R.drawable.wegoh_icon_refresh
        CarSymbol.Download -> R.drawable.wegoh_icon_download
        CarSymbol.Check -> R.drawable.wegoh_icon_check
        CarSymbol.Lock -> R.drawable.wegoh_icon_lock
        CarSymbol.Pin -> R.drawable.wegoh_icon_pin
        CarSymbol.Share -> R.drawable.wegoh_icon_share
        CarSymbol.File -> R.drawable.wegoh_icon_file
        CarSymbol.Info -> R.drawable.wegoh_icon_info
        CarSymbol.Close -> R.drawable.wegoh_icon_close
        CarSymbol.Alert -> R.drawable.wegoh_icon_alert
        CarSymbol.Brand -> R.drawable.wegoh_icon_brand
        CarSymbol.Home -> R.drawable.wegoh_icon_home
        CarSymbol.People -> R.drawable.wegoh_icon_people
        CarSymbol.Group -> R.drawable.wegoh_icon_group
        CarSymbol.Person -> R.drawable.wegoh_icon_person
        CarSymbol.Edit -> R.drawable.wegoh_icon_edit
        CarSymbol.Music -> R.drawable.wegoh_icon_music
        CarSymbol.Clock -> R.drawable.wegoh_icon_clock
        CarSymbol.Settings -> R.drawable.wegoh_icon_settings
        CarSymbol.Down -> R.drawable.wegoh_icon_down
        CarSymbol.Next -> R.drawable.wegoh_icon_next
        CarSymbol.SkipNext -> R.drawable.wegoh_icon_skip_next
        CarSymbol.Delete -> R.drawable.wegoh_icon_delete
        CarSymbol.Speed -> R.drawable.wegoh_icon_speed
        CarSymbol.Plus -> R.drawable.wegoh_icon_plus
        CarSymbol.Car -> R.drawable.wegoh_icon_car
        CarSymbol.Shield -> R.drawable.wegoh_icon_shield
        CarSymbol.Link -> R.drawable.wegoh_icon_link
        CarSymbol.Bookmark -> R.drawable.wegoh_icon_bookmark
        CarSymbol.Remix -> R.drawable.wegoh_icon_remix
        CarSymbol.Up -> R.drawable.wegoh_icon_up
        CarSymbol.Message -> R.drawable.wegoh_icon_message
        CarSymbol.Flag -> R.drawable.wegoh_icon_flag
        CarSymbol.Map -> R.drawable.wegoh_icon_map
        CarSymbol.Microphone -> R.drawable.wegoh_icon_microphone
    }
    Icon(painterResource(product),contentDescription=null,modifier=modifier,tint=color)
}

internal val LocalCarTextAlign=staticCompositionLocalOf {TextAlign.Start}

/** Failure, recovery and status notices keep every line: copy stays short, but the screen never ellipsizes it. */
const val CarMessageLines = Int.MAX_VALUE

@Composable
fun CarText(text: String, modifier: Modifier = Modifier, style: TextStyle = LocalCarBodyStyle.current,
    secondary: Boolean = false, maxLines: Int = 1) {
    val p=LocalCarPalette.current
    Text(text, modifier, style=if(maxLines>1)style.copy(lineBreak=LineBreak.Heading) else style, color=if(secondary)p.secondary else p.text,
        maxLines=maxLines, overflow=TextOverflow.Ellipsis,textAlign=LocalCarTextAlign.current)
}

/** Official center/middle 95% visual feedback keeps layout, hit area and popup anchors fixed. */
@Composable
fun Modifier.carTap(enabled: Boolean = true, role: Role = Role.Button,
    source: MutableInteractionSource? = null, onClick: () -> Unit): Modifier {
    val actual = source ?: remember { MutableInteractionSource() }
    val pressed by actual.collectIsPressedAsState()
    val focused by actual.collectIsFocusedAsState()
    val focusColor=LocalCarPalette.current.text
    val feedback = LocalHapticFeedback.current
    return clickable(enabled=enabled,role=role,interactionSource=actual,indication=null) {
        feedback.performHapticFeedback(HapticFeedbackType.LongPress);onClick()
    }.drawWithContent {
        if(pressed)scale(CarTokens.PressedScale,CarTokens.PressedScale,pivot=Offset(size.width*CarTokens.PressedOriginFractionX,size.height*CarTokens.PressedOriginFractionY)){this@drawWithContent.drawContent()}
        else drawContent()
        if(focused)drawRoundRect(focusColor,topLeft=Offset(CarTokens.FocusInset.toPx(),CarTokens.FocusInset.toPx()),
            size=Size((size.width-CarTokens.FocusInset.toPx()*2).coerceAtLeast(0f),(size.height-CarTokens.FocusInset.toPx()*2).coerceAtLeast(0f)),
            cornerRadius=CornerRadius(CarTokens.Radius.toPx()),style=Stroke(CarTokens.BorderWidth.toPx()))
    }
}

@Composable
fun CarAction(label: String, icon: CarSymbol? = null, onClick: () -> Unit, modifier: Modifier = Modifier,
    primary: Boolean = false, enabled: Boolean = true, busy: Boolean = false, accessibility: String = label) {
    val p=LocalCarPalette.current
    val source=remember{MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    val feedback=LocalHapticFeedback.current
    val color=if(!enabled)p.secondary else if(primary)p.onButton else p.text
    val large=LocalCarLargeAction.current
    val visualHeight=if(large)CarTokens.PopupLargeButtonHeight else CarTokens.ButtonVisualHeight
    val minWidth=if(large)CarTokens.PopupLargeButtonMinWidth else CarTokens.ButtonMinWidth
    val radius=if(large)CarTokens.PopupLargeButtonRadius else CarTokens.ButtonRadius
    val paddingH=if(large)CarTokens.PopupLargeButtonPaddingHorizontal else CarTokens.ButtonPadding
    val paddingV=if(large)CarTokens.PopupLargeButtonPaddingVertical else CarTokens.ButtonPaddingVertical
    val gap=if(large)CarTokens.PopupLargeButtonGap else CarTokens.ButtonGap
    val iconSize=if(large)CarTokens.PopupLargeButtonIcon else CarTokens.ButtonIcon
    val sizeModifier=if(LocalCarActionGroup.current)modifier.fillMaxWidth() else modifier.width(IntrinsicSize.Max)
    Box(sizeModifier.widthIn(min=minWidth).heightIn(min=maxOf(CarTokens.Touch,visualHeight))
        .carTap(enabled=enabled&&!busy,source=source,onClick=onClick)
        .semantics {contentDescription=accessibility},contentAlignment=Alignment.Center) {
    Row(Modifier.fillMaxWidth().heightIn(min=visualHeight).clip(RoundedCornerShape(radius))
        .background(if(!enabled)p.low else if(primary)if(pressed)p.filledPressed else p.button else if(pressed)p.selected else p.low)
        .padding(horizontal=paddingH,vertical=paddingV),
        horizontalArrangement=Arrangement.Center,verticalAlignment=Alignment.CenterVertically) {
        val tint=color
        if(busy) CarLoading(Modifier.size(iconSize),color=tint)
        else if(icon!=null)CarIcon(icon,Modifier.size(iconSize),tint)
        if(busy || icon!=null)Spacer(Modifier.width(gap))
        Text(label,style=if(large)CarType.Section else CarType.Action,color=tint,maxLines=if(large || LocalCarActionGroup.current)2 else 1,overflow=TextOverflow.Ellipsis)
    }
    }
}

@Composable
fun CarIconAction(label: String, icon: CarSymbol, onClick: () -> Unit, enabled: Boolean = true) {
    val p=LocalCarPalette.current
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    val feedback=LocalHapticFeedback.current
    Box(Modifier.size(width=maxOf(CarTokens.Touch,CarTokens.IconButtonVisualWidth),height=maxOf(CarTokens.Touch,CarTokens.IconButtonVisualHeight))
        .carTap(enabled=enabled,source=source,onClick=onClick)
        .semantics{contentDescription=label},contentAlignment=Alignment.Center) {
        Box(Modifier.size(CarTokens.IconButtonVisualWidth,CarTokens.IconButtonVisualHeight).clip(RoundedCornerShape(CarTokens.IconButtonRadius))
            .background(if(pressed)p.selected else p.background),contentAlignment=Alignment.Center) {
        CarIcon(icon,Modifier.size(CarTokens.IconButtonIcon),color=if(enabled)p.text else p.secondary)
        }
    }
}

@Composable
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
/** Pleos System Popup의 Title·Description은 가운데 정렬 머리(Figma 67:29533, 간격 24)이고,
 * Body는 그 아래 별도 슬롯이라 목록·카드처럼 시작 정렬로 둔다. 문장 설명은 [description]으로 넘긴다. */
fun CarPopup(title: String, onDismiss: () -> Unit, body: (@Composable ColumnScope.() -> Unit)? = null,
    description: String? = null, actionColumns: Int=2,actions: @Composable RowScope.() -> Unit) {
    // 팝업은 자기 표면(테마 배경)을 그리므로 여는 쪽 카드가 바꾼 글자색(INK의 onInk 등)을 물려받지 않는다.
    val p=LocalCarThemePalette.current
    val popupHeight=minOf((LocalConfiguration.current.screenHeightDp.dp-CarTokens.Frame*2).coerceAtLeast(CarTokens.Row*2),CarTokens.PopupMaxHeight)
    Dialog(onDismissRequest=onDismiss,properties=DialogProperties(usePlatformDefaultWidth=false)) {
        ObserveOwnedCarWindow()
        val window=(LocalView.current.parent as? DialogWindowProvider)?.window
        SideEffect {
            window?.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING)
            if(Build.VERSION.SDK_INT>=30)window?.let { win ->
                val params=win.attributes
                params.setFitInsetsTypes(WindowInsets.Type.statusBars() or WindowInsets.Type.navigationBars())
                win.attributes=params
            }
        }
        Box(Modifier.fillMaxWidth().padding(CarTokens.Frame),contentAlignment=Alignment.Center) {
        CompositionLocalProvider(LocalCarPalette provides p,LocalCarTextAlign provides TextAlign.Center,LocalCarBodyStyle provides CarType.DialogBody,LocalCarLargeAction provides false) {
        Column(Modifier.widthIn(max=CarTokens.PopupMaxWidth).fillMaxWidth().heightIn(max=popupHeight).pleosPopupShadow().clip(RoundedCornerShape(CarTokens.PopupRadius))
            .background(p.background).padding(CarTokens.PopupPadding),verticalArrangement=Arrangement.spacedBy(CarTokens.PopupGap),horizontalAlignment=Alignment.CenterHorizontally) {
            Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),horizontalAlignment=Alignment.CenterHorizontally) {
                CarText(title,style=CarType.Title,maxLines=2)
                description?.let {CarText(it,Modifier.fillMaxWidth(),style=CarType.DialogBody,maxLines=CarMessageLines)}
            }
            if(body!=null)CompositionLocalProvider(LocalCarTextAlign provides TextAlign.Start) {
                Column(Modifier.fillMaxWidth().weight(1f,fill=false).verticalScroll(rememberScrollState()),
                    verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),content=body)
            }
            // Official horizontal/vertical action variants: wrap by measured
            // intrinsic width rather than clipping essential confirmation text.
            CompositionLocalProvider(LocalCarLargeAction provides true) {
                CarPopupActions(Modifier.fillMaxWidth(),actionColumns,actions)
            }
        }
        }
        }
    }
}

/** Official figures keep the dark confirmation before the light cancellation on both axes.
 * Figma calls those styles Secondary and Primary respectively; they are not action semantics.
 */
@Composable
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
internal fun CarPopupActions(modifier: Modifier=Modifier,columns: Int=2,actions: @Composable RowScope.()->Unit) {
    val gap=CarTokens.PopupButtonsGap
    FlowRow(modifier,maxItemsInEachRow=columns,horizontalArrangement=Arrangement.spacedBy(gap),verticalArrangement=Arrangement.spacedBy(gap)){actions()}
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
fun CarMetadata(values: List<String>,modifier: Modifier=Modifier,style: TextStyle=CarType.Label,secondary: Boolean=true) {
    if(values.none{it.isNotBlank()})return
    FlowRow(modifier,horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
        values.filter{it.isNotBlank()}.forEach {CarText(it,style=style,secondary=secondary,maxLines=2)}
    }
}

@Composable
fun CarChoice(title: String,checked: Boolean,symbol: CarSymbol,enabled: Boolean=true,onClick: ()->Unit) {
    val p=LocalCarPalette.current
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    val background=if(checked)p.selected else p.low
    Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Row)
        .carTap(enabled=enabled,role=Role.RadioButton,source=source,onClick=onClick)
        .clip(RoundedCornerShape(CarTokens.Radius))
        .background(if(pressed)p.pressedOverlay.compositeOver(background) else background)
        .then(if(checked)Modifier.border(CarTokens.BorderWidth,p.text,RoundedCornerShape(CarTokens.Radius))else Modifier)
        .clearAndSetSemantics {contentDescription=title;role=Role.RadioButton;selected=checked;toggleableState=ToggleableState(checked)
            stateDescription=if(checked)"선택됨" else "선택 안 됨";if(!enabled)disabled() else onClick{onClick();true}}
        .padding(CarTokens.SpaceLarge),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceLarge)) {
        CarIcon(symbol,color=if(enabled)p.text else p.secondary);CarText(title,Modifier.weight(1f),style=CarType.Section,secondary=!enabled,maxLines=2)
        Box(Modifier.size(CarTokens.RadioSize).clip(CircleShape)
            .background(if(checked)p.selectionMark else p.background)
            .border(if(checked)CarTokens.RadioSelectedBorder else CarTokens.RadioBorder,
                p.selectionOn,CircleShape))
    }
}

/** UI navigation only. Home never stops the controller/session or clears user records. */
data class CarPageNavigation(val select: (String)->Unit,val home: ()->Unit)
val LocalCarPageNavigation=staticCompositionLocalOf<CarPageNavigation?> {null}
val LocalVehicleLandingPage=staticCompositionLocalOf {"trips"}
data class CarPageItem(val title: String,val symbol: CarSymbol,val selected: Boolean,val onSelect: ()->Unit)

@Composable
fun CarPageHeader(title: String,onBack: ()->Unit,onHome: ()->Unit,items: List<CarPageItem>,
    menuEnabled: Boolean=true,suffix: @Composable RowScope.()->Unit={}) {
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val narrow=maxWidth<CarTokens.CompactHeaderBreakpoint
        Column(Modifier.fillMaxWidth().heightIn(min=CarTokens.Header),verticalArrangement=Arrangement.Center) {
            if(narrow) {
                Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
                    CarIconAction("뒤로",CarSymbol.Back,onBack);Spacer(Modifier.weight(1f));suffix()
                }
                Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
                    CarIconAction("홈",CarSymbol.Home,onHome)
                    CarPageMenu(title,items,menuEnabled,Modifier.weight(1f))
                }
            } else Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
                CarIconAction("뒤로",CarSymbol.Back,onBack)
                CarIconAction("홈",CarSymbol.Home,onHome)
                CarPageMenu(title,items,menuEnabled,Modifier.weight(1f))
                suffix()
            }
        }
    }
}

@Composable
private fun CarPageMenu(title: String,items: List<CarPageItem>,enabled: Boolean,modifier: Modifier) {
    val p=LocalCarPalette.current
    var expanded by remember {mutableStateOf(false)}
    val source=remember {MutableInteractionSource()};val pressed by source.collectIsPressedAsState()
    LaunchedEffect(enabled,title) {expanded=false}
    BoxWithConstraints(modifier) {
        Box(Modifier.heightIn(min=CarTokens.Touch).width(IntrinsicSize.Max).widthIn(max=maxWidth)
            .carTap(enabled=enabled&&items.isNotEmpty(),source=source){expanded=!expanded}
            .semantics {contentDescription="전체 메뉴";stateDescription=title+if(expanded)" 펼침" else " 접힘"},contentAlignment=Alignment.Center) {
            val background=if(expanded)p.selected else p.background
            Row(Modifier.clip(RoundedCornerShape(CarTokens.Radius)).background(if(pressed)p.pressedOverlay.compositeOver(background) else background)
                .padding(horizontal=CarTokens.PagePrimaryPaddingHorizontal,vertical=CarTokens.PagePrimaryPaddingVertical),
                verticalAlignment=Alignment.CenterVertically) {
                CarText(title,Modifier.weight(1f,fill=false),style=CarType.Title)
                if(items.isNotEmpty())CarIcon(if(expanded)CarSymbol.Up else CarSymbol.Down,Modifier.padding(start=CarTokens.PagePrimaryTitleGap).size(CarTokens.PagePrimaryIndicatorIcon))
            }
        }
        androidx.compose.material3.MaterialTheme(shapes=androidx.compose.material3.MaterialTheme.shapes.copy(extraSmall=RoundedCornerShape(CarTokens.Radius))) {
        DropdownMenu(expanded=expanded&&enabled,onDismissRequest={expanded=false},
            modifier=Modifier.width(maxWidth.coerceIn(CarTokens.DropdownMinWidth,CarTokens.DropdownMaxWidth)).background(p.background)) {
            ObserveOwnedCarWindow()
            items.forEach {item->CarChoice(item.title,item.selected,item.symbol){expanded=false;item.onSelect()}}
        }
        }
    }
}
