@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package io.wegoh.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathMeasure
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import kotlinx.coroutines.delay
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.style.TextAlign
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.nativebusiness.NativeBusinessPanel
import io.wegoh.app.ui.*
import androidx.compose.foundation.shape.CircleShape

/** Setup-only internal child Activity. No OEM driving/status/GNB imitation. */
class VehicleConnectionActivity : ComponentActivity() {
    private lateinit var windows: CarWindowVisibility
    private val app get()=application as WegoApplication
    private val connection get()=app.vehicleConnection
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        windows=CarWindowVisibility(this) {app.controller.setVisible(it.visible,this,it.focused)}
        setContent {
            var progress by remember { mutableStateOf(connection.status()) }
            var businessOpen by remember {mutableStateOf(false)}
            DisposableEffect(connection) { val observer=connection.observe {progress=it};onDispose {observer.close()} }
            val allowed=app.controller.state.setupAllowed
            val previousExpiry=if(progress.previousConnection!=null)connection.verifiedDataBoundary()?.expiresAtMillis else null
            val checkedAt by produceState(System.currentTimeMillis(),previousExpiry) {
                value=System.currentTimeMillis()
                if(previousExpiry!=null && value<previousExpiry) {
                    delay(previousExpiry-value);value=System.currentTimeMillis()
                }
            }
            val retainPanel=progress.previousConnection!=null && previousExpiry!=null && checkedAt<previousExpiry
            BackHandler {if(businessOpen)businessOpen=false else finish()}
            ProvideCarWindowVisibility(windows) {WegoCarTheme {
                if(businessOpen && (progress.stage==VehicleConnection.Stage.CONNECTED || retainPanel)) {
                    NativeBusinessPanel(connection,allowed,{businessOpen=false},{})
                } else ConnectionScreen(progress,allowed,{finish()},{
                startActivity(Intent(this,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP).putExtra("screen","discover"));finish()
            },onStart={connection.start("우리 차",VehicleConnection.DEFAULT_SCOPES)},onRetry={connection.check()},onDisconnect={connection.disconnect()},
                onSwitch={connection.switchAccount("우리 차",VehicleConnection.DEFAULT_SCOPES)},onRegister={connection.registerNewInstallation()},
                onRequestScopes={connection.requestScopes("우리 차",VehicleConnection.DEFAULT_SCOPES)},onBusiness={businessOpen=true}) }}
        }
    }
    override fun onDestroy() {windows.close();super.onDestroy()}
}

@Composable
internal fun ConnectionScreen(progress: VehicleConnection.Progress, allowed: Boolean,
    onBack: ()->Unit,onHome: ()->Unit,onStart: ()->Unit,onRetry: ()->Unit,
    onDisconnect: ()->Unit,onSwitch: ()->Unit,onRegister: ()->Unit = {},onRequestScopes: ()->Unit = {},onHistory: (()->Unit)? = null,onBusiness: (()->Unit)? = null) {
    val shown=if(progress.stage==VehicleConnection.Stage.CHECKING)progress.previousConnection ?: progress else progress
    if(allowed && shown.stage==VehicleConnection.Stage.CONNECTED) {
        ConnectedVehiclePage(refreshing=shown!==progress,onBack=onBack,onDisconnect=onDisconnect,onSwitch=onSwitch)
        return
    }
    TripSurface {CarScreenScaffold("차량 연결",onBack,onHome) {
        val body: @Composable ()->Unit = {
            ConnectionBody(progress,allowed,onStart,onRetry,onDisconnect,onSwitch,onRegister,onRequestScopes,onHistory=onHistory,onBusiness=onBusiness)
        }
        if(allowed && progress.stage in setOf(VehicleConnection.Stage.RECOVERY_REQUIRED,VehicleConnection.Stage.UNAVAILABLE,
            VehicleConnection.Stage.EXPIRED,VehicleConnection.Stage.DENIED)) {
            Box(Modifier.weight(1f).fillMaxWidth(),contentAlignment=Alignment.Center) {
                Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(vertical=CarTokens.Gap)) {body()}
            }
        } else Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(vertical=CarTokens.Gap),
            verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),horizontalAlignment=Alignment.CenterHorizontally) {body()}
    }}
}

