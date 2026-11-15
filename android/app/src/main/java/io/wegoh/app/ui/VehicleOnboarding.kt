package io.wegoh.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asComposePath
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign

internal data class OnboardingPalette(val accent: Color,val soft: Color,val ink: Color,val onInk: Color,val route: Color)
@Composable
internal fun onboardingPalette(): OnboardingPalette = if(LocalCarPalette.current.background==PleosPalette.Night.background)
    OnboardingPalette(CarTokens.NightBrandBlue,CarTokens.NightAccentSoft,CarTokens.NightInk,
        CarTokens.NightOnInk,CarTokens.NightRouteOnInk)
else OnboardingPalette(CarTokens.BrandBlue,CarTokens.AccentSoft,CarTokens.Ink,
    CarTokens.OnInk,CarTokens.RouteOnInk)

@Composable
internal fun VehicleOnboardingLayout(onSkip: (() -> Unit)?=null,permission: Boolean=false,
    artwork: @Composable ()->Unit,actions: @Composable RowScope.()->Unit,body: @Composable ColumnScope.()->Unit) {
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val narrow=maxWidth<CarTokens.OnboardingBreakpoint
        val artHeight=(maxHeight*if(permission)0.24f else 0.36f).coerceAtMost(
            if(permission)CarTokens.OnboardingPermissionIllustrationHeight else CarTokens.OnboardingIllustrationHeight)
        CompositionLocalProvider(LocalCarTextAlign provides TextAlign.Start) {
            if(narrow) {
                Column(Modifier.fillMaxSize(),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    OnboardingHeader(onSkip)
                    Box(Modifier.fillMaxWidth().height(artHeight)) {artwork()}
                    Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),
                        verticalArrangement=Arrangement.spacedBy(CarTokens.Gap,Alignment.CenterVertically)) {body()}
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),content=actions)
                }
            } else {
                Row(Modifier.fillMaxSize(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Frame)) {
                    Box(Modifier.weight(1f).fillMaxHeight()) {artwork()}
                    Column(Modifier.weight(1f).fillMaxHeight().padding(horizontal=CarTokens.SpaceMedium),
                        verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                        OnboardingHeader(onSkip)
                        Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),
                            verticalArrangement=Arrangement.spacedBy(CarTokens.Gap,Alignment.CenterVertically)) {body()}
                        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),content=actions)
                    }
                }
            }
        }
    }
}

@Composable
private fun OnboardingHeader(onSkip: (() -> Unit)?) {
    val p=onboardingPalette()
    Row(Modifier.fillMaxWidth().heightIn(min=CarTokens.Touch),verticalAlignment=Alignment.CenterVertically,
        horizontalArrangement=Arrangement.SpaceBetween) {
        Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(CarTokens.ButtonGap)) {
            Canvas(Modifier.size(CarTokens.OnboardingBrandMark)) {
                drawRoundRect(p.accent,cornerRadius=androidx.compose.ui.geometry.CornerRadius(size.width*0.22f))
                val path=androidx.core.graphics.PathParser.createPathFromPathData(
                    "M67 152h51c25 0 35 9 53 9 19 0 27-14 39-32 18-26 32-41 54-41h29q4 0 4 4v32q0 4-4 4h-15c-25 0-35 21-47 44-27 54-57 94-112 94H67q-4 0-4-4v-33q0-4 4-4h42c29 0 55-20 76-43-11 4-21 5-34 5H67q-4 0-4-4v-27q0-4 4-4Z")
                drawContext.canvas.save()
                drawContext.canvas.scale(size.width/360f,size.height/360f)
                drawPath(androidx.compose.ui.graphics.Path().apply {addPath(path!!.asComposePath())},p.onInk)
                drawContext.canvas.restore()
            }
            CarText("WegoH",style=CarType.Title.copy(fontSize=CarTokens.OnboardingWordmarkSize,lineHeight=CarTokens.OnboardingWordmarkLine))
        }
        if(onSkip!=null)VehicleOnboardingButton("건너뛰기",onSkip,Modifier.widthIn(min=CarTokens.OnboardingSkipWidth))
    }
}

