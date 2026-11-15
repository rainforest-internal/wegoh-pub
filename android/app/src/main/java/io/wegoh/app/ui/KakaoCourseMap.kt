package io.wegoh.app.ui

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import android.os.Handler
import android.os.Looper
import android.widget.FrameLayout
import android.content.Context
import android.view.MotionEvent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFontFamilyResolver
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.kakao.vectormap.*
import com.kakao.vectormap.camera.CameraAnimation
import com.kakao.vectormap.camera.CameraUpdateFactory
import com.kakao.vectormap.label.CompetitionType
import com.kakao.vectormap.label.CompetitionUnit
import com.kakao.vectormap.label.Label
import com.kakao.vectormap.label.LabelLayerOptions
import com.kakao.vectormap.label.LabelManager
import com.kakao.vectormap.label.LabelOptions
import com.kakao.vectormap.label.LabelStyle
import com.kakao.vectormap.label.LabelTextBuilder
import com.kakao.vectormap.label.OrderingType
import com.kakao.vectormap.shape.DimScreenCover
import com.kakao.vectormap.shape.MapPoints
import com.kakao.vectormap.shape.Polyline
import com.kakao.vectormap.shape.PolylineOptions
import com.kakao.vectormap.shape.PolylineStyle
import com.kakao.vectormap.shape.ShapeLayerOptions
import com.kakao.vectormap.shape.ShapeLayerPass
import com.kakao.vectormap.shape.ShapeManager
import io.wegoh.app.BuildConfig
import io.wegoh.app.TripPosition
import io.wegoh.app.TripRouteStop
import io.wegoh.app.nativeauth.CourseRoadCoordinate
import io.wegoh.app.nativeauth.TripCarPosition
import io.wegoh.app.nativeauth.TripDetail

internal data class CourseMapPoint(val key: String,val name: String,val latitude: Double,val longitude: Double)

internal fun courseMapPoints(stops: List<TripRouteStop>): List<CourseMapPoint> = stops.mapNotNull {stop->
    val lat=stop.lat;val lng=stop.lng
    if(lat==null || lng==null || !lat.isFinite() || !lng.isFinite() || lat !in -90.0..90.0 || lng !in -180.0..180.0)null
    else CourseMapPoint(stop.key,stop.name,lat,lng)
}.distinctBy {it.key}

internal const val COURSE_MAP_VEHICLE_KEY="wegoh:vehicle"
internal fun courseMapVehicle(position: TripPosition?): CourseMapPoint? =
    position?.takeIf {it.valid}?.let {CourseMapPoint(COURSE_MAP_VEHICLE_KEY,"지금 여기",it.latitude,it.longitude)}

/** 지도에 올릴 다른 차 하나. 경로·픽업·드랍 없이 현재 위치와 차 번호만 쓴다. */
internal data class CourseMapCar(val key: String,val label: String,val latitude: Double,val longitude: Double,val stale: Boolean)

/** 서버는 60초 이내 위치만 주므로, 차량 전송 주기의 세 배가 지난 위치는 늦은 위치로 구분해 보여 준다. */
internal const val COURSE_MAP_CAR_STALE_MILLIS=30_000L

/** 여행 상세에 보이는 다른 차만 표시한다. 내 차(운전·동승)는 이 기기 GPS 표식으로 따로 그린다. */
internal fun courseMapOtherCars(trip: TripDetail?,positions: List<TripCarPosition>): List<CourseMapCar> {
    trip ?: return emptyList()
    val mine=trip.myCar?.id
    val cars=trip.cars.associateBy {it.id}
    return positions.mapNotNull {position->
        val car=cars[position.carId]?.takeIf {it.id!=mine} ?: return@mapNotNull null
        if(!position.latitude.isFinite() || position.latitude !in -90.0..90.0 ||
            !position.longitude.isFinite() || position.longitude !in -180.0..180.0)return@mapNotNull null
        val stale=position.ageMillis>COURSE_MAP_CAR_STALE_MILLIS
        CourseMapCar("wegoh:car:"+car.id,(car.ordinal?.let {"${it}호차"} ?: car.name)+if(stale)" (이전 위치)" else "",
            position.latitude,position.longitude,stale)
    }
}

/** 카메라가 마지막으로 맞춘 장면. 경로·도로·초점 장소가 바뀌면 새 장면이다. */
internal data class CourseMapScene(val points: List<CourseMapPoint>,val road: List<CourseRoadCoordinate>,val focusKey: String?)
internal data class CourseMapFrame(val scene: CourseMapScene,val vehicle: CourseMapPoint?)