@Composable
internal fun ConnectionBody(progress: VehicleConnection.Progress, allowed: Boolean,
    onStart: ()->Unit,onRetry: ()->Unit,onDisconnect: ()->Unit,onSwitch: ()->Unit,onRegister: ()->Unit = {},onRequestScopes: ()->Unit = {},
    canInteract: ()->Boolean = {true},onboarding: Boolean=false,onHistory: (()->Unit)? = null,onBusiness: (()->Unit)? = null,
    windowFocused: Boolean=true) {
    val refreshing=progress.stage==VehicleConnection.Stage.CHECKING && progress.previousConnection!=null
    val display=if(refreshing)requireNotNull(progress.previousConnection) else progress
    val context=androidx.compose.ui.platform.LocalContext.current
    val window=LocalCarWindowVisibility.current
    fun permitted()=windowFocused && window?.state?.focused!=false && canInteract()
    fun focused(action: ()->Unit): ()->Unit = {if(!refreshing && permitted())action()}
    val deadline=display.expiresAtMillis
    val firstSeen=rememberSaveable(display.userCode,deadline) {System.currentTimeMillis()}
    val active=allowed && display.stage==VehicleConnection.Stage.APPROVAL_REQUIRED
    val now by produceState(System.currentTimeMillis(),deadline,active) {
        value=System.currentTimeMillis()
        if(active && deadline!=null)while(value<deadline) {delay(250);value=System.currentTimeMillis()}
    }
    val remaining=deadline?.let {(it-maxOf(now,System.currentTimeMillis())).coerceAtLeast(0)} ?: 0L
    val stage=if(display.stage==VehicleConnection.Stage.APPROVAL_REQUIRED && remaining==0L)VehicleConnection.Stage.EXPIRED else display.stage
    val visibility=connectionVisibility(allowed,permitted(),stage)
    if(visibility==ConnectionVisibility.RESTRICTED) {CarRestrictedState();return}
    val title=when(stage) {
        VehicleConnection.Stage.READY->"내 계정 연결"
        VehicleConnection.Stage.APPROVAL_REQUIRED->"휴대전화로 연결"
        VehicleConnection.Stage.CONNECTED->"연결됨"
        VehicleConnection.Stage.LOCKED->"연결 잠김"
        VehicleConnection.Stage.REMOTE_REVOCATION_PENDING->"연결 해제 확인 중"
        VehicleConnection.Stage.EXPIRED->"연결이 만료됐어요"
        VehicleConnection.Stage.DENIED->"다시 연결해 주세요"
        VehicleConnection.Stage.RECOVERY_REQUIRED,VehicleConnection.Stage.UNAVAILABLE->"연결을 확인해 주세요"
        VehicleConnection.Stage.SETUP_BLOCKED->CAR_PARK_REQUIRED
        else->"연결 확인 중"
    }
    if(stage in setOf(VehicleConnection.Stage.CHECKING,VehicleConnection.Stage.CONNECTING)) {
        CarLoadingState(title)
        return
    }
    if(stage in setOf(VehicleConnection.Stage.RECOVERY_REQUIRED,VehicleConnection.Stage.UNAVAILABLE,
        VehicleConnection.Stage.EXPIRED,VehicleConnection.Stage.DENIED)) {
        CompositionLocalProvider(LocalCarTextAlign provides TextAlign.Center) {
            Column(Modifier.fillMaxWidth().padding(CarTokens.Frame),horizontalAlignment=Alignment.CenterHorizontally,
                verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                CarText(title,Modifier.fillMaxWidth(),style=CarType.Hero,maxLines=3)
                val register=progress.canRegisterAgain && stage in setOf(VehicleConnection.Stage.RECOVERY_REQUIRED,VehicleConnection.Stage.UNAVAILABLE)
                if(register)CarText("휴대전화에서 이전 기기의 연결을 해제하세요",secondary=true,maxLines=3)
                CarButton(if(register)"새 기기로 등록" else "다시 시도",focused(if(register)onRegister else onStart),
                    Modifier.widthIn(max=CarTokens.PopupMaxWidth).fillMaxWidth(),primary=true,
                    icon=if(register)CarSymbol.Link else CarSymbol.Refresh)
            }
        }
        return
    }
    val entry=onboarding && stage in setOf(VehicleConnection.Stage.READY,VehicleConnection.Stage.LOCKED,
        VehicleConnection.Stage.EXPIRED,VehicleConnection.Stage.DENIED)
    val instructions=entry || stage==VehicleConnection.Stage.APPROVAL_REQUIRED
    val actionWidth=Modifier.fillMaxWidth()
    ConnectionAccountLayout(showVisual=stage==VehicleConnection.Stage.APPROVAL_REQUIRED,visual={
        CarCard(tone=CarCardTone.INK,radius=CarTokens.RadiusHero,padding=PaddingValues(CarTokens.PopupPadding)) {
            Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),horizontalAlignment=Alignment.CenterHorizontally) {
                if(stage==VehicleConnection.Stage.APPROVAL_REQUIRED) {
                    val uri=display.verificationUri;val code=display.userCode
                    if(visibility==ConnectionVisibility.CODE_HIDDEN && deadline!=null) {
                        ConnectionQrGauge((remaining.toFloat()/(deadline-firstSeen).coerceAtLeast(1)).coerceIn(0f,1f)) {
                            CarIcon(CarSymbol.Lock,Modifier.size(CarTokens.IconLarge).align(Alignment.Center),LocalCarPalette.current.routeOnInk)
                        }
                        CarText("다른 앱을 쓰는 동안 코드를 가렸어요",style=CarType.Label,secondary=true,maxLines=2)
                        CarText("화면을 눌러 계속",style=CarType.Title,maxLines=2)
                        val seconds=(remaining+999)/1000
                        CarStatusPill("남은 시간 ${seconds/60}:${(seconds%60).toString().padStart(2,'0')}",kind=CarStatusTone.ON_INK)
                    } else if(visibility==ConnectionVisibility.SHOWN && uri!=null && code!=null) {
                        val bitmap=remember(uri) {
                            check(uri=="https://wegoh.devforest.io/enroll.html?user_code=$code")
                            val qr=QRCodeWriter().encode(uri,BarcodeFormat.QR_CODE,512,512,mapOf(
                                EncodeHintType.MARGIN to 4,EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M))
                            android.graphics.Bitmap.createBitmap(512,512,android.graphics.Bitmap.Config.ARGB_8888).apply {
                                setPixels(IntArray(512*512){i->if(qr[i%512,i/512])android.graphics.Color.BLACK else android.graphics.Color.WHITE},0,512,0,0,512,512)
                            }.asImageBitmap()
                        }
                        ConnectionQrGauge((remaining.toFloat()/(requireNotNull(deadline)-firstSeen).coerceAtLeast(1)).coerceIn(0f,1f)) {
                            Image(bitmap,"차량 연결 QR 코드",Modifier.fillMaxSize().padding(CarTokens.Gap/2))
                        }
                        CarText("연결 코드",style=CarType.Label,secondary=true)
                        CarText(code,style=CarType.Hero)
                        val seconds=(remaining+999)/1000
                        CarStatusPill("남은 시간 ${seconds/60}:${(seconds%60).toString().padStart(2,'0')}",kind=CarStatusTone.ON_INK)
                    }
                } else {
                    CarIcon(when(stage) {
                        VehicleConnection.Stage.CONNECTED->CarSymbol.Check
                        VehicleConnection.Stage.LOCKED,VehicleConnection.Stage.REMOTE_REVOCATION_PENDING->CarSymbol.Lock
                        VehicleConnection.Stage.EXPIRED,VehicleConnection.Stage.DENIED,VehicleConnection.Stage.RECOVERY_REQUIRED,
                        VehicleConnection.Stage.UNAVAILABLE->CarSymbol.Alert
                        else->CarSymbol.Link
                    },Modifier.size(CarTokens.IconLarge),LocalCarPalette.current.routeOnInk)
                    CarStatusPill(title,kind=CarStatusTone.ON_INK)
                }
            }
        }
    }) {
        CarText(if(entry && stage in setOf(VehicleConnection.Stage.READY,VehicleConnection.Stage.LOCKED))"차량을 연결해 주세요" else title,
            Modifier.fillMaxWidth(),style=CarType.Hero,maxLines=3)
        if(instructions) {
            CompositionLocalProvider(LocalCarTextAlign provides TextAlign.Start) {
                Column(Modifier.width(IntrinsicSize.Max),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                    ConnectionAccountStep("1","WegoH 앱 → 설정 → 연결 차량 설정")
                    ConnectionAccountStep("2","QR 스캔 또는 코드 입력")
                    ConnectionAccountStep("3","차량 이름과 코드 확인 후 연결")
                }
            }
        }
        when(stage) {
            VehicleConnection.Stage.APPROVAL_REQUIRED -> {
                CarButton("취소",focused(onDisconnect),actionWidth,icon=CarSymbol.Close)
            }
            VehicleConnection.Stage.CONNECTED -> {
                if(refreshing)CarText("연결 상태 확인 중",secondary=true,maxLines=1)
                CarButton("다른 계정으로 연결",focused(onSwitch),actionWidth,icon=CarSymbol.Person,enabled=!refreshing)
                CarButton("연결 해제",focused(onDisconnect),actionWidth,icon=CarSymbol.Lock,enabled=!refreshing)
            }
            VehicleConnection.Stage.REMOTE_REVOCATION_PENDING -> {
                CarText("이 차는 잠겼지만 연결 해제는 아직 확인 중이에요",secondary=true,maxLines=3)
                CarButton("다시 확인",focused(onRetry),actionWidth,icon=CarSymbol.Refresh)
                CarButton("연결",focused(onStart),actionWidth,primary=true,icon=CarSymbol.Link)
            }
            VehicleConnection.Stage.READY,VehicleConnection.Stage.LOCKED -> CarButton(if(onboarding)"차량 연결" else "연결",focused(onStart),actionWidth,primary=true,icon=CarSymbol.Link)
            else -> Unit
        }
    }
}