@Composable
internal fun VehicleOnboardingButton(label: String,onClick: ()->Unit,modifier: Modifier=Modifier,
    primary: Boolean=false,enabled: Boolean=true,icon: CarSymbol?=null) {
    CarButton(label,onClick,modifier,primary=primary,enabled=enabled,icon=icon)
}

@Composable
internal fun VehicleOnboardingSteps(page: Int) {
    val p=onboardingPalette();val base=LocalCarPalette.current
    Row(Modifier.semantics(mergeDescendants=true) {contentDescription="안내 3장 중 ${page+1}번째"},verticalAlignment=Alignment.CenterVertically) {
        Canvas(Modifier.width(CarTokens.OnboardingDot*3+CarTokens.OnboardingConnector*2).height(CarTokens.OnboardingDot)) {
            val r=CarTokens.OnboardingDot.toPx()/2
            val gap=CarTokens.OnboardingConnector.toPx()
            for(i in 0..2) {
                val x=r+i*(r*2+gap)
                if(i<2)drawLine(if(i<page)base.text else base.divider,Offset(x+r,r),Offset(x+r+gap,r),
                    CarTokens.OnboardingStroke.toPx(),pathEffect=if(i<page)null else PathEffect.dashPathEffect(floatArrayOf(r/4,r/3)))
                val c=Offset(x,r)
                if(i==page)drawCircle(p.accent,r-CarTokens.OnboardingCurrentBorder.toPx()/2,c,style=Stroke(CarTokens.OnboardingCurrentBorder.toPx()))
                else if(i<page)drawCircle(base.text,r,c)
                else if(i==2)drawRoundRect(base.divider,Offset(x-r,0f),androidx.compose.ui.geometry.Size(r*2,r*2),
                    androidx.compose.ui.geometry.CornerRadius(r/2),style=Stroke(CarTokens.OnboardingStroke.toPx()))
                else drawCircle(base.divider,r,c,style=Stroke(CarTokens.OnboardingStroke.toPx()))
            }
        }
        Spacer(Modifier.width(CarTokens.Gap))
        CarText("${page+1} / 3",style=CarType.Label,secondary=true)
    }
}

