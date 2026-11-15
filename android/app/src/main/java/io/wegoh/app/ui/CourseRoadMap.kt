package io.wegoh.app.ui

import android.os.Handler
import android.os.Looper
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import io.wegoh.app.*
import io.wegoh.app.nativeauth.TripRouteItem
import io.wegoh.app.nativeauth.VehicleConnection
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

private data class CourseRoadMapAccess(val cache: CourseRoadMaps,val boundary: String?)
private val LocalCourseRoadMaps=staticCompositionLocalOf<CourseRoadMapAccess?> {null}

@Composable
internal fun ProvideCourseRoadMaps(connection: VehicleConnection,content: @Composable ()->Unit) {
    fun boundary()=connection.contentDataBoundary(VehicleConnection.Scope.COURSES)?.let {
        "${it.storageKey}:${it.revision}:${connection.dataStreamRevision()}"
    }
    val cache=remember(connection) {
        val api=connection.courseRoadMapsApi
        CourseRoadMaps(::boundary,
            {course,callback->api.pack(course.id,course.version,course.checksum,{decodeCourseRoadPack(course,it)},callback)},
            {course,points,callback->api.route(course.id,course.version,course.checksum,points,callback)})
    }
    var current by remember(connection) {mutableStateOf(boundary())}
    val lifecycle=LocalLifecycleOwner.current.lifecycle
    DisposableEffect(connection,lifecycle) {
        val main=Handler(Looper.getMainLooper())
        fun refresh() {
            val next=boundary()
            if(next!=current) {cache.clear();current=next}
        }
        val watch=connection.observeDataBoundary {main.post {refresh()}}
        val observer=LifecycleEventObserver {_,event->
            if(event==Lifecycle.Event.ON_STOP) {cache.clear();current=null}
            else if(event==Lifecycle.Event.ON_RESUME)refresh()
        }
        lifecycle.addObserver(observer)
        onDispose {watch.close();lifecycle.removeObserver(observer);main.removeCallbacksAndMessages(null);cache.clear()}
    }
    CompositionLocalProvider(LocalCourseRoadMaps provides CourseRoadMapAccess(cache,current),content=content)
}

@Composable
internal fun CourseRoadMap(course: PublishedPack?,modifier: Modifier=Modifier,enabled: Boolean=true,
    fallback: List<TripRouteStop> = emptyList(),interactive: Boolean=false,numbersOnly: Boolean=false) {
    val access=LocalCourseRoadMaps.current
    val view=LocalView.current
    var visible by remember(course) {mutableStateOf(false)}
    var result by remember(course,access?.boundary,enabled) {mutableStateOf<Result<CourseRoadPreview>?>(null)}
    LaunchedEffect(course,access?.boundary,enabled,visible) {
        if(course!=null && access?.boundary!=null && enabled && visible) {
            delay(250)
            result=suspendCancellableCoroutine {continuation->
                val task=access.cache.load(course) {if(continuation.isActive)continuation.resume(it)}
                continuation.invokeOnCancellation {task.close()}
            }
        }
    }
    Box(modifier.onGloballyPositioned {coordinates->
        visible=coordinates.boundsInWindow().overlaps(Rect(0f,0f,view.width.toFloat(),view.height.toFloat()))
    },contentAlignment=Alignment.Center) {
        val preview=result?.getOrNull()
        if(course==null && fallback.isNotEmpty())KakaoCourseMap(fallback,Modifier.fillMaxSize(),interactive,numbersOnly=numbersOnly)
        else if(preview!=null && enabled && access?.boundary!=null) {
            val stops=preview.stops.map {TripRouteStop(TripRouteItem("course",it.id,course!!.id),it.name,it.latitude,it.longitude)}
            KakaoCourseMap(stops,Modifier.fillMaxSize(),interactive,preview.path,numbersOnly)
        } else TripText(when {
            !enabled->"경로를 다시 불러와 주세요"
            access?.boundary==null->"차량 연결을 확인해 주세요"
            result?.isFailure==true->"경로를 불러오지 못했어요"
            course==null->"표시할 장소가 없어요"
            else->"지도 불러오는 중"
        },Modifier.padding(CarTokens.Frame),style=CarType.Label,maxLines=3)
    }
}