/** 연결 화면 노출 판정. 주행 제한이 가장 우선이다. 창 포커스가 없으면 연결 코드·QR만 가리고 나머지는 실제 상태를 보인다. */
internal enum class ConnectionVisibility {RESTRICTED,CODE_HIDDEN,SHOWN}

internal fun connectionVisibility(allowed: Boolean,focused: Boolean,stage: VehicleConnection.Stage)=when {
    !allowed->ConnectionVisibility.RESTRICTED
    !focused && stage==VehicleConnection.Stage.APPROVAL_REQUIRED->ConnectionVisibility.CODE_HIDDEN
    else->ConnectionVisibility.SHOWN
}

@Composable
private fun ConnectionAccountLayout(showVisual: Boolean,visual: @Composable ()->Unit,body: @Composable ColumnScope.()->Unit) {
    if(!showVisual) {
        Box(Modifier.fillMaxWidth(),contentAlignment=Alignment.Center) {
            CompositionLocalProvider(LocalCarTextAlign provides TextAlign.Center) {
                Column(Modifier.widthIn(max=CarTokens.PopupMaxWidth).fillMaxWidth(),
                    horizontalAlignment=Alignment.CenterHorizontally,
                    verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),content=body)
            }
        }
        return
    }
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        if(maxWidth<CarTokens.Breakpoint) {
            Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
                visual()
                Column(Modifier.fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),content=body)
            }
        } else Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Frame),verticalAlignment=Alignment.CenterVertically) {
            Box(Modifier.weight(1f)) {visual()}
            Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap),content=body)
        }
    }
}