/** 카메라가 담을 좌표. 차와 다음 장소가 있으면 그 둘만, 아니면 경로 전체(+차)를 담는다. */
internal fun courseMapCameraTargets(scene: CourseMapScene,vehicle: CourseMapPoint?): List<CourseRoadCoordinate> {
    val focus=scene.points.firstOrNull {it.key==scene.focusKey}
    val places=if(vehicle!=null && focus!=null)listOf(focus) else scene.points
    return (places+listOfNotNull(vehicle)).map {CourseRoadCoordinate(it.latitude,it.longitude)}+
        if(vehicle!=null && focus!=null)emptyList() else scene.road
}

/**
 * 카메라를 다시 맞출지 정한다.
 * - 장면(경로·다음 장소)이 바뀌면 항상 맞춘다.
 * - 사용자가 지도를 직접 움직였으면 같은 장면 안에서는 자동으로 움직이지 않는다.
 * - 차 위치가 처음 들어오거나 차가 화면 밖으로 나가면 맞춘다.
 * - 추종(주행) 모드는 차가 마지막으로 맞춘 자리에서 화면상 [followDriftPx] 이상 움직이면 맞춘다.
 */
internal fun courseMapCameraShouldFit(scene: CourseMapScene,framed: CourseMapFrame?,vehicle: CourseMapPoint?,follow: Boolean,
    userMoved: Boolean,vehicleInView: Boolean?,vehicleDriftPx: Float?,followDriftPx: Float): Boolean = when {
    framed==null || framed.scene!=scene->true
    userMoved || vehicle==null->false
    framed.vehicle==null->true
    vehicleInView==false->true
    else->follow && vehicleDriftPx!=null && vehicleDriftPx>=followDriftPx
}

/** 화면 좌표가 가장자리에서 [inset]만큼 들어온 영역 안에 있는지. */
internal fun courseMapPointInView(x: Int,y: Int,width: Int,height: Int,inset: Int): Boolean =
    width>0 && height>0 && x in inset..(width-inset) && y in inset..(height-inset)

/**
 * 장소 이름 레이블의 경쟁 순위. 이름끼리 겹치면 순위가 높은 이름만 남는다.
 * 지금 향하는 장소가 가장 높고, 나머지는 경로 순서가 앞설수록 높다.
 */
internal fun courseMapNameRanks(points: List<CourseMapPoint>,focusKey: String?): Map<String,Long> =
    points.mapIndexed {index,point->point.key to if(point.key==focusKey)points.size.toLong() else (points.lastIndex-index).toLong()}.toMap()

/** 화면 좌표의 원형 표식. [owner]는 그 표식이 속한 장소 키이며, 차 표식은 null이다. */
internal data class CourseMapDisc(val owner: String?,val x: Float,val y: Float,val radius: Float)

/** 화면 좌표의 이름 글자 영역. */
internal data class CourseMapNameBox(val key: String,val left: Float,val top: Float,val right: Float,val bottom: Float)

/**
 * 장소 이름 글자 영역. 이름은 장소 위치에 가운데 맞춘 [markerSize] 높이 투명 아이콘 아래(MapGravity.BOTTOM)에 쓰므로
 * 글자 영역은 표식 아랫변에서 시작해 가로 가운데로 놓인다.
 */
internal fun courseMapNameBox(key: String,x: Float,y: Float,markerSize: Int,textWidth: Float,textHeight: Float): CourseMapNameBox {
    val top=y+markerSize/2f
    return CourseMapNameBox(key,x-textWidth/2f,top,x+textWidth/2f,top+textHeight)
}

/** 원과 사각형이 겹치는지(맞닿은 경계는 겹침이 아님). */
internal fun courseMapDiscHitsBox(disc: CourseMapDisc,box: CourseMapNameBox): Boolean {
    val dx=disc.x-disc.x.coerceIn(box.left,box.right)
    val dy=disc.y-disc.y.coerceIn(box.top,box.bottom)
    return dx*dx+dy*dy<disc.radius*disc.radius
}

/**
 * 표식과 겹쳐 숨길 장소 이름. 번호·차 표식은 SDK 기본 레이어(경쟁 없음)에 있어 이름 레이어와 경쟁하지 않으므로,
 * 화면 좌표로 투영해 다른 장소의 번호 표식이나 차 표식과 겹치는 이름을 앱에서 숨긴다(번호 > 이름).
 * 자기 장소 표식은 이름 위에 있어 겹치지 않으므로 제외한다. 이름끼리의 겹침은 이름 레이어의 Same 경쟁이 맡는다.
 */
