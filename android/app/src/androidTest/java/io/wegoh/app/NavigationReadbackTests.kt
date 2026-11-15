package io.wegoh.app

import android.test.InstrumentationTestCase
import ai.pleos.playground.navi.data.DestinationInfo
import ai.pleos.playground.navi.data.WaypointInfo

/** Synthetic model guard cases only; not actual NaviHelper delivery evidence. */
@Suppress("DEPRECATION")
class NavigationReadbackTests: InstrumentationTestCase() {
    fun testDelegationObservationKeepsFlagConflictAndCanonicalCoordinates() {
        val pack=instrumentation.targetContext.assets.open("packs/01-city-story.json").use {PackCodec.decode(PackCodec.read(it))}
        val original=pack.stops.last();assertFalse(original.poiId.isNullOrEmpty())
        val route=coordinateRouteInfo(original)
        assertEquals(original.latitude,route.latitude);assertEquals(original.longitude,route.longitude)
        assertEquals(original.latitude,route.displayLatitude);assertEquals(original.longitude,route.displayLongitude)
        assertEquals("",route.poiId);assertFalse("Stored metadata must be preserved",original.poiId.isNullOrEmpty())
        val via=coordinateWaypointInfo(original,1)
        assertEquals(original.latitude,via.latitude);assertEquals(original.longitude,via.longitude)
        assertEquals("",via.poiId);assertEquals(ai.pleos.playground.navi.constants.WaypointIndex.SECOND,via.waypointIndex)
        assertTrue(runCatching {coordinateWaypointInfo(original,2)}.exceptionOrNull() is IllegalArgumentException)
        val client=NavigationClient(instrumentation.targetContext,{})
        try {
            for(stops in listOf(emptyList(),List(4){original})) {
                assertTrue(runCatching {client.request(pack.copy(stops=stops))}.exceptionOrNull() is IllegalArgumentException)
            }
        } finally {client.release()}
        val observed=NavigationObservation(ai.pleos.playground.navi.constants.NavigationStatus.ROUTE_DRIVE,
            ai.pleos.playground.navi.constants.NaviMode.ROUTE_GUIDING,false,true,true,true)
        assertTrue(observed.oemGuidanceReported);assertTrue(observed.activeFlagConflict);assertEquals(false,observed.isRouting)
        assertTrue(observed.copy(isRouting=true).oemGuidanceReported)
        assertFalse("A true provider flag must not be relabeled conflicting",observed.copy(isRouting=true).activeFlagConflict)
        assertFalse("Wrong destination cannot become an OEM guidance observation",observed.copy(targetMatches=false).oemGuidanceReported)
        assertFalse("Unverified/missing/reversed waypoint order cannot become an observation",observed.copy(orderMatches=false).oemGuidanceReported)
        assertFalse("Late invalidated epoch cannot become an observation",observed.copy(requestCurrent=false).oemGuidanceReported)
        assertFalse("Search alone is not guidance",observed.copy(status=ai.pleos.playground.navi.constants.NavigationStatus.FREE_DRIVE).oemGuidanceReported)
        assertFalse("Route status alone is not guidance",observed.copy(mode=ai.pleos.playground.navi.constants.NaviMode.SAFE_GUIDING).oemGuidanceReported)
    }
    fun testActiveMatchingRouteOnlyAndLateEpochRejection() {
        val original=instrumentation.targetContext.assets.open("packs/01-city-story.json").use {PackCodec.decode(PackCodec.read(it))}
        val first=original.stops.first();val last=original.stops.last()
        val middle=first.copy(id="synthetic-middle",latitude=first.latitude+0.005)
        val pack=original.copy(stops=listOf(first,middle,last))
        val remaining=remainingNavigationPack(pack,setOf(first.id,middle.id))!!
        assertEquals(pack.key,remaining.key);assertEquals(listOf(last.id),remaining.stops.map {it.id})
        assertNull("All-complete courses must not send an empty or backwards route",remainingNavigationPack(pack,pack.stops.map {it.id}.toSet()))
        assertEquals(pack.stops,remainingNavigationPack(pack,emptySet())!!.stops)

        fun via(stop: Stop,seconds: Int,meters: Int)=WaypointInfo(name=stop.name,address="",latitude=stop.latitude,longitude=stop.longitude,
            remainDistance=meters,remainTime=seconds,poiId="",poiSubId=null)
        val target=DestinationInfo(latitude=last.latitude,longitude=last.longitude,name=last.name,address="",remainDistance=1000,remainTime=120,tollFare=0,poiId="",poiSubId=null)
        val waypoints=listOf(via(first,60,500),via(middle,90,750))
        assertNotNull("The provider's explicit empty waypoint list verifies the remaining destination",verifiedNavigationReadback(remaining,true,true,target,emptyList(),100,100))
        assertNull("No waypoint callback must not be assumed to mean no old waypoints",verifiedNavigationReadback(remaining,true,true,target,null,100,100))

        val matched=verifiedNavigationReadback(pack,true,true,target,waypoints,100,100)
        assertNotNull("Current active matching destination and ordered waypoints must be accepted",matched)
        assertEquals(listOf(first.id,middle.id,last.id),matched!!.legs.map {it.stopId})
        assertNull("Search started without an active route is not confirmation",verifiedNavigationReadback(pack,false,true,target,waypoints,100,100))
        assertNull("Another destination is not this selected course",verifiedNavigationReadback(pack,true,true,target.copy(latitude=last.latitude+0.01),waypoints,100,100))
        assertNull("Reversed waypoint order is not this selected course",verifiedNavigationReadback(pack,true,true,target,waypoints.reversed(),100,100))
        assertNull("Late data from an invalidated client epoch must be ignored",verifiedNavigationReadback(pack,true,false,target,waypoints,100,100))
    }
    /** Real lifecycle/selection/timer path, isolated records; no route or location injection. */
    fun testChangingSelectionInvalidatesPendingNavigation() {
        val base=instrumentation.targetContext
        val id="navigation-selection-"+java.util.UUID.randomUUID()
        val dir=java.io.File(base.cacheDir,id).apply{mkdirs()}
        val isolated=object: android.content.ContextWrapper(base) {
            override fun getApplicationContext(): android.content.Context=this
            override fun getFilesDir()=java.io.File(dir,"files").apply{mkdirs()}
            override fun getNoBackupFilesDir()=java.io.File(dir,"no-backup").apply{mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences("$id-$name",mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences("$id-$name")
        }
        fun originals(): String {
            val progress=ProgressStore(base)
            return PackRepository(base).list().sortedBy{it.key}.joinToString {it.key+progress.read(it).sorted().toString()}+VisitedPlaces(base).list().toString()
        }
        val before=originals();lateinit var controller: WegoController
        instrumentation.runOnMainSync {controller=WegoController(isolated,base.applicationContext);controller.setVisible(true)}
        try {
            val until=android.os.SystemClock.uptimeMillis()+12000
            while(!controller.state.setupAllowed && android.os.SystemClock.uptimeMillis()<until)Thread.sleep(100)
            instrumentation.runOnMainSync {
                assertTrue(controller.state.setupAllowed)
                val first=controller.state.packs.first {it.stops.size==3}.key;val second=controller.state.packs.first {it.key!=first}.key
                controller.refresh()
                controller.refresh()
                controller.select(first)
                assertEquals("Repeated unchanged refreshes must keep displayed courses selectable",first,controller.state.selectedKey)
                controller.select(second)
                assertEquals("Switching back must also work",second,controller.state.selectedKey)
                val pack=controller.state.packs.first {it.key==first}
                assertTrue(ProgressStore(isolated).save(pack,pack.stops.map {it.id}.toSet()))
                controller.select(first)
                val complete=controller.state.completed
                controller.requestNavigation(wholeCourse=true);assertTrue(controller.state.navigationBusy)
                val clientField=NavigationCoordinator::class.java.getDeclaredField("client").apply {isAccessible=true}
                val requestField=NavigationClient::class.java.getDeclaredField("requested").apply {isAccessible=true}
                val client=clientField.get(controller.navigationCoordinator)
                assertEquals("Whole-course departure must retain every completed stop in order",pack.stops,
                    (requestField.get(client) as DrivePack).stops)
                assertEquals(complete,controller.state.completed);assertFalse(controller.state.active)
                assertFalse(controller.state.locationConsented)
                controller.requestNavigation(wholeCourse=true)
                assertSame("Repeated departure while busy must not replace the pending request",client,clientField.get(controller.navigationCoordinator))
                // Invalidate before initialize's posted connection can send a route.
                controller.select(second)
                assertFalse(controller.state.navigationBusy);assertEquals(NavigationPhase.IDLE,controller.state.navigationPhase)
                assertNull(controller.state.navigationObservation)
                controller.requestNavigation();assertTrue(controller.state.navigationBusy)
                controller.refresh(first)
                assertFalse(controller.state.navigationBusy);assertEquals(NavigationPhase.IDLE,controller.state.navigationPhase)
                assertEquals(first,controller.state.selectedKey)
                val safeState=controller.state
                val stateField=WegoController::class.java.getDeclaredField("journeyState\$delegate").apply {isAccessible=true}
                @Suppress("UNCHECKED_CAST")
                val mutable=stateField.get(controller) as androidx.compose.runtime.MutableState<WegoState>
                val privatePack=pack.copy(source=CoursesRepository.SOURCE)
                mutable.value=safeState.copy(packs=listOf(privatePack),selectedKey=privatePack.key)
                controller.requestNavigation(wholeCourse=true)
                assertFalse("Whole-course cannot bypass account authority",controller.state.navigationBusy)
                assertNull(clientField.get(controller.navigationCoordinator));assertEquals("차량 연결을 확인해 주세요",controller.state.error)
                assertEquals(complete,ProgressStore(isolated).read(pack))
                mutable.value=safeState
            }
            // The actual old 15-second callbacks run; neither may fail the new selection.
            Thread.sleep(16000);instrumentation.waitForIdleSync()
            assertNull(controller.state.error);assertFalse(controller.state.navigationBusy)
            assertEquals(NavigationPhase.IDLE,controller.state.navigationPhase)
            assertNull(controller.state.navigationObservation)
        } finally {
            instrumentation.runOnMainSync {controller.close()}
            assertEquals("Selection regression must preserve user records",before,originals())
        }
    }

}
