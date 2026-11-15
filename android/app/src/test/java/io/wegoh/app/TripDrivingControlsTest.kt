package io.wegoh.app

import io.wegoh.app.nativeauth.*
import org.junit.Assert.*
import org.junit.Test

class TripDrivingControlsTest {
    private val owner=TripMember("f".repeat(40),"사용자A",true,true,true)
    private val car=TripCar("c".repeat(32),"사용자A 차",owner.id,owner.name,4,true,false,emptyList(),emptyList())
    private val detail=TripDetail("a".repeat(32),"강릉 여행","",listOf(owner),listOf(car),state="active",revision=1,courses=emptyList())
    private fun page(gear: TripGear,known: Boolean)=TripsPageState(detail=detail,gear=gear,carUxKnown=known)

    @Test fun handRaiseAndRepliesWorkInDriveOnceCarUxWasRead() {
        assertTrue(page(TripGear.DRIVE,true).canUseSignalControls(setupAllowed=false))
        assertTrue(page(TripGear.DRIVE,true).canUseSignalResponses(setupAllowed=false))
        assertTrue(page(TripGear.DRIVE,true).usesDrivingSignalComposer())
    }
    @Test fun unknownCarUxOrOtherGearsFailClosed() {
        assertFalse(page(TripGear.DRIVE,false).canUseSignalControls(setupAllowed=false))
        assertFalse(page(TripGear.DRIVE,false).canUseSignalResponses(setupAllowed=false))
        for(gear in listOf(TripGear.OTHER,TripGear.UNKNOWN)) {
            assertFalse(page(gear,true).canUseSignalControls(setupAllowed=true))
            assertFalse(page(gear,true).canUseSignalResponses(setupAllowed=true))
        }
    }
    @Test fun restrictedNonParkGearsKeepTheDrivingDashboardForAnActiveTrip() {
        assertTrue(page(TripGear.DRIVE,true).showsDrivingDashboard(setupAllowed=false))
        for(gear in listOf(TripGear.OTHER,TripGear.UNKNOWN)) {
            assertTrue(page(gear,true).showsDrivingDashboard(setupAllowed=false))
            assertFalse("Read-only dashboard must not widen controls",page(gear,true).canUseSignalControls(setupAllowed=false))
            assertFalse("Unrestricted CarUx keeps the regular screens",page(gear,true).showsDrivingDashboard(setupAllowed=true))
            assertFalse("No active trip: the restricted state stays",
                page(gear,true).copy(detail=detail.copy(state="planned")).showsDrivingDashboard(setupAllowed=false))
        }
        assertFalse(page(TripGear.PARK,true).showsDrivingDashboard(setupAllowed=false))
    }
    @Test fun parkKeepsTheFullComposerAndNeedsUnrestrictedCarUx() {
        assertTrue(page(TripGear.PARK,true).canUseSignalControls(setupAllowed=true))
        assertFalse(page(TripGear.PARK,true).usesDrivingSignalComposer())
        assertFalse(page(TripGear.PARK,true).canUseSignalControls(setupAllowed=false))
    }
    @Test fun finishedRouteStillBlocksSendingInDrive() {
        val done=page(TripGear.DRIVE,true).copy(detail=detail.copy(state="completed"))
        assertFalse(done.canUseSignalControls(setupAllowed=false))
    }
    @Test fun inlineWalkieTalkieAllowsReadCarUxWhileLegacyHostStaysParkedOnly() {
        val drivingFlags=0x7F
        assertTrue(nativeVoiceCarUxPermits(drivingOptimized=true,requiresDistractionOptimization=true,activeRestrictions=drivingFlags))
        assertFalse(nativeVoiceCarUxPermits(drivingOptimized=false,requiresDistractionOptimization=true,activeRestrictions=drivingFlags))
        assertTrue(nativeVoiceCarUxPermits(drivingOptimized=false,requiresDistractionOptimization=false,activeRestrictions=0))
    }
}