internal fun courseMapNamesHiddenByMarkers(names: List<CourseMapNameBox>,discs: List<CourseMapDisc>): Set<String> =
    names.filter {box->discs.any {it.owner!=box.key && courseMapDiscHitsBox(it,box)}}.map {it.key}.toSet()

/**
 * 지도 위 글자색·바탕 덮개·표식 색. 덮개가 null이면 지도 타일을 그대로 쓴다.
 * [ring]은 장소·차 표식의 바깥 테두리, [vehicle]·[otherCar]·[staleCar]는 내 차·다른 차·늦은 위치 차의 안쪽 색이다.
 * [route]는 경로선 안쪽 색, [routeCasing]은 경로선 외곽선 색이다.
 */
internal data class CourseMapInk(val text: Color,val halo: Color,val dim: Color?,val ring: Color,
    val vehicle: Color,val otherCar: Color,val staleCar: Color,val route: Color,val routeCasing: Color)

/**
 * Kakao 지도 타일은 앱 테마와 무관하게 밝다. 주간에는 밝은 타일 기준 글자색을 쓰고,
 * 야간에는 타일을 야간 배경색으로 덮어 주변 야간 화면과 밝기를 맞춘 뒤 야간 글자색을 쓴다.
 * 표식은 앱 카드 역할(ink 등)이 아닌 지도 전용 색을 쓴다. 주간은 표식 색이 흰 타일과 대비를 맡고,
 * 야간은 덮인 타일 위에서 밝은 바깥 테두리가 대비를 맡는다. 경로선도 같은 방식으로 지도 전용 안쪽 색과 외곽선을 쓴다.
 */
internal fun courseMapInk(theme: CarPalette): CourseMapInk =
    if(theme.background==PleosPalette.Night.background)
        CourseMapInk(CarTokens.NightMapLabelText,CarTokens.NightMapLabelHalo,theme.background.copy(alpha=CarTokens.MapNightDimAlpha),
            CarTokens.NightMapMarkerRing,CarTokens.NightMapVehicle,CarTokens.NightMapOtherCar,CarTokens.NightMapStaleCar,
            CarTokens.NightMapRouteLine,CarTokens.NightMapRouteCasing)
    else CourseMapInk(CarTokens.MapLabelText,CarTokens.MapLabelHalo,null,
        CarTokens.MapMarkerRing,CarTokens.MapVehicle,CarTokens.MapOtherCar,CarTokens.MapStaleCar,
        CarTokens.MapRouteLine,CarTokens.MapRouteCasing)

private const val COURSE_MAP_NAME_LAYER="wegoh:stop-names"
private const val COURSE_MAP_ROUTE_LAYER="wegoh:route"

/**
 * 경로선을 그리는 Shape 패스. 기본 Shape 레이어(ShapeLayerPass.Default)는 지도 배경 층이라
 * 야간 덮개(DimScreenCover.Map)에 함께 덮인다. Route 패스는 SDK 문서상 지도 배경·Overlay·RouteLine보다 위에 그려진다.
 */
internal val COURSE_MAP_ROUTE_PASS: ShapeLayerPass=ShapeLayerPass.Route

/**
 * 이 패스의 Shape가 DimScreenCover.Map 덮개 아래에 그려지는지. 덮개 위라고 문서로 확인한 패스는 Route뿐이다.
 * Default는 실제 화면에서 덮개 아래로 확인했고, Overlay는 덮개와의 순서가 문서에 없어 아래로 본다.
 */
internal fun courseMapShapeUnderDim(pass: ShapeLayerPass): Boolean=pass!=ShapeLayerPass.Route

/** 덮개 합성 뒤 화면에 보이는 색. 덮개 아래 층은 덮개 색이 위에 합성되고, 덮개 위 층(라벨 등)은 원래 색 그대로다. */
internal fun courseMapSeen(color: Color,dim: Color?,underDim: Boolean): Color=if(dim!=null && underDim)dim.compositeOver(color) else color