@Composable
private fun ConnectionAccountStep(number: String,text: String) {
    Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
        CarStatusPill(number,kind=CarStatusTone.SOFT)
        CarText(text,Modifier.weight(1f),style=CarType.Label,maxLines=3)
    }
}

@Composable
private fun ConnectionQrGauge(fraction: Float,content: @Composable BoxScope.()->Unit) {
    val palette=LocalCarPalette.current
    Box(Modifier.sizeIn(maxWidth=CarTokens.QrSize+CarTokens.Gap,maxHeight=CarTokens.QrSize+CarTokens.Gap).aspectRatio(1f)) {
        Canvas(Modifier.matchParentSize().semantics {contentDescription="연결 코드 유효 시간";progressBarRangeInfo=ProgressBarRangeInfo(fraction,0f..1f)}) {
            val stroke=(CarTokens.BorderWidth*2).toPx();val edge=stroke/2;val right=size.width-edge;val bottom=size.height-edge
            val radius=CarTokens.Radius.toPx()
            val path=Path().apply {
                moveTo(size.width/2,edge);lineTo(right-radius,edge);quadraticBezierTo(right,edge,right,edge+radius)
                lineTo(right,bottom-radius);quadraticBezierTo(right,bottom,right-radius,bottom)
                lineTo(edge+radius,bottom);quadraticBezierTo(edge,bottom,edge,bottom-radius)
                lineTo(edge,edge+radius);quadraticBezierTo(edge,edge,edge+radius,edge);lineTo(size.width/2,edge)
            }
            drawPath(path,palette.divider,style=Stroke(stroke))
            val measure=PathMeasure().apply {setPath(path,false)}
            val remaining=Path();measure.getSegment(0f,measure.length*fraction,remaining)
            drawPath(remaining,palette.text,style=Stroke(stroke,cap=StrokeCap.Round))
        }
        content()
    }
}

