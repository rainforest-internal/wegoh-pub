package io.wegoh.app.ui

import io.wegoh.app.nativeauth.*
import org.junit.Assert.assertEquals
import org.junit.Test

class TripCourseCompletionTest {
    private val join=TripRouteItem("course","seoul-station","course-1")
    private fun plan(drop: List<TripRouteItem>)=TripRoutePlan(2,"shared",listOf(
        TripRouteSegment("pickup",emptyList()),TripRouteSegment("shared",listOf(join)),TripRouteSegment("drop",drop)),
        TripJoinPoint("course-1","seoul-station","서울역",37.55,126.97),null,3,join,TripJoinBarrier(listOf("car-1"),1,true))
    private fun mine(drop: List<TripRouteItem>)=TripCar("car-1","사용자D의 차","driver","사용자D",4,isMine=true,iRide=false,
        passengers=emptyList(),routePlan=plan(drop),ordinal=1)
    private fun other(phase: String)=TripCar("car-2","다른 차","driver-2","사용자B",4,isMine=false,iRide=false,
        passengers=emptyList(),routeStatus=TripRouteStatus(phase),ordinal=2)
    private fun trip(vararg cars: TripCar)=TripDetail("trip","가","",emptyList(),cars.toList(),state="active",routeContractVersion=2)

    @Test
    fun lastCarWithoutDropWarnsThatTheTripEnds() {
        assertEquals(TripCourseCompletion.TRIP_ENDS,tripCourseCompletion(trip(mine(emptyList()))))
        assertEquals(TripCourseCompletion.TRIP_ENDS,tripCourseCompletion(trip(mine(emptyList()),other("done"))))
        assertEquals(TripCourseCompletion.CAR_DONE,tripCourseCompletion(trip(mine(emptyList()),other("shared"))))
        assertEquals(TripCourseCompletion.DROP_NEXT,tripCourseCompletion(trip(mine(listOf(TripRouteItem("drop","office"))))))
    }
}