@Composable
internal fun KakaoCourseMap(stops: List<TripRouteStop>,modifier: Modifier=Modifier,interactive: Boolean=false,
    road: List<CourseRoadCoordinate> = emptyList(),numbersOnly: Boolean=false,vehicle: TripPosition?=null,
    focus: TripRouteStop?=null,follow: Boolean=false,others: List<CourseMapCar> = emptyList()) {
    val points=remember(stops) {courseMapPoints(stops)}
    val vehiclePoint=courseMapVehicle(vehicle)
    val context=LocalContext.current
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    val density=LocalDensity.current
    val palette=LocalCarPalette.current
    val surfaceColors=MaterialTheme.colorScheme
    val textSize=with(density) {CarType.Label.fontSize.toPx()}.toInt()
    val markerSize=with(density) {maxOf(CarTokens.MapMarkerSize.roundToPx(),textSize*2)}
    val markerTypeface=LocalFontFamilyResolver.current.resolve(
        fontFamily=CarType.Label.fontFamily,fontWeight=requireNotNull(CarType.Label.fontWeight)
    ).value as Typeface
    val markerBorder=with(density) {CarTokens.RouteCurrentBorder.toPx()}
    val vehicleOuter=with(density) {CarTokens.RouteMarkerDot.toPx()}
    val vehicleInner=with(density) {CarTokens.RouteMarkerInner.toPx()}
    val roadWidth=with(density) {CarTokens.RouteLine.toPx()}
    val roadCasingWidth=with(density) {CarTokens.MapRouteCasingWidth.toPx()}
    val cameraPadding=with(density) {CarTokens.MapCameraPadding.roundToPx()}
    val ink=palette.accent.toArgb()
    val mapInk=courseMapInk(LocalCarThemePalette.current)
    val text=mapInk.text.toArgb();val halo=mapInk.halo.toArgb();val dim=mapInk.dim?.toArgb()
    val haloWidth=with(density) {CarTokens.MapLabelHaloWidth.roundToPx()}
    val canvas=surfaceColors.surface.toArgb()
    val ring=mapInk.ring.toArgb()
    val vehicleInk=mapInk.vehicle.toArgb()
    val otherInk=mapInk.otherCar.toArgb();val staleInk=mapInk.staleCar.toArgb()
    val roadInk=mapInk.route.toArgb();val roadCasing=mapInk.routeCasing.toArgb()
    val keyPresent=BuildConfig.KAKAO_NATIVE_APP_KEY.isNotBlank()
    val controller=remember(context,points.isEmpty(),keyPresent) {CourseMapController()}
    var failure by remember(controller) {mutableStateOf<String?>(null)}
    var ready by remember(controller) {mutableStateOf(false)}
    val message=when {
        points.isEmpty()->"표시할 장소가 없어요"
        !keyPresent->"지도를 사용할 수 없어요"
        failure!=null->failure
        !ready->"지도 불러오는 중"
        else->null
    }
    Box(modifier.fillMaxWidth().clip(RoundedCornerShape(CarTokens.RadiusCard)).background(surfaceColors.surface)
        .semantics {contentDescription="장소 지도. "+points.joinToString(" → ") {it.name}+(if(vehiclePoint!=null)". 내 차 위치 표시" else "")+
            (if(others.isNotEmpty())". 다른 차 "+others.joinToString(", ") {it.label} else "")},contentAlignment=Alignment.Center) {
        if(points.isNotEmpty() && keyPresent && failure==null)AndroidView(
            factory={viewContext->
                val host=CourseMapHost(viewContext)
                try {
                    if(!KakaoMapSdk.isInitialized())KakaoMapSdk.init(viewContext.applicationContext,BuildConfig.KAKAO_NATIVE_APP_KEY)
                    val view=MapView(viewContext)
                    controller.view=view
                    host.addView(view,FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,FrameLayout.LayoutParams.MATCH_PARENT))
                    view.setFinishManually(true)
                    view.start(object: MapLifeCycleCallback() {
                        override fun onMapDestroy() {controller.map=null}
                        override fun onMapError(error: Exception) {
                            controller.main.post {if(!controller.disposed)failure="지도를 불러오지 못했어요"}
                        }
                    },object: KakaoMapReadyCallback() {
                        override fun getPosition(): LatLng=LatLng.from(points.first().latitude,points.first().longitude)
                        override fun onMapReady(map: KakaoMap) {
                            controller.main.post {
                                if(!controller.disposed) {
                                    controller.map=map;controller.render();ready=true
                                }
                            }
                        }
                    })
                    if(lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))view.resume()
                } catch(error: LinkageError) {
                    controller.main.post {if(!controller.disposed)failure="이 기기에서는 지도를 사용할 수 없어요"}
                } catch(error: RuntimeException) {
                    controller.main.post {if(!controller.disposed)failure="지도를 불러오지 못했어요"}
                }
                host
            },modifier=Modifier.fillMaxSize(),onRelease={controller.dispose()},update={host->
                host.inputEnabled=interactive
                controller.dim(dim)
                controller.vehicle(vehiclePoint,vehicleOuter,vehicleInner,vehicleInk)
                controller.update(points,interactive,markerSize,markerBorder,cameraPadding,textSize,markerTypeface,ink,text,halo,haloWidth,canvas,ring,road,roadWidth,roadCasingWidth,roadInk,roadCasing,numbersOnly,
                    focus?.key,follow)
                controller.others(others,otherInk,staleInk)
            }
        )
        if(message!=null)Column(Modifier.padding(CarTokens.Frame),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),
            horizontalAlignment=Alignment.CenterHorizontally) {
            TripText(message,style=CarType.Label,maxLines=3,color=surfaceColors.onSurface)
        }
    }
    DisposableEffect(controller,lifecycle) {
        val observer=LifecycleEventObserver {_,event->
            when(event) {
                Lifecycle.Event.ON_RESUME->controller.view?.resume()
                Lifecycle.Event.ON_PAUSE->controller.view?.pause()
                else->Unit
            }
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            controller.dispose()
        }
    }
}