@Composable
fun VehicleConnectionPanel(connection: VehicleConnection, allowed: Boolean,manageForeground: Boolean=true,
    onboarding: Boolean=false,walkthroughSeen: Boolean=true,onWalkthroughComplete: (() ->Unit)?=null,
    connectedContent: (@Composable ()->Unit)?=null,onLocalCourses: (() ->Unit)?=null,
    canRequestPermissions: ()->Boolean={false}) {
    var progress by remember(connection) { mutableStateOf(connection.status()) }
    var connectedEpoch by remember(connection) {mutableStateOf(connection.verifiedDataBoundary()?.revision)}
    val display=remember(connection) {AccountReadSnapshot(connection) {connectedEpoch=null}.also {snapshot ->
        connection.verifiedDataBoundary()?.let(snapshot::remember)
    }}
    var foreground by remember(connection) { mutableStateOf(false) }
    DisposableEffect(connection) {
        val observer=connection.observe {
            if(it.stage==VehicleConnection.Stage.CONNECTED) {
                connectedEpoch=connection.dataEpoch();connection.verifiedDataBoundary()?.let(display::remember)
            } else if(!display.canRetain()) {connectedEpoch=null;display.forget()}
            progress=it
        }
        onDispose {observer.close();display.forget()}
    }
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    val view=LocalView.current
    LaunchedEffect(connection,allowed,manageForeground) {if(manageForeground)connection.setSetupAllowed(allowed)}
    DisposableEffect(connection,lifecycle,view,manageForeground) {
        var ownsForeground=false
        fun updateForeground() {
            val active=lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) && view.hasWindowFocus()
            foreground=active
            if(manageForeground && active!=ownsForeground) {ownsForeground=active;connection.setForeground(active)}
        }
        val observer=LifecycleEventObserver {_,_->updateForeground()}
        val focus=android.view.ViewTreeObserver.OnWindowFocusChangeListener {updateForeground()}
        val tree=view.viewTreeObserver
        lifecycle.addObserver(observer);tree.addOnWindowFocusChangeListener(focus);updateForeground()
        onDispose {
            lifecycle.removeObserver(observer)
            if(tree.isAlive)tree.removeOnWindowFocusChangeListener(focus)
            if(ownsForeground)connection.setForeground(false)
        }
    }
    val connected=progress.stage==VehicleConnection.Stage.CONNECTED ||
        connectedEpoch!=null && connectedEpoch==connection.dataEpoch() && display.canRetain()
    val content: @Composable ()->Unit = {
        if(connectedContent!=null && connected) {
            connectedContent()
        } else {
            val showsWalkthrough=onboarding && !walkthroughSeen && onWalkthroughComplete!=null && progress.stage in setOf(
                VehicleConnection.Stage.READY,VehicleConnection.Stage.LOCKED,VehicleConnection.Stage.EXPIRED,VehicleConnection.Stage.DENIED,
                VehicleConnection.Stage.SETUP_BLOCKED)
            val body: @Composable ()->Unit = {
                if(showsWalkthrough) {
                    FirstRunWalkthrough(allowed,
                        canInteract={lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) && view.hasWindowFocus()},
                        onComplete=requireNotNull(onWalkthroughComplete))
                } else {
                ConnectionBody(progress,allowed,onStart={connection.start("우리 차",VehicleConnection.DEFAULT_SCOPES)},onRetry={connection.check()},
                    onDisconnect={connection.disconnect()},onSwitch={connection.switchAccount("우리 차",VehicleConnection.DEFAULT_SCOPES)},onRegister={connection.registerNewInstallation()},
                    onRequestScopes={connection.requestScopes("우리 차",VehicleConnection.DEFAULT_SCOPES)},
                    canInteract={lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) && view.hasWindowFocus()},onboarding=onboarding,
                    windowFocused=foreground)
                }
            }
            if(onboarding)ConnectionEntry(fullScreen=showsWalkthrough,content=body) else body()
        }
    }
    if(onboarding)FirstRunPermissionEntry(walkthroughSeen,connected,allowed,foreground,
        canRequest={canRequestPermissions() && lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) && view.hasWindowFocus()},content=content)
    else content()
}