@Composable
internal fun VehicleOnboardingArtwork(page: Int) {
    val p=onboardingPalette()
    val background=LocalCarPalette.current.background
    BoxWithConstraints(Modifier.fillMaxSize().clip(RoundedCornerShape(CarTokens.OnboardingHeroRadius)).background(p.soft)) {
        val artworkHeight=maxHeight
        if(page==0) {
            Canvas(Modifier.fillMaxSize()) {
                val path=Path().apply {
                    moveTo(-size.width*0.05f,size.height*0.88f)
                    cubicTo(size.width*0.3f,size.height*0.88f,size.width*0.25f,size.height*0.65f,size.width*0.5f,size.height*0.64f)
                    cubicTo(size.width*0.82f,size.height*0.6f,size.width*0.55f,size.height*0.18f,size.width*1.05f,size.height*0.1f)
                }
                drawPath(path,background,style=Stroke(size.minDimension*0.15f,cap=StrokeCap.Round))
                drawPath(path,p.accent,style=Stroke(CarTokens.OnboardingStroke.toPx()*2,cap=StrokeCap.Round,
                    pathEffect=PathEffect.dashPathEffect(floatArrayOf(CarTokens.SpaceSmall.toPx()/2,CarTokens.Gap.toPx()))))
                for((index,point) in listOf(Offset(0.19f,0.85f),Offset(0.5f,0.64f),Offset(0.7f,0.35f)).withIndex()) {
                    val c=Offset(size.width*point.x,size.height*point.y)
                    drawCircle(p.onInk,size.minDimension*0.06f,c)
                    drawCircle(listOf(p.ink,p.accent,p.route)[index],size.minDimension*0.041f,c)
                }
                if(artworkHeight>CarTokens.OnboardingIllustrationHeight) {
                    val destination=Offset(size.width*0.9f,size.height*0.15f)
                    drawCircle(p.accent,CarTokens.RouteCurrentDot.toPx()*2,destination,style=Stroke(CarTokens.RouteDotBorder.toPx()))
                    drawCircle(p.accent,CarTokens.RouteMarkerInner.toPx(),destination)
                }
            }
            if(artworkHeight>CarTokens.OnboardingIllustrationHeight)Column(Modifier.padding(CarTokens.PopupPadding)
                .background(LocalCarPalette.current.background,RoundedCornerShape(CarTokens.ButtonRadius)).padding(CarTokens.Gap)) {
                CarText("강릉 바다 드라이브",style=CarType.Label,secondary=true)
                CarMetadata(listOf("장소 3곳","내비로 출발"),style=CarType.Section,secondary=false)
            }
        } else if(page==1 && artworkHeight<=CarTokens.OnboardingIllustrationHeight) {
            Row(Modifier.fillMaxSize().padding(CarTokens.Frame),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),
                verticalAlignment=Alignment.CenterVertically) {
                Column(Modifier.weight(1f).fillMaxHeight().background(p.ink,RoundedCornerShape(CarTokens.PopupRadius)).padding(CarTokens.Gap),
                    verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    Canvas(Modifier.fillMaxWidth().weight(1f)) {
                        val heights=listOf(0.35f,0.65f,1f,0.55f,0.8f,0.28f,0.62f,0.45f)
                        val unit=size.width/(heights.size*2)
                        heights.forEachIndexed {i,h->drawLine(if(i==2 || i==6)p.onInk else p.route,Offset(unit+i*unit*2,size.height),
                            Offset(unit+i*unit*2,size.height*(1-h)),unit,StrokeCap.Round)}
                    }
                    Column(verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                        androidx.compose.material3.Text("내 플레이리스트",style=CarType.Label,color=CarTokens.OnInk)
                        androidx.compose.material3.Text("주말 드라이브",style=CarType.Title,color=p.onInk)
                    }
                }
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    for(title in listOf("바다로 가는 길","느긋한 오후")) {
                        Column(Modifier.fillMaxWidth().background(LocalCarPalette.current.background,RoundedCornerShape(CarTokens.ButtonRadius)).padding(CarTokens.Gap),
                            verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                            CarText(title,style=CarType.Section,maxLines=2)
                            CarText("음악 링크",style=CarType.Label,secondary=true)
                        }
                    }
                }
            }
        } else if(page==1) {
            Column(Modifier.align(Alignment.Center).padding(CarTokens.PopupPadding),verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                Column(Modifier.fillMaxWidth().background(p.ink,RoundedCornerShape(CarTokens.PopupRadius)).padding(CarTokens.PopupPadding),
                    verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    Canvas(Modifier.fillMaxWidth().height((artworkHeight*0.24f).coerceAtMost(CarTokens.OnboardingPermissionIllustrationHeight))) {
                        val heights=listOf(0.35f,0.65f,1f,0.55f,0.8f,0.28f,0.62f,0.45f,0.75f,0.38f)
                        val unit=size.width/(heights.size*2)
                        heights.forEachIndexed {i,h->drawLine(if(i==2 || i==6)p.onInk else p.route,Offset(unit+i*unit*2,size.height),
                            Offset(unit+i*unit*2,size.height*(1-h)),unit,StrokeCap.Round)}
                    }
                    androidx.compose.material3.Text("내 플레이리스트",style=CarType.Label,color=CarTokens.OnInk)
                    androidx.compose.material3.Text("주말 드라이브",style=CarType.Title,color=p.onInk)
                }
                if(artworkHeight>CarTokens.OnboardingIllustrationHeight)for(title in listOf("바다로 가는 길","느긋한 오후")) {
                    Row(Modifier.fillMaxWidth().background(LocalCarPalette.current.background,RoundedCornerShape(CarTokens.ButtonRadius)).padding(CarTokens.Gap),
                        horizontalArrangement=Arrangement.SpaceBetween) {
                        CarText(title,style=CarType.Action)
                        CarText("음악 링크",style=CarType.Label,secondary=true)
                    }
                }
            }
        } else {
            val compactArtwork=artworkHeight<=CarTokens.OnboardingIllustrationHeight
            Row(Modifier.align(Alignment.Center).padding(CarTokens.PopupPadding),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
                Column(Modifier.weight(2f).then(if(compactArtwork)Modifier.fillMaxHeight() else Modifier).background(LocalCarPalette.current.background,RoundedCornerShape(CarTokens.PopupRadius)).padding(CarTokens.Gap),
                    horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    CarIcon(CarSymbol.Car,Modifier.fillMaxWidth().then(if(compactArtwork)Modifier.weight(1f) else Modifier.aspectRatio(1f)).padding(CarTokens.PopupPadding)
                        .semantics {contentDescription="차량 연결"},p.accent)
                    CarText("차량 연결",style=CarType.Label,maxLines=2)
                }
                Column(Modifier.weight(1f).background(p.ink,RoundedCornerShape(CarTokens.PopupRadius)).padding(CarTokens.Gap),
                    horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.spacedBy(CarTokens.Gap)) {
                    CarIcon(CarSymbol.Check,Modifier.size(CarTokens.IconLarge),p.route)
                    androidx.compose.material3.Text("iPhone 앱",style=CarType.Label,color=p.onInk)
                }
            }
        }
    }
}