private class CourseMapController {
    val main=Handler(Looper.getMainLooper())
    var disposed=false
    var view: MapView?=null
    var map: KakaoMap?=null
    private var points: List<CourseMapPoint> = emptyList()
    private var interactive=false
    private var numbersOnly=false
    private var markerSize=0
    private var markerBorder=0f
    private var padding=0
    private var textSize=0
    private var markerTypeface: Typeface?=null
    private var ink=0
    private var text=0
    private var halo=0
    private var haloWidth=0
    private var canvas=0
    private var ring=0
    private var drawn: List<CourseMapPoint>?=null
    private var marker: Bitmap?=null
    private var road: List<CourseRoadCoordinate> = emptyList()
    private var drawnRoad: List<CourseRoadCoordinate>?=null
    private var roadWidth=0f
    private var roadCasingWidth=0f
    private var roadInk=0
    private var roadCasing=0
    private var polyline: Polyline?=null
    private var vehicle: CourseMapPoint?=null
    private var vehicleOuter=0f
    private var vehicleInner=0f
    private var vehicleInk=0
    private var vehicleLabel: Label?=null
    private var others: List<CourseMapCar> = emptyList()
    private var otherInk=0
    private var staleInk=0
    private val otherLabels=mutableMapOf<String,Pair<CourseMapCar,Label>>()
    private val nameLabels=mutableMapOf<String,Label>()
    private val nameSizes=mutableMapOf<String,Pair<Float,Float>>()
    private var focusKey: String?=null
    private var drawnFocus: String?=null
    private var dim: Int?=null
    private var follow=false
    private var framed: CourseMapFrame?=null
    @Volatile private var userMoved=false

