package io.wegoh.app

import android.content.Intent
import android.test.InstrumentationTestCase

/** Real SDK smoke check. The host script supplies virtual GPS; no SDK callbacks are mocked. */
@Suppress("DEPRECATION")
class SdkSmokeTests : InstrumentationTestCase() {
    private fun waitFor(label: String, seconds: Int, predicate: () -> Boolean) {
        val end = System.currentTimeMillis() + seconds * 1000
        while (System.currentTimeMillis() < end) {
            var result = false
            instrumentation.runOnMainSync { result = predicate() }
            if (result) return
            Thread.sleep(250)
        }
        fail("Timed out: $label")
    }
    fun testReleasedNavigationIgnoresLateConnection() {
        val reports=java.util.Collections.synchronizedList(mutableListOf<String>())
        val overviews=java.util.concurrent.atomic.AtomicInteger()
        val phases=java.util.concurrent.atomic.AtomicInteger()
        val observations=java.util.concurrent.atomic.AtomicInteger()
        val pack=instrumentation.targetContext.assets.open("packs/01-city-story.json").use {PackCodec.decode(PackCodec.read(it))}
        instrumentation.runOnMainSync {
            val client=NavigationClient(instrumentation.targetContext,{reports.add(it)},{overviews.incrementAndGet()},onPhase={phases.incrementAndGet()},onObservation={observations.incrementAndGet()})
            try {client.request(pack)} finally {client.release()}
        }
        // The real initialize callback posts to the main queue. Release happens before that
        // queue can run, so neither a late connection nor its failure may publish a route/status.
        val afterRelease=overviews.get();val phasesAfterRelease=phases.get();val observationsAfterRelease=observations.get()
        Thread.sleep(2000)
        instrumentation.waitForIdleSync()
        assertTrue("Released navigation must not publish late status or send a route",reports.isEmpty())
        assertEquals("Released navigation must not replace cleared overview",afterRelease,overviews.get())
        assertEquals("Released navigation must not publish late typed phase",phasesAfterRelease,phases.get())
        assertEquals("Released navigation must not publish late provider observations",observationsAfterRelease,observations.get())
    }
    fun testReleasedSdkCallbacksHaveNoEffects() {
        val reports=mutableListOf<String>();var locations=0;var overviews=0;var observations=0;val phases=mutableListOf<NavigationPhase>()
        instrumentation.runOnMainSync {
            val navigation=NavigationClient(instrumentation.targetContext,{reports.add(it)},{overviews++},onPhase={phases.add(it)},onObservation={observations++})
            val navListener=NavigationClient::class.java.getDeclaredField("listener").apply {isAccessible=true}
                .get(navigation) as ai.pleos.playground.navi.helper.listener.NaviHelperEventListener
            navListener.onError(ai.pleos.playground.navi.constants.NaviErrorCode.values().first())
            assertFalse("Listener fixture must exercise a real client callback",reports.isEmpty())
            navigation.release();reports.clear();phases.clear();val cleared=overviews;val observationsAfterRelease=observations
            navListener.onError(ai.pleos.playground.navi.constants.NaviErrorCode.values().first())
            navListener.onDestinationChanged();navListener.onRouteCancelled();navListener.onRoutingCompleted()
            navListener.onNavigationStatus(ai.pleos.playground.navi.constants.NavigationStatus.ROUTE_DRIVE)
            assertTrue(reports.isEmpty());assertTrue(phases.isEmpty());assertEquals(cleared,overviews)
            assertEquals(observationsAfterRelease,observations)
            val location=LocationClient(instrumentation.targetContext,{locations++},{reports.add(it.name)})
            val listener=LocationClient::class.java.getDeclaredField("listener").apply {isAccessible=true}
                .get(location) as ai.pleos.playground.location.fused.listener.FusedLocationListener
            try {location.start()} finally {location.release()}
            reports.clear();val last=locations
            // Deliberately delayed synthetic callback delivery, separate from real SDK smoke.
            listener.onChanged(null);listener.onError(IllegalStateException("SYNTHETIC_LATE_CALLBACK"))
            assertEquals(last,locations);assertTrue(reports.isEmpty())
            try {location.start();fail("Released SDK instance cannot be reused")}catch(expected: IllegalStateException) { }
        }
    }
    fun testRealLocationAndNavigation() = runRealLocationAndNavigation(false)
    /** Existing Studio input shape has coordinates/place metadata but no SDK POI identity.
     * This observes provider acceptance; it does not assert undocumented empty-ID support. */
    fun testRealCoordinateOnlyLocationAndNavigation() = runRealLocationAndNavigation(true)
    /** New delegation contract; historic strict-ACTIVE trials remain distinct failures. */
    fun testRealOemDelegationObservation() = runRealLocationAndNavigation(false,true)
    private fun runRealLocationAndNavigation(coordinateOnly: Boolean,delegationObservation: Boolean=false) {
        val activity = instrumentation.startActivitySync(Intent(instrumentation.targetContext, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val base=instrumentation.targetContext
        val id="sdk-runtime-"+java.util.UUID.randomUUID()
        val dir=java.io.File(base.cacheDir,id).apply {mkdirs()}
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
        val before=originals()
        lateinit var controller: WegoController
        instrumentation.runOnMainSync {controller=WegoController(isolated,base.applicationContext);controller.setVisible(true)}
        try {
            waitFor("CarUxRestrictions", 12) { controller.state.setupAllowed }
            val key=if(coordinateOnly) {
                val json=org.json.JSONObject(base.assets.open("packs/01-city-story.json").use {PackCodec.read(it)})
                json.put("id","sdk-coordinate-only")
                val stops=json.getJSONArray("stops")
                for(i in 0 until stops.length())stops.getJSONObject(i).remove("poiId")
                // Only this UUID-isolated encrypted repository receives the new object.
                controller.repository.importPack(json.toString().byteInputStream()).key
            } else "city-story@1"
            instrumentation.runOnMainSync {
                assertTrue(controller.consentLocation())
                controller.select(key)
                controller.reset()
                controller.begin(key)
            }
            waitFor("session started", 10) { controller.state.active || controller.state.error != null }
            assertNull("Session error", controller.state.error)
            assertTrue(controller.state.active)
            waitFor("real FusedLocation event", 35) { controller.state.completed.contains("gangnam") }
            val count = controller.state.history.takeWhile {it!="SESSION_START"}.count { it.startsWith("EVENT_EXECUTED ") }
            assertEquals(1, count)
            instrumentation.runOnMainSync { controller.requestNavigation() }
            if(delegationObservation) {
                waitFor("current OEM guidance report with matching requested identity",25) {
                    controller.state.navigationPhase in setOf(NavigationPhase.OEM_GUIDANCE_REPORTED,NavigationPhase.ACTIVE) &&
                        controller.state.navigationObservation?.oemGuidanceReported==true
                }
                val observation=controller.state.navigationObservation!!
                assertEquals(ai.pleos.playground.navi.constants.NavigationStatus.ROUTE_DRIVE,observation.status)
                assertEquals(ai.pleos.playground.navi.constants.NaviMode.ROUTE_GUIDING,observation.mode)
                assertNotNull("Actual route-state callback must preserve its raw flag",observation.isRouting)
                val expectedPhase=if(observation.isRouting==true)NavigationPhase.ACTIVE else NavigationPhase.OEM_GUIDANCE_REPORTED
                assertEquals(expectedPhase,controller.state.navigationPhase)
                assertEquals(observation.isRouting==false,observation.activeFlagConflict)
                assertTrue(observation.targetMatches && observation.orderMatches && observation.requestCurrent)
                if(observation.isRouting==false)assertNull("Conflicting provider flag must not publish a verified overview",controller.state.navigationOverview)
                assertFalse(controller.state.navigationBusy)
                assertNull(controller.state.error)
                // The unchanged15-second deadline is for missing response, not a received
                // truthful provider observation. It must not later reclassify this as no response.
                Thread.sleep(16000);instrumentation.waitForIdleSync()
                assertEquals(expectedPhase,controller.state.navigationPhase)
                assertEquals(observation,controller.state.navigationObservation)
                assertNull(controller.state.error)
                if(observation.isRouting==false)assertNull(controller.state.navigationOverview)
                assertEquals("Repeated real location updates must not execute another stop",1,controller.state.completed.size)
                java.io.File(base.cacheDir,"sdk-delegation-observation.json").writeText(org.json.JSONObject()
                    .put("recordedAtMillis",System.currentTimeMillis()).put("virtualGps",true)
                    .put("status",observation.status!!.name).put("mode",observation.mode!!.name)
                    .put("isRouting",observation.isRouting).put("activeFlagConflict",observation.activeFlagConflict)
                    .put("targetMatches",observation.targetMatches).put("orderMatches",observation.orderMatches)
                    .put("phase",controller.state.navigationPhase.name).put("verifiedActive",expectedPhase==NavigationPhase.ACTIVE)
                    .put("verifiedOverviewPublished",controller.state.navigationOverview!=null).put("oldDeadlineDidNotMisclassifyResponse",true).toString(2))
                return
            }
            waitFor("NaviHelper routing callback", 25) {
                controller.state.navigationPhase==NavigationPhase.ACTIVE
            }
            assertNull("Navigation error after verified active route",controller.state.error)
            // Provider read delivery is observed, never replaced with mock estimates.
            val until=System.currentTimeMillis()+5000
            while(System.currentTimeMillis()<until && controller.state.navigationOverview==null)Thread.sleep(100)
            val summary=controller.state.navigationOverview
            val record=org.json.JSONObject().put("recordedAtMillis",System.currentTimeMillis()).put("virtualGps",true).put("providerOverviewReceived",summary!=null)
                .put("matchedStops",summary?.legs?.size ?: 0).put("trafficSections",summary?.traffic?.size ?: 0)
            java.io.File(base.cacheDir,"sdk-navigation-overview.json").writeText(record.toString(2))
        } finally {
            val snapshot=controller.state
            java.io.File(base.cacheDir,"sdk-fused-state.json").writeText(org.json.JSONObject().put("recordedAtMillis",System.currentTimeMillis()).put("virtualGps",true)
                .put("receivedData",snapshot.location=="위치 수신").put("locationStatus",snapshot.location)
                .put("error",snapshot.error).put("active",snapshot.active).put("completedCount",snapshot.completed.size).toString(2))
            instrumentation.runOnMainSync {controller.close()}
            assertNull("Closing the client must clear current provider observations",controller.state.navigationObservation)
            assertEquals("SDK smoke must preserve the user's pack progress and visit records",before,originals())
        }
    }
}
