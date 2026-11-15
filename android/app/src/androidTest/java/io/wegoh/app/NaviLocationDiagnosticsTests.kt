package io.wegoh.app

import ai.pleos.playground.navi.constants.NaviErrorCode
import ai.pleos.playground.navi.constants.NavigationStatus
import ai.pleos.playground.navi.data.CurrentLocationInfo
import ai.pleos.playground.navi.data.RouteStateInfo
import ai.pleos.playground.navi.helper.NaviHelper
import ai.pleos.playground.navi.helper.listener.NaviHelperEventListener
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

@Suppress("DEPRECATION")
class NaviLocationDiagnosticsTests: InstrumentationTestCase() {
    fun testExplicitCurrentLocationObservationOnly() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        assertEquals("navi-location-only",args.getString("diagnosticConsent"))
        assertTrue(BuildConfig.DEBUG)
        val context=instrumentation.targetContext
        assertEquals("1",Runtime.getRuntime().exec(arrayOf("getprop","ro.kernel.qemu")).inputStream.bufferedReader().use {it.readText().trim()})
        assertEquals(10,android.os.Process.myUid()/100000)
        assertEquals(PackageManager.PERMISSION_GRANTED,context.checkSelfPermission("pleos.car.permission.NAVI_ROUTE"))
        fun sessionRunning()=context.getSystemService(android.app.ActivityManager::class.java).getRunningServices(100)
            .any {it.service.className==SessionService::class.java.name}
        assertFalse("Use the diagnostic without a running journey service",sessionRunning())
        fun records()=context.noBackupFilesDir.walkTopDown().filter {it.isFile}.associate {
            it.relativeTo(context.noBackupFilesDir).path to MessageDigest.getInstance("SHA-256").digest(it.readBytes()).toList()
        }
        val before=records();val lock=Any();val accepting=AtomicBoolean(true)
        val connected=AtomicBoolean(false);val registered=AtomicBoolean(false);val connection=CountDownLatch(1)
        val helper=NaviHelper(context.applicationContext);val main=Handler(Looper.getMainLooper())
        var querySeq=0;var callbackSeq=0;var queryFailures=0;var sdkErrors=0;var observationTimeouts=0
        var waitingForObservation=false;var timeoutRecorded=false;var stopQueries=false
        var lastQueryElapsed: Long?=null;var lastLoggedElapsed: Long?=null
        var callbacksWithoutLocalWait=0;var lateCallbacks=0;var invalidCoordinates=0
        var coordinateChanges=0;var previous: Pair<Double,Double>?=null
        val positions=mutableSetOf<Pair<Double,Double>>();val routeStates=JSONArray()
        fun log(event: String,data: JSONObject) {Log.d("WegoH-NaviLocation",event+" "+data.toString())}
        val listener=object: NaviHelperEventListener {
            override fun onCurrentLocationInfo(info: CurrentLocationInfo) {
                val wall=System.currentTimeMillis();val elapsed=SystemClock.elapsedRealtime()
                synchronized(lock) {
                    if(!accepting.get()){lateCallbacks++;return}
                    callbackSeq++
                    val wasWaiting=waitingForObservation
                    if(!wasWaiting)callbacksWithoutLocalWait++
                    val afterTimeout=timeoutRecorded
                    waitingForObservation=false;timeoutRecorded=false
                    val valid=info.latitude.isFinite() && info.longitude.isFinite() && info.latitude in -90.0..90.0 && info.longitude in -180.0..180.0
                    if(valid) {
                        val position=info.latitude to info.longitude
                        if(previous!=null && previous!=position)coordinateChanges++
                        previous=position;positions.add(position)
                    } else invalidCoordinates++
                    if(lastLoggedElapsed?.let {elapsed-it<1000}==true)return
                    lastLoggedElapsed=elapsed
                    log("navi.location.callback: received",JSONObject().put("callback_seq",callbackSeq)
                        .put("last_query_seq",querySeq).put("elapsed_since_last_query_ms",lastQueryElapsed?.let {elapsed-it} ?: JSONObject.NULL)
                        .put("query_callback_correlation","not_provided_by_sdk").put("local_wait_was_active",wasWaiting)
                        .put("after_observation_timeout",afterTimeout).put("received_at_ms",wall).put("received_elapsed_ms",elapsed)
                        .put("source","NaviHelper.CurrentLocationInfo").put("coordinates_valid",valid)
                        .put("latitude",if(info.latitude.isFinite())info.latitude else JSONObject.NULL)
                        .put("longitude",if(info.longitude.isFinite())info.longitude else JSONObject.NULL)
                        .put("heading",if(info.heading.isFinite())info.heading else JSONObject.NULL)
                        .put("route_id",info.routeId).put("current_route_index",info.currentRouteIndex ?: JSONObject.NULL))
                }
            }
            override fun onRouteStateInfo(info: RouteStateInfo) {synchronized(lock) {
                if(!accepting.get())return
                val state=JSONObject().put("received_at_ms",System.currentTimeMillis()).put("received_elapsed_ms",SystemClock.elapsedRealtime())
                    .put("navi_mode",info.naviMode.name).put("is_routing",info.isRouting)
                routeStates.put(state);log("navi.route.state: received",state)
            }}
            override fun onNavigationStatus(status: NavigationStatus) {if(accepting.get())
                log("navi.route.status: received",JSONObject().put("status",status.name).put("received_elapsed_ms",SystemClock.elapsedRealtime()))}
            override fun onError(code: NaviErrorCode) {synchronized(lock) {
                if(accepting.get()){sdkErrors++;stopQueries=true;log("navi.location.query: failed",JSONObject().put("reason","sdk_error_unmatched").put("code",code.name))}
            }}
        }
        val startedAt=System.currentTimeMillis()
        try {
            instrumentation.runOnMainSync {helper.initialize(onConnected={main.post {
                if(!accepting.get())return@post
                runCatching {helper.addListener(listener);registered.set(true);connected.set(true)}
                    .onFailure {log("navi.location.connection: failed",JSONObject().put("reason",it.javaClass.simpleName))}
                connection.countDown()
            }},onFailed={
                log("navi.location.connection: failed",JSONObject().put("reason","initialization_failed"));connection.countDown()
            })}
            assertTrue("NaviHelper connection callback missing",connection.await(10,TimeUnit.SECONDS))
            assertTrue("NaviHelper connection failed",connected.get())
            instrumentation.runOnMainSync {runCatching {helper.getRouteStateInfo()}.onFailure {
                log("navi.route.state: failed",JSONObject().put("reason",it.javaClass.simpleName))}}
            val until=SystemClock.elapsedRealtime()+60000
            while(SystemClock.elapsedRealtime()<until) {
                instrumentation.runOnMainSync {
                    val elapsed=SystemClock.elapsedRealtime()
                    val issue=synchronized(lock) {
                        if(waitingForObservation && !timeoutRecorded && lastQueryElapsed?.let {elapsed-it>=3000}==true) {
                            observationTimeouts++;timeoutRecorded=true
                            log("navi.location.query: failed",JSONObject().put("reason","no_location_observation_within_3000ms")
                                .put("last_query_seq",querySeq).put("query_callback_correlation","unconfirmed"))
                        }
                        if(waitingForObservation || stopQueries)false else {
                            querySeq++;lastQueryElapsed=elapsed;waitingForObservation=true
                            log("navi.location.query: sent",JSONObject().put("query_seq",querySeq).put("requested_at_ms",System.currentTimeMillis()).put("requested_elapsed_ms",elapsed));true
                        }
                    }
                    if(issue)runCatching {helper.getCurrentLocationInfo()}.onFailure {synchronized(lock) {
                        queryFailures++;stopQueries=true
                        log("navi.location.query: failed",JSONObject().put("reason",it.javaClass.simpleName).put("query_seq",querySeq))
                    }}
                }
                Thread.sleep(1000)
            }
            instrumentation.runOnMainSync {runCatching {helper.getRouteStateInfo()}}
            Thread.sleep(300)
        } finally {
            accepting.set(false)
            instrumentation.runOnMainSync {if(registered.get())runCatching {helper.removeListener(listener)};runCatching {helper.release()}}
            Thread.sleep(1500)
            synchronized(lock) {
                File(context.cacheDir,"navi-location-diagnostic.json").writeText(JSONObject().put("startedAtMillis",startedAt)
                    .put("finishedAtMillis",System.currentTimeMillis()).put("userId",android.os.Process.myUid()/100000)
                    .put("connectionEstablished",connected.get())
                    .put("queryCalls",querySeq).put("locationCallbacks",callbackSeq).put("coordinateChanges",coordinateChanges)
                    .put("distinctCoordinates",positions.size).put("invalidCoordinates",invalidCoordinates)
                    .put("callbacksWithoutLocalWait",callbacksWithoutLocalWait).put("observationTimeouts",observationTimeouts)
                    .put("queryFailures",queryFailures).put("sdkErrors",sdkErrors).put("lateLocationCallbacks",lateCallbacks)
                    .put("routeStates",routeStates).put("protectedRecordsUnchanged",before==records())
                    .put("sessionServicePresentAfter",sessionRunning())
                    .put("queryCallbackCorrelation","not_provided_by_sdk").put("sdkGenerationTimestamp","not_in_model")
                    .put("testPath","Read-only NaviHelper; no route/location writes, Controller or journey service start").toString(2))
            }
            assertEquals("The diagnostic must preserve protected records",before,records())
            assertFalse("The diagnostic must not start a journey service",sessionRunning())
        }
        assertTrue("No current-location callback observed",callbackSeq>0)
    }
}
