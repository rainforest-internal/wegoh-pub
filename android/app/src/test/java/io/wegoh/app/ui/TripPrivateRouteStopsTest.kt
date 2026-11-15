package io.wegoh.app.ui

import io.wegoh.app.TripRouteStop
import io.wegoh.app.nativeauth.*
import org.junit.Assert.assertEquals
import org.junit.Test

class TripPrivateRouteStopsTest {
    private val pickup=TripRouteItem("pickup","home")
    private val join=TripRouteItem("course","seoul-station","course-1")
    private val nextCourse=TripRouteItem("course","museum","course-1")
    private val signal=TripRouteItem("signal","cafe")
    private val drop=TripRouteItem("drop","office")
    private val stops=listOf(pickup,join,signal,nextCourse,drop).map {TripRouteStop(it,it.ref,37.5,127.0)}

    private fun plan(phase: String)=TripRoutePlan(2,phase,listOf(
        TripRouteSegment("pickup",listOf(pickup)),
        TripRouteSegment("shared",listOf(join,signal,nextCourse)),
        TripRouteSegment("drop",listOf(drop))),
        TripJoinPoint("course-1","seoul-station","서울역",37.55,126.97),null,1,signal,TripJoinBarrier(emptyList(),1,true))

    @Test
    fun signalAddedToSharedSegmentStaysOnPrivateMap() {
        assertEquals(listOf(pickup,join,signal),tripPrivateRouteStops(stops,plan("pickup")).map {it.item})
        assertEquals(listOf(signal,drop),tripPrivateRouteStops(stops,plan("drop")).map {it.item})
    }

    @Test
    fun signalStopIsNotCalledJoinPoint() {
        assertEquals("손들기 장소",tripPrivateNextLabel(signal))
        assertEquals("도착했어요",tripPrivateArrivalLabel(signal,pickup))
        assertEquals("합류 지점",tripPrivateNextLabel(join))
        assertEquals("합류 지점 도착",tripPrivateArrivalLabel(join,pickup))
        assertEquals("탔어요",tripPrivateArrivalLabel(pickup,pickup))
        assertEquals("우리 차 주행 완료",tripPrivateArrivalLabel(drop,drop))
    }
}
