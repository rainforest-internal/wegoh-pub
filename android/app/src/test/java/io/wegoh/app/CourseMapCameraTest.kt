package io.wegoh.app

import io.wegoh.app.nativeauth.CourseRoadCoordinate
import io.wegoh.app.ui.COURSE_MAP_VEHICLE_KEY
import io.wegoh.app.ui.CourseMapFrame
import io.wegoh.app.ui.CourseMapPoint
import io.wegoh.app.ui.CourseMapScene
import io.wegoh.app.ui.courseMapCameraShouldFit
import io.wegoh.app.ui.courseMapCameraTargets
import io.wegoh.app.ui.courseMapPointInView
import org.junit.Assert.*
import org.junit.Test

class CourseMapCameraTest {
    private val station=CourseMapPoint("pickup:station","서울역",37.5547,126.9707)
    private val join=CourseMapPoint("course:join","합류",37.40,127.10)
    private val car=CourseMapPoint(COURSE_MAP_VEHICLE_KEY,"지금 여기",37.413,127.095)
    private val scene=CourseMapScene(listOf(station,join),emptyList(),station.key)

    private fun fit(framed: CourseMapFrame?,vehicle: CourseMapPoint?=car,follow: Boolean=false,userMoved: Boolean=false,
        inView: Boolean?=true,drift: Float?=0f,current: CourseMapScene=scene)=
        courseMapCameraShouldFit(current,framed,vehicle,follow,userMoved,inView,drift,24f)

    @Test fun carAndNextPlaceAreFramedTogetherOnceTheCarIsKnown() {
        assertEquals(listOf(CourseRoadCoordinate(station.latitude,station.longitude),CourseRoadCoordinate(car.latitude,car.longitude)),
            courseMapCameraTargets(scene,car))
    }
    @Test fun withoutCarOrNextPlaceTheWholeRouteIsFramed() {
        val road=listOf(CourseRoadCoordinate(37.5,127.0))
        val withRoad=scene.copy(road=road)
        assertEquals(listOf(station,join).map {CourseRoadCoordinate(it.latitude,it.longitude)}+road,courseMapCameraTargets(withRoad,null))
        val done=scene.copy(focusKey=null)
        assertEquals(listOf(station,join,car).map {CourseRoadCoordinate(it.latitude,it.longitude)},courseMapCameraTargets(done,car))
        val unknownFocus=scene.copy(focusKey="signal:missing")
        assertEquals(3,courseMapCameraTargets(unknownFocus,car).size)
    }
    @Test fun firstFrameAndSceneChangesAlwaysFitEvenAfterUserMovedTheMap() {
        assertTrue(fit(null,vehicle=null))
        val framed=CourseMapFrame(scene,car)
        assertTrue(fit(framed,userMoved=true,current=scene.copy(focusKey=join.key)))
        assertTrue(fit(framed,userMoved=true,current=scene.copy(points=listOf(join))))
    }
    @Test fun carArrivingAfterTheFirstFrameRefitsUnlessUserMovedTheMap() {
        val routeOnly=CourseMapFrame(scene,null)
        assertTrue(fit(routeOnly,inView=false))
        assertFalse(fit(routeOnly,userMoved=true,inView=false))
        assertFalse(fit(routeOnly,vehicle=null))
    }
    @Test fun parkedMapRefitsOnlyWhenTheCarLeavesTheView() {
        val framed=CourseMapFrame(scene,car)
        assertFalse(fit(framed,drift=500f))
        assertTrue(fit(framed,inView=false))
        assertFalse(fit(framed,inView=false,userMoved=true))
    }
    @Test fun drivingMapFollowsTheCarOnceItDriftsByAMarkerRadius() {
        val framed=CourseMapFrame(scene,car)
        assertFalse(fit(framed,follow=true,drift=23f))
        assertTrue(fit(framed,follow=true,drift=24f))
        assertFalse(fit(framed,follow=true,drift=null))
        assertTrue(fit(framed,follow=true,inView=false,drift=null))
    }
    @Test fun viewCheckKeepsTheWholeMarkerInsideTheMap() {
        assertTrue(courseMapPointInView(100,50,200,100,10))
        assertTrue(courseMapPointInView(10,90,200,100,10))
        assertFalse(courseMapPointInView(5,50,200,100,10))
        assertFalse(courseMapPointInView(100,95,200,100,10))
        assertFalse(courseMapPointInView(-300,50,200,100,10))
        assertFalse(courseMapPointInView(0,0,0,0,0))
    }
}
