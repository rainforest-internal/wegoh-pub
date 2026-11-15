package io.wegoh.app

import io.wegoh.app.nativeauth.TripRouteItem
import io.wegoh.app.ui.COURSE_MAP_VEHICLE_KEY
import io.wegoh.app.ui.courseMapPoints
import io.wegoh.app.ui.courseMapVehicle
import io.wegoh.app.ui.courseMapOtherCars
import io.wegoh.app.nativeauth.TripCar
import io.wegoh.app.nativeauth.TripCarPosition
import io.wegoh.app.nativeauth.TripDetail
import org.junit.Assert.*
import org.junit.Test

class CourseMapPointsTest {
    @Test fun onlyActualFiniteCoordinatesAreMappedInRouteOrder() {
        val first=TripRouteStop(TripRouteItem("pickup","a"),"픽업",37.55,126.91)
        val last=TripRouteStop(TripRouteItem("course","z","coast"),"합류",36.61,126.39)
        val points=courseMapPoints(listOf(first,
            TripRouteStop(TripRouteItem("pickup","missing"),"좌표 없음",null,null),
            TripRouteStop(TripRouteItem("pickup","nan"),"잘못된 좌표",Double.NaN,127.0),
            TripRouteStop(TripRouteItem("pickup","range"),"범위 밖",91.0,127.0),last,first))
        assertEquals(listOf(first.key,last.key),points.map {it.key})
        assertEquals(37.55,points[0].latitude,0.0)
        assertEquals(126.39,points[1].longitude,0.0)
    }
    @Test fun vehiclePositionBecomesASeparateMarkerOnlyWhenValid() {
        val vehicle=checkNotNull(courseMapVehicle(TripPosition(37.51,127.02,90.0)))
        assertEquals(COURSE_MAP_VEHICLE_KEY,vehicle.key)
        assertEquals(37.51,vehicle.latitude,0.0);assertEquals(127.02,vehicle.longitude,0.0)
        assertNull(courseMapVehicle(null))
        assertNull(courseMapVehicle(TripPosition(Double.NaN,127.0)))
        assertNull(courseMapVehicle(TripPosition(37.0,181.0)))
    }
    @Test fun otherCarsOmitMyCarUnknownCarsAndMarkLatePositions() {
        val mine=TripCar("m".repeat(32),"내 차","me","나",2,true,false,emptyList(),ordinal=1)
        val other=TripCar("o".repeat(32),"우리 차","friend","친구",2,false,false,emptyList(),ordinal=2)
        val unnamed=TripCar("u".repeat(32),"캠핑카","third","셋째",2,false,false,emptyList())
        val trip=TripDetail("t".repeat(32),"여행","",emptyList(),listOf(mine,other,unnamed),state="active")
        val cars=courseMapOtherCars(trip,listOf(
            TripCarPosition(mine.id,37.0,127.0,"vehicle",0),
            TripCarPosition(other.id,37.1,127.1,"vehicle",5_000),
            TripCarPosition(unnamed.id,37.2,127.2,"phone",45_000),
            TripCarPosition("x".repeat(32),37.3,127.3,"phone",0)))
        assertEquals(listOf("2호차","캠핑카 (이전 위치)"),cars.map {it.label})
        assertEquals(listOf(false,true),cars.map {it.stale})
        assertEquals(37.1,cars[0].latitude,0.0)
        assertTrue(courseMapOtherCars(null,listOf(TripCarPosition(other.id,37.1,127.1,"vehicle",0))).isEmpty())
    }
}