    fun update(points: List<CourseMapPoint>,interactive: Boolean,markerSize: Int,markerBorder: Float,padding: Int,textSize: Int,markerTypeface: Typeface,ink: Int,text: Int,halo: Int,haloWidth: Int,canvas: Int,ring: Int,
        road: List<CourseRoadCoordinate>,roadWidth: Float,roadCasingWidth: Float,roadInk: Int,roadCasing: Int,numbersOnly: Boolean,focusKey: String?,follow: Boolean) {
        if(this.numbersOnly!=numbersOnly || this.markerSize!=markerSize || this.markerBorder!=markerBorder || this.textSize!=textSize || this.markerTypeface!=markerTypeface || this.ink!=ink || this.text!=text || this.halo!=halo || this.haloWidth!=haloWidth || this.canvas!=canvas || this.ring!=ring)drawn=null
        this.numbersOnly=numbersOnly
        this.points=points;this.interactive=interactive;this.markerSize=markerSize;this.markerBorder=markerBorder;this.padding=padding
        this.textSize=textSize;this.markerTypeface=markerTypeface;this.ink=ink;this.text=text;this.halo=halo;this.haloWidth=haloWidth;this.canvas=canvas;this.ring=ring
        if(this.roadWidth!=roadWidth || this.roadCasingWidth!=roadCasingWidth || this.roadInk!=roadInk || this.roadCasing!=roadCasing)drawnRoad=null
        this.road=road;this.roadWidth=roadWidth;this.roadCasingWidth=roadCasingWidth;this.roadInk=roadInk;this.roadCasing=roadCasing
        this.focusKey=focusKey;this.follow=follow
        render()
    }
    fun dim(color: Int?) {
        this.dim=color
        renderDim()
    }
    /** 야간에는 지도 타일만 덮는다. 장소 표식·이름(라벨)과 Route 패스의 경로선은 덮개 위에 그대로 둔다. */
    private fun renderDim() {
        val layer=map?.dimScreenManager?.dimScreenLayer ?: return
        val color=dim
        if(color==null) {layer.setVisible(false);return}
        layer.setDimScreenCover(DimScreenCover.Map)
        layer.setColor(color)
        layer.setVisible(true)
    }
    fun vehicle(point: CourseMapPoint?,outer: Float,inner: Float,ink: Int) {
        if(vehicleOuter!=outer || vehicleInner!=inner || vehicleInk!=ink) {vehicleLabel?.remove();vehicleLabel=null}
        vehicle=point;vehicleOuter=outer;vehicleInner=inner;vehicleInk=ink
        renderVehicle()
        hideNamesUnderMarkers()
    }
    fun others(cars: List<CourseMapCar>,ink: Int,stale: Int) {
        if(otherInk!=ink || staleInk!=stale) {otherLabels.values.forEach {it.second.remove()};otherLabels.clear()}
        others=cars;otherInk=ink;staleInk=stale
        renderOthers()
        hideNamesUnderMarkers()
    }
    /** 다른 차 표식은 위치만 옮기고, 지도 시점은 바꾸지 않는다(운전 중 화면이 계속 움직이지 않게). */
    private fun renderOthers() {
        val layer=map?.labelManager?.layer ?: return
        val wanted=others.associateBy {it.key}
        otherLabels.keys.filter {it !in wanted}.forEach {otherLabels.remove(it)?.second?.remove()}
        if(vehicleOuter<=0f)return
        for(car in others) {
            val position=LatLng.from(car.latitude,car.longitude)
            val existing=otherLabels[car.key]
            if(existing!=null && existing.first.label==car.label && existing.first.stale==car.stale) {
                existing.second.moveTo(position);otherLabels[car.key]=car to existing.second;continue
            }
            existing?.second?.remove()
            val size=kotlin.math.ceil(vehicleOuter*2).toInt()
            val bitmap=Bitmap.createBitmap(size,size,Bitmap.Config.ARGB_8888)
            val paint=Paint(Paint.ANTI_ALIAS_FLAG)
            val surface=Canvas(bitmap)
            val radius=size/2f
            paint.color=ring;surface.drawCircle(radius,radius,vehicleOuter,paint)
            paint.color=if(car.stale)staleInk else otherInk;surface.drawCircle(radius,radius,vehicleInner,paint)
            val label=layer.addLabel(LabelOptions.from(car.key,position).setClickable(false).setRank(Long.MAX_VALUE-1)
                .setStyles(LabelStyle.from(bitmap).setApplyDpScale(false).setAnchorPoint(0.5f,0.5f).setTextStyles(textSize,text,haloWidth,halo))
                .setTexts(LabelTextBuilder().setTexts(car.label))) ?: continue
            otherLabels[car.key]=car to label
        }
    }
    private fun frame() {
        val active=map ?: return
        if(points.isEmpty() || drawn!=points)return
        if(!interactive)userMoved=false
        val scene=CourseMapScene(points,road,focusKey)
        val current=vehicle
        val previous=framed
        val radius=kotlin.math.ceil(vehicleOuter).toInt()
        val viewport=active.viewport
        val now=current?.let {active.toScreenPoint(LatLng.from(it.latitude,it.longitude))}
        val before=previous?.vehicle?.let {active.toScreenPoint(LatLng.from(it.latitude,it.longitude))}
        val inView=now?.let {courseMapPointInView(it.x,it.y,viewport.width(),viewport.height(),radius)}
        val drift=if(now!=null && before!=null)kotlin.math.hypot((now.x-before.x).toFloat(),(now.y-before.y).toFloat()) else null
        if(!courseMapCameraShouldFit(scene,previous,current,follow,userMoved,inView,drift,vehicleOuter))return
        if(previous?.scene!=scene)userMoved=false
        val positions=courseMapCameraTargets(scene,current).map {LatLng.from(it.latitude,it.longitude)}.toTypedArray()
        val update=if(positions.size==1)CameraUpdateFactory.newCenterPosition(positions.first(),16)
            else CameraUpdateFactory.fitMapPoints(positions,padding,16)
        if(previous==null)active.moveCamera(update) else active.moveCamera(update,CameraAnimation.from(CarTokens.MotionLong1Ms))
        framed=CourseMapFrame(scene,current)
    }
    private fun renderVehicle() {
        val layer=map?.labelManager?.layer ?: return
        val point=vehicle
        if(point==null || vehicleOuter<=0f) {vehicleLabel?.remove();vehicleLabel=null;return}
        val position=LatLng.from(point.latitude,point.longitude)
        vehicleLabel?.let {it.moveTo(position);return}
        val size=kotlin.math.ceil(vehicleOuter*2).toInt()
        val bitmap=Bitmap.createBitmap(size,size,Bitmap.Config.ARGB_8888)
        val paint=Paint(Paint.ANTI_ALIAS_FLAG)
        val surface=Canvas(bitmap)
        val radius=size/2f
        paint.color=ring;surface.drawCircle(radius,radius,vehicleOuter,paint)
        paint.color=vehicleInk;surface.drawCircle(radius,radius,vehicleInner,paint)
        vehicleLabel=layer.addLabel(LabelOptions.from(point.key,position).setClickable(false).setRank(Long.MAX_VALUE)
            .setStyles(LabelStyle.from(bitmap).setApplyDpScale(false).setAnchorPoint(0.5f,0.5f)))
    }
    fun render() {
        val active=map ?: return
        GestureType.values().forEach {active.setGestureEnable(it,interactive)}
        active.setOnMapClickListener(null)
        active.setOnLabelClickListener(null)
        active.setOnCameraMoveStartListener {_,gesture->if(gesture!=GestureType.Unknown)userMoved=true}
        // 카메라 이동·줌이 끝나면 화면 좌표가 바뀌므로 표식과 이름의 겹침을 다시 판정한다.
        active.setOnCameraMoveEndListener {_,_,_->main.post {hideNamesUnderMarkers()}}
        renderDim()
        if(points.isEmpty() || markerSize<=0 || drawn==points && drawnRoad==road && drawnFocus==focusKey) {renderVehicle();renderOthers();frame();hideNamesUnderMarkers();return}
        polyline?.remove();polyline=null
        // 경로선은 야간 덮개 위 패스의 전용 레이어에 그린다. 기본 레이어에 두면 덮개에 덮여 외곽선까지 어두워진다.
        val shapes=active.shapeManager
        val routeLayer=shapes?.getLayer(COURSE_MAP_ROUTE_LAYER)
            ?: shapes?.addLayer(ShapeLayerOptions.from(COURSE_MAP_ROUTE_LAYER,ShapeManager.DEFAULT_Z_ORDER,COURSE_MAP_ROUTE_PASS))
        if(road.size>=2)polyline=routeLayer?.addPolyline(PolylineOptions.from(
            MapPoints.fromLatLng(road.map {LatLng.from(it.latitude,it.longitude)}),PolylineStyle.from(roadWidth,roadInk,roadCasingWidth,roadCasing)))
        val labels=active.labelManager ?: return
        val layer=labels.layer ?: return
        layer.removeAll()
        vehicleLabel=null
        otherLabels.clear()
        nameLabels.clear()
        nameSizes.clear()
        // 장소 이름은 번호 표식과 다른 레이어에 두고 이름끼리만 경쟁시킨다. 가까운 장소의 이름이 겹치면 순위가 낮은 이름을 숨기고,
        // 번호 표식은 경쟁하지 않아 모든 장소가 계속 보인다. 표식과 겹친 이름은 [hideNamesUnderMarkers]가 숨긴다.
        val names=labels.getLayer(COURSE_MAP_NAME_LAYER) ?: labels.addLayer(LabelLayerOptions.from(COURSE_MAP_NAME_LAYER)
            .setCompetitionType(CompetitionType.Same).setCompetitionUnit(CompetitionUnit.IconAndText)
            .setOrderingType(OrderingType.Rank).setZOrder(LabelManager.DEFAULT_Z_ORDER-1))
        names?.removeAll()
        val bitmap=Bitmap.createBitmap(markerSize,markerSize,Bitmap.Config.ARGB_8888)
        val paint=Paint(Paint.ANTI_ALIAS_FLAG)
        val surface=Canvas(bitmap)
        val radius=markerSize/2f
        paint.color=ring;surface.drawCircle(radius,radius,radius,paint)
        paint.color=ink;surface.drawCircle(radius,radius,(radius-markerBorder).coerceAtLeast(0f),paint)
        val numberPaint=Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color=canvas;textAlign=Paint.Align.CENTER;textSize=this@CourseMapController.textSize.toFloat()
            typeface=requireNotNull(markerTypeface)
        }
        // 이름은 표식 높이만큼 비운 투명 아이콘 아래(MapGravity.BOTTOM)에 써서 번호 표식을 가리지 않는다.
        val spacer=Bitmap.createBitmap(1,markerSize,Bitmap.Config.ARGB_8888)
        val nameStyle=LabelStyle.from(spacer).setApplyDpScale(false).setAnchorPoint(0.5f,0.5f)
            .setTextStyles(textSize,text,haloWidth,halo).setTextGravity(MapGravity.BOTTOM)
        val ranks=courseMapNameRanks(points,focusKey)
        // 겹침 판정용 글자 크기. SDK가 쓰는 글꼴은 공개되지 않아 같은 글자 크기의 기본 글꼴로 재고, 글자 테두리(halo)만큼 넓힌다.
        val namePaint=Paint(Paint.ANTI_ALIAS_FLAG).apply {textSize=this@CourseMapController.textSize.toFloat()}
        val nameHeight=namePaint.descent()-namePaint.ascent()+haloWidth*2
        points.forEachIndexed {index,point->
            val position=LatLng.from(point.latitude,point.longitude)
            val numbered=bitmap.copy(Bitmap.Config.ARGB_8888,true)
            Canvas(numbered).drawText("${index+1}",radius,radius-(numberPaint.ascent()+numberPaint.descent())/2,numberPaint)
            layer.addLabel(LabelOptions.from(point.key,position).setClickable(false)
                .setStyles(LabelStyle.from(numbered).setApplyDpScale(false).setAnchorPoint(0.5f,0.5f)))
            if(!numbersOnly)names?.addLabel(LabelOptions.from("name:"+point.key,position).setClickable(false).setRank(ranks.getValue(point.key))
                .setStyles(nameStyle).setTexts(LabelTextBuilder().setTexts(point.name)))?.let {
                nameLabels[point.key]=it
                nameSizes[point.key]=namePaint.measureText(point.name)+haloWidth*2 to nameHeight
            }
        }
        marker=bitmap
        renderVehicle()
        renderOthers()
        drawn=points
        drawnRoad=road
        drawnFocus=focusKey
        frame()
        hideNamesUnderMarkers()
    }
    /** 다른 장소의 번호 표식이나 차 표식과 화면에서 겹치는 이름을 숨기고, 겹침이 풀린 이름은 다시 보인다. */
    private fun hideNamesUnderMarkers() {
        val active=map ?: return
        if(nameLabels.isEmpty())return
        fun screen(latitude: Double,longitude: Double)=active.toScreenPoint(LatLng.from(latitude,longitude))
        val discs=buildList {
            points.forEach {point->screen(point.latitude,point.longitude)?.let {add(CourseMapDisc(point.key,it.x.toFloat(),it.y.toFloat(),markerSize/2f))}}
            if(vehicleOuter>0f) {
                vehicle?.let {car->screen(car.latitude,car.longitude)?.let {add(CourseMapDisc(null,it.x.toFloat(),it.y.toFloat(),vehicleOuter))}}
                others.forEach {car->screen(car.latitude,car.longitude)?.let {add(CourseMapDisc(null,it.x.toFloat(),it.y.toFloat(),vehicleOuter))}}
            }
        }
        val boxes=points.mapNotNull {point->
            val (width,height)=nameSizes[point.key] ?: return@mapNotNull null
            val at=screen(point.latitude,point.longitude) ?: return@mapNotNull null
            courseMapNameBox(point.key,at.x.toFloat(),at.y.toFloat(),markerSize,width,height)
        }
        val hidden=courseMapNamesHiddenByMarkers(boxes,discs)
        nameLabels.forEach {(key,label)->if(key in hidden) {if(label.isShow)label.hide()} else if(!label.isShow)label.show()}
    }
    fun dispose() {
        if(disposed)return
        disposed=true
        map=null
        vehicleLabel=null
        otherLabels.clear()
        nameLabels.clear()
        nameSizes.clear()
        view?.finish();view=null
        marker=null
        main.removeCallbacksAndMessages(null)
    }
}

private class CourseMapHost(context: Context): FrameLayout(context) {
    var inputEnabled=false
    override fun dispatchTouchEvent(event: MotionEvent): Boolean = if(inputEnabled)super.dispatchTouchEvent(event) else true
}
