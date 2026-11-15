package io.wegoh.app.ui

import io.wegoh.app.CourseDrivingResult
import io.wegoh.app.TripsPageState
import io.wegoh.app.nativeauth.*
import org.junit.Assert.*
import org.junit.Test

class TripLiveScoresTest {
    private val ownId="1".repeat(32)
    private val otherId="2".repeat(32)
    private val own=TripCar(ownId,"내 차량","me","나",4,true,false,emptyList())
    private val other=TripCar(otherId,"일행 차량","friend","친구",4,false,false,emptyList())
    private val trip=TripDetail("a".repeat(32),"여행","",emptyList(),listOf(other,own),state="active",routeContractVersion=2)
    private fun report(id: String,score: Int?,state: String="pending",final: Boolean=false)=
        TripDrivingVersusCar(id,id,true,state,null,0,emptyList(),score,final)
    private fun versus(vararg cars: TripDrivingVersusCar,scope: String="trip")=
        TripDrivingVersus("safe-driving-versus",true,"pending",null,cars.toList(),emptyList(),false,scope)
    private fun state(versus: TripDrivingVersus?=null,local: CourseDrivingResult?=null)=
        TripsPageState(selectedId=trip.id,detail=trip,isCurrent=true,drivingVersus=versus,
            liveCourseId="trip-total-v1",liveCourseScore=local)

    @Test fun ownCurrentTotalComesFirstWhileOtherCarsUseSharedTotals() {
        val rows=tripLiveScoreRows(trip,state(versus(report(ownId,95),report(otherId,90)),
            CourseDrivingResult(accelerations=2,brakings=1,measuredMillis=3000)))
        assertEquals(listOf(ownId,otherId),rows.map {it.carId})
        assertTrue(rows.first().own)
        assertEquals(listOf(85,90),rows.map {it.score})
        assertTrue(rows.all {it.status=="현재 점수"})
    }

    @Test fun missingMeasurementsAndCourseAveragesNeverBecomeTripScores() {
        val legacy=report(otherId,null).copy(averageScore=99.0)
        val rows=tripLiveScoreRows(trip,state(versus(legacy,scope="courses"),CourseDrivingResult()).copy(liveCourseId="a-course"))
        assertTrue(rows.all {it.score==null})
        assertTrue(rows.all {it.status=="여행 점수 확인 필요"})
        assertTrue(tripLiveScoreRows(trip,state()).all {it.score==null && it.status=="측정 대기"})
    }

    @Test fun hiddenWithdrawnAndUnavailableRowsCannotBeOverriddenByLocalScore() {
        for(blocked in listOf("sharing-unavailable","withdrawn","unavailable")) {
            val rows=tripLiveScoreRows(trip,state(versus(report(ownId,null,blocked),report(otherId,null,blocked)),
                CourseDrivingResult(measuredMillis=1000)))
            assertTrue(rows.all {it.score==null})
        }
        val rows=tripLiveScoreRows(trip,state(versus(report(otherId,100).copy(participating=false))))
        assertEquals("참가 종료",rows.last().status)
        assertNull(rows.last().score)
    }

    @Test fun staleAccountOrDifferentTripDoesNotShowScores() {
        val shared=versus(report(ownId,95),report(otherId,90))
        assertTrue(tripLiveScoreRows(trip,state(shared).copy(isCurrent=false)).all {it.score==null && it.status=="연결 확인 중"})
        assertTrue(tripLiveScoreRows(trip,state(shared).copy(detail=trip.copy(id="b".repeat(32)))).all {it.score==null})
    }

    @Test fun zeroAndFinalScoresRemainVisible() {
        val rows=tripLiveScoreRows(trip,state(versus(report(otherId,0,"ready",true)),
            CourseDrivingResult(measuredMillis=1000,completed=true)))
        assertEquals(listOf(100,0),rows.map {it.score})
        assertTrue(rows.all {it.status=="최종 점수"})
    }

    @Test fun loadingAndReadFailuresKeepExplicitRowStates() {
        assertTrue(tripLiveScoreRows(trip,state().copy(drivingVersusLoading=true)).all {it.score==null && it.status=="불러오는 중"})
        assertTrue(tripLiveScoreRows(trip,state().copy(drivingVersusNotice="실패")).all {it.score==null && it.status=="점수 확인 필요"})
    }

    @Test fun drivingCompanionScoresExcludeOwnCarAndHiddenCars() {
        val shared=versus(report(ownId,95),report(otherId,90))
        assertEquals(mapOf(otherId to 90),tripCompanionScores(trip,state(shared)))
        assertEquals(emptyMap<String,Int>(),tripCompanionScores(trip,state(versus(report(otherId,null,"sharing-unavailable")))))
        assertEquals(emptyMap<String,Int>(),tripCompanionScores(trip,state(shared).copy(isCurrent=false)))
        assertEquals(emptyMap<String,Int>(),tripCompanionScores(trip,state(versus(report(otherId,90).copy(averageScore=90.0),scope="courses"))))
    }
}