@Composable
internal fun VehiclePermissionArtwork() {
    val p=onboardingPalette()
    Box(Modifier.fillMaxSize().clip(RoundedCornerShape(CarTokens.OnboardingHeroRadius)).background(p.ink)) {
        Canvas(Modifier.fillMaxSize()) {
            val path=Path().apply {moveTo(-size.width*0.1f,size.height*0.55f);cubicTo(size.width*0.4f,size.height*0.6f,size.width*0.3f,size.height*0.2f,size.width*1.1f,size.height*0.18f)}
            drawPath(path,CarTokens.NightAccentSoft,style=Stroke(size.minDimension*0.15f,cap=StrokeCap.Round))
            drawPath(path,p.route,style=Stroke(CarTokens.OnboardingStroke.toPx()*2,pathEffect=PathEffect.dashPathEffect(floatArrayOf(CarTokens.SpaceSmall.toPx(),CarTokens.Gap.toPx()))))
            val c=Offset(size.width*0.5f,size.height*0.38f)
            drawCircle(p.route,size.minDimension*0.07f,c)
            drawCircle(p.ink,size.minDimension*0.025f,c)
        }
        Column(Modifier.align(Alignment.BottomStart).padding(CarTokens.PopupPadding),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
            androidx.compose.material3.Text("경로와 여행 진행 중에만 사용",style=CarType.Label,color=p.route)
            androidx.compose.material3.Text("방문 장소 확인\n안전운전 점수 계산",style=CarType.Title,color=p.onInk)
        }
    }
}

@Composable
internal fun VehiclePermissionRow(icon: CarSymbol,title: String,description: String) {
    val p=onboardingPalette()
    Row(Modifier.fillMaxWidth().border(CarTokens.OnboardingBorder,LocalCarPalette.current.divider,RoundedCornerShape(CarTokens.ButtonRadius))
        .padding(CarTokens.Gap),horizontalArrangement=Arrangement.spacedBy(CarTokens.Gap),verticalAlignment=Alignment.CenterVertically) {
        Box(Modifier.size(CarTokens.Touch).background(p.soft,RoundedCornerShape(CarTokens.ButtonRadius)),contentAlignment=Alignment.Center) {
            CarIcon(icon,Modifier.size(CarTokens.Icon),p.accent)
        }
        Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
            CarText(title,style=CarType.Section)
            CarText(description,secondary=true,maxLines=3)
        }
    }
}
