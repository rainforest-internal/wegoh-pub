package io.wegoh.app

import io.wegoh.app.nativeauth.*
import org.junit.Assert.*
import org.junit.Test

class TripPreparationReadinessTest {
    private val driver=TripMember("driver","운전자",true,true,true,readiness=TripReadiness.READY)
    private val rider=TripMember("rider","동승자",true,false,false,readiness=TripReadiness.READY)
    private val car=TripCar("car","우리 차",driver.id,driver.name,3,true,false,listOf(TripPassenger(rider.id,rider.name,false)))
    private val course=TripCourse("course","바다 코스",stopCount=1,stops=listOf(TripCourseStop("stop","바다")))
    private val trip=TripDetail("trip","여행","",listOf(driver,rider),listOf(car),state="planned",revision=2,courses=listOf(course))

    @Test fun driverDoesNotNeedToChoosePersonalPickupAndDrop() {
        assertEquals(listOf(true,true,true,true),tripPreparationChecks(trip).map {it.done})
        val unassigned=rider.copy(carId=null)
        assertTrue(tripPreparationChecks(trip.copy(members=listOf(driver,unassigned)))[1].done)
    }
    @Test fun passengerChecklistUsesTheirOwnStops() {
        val passengerTrip=trip.copy(members=listOf(driver.copy(isMe=false),rider.copy(isMe=true)),
            cars=listOf(car.copy(isMine=false,iRide=true,places=listOf(
                TripPlace("역",kind="pickup",selectedBy=listOf(driver.id)),TripPlace("집",kind="drop",selectedBy=listOf(driver.id))))))
        assertFalse(tripPreparationChecks(passengerTrip)[2].done)
        val chosen=passengerTrip.copy(cars=listOf(passengerTrip.cars.single().copy(places=listOf(
            TripPlace("역",kind="pickup",selectedBy=listOf(rider.id)),TripPlace("집",kind="drop",selectedBy=listOf(rider.id))))))
        assertTrue(tripPreparationChecks(chosen)[2].done)
    }
    @Test fun pendingInvitationsAreVisibleWithoutBecomingAStartRequirement() {
        val pending=trip.copy(members=trip.members+TripMember("pending","초대 중",false,false,false,readiness=TripReadiness.INVITED))
        assertFalse(tripPreparationChecks(pending)[0].done)
        assertTrue(tripCanStart(pending))
    }
    @Test fun groupReadinessNeedsEveryVisibleMemberReadyWithoutGatingStart() {
        assertEquals("일행 준비",tripPreparationChecks(trip)[0].label)
        assertEquals(2,tripPlanOverview(trip).ready)
        val preparing=trip.copy(members=listOf(driver,rider.copy(readiness=TripReadiness.NEEDS_PLACES)))
        assertFalse(tripPreparationChecks(preparing)[0].done)
        assertEquals(1,tripPlanOverview(preparing).ready)
        assertTrue(tripCanStart(preparing))
    }
    @Test fun soloTripCountsGroupReadinessAsNotApplicable() {
        val solo=trip.copy(members=listOf(driver),cars=listOf(car.copy(passengers=emptyList())))
        val checks=tripPreparationChecks(solo)
        assertEquals(listOf(true,true,true,true),checks.map {it.done})
        assertEquals(listOf(true,false,true,false),checks.map {it.notApplicable})
        assertEquals(0,checks.count {!it.done})
        assertTrue(tripCanStart(solo))
        val withInvite=solo.copy(members=listOf(driver,TripMember("pending","초대 중",false,false,false,readiness=TripReadiness.INVITED)))
        assertFalse(tripPreparationChecks(withInvite)[0].done)
        assertFalse(tripPreparationChecks(withInvite)[0].notApplicable)
    }
    @Test fun startRequiresTheExistingOwnerRevisionCarAndCompleteCourseContract() {
        assertTrue(tripCanStart(trip))
        assertFalse(tripCanStart(trip.copy(cars=emptyList())))
        assertFalse(tripCanStart(trip.copy(courses=emptyList())))
        assertFalse(tripCanStart(trip.copy(courses=listOf(course.copy(stops=null)))))
        assertFalse(tripCanStart(trip.copy(courses=listOf(course.copy(stops=emptyList())))))
        assertFalse(tripCanStart(trip.copy(revision=null)))
        assertFalse(tripCanStart(trip.copy(state="active")))
        assertFalse(tripCanStart(trip.copy(members=listOf(driver.copy(isMe=false),rider.copy(isMe=true)))))
    }
}
