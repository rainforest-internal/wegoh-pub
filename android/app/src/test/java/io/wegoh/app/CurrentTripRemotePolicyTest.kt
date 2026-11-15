package io.wegoh.app

import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.currentTripRemotePolicy
import io.wegoh.app.ui.remotePolicyForReceiver
import io.wegoh.app.ui.remotePolicyFamilies
import io.wegoh.app.ui.remotePolicyFamilySummary
import org.junit.Assert.*
import org.junit.Test

class CurrentTripRemotePolicyTest {
    private val policy=TripRemotePolicy(true,setOf("hvac.temperature"),"device")
    private val car=TripCar("car","사용자A의 차","me","사용자A",2,true,false,emptyList(),remotePolicy=policy)
    private val trip=TripDetail("trip","서해안 드라이브","",listOf(TripMember("me","사용자A",true,true,true)),listOf(car),state="active")
    private val current=TripsPageState(AccountReadStatus.READY,selectedId=trip.id,detail=trip,isCurrent=true)

    @Test fun receivingVehicleMustMatchThePolicyTarget() {
        assertSame(policy,remotePolicyForReceiver(policy,"device"))
        assertNull(remotePolicyForReceiver(policy,"other-device"))
        assertNull(remotePolicyForReceiver(policy,null))
        assertNull(remotePolicyForReceiver(policy.copy(deviceId=null),"device"))
        val off=policy.copy(enabled=false)
        assertSame(off,remotePolicyForReceiver(off,null))
    }
    @Test fun displayedGroupsCoverTheCanonicalActionsExactlyOnce() {
        val actions=remotePolicyFamilies.flatMap {it.second}
        assertEquals(TripRemotePolicy.supportedActions,actions.toSet())
        assertEquals(actions.size,actions.toSet().size)
        assertEquals(5,remotePolicyFamilies.single {it.first=="공조"}.second.size)
    }
    @Test fun summaryNamesEachFamilyOnceWithoutRepeatingAllowed() {
        val partial=TripRemotePolicy(true,setOf("hvac.temperature","light.cabin","light.reading","light.ambient"),"device")
        assertEquals(listOf("공조 1/5","조명") to listOf("창문","시트"),remotePolicyFamilySummary(partial))
        assertEquals(emptyList<String>() to remotePolicyFamilies.map {it.first},remotePolicyFamilySummary(partial.copy(enabled=false)))
        val summary=remotePolicyFamilySummary(partial)
        assertTrue((summary.first+summary.second).none {"허용" in it})
    }
    @Test fun onlyCurrentSelectedActiveTripCanSupplyPolicy() {
        assertSame(policy,currentTripRemotePolicy(current))
        assertNull(currentTripRemotePolicy(current.copy(isCurrent=false)))
        assertNull(currentTripRemotePolicy(current.copy(status=AccountReadStatus.LOADING)))
        assertNull(currentTripRemotePolicy(current.copy(selectedId="another-trip")))
        assertNull(currentTripRemotePolicy(current.copy(selectedId=null)))
        assertNull(currentTripRemotePolicy(current.copy(detail=trip.copy(state="completed"))))
        assertNull(currentTripRemotePolicy(current.copy(detail=trip.copy(state="planned"))))
    }
    @Test fun unknownPolicyAndOtherCarsNeverBecomeAnOffOrAllowedPolicy() {
        val unknown=car.copy(remotePolicy=null)
        val other=car.copy(id="other",isMine=false,iRide=false)
        assertNull(currentTripRemotePolicy(current.copy(detail=trip.copy(cars=listOf(unknown,other)))))
        assertNull(currentTripRemotePolicy(current.copy(detail=trip.copy(cars=listOf(other)))))
        val off=policy.copy(enabled=false)
        assertSame(off,currentTripRemotePolicy(current.copy(detail=trip.copy(cars=listOf(car.copy(remotePolicy=off))))))
    }
    @Test fun independentlyLoadedPolicyDoesNotRequireASelectedTripAndClearsWhenStale() {
        val independent=current.copy(selectedId=null,detail=null,
            remotePolicySnapshot=TripRemotePolicySnapshot(AccountReadStatus.READY,trip.id,trip.title,policy))
        assertSame(policy,currentTripRemotePolicy(independent))
        assertNull(currentTripRemotePolicy(independent.copy(isCurrent=false)))
        assertNull(currentTripRemotePolicy(independent.suspended(true)))
        assertNull(currentTripRemotePolicy(independent.copy(remotePolicySnapshot=TripRemotePolicySnapshot(AccountReadStatus.READY))))
    }
    @Test fun selectedActiveTripDetailCoversASnapshotThatIsNotReady() {
        assertSame(policy,currentTripRemotePolicy(current))
        assertSame(policy,currentTripRemotePolicy(current.copy(remotePolicySnapshot=TripRemotePolicySnapshot(AccountReadStatus.LOADING))))
        assertSame(policy,currentTripRemotePolicy(current.copy(remotePolicySnapshot=TripRemotePolicySnapshot(AccountReadStatus.UNAVAILABLE))))
        val loadingWithoutDetail=current.copy(selectedId=null,detail=null,remotePolicySnapshot=TripRemotePolicySnapshot(AccountReadStatus.LOADING))
        assertNull(currentTripRemotePolicy(loadingWithoutDetail))
        assertNull(currentTripRemotePolicy(current.copy(detail=trip.copy(state="completed"),
            remotePolicySnapshot=TripRemotePolicySnapshot(AccountReadStatus.LOADING))))
    }
    @Test fun sameTripSnapshotAndDetailUseTheNewerRevision() {
        val allowed=policy.copy(revision=4)
        val off=policy.copy(enabled=false,revision=5)
        fun state(snapshot: TripRemotePolicy?,detail: TripRemotePolicy?)=current.copy(
            detail=trip.copy(cars=listOf(car.copy(remotePolicy=detail))),
            remotePolicySnapshot=TripRemotePolicySnapshot(AccountReadStatus.READY,trip.id,trip.title,snapshot))
        assertSame(off,currentTripRemotePolicy(state(allowed,off)))
        assertSame(off,currentTripRemotePolicy(state(off,allowed)))
        assertSame(allowed,currentTripRemotePolicy(state(allowed,allowed.copy())))
        assertEquals(policy,currentTripRemotePolicy(state(policy,policy.copy())))
        assertNull(currentTripRemotePolicy(state(allowed,off.copy(revision=null))))
        assertNull(currentTripRemotePolicy(state(null,allowed)))
        assertNull(currentTripRemotePolicy(state(allowed,null)))
    }
    @Test fun snapshotForAnotherTripDoesNotLabelTheSelectedTrip() {
        val other=TripRemotePolicySnapshot(AccountReadStatus.READY,"other-trip","다른 여행",policy.copy(revision=9))
        assertNull(currentTripRemotePolicy(current.copy(remotePolicySnapshot=other)))
        assertNull(currentTripRemotePolicy(current.copy(remotePolicySnapshot=TripRemotePolicySnapshot(AccountReadStatus.READY))))
    }
}