@Composable
internal fun ConnectionEntry(fullScreen: Boolean=false,content: @Composable ()->Unit) {
    val frame: @Composable ()->Unit = {BoxWithConstraints(Modifier.fillMaxSize().background(LocalCarPalette.current.background).systemBarsPadding()
        .padding(horizontal=CarTokens.Frame,vertical=CarTokens.Gap)) {
        if(fullScreen) {content();return@BoxWithConstraints}
        val viewportHeight=maxHeight
        CompositionLocalProvider(LocalCarTextAlign provides TextAlign.Center) {
            Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).heightIn(min=viewportHeight),
                verticalArrangement=Arrangement.Center,horizontalAlignment=Alignment.CenterHorizontally) {content()}
        }
    }}
    if(fullScreen)frame() else TripSurface {frame()}
}

@Composable
private fun ConnectedVehiclePage(refreshing: Boolean,onBack: ()->Unit,
    onDisconnect: ()->Unit,onSwitch: ()->Unit) = TripSurface {
    val window=LocalCarWindowVisibility.current
    fun focused(action: ()->Unit): ()->Unit = {if(!refreshing && window?.state?.focused!=false)action()}
    val narrow=LocalTripLayoutWidth.current<CarTokens.Breakpoint
    Column(Modifier.fillMaxSize().padding(CarTokens.SpaceMedium).then(if(narrow)Modifier.verticalScroll(rememberScrollState()) else Modifier),
        verticalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
        TripHeading("차량 연결",onBack=onBack)
        TripAdaptiveRow(narrow=narrow,gap=CarTokens.PopupPadding) {
            Column(Modifier.weight(600f),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                CarCard(tone=CarCardTone.SOFT,padding=PaddingValues(CarTokens.Frame),radius=CarTokens.RadiusCard) {
                    Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
                        Box(Modifier.size(CarTokens.IconLarge).background(LocalCarPalette.current.accentSoft,CircleShape),contentAlignment=Alignment.Center) {
                            CarIcon(CarSymbol.Check,Modifier.size(CarTokens.Icon),LocalCarPalette.current.accent)
                        }
                        Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                            TripText("연결됨",style=CarType.Title)
                            if(refreshing)TripText("연결 상태 확인 중",secondary=true,maxLines=2)
                        }
                    }
                }
                FlowRow(horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    CarButton("다른 계정으로 연결",focused(onSwitch),Modifier.weight(1f),icon=CarSymbol.Person,enabled=!refreshing)
                    CarButton("연결 해제",focused(onDisconnect),Modifier.weight(1f),variant=CarButtonStyle.DANGER,icon=CarSymbol.Lock,enabled=!refreshing)
                }
                TripText("해제하면 이 차에서 내 경로, 음악, 여행을 볼 수 없어요",secondary=true,
                    style=CarType.Label,maxLines=3)
            }
        }
    }
}
