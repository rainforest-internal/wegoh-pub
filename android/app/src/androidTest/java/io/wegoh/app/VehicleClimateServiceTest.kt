package io.wegoh.app

import android.app.ActivityManager
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.test.InstrumentationTestCase

class VehicleClimateServiceTest: InstrumentationTestCase() {
    private fun field(owner: Any,name: String)=owner.javaClass.getDeclaredField(name).apply {isAccessible=true}
    private fun await(label: String,check: ()->Boolean) {
        val end=SystemClock.elapsedRealtime()+30_000
        while(SystemClock.elapsedRealtime()<end) {if(check())return;Thread.sleep(100)}
        fail(label)
    }
    fun testBoundReceiverReleasesExpiredAuthorityAndRestartsAfterFreshAuthorization() {
        val context=instrumentation.targetContext
        val activity=instrumentation.startActivitySync(Intent(context,VehicleClimateActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as VehicleClimateActivity
        val fixture=(context.applicationContext as WegoApplication).simulateApprovedReceiver()
        val service=fixture.service
        val intent=Intent(context,VehicleClimateService::class.java)
        try {
            instrumentation.runOnMainSync {context.startForegroundService(intent)}
            await("authorized receiver not active") {VehicleClimateService.active}
            var originalHost: Any?=null
            instrumentation.runOnMainSync {
                originalHost=field(service,"host").get(service)
                assertNotNull(originalHost)
                fixture.revision.set(null)
                // Polling rechecks the same authority that the expiry observer checks.
                (field(service,"poll").get(service) as Runnable).run()
                assertFalse(VehicleClimateService.active)
                assertNull("SDK owner must close while the service is still bound",field(service,"host").get(service))
                assertNull(field(service,"safety").get(service))
            }
            val manager=context.getSystemService(ActivityManager::class.java)
            assertFalse(manager.getRunningServices(100).any {
                it.service.className==VehicleClimateService::class.java.name && it.foreground
            })
            instrumentation.runOnMainSync {
                // A repeated start without renewed authorization must stay stopped.
                service.onStartCommand(intent,0,2)
                assertFalse(VehicleClimateService.active)
                assertNull(field(service,"host").get(service))
                // The fixture binding keeps this exact Service instance alive.
                fixture.revision.set(2L)
                context.startForegroundService(intent)
            }
            await("bound receiver did not restart after fresh authorization") {VehicleClimateService.active}
            instrumentation.runOnMainSync {
                assertTrue(VehicleClimateService.active)
                val replacement=field(service,"host").get(service)
                assertNotNull(replacement)
                assertNotSame("New authority needs a fresh SDK owner",originalHost,replacement)
                assertNotNull(field(service,"safety").get(service))
            }
            assertTrue(manager.getRunningServices(100).any {
                it.service.className==VehicleClimateService::class.java.name && it.foreground
            })
        } finally {
            instrumentation.runOnMainSync {context.stopService(intent);activity.finish()}
            fixture.close()
            await("receiver did not close") {!VehicleClimateService.active}
        }
    }
    fun testReceiverSurvivesScreenAndDriving() {
        val context=instrumentation.targetContext
        val activity=instrumentation.startActivitySync(Intent(context,VehicleClimateActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as VehicleClimateActivity
        val receiverFixture=(context.applicationContext as WegoApplication).simulateApprovedReceiver()
        var safety: ClimateCarSafety?=null
        try {
            instrumentation.runOnMainSync {
                safety=ClimateCarSafety(context) {}
                safety!!.setReceiverActive(true)
                context.startForegroundService(Intent(context,VehicleClimateService::class.java))
            }
            await("receiver not active") {VehicleClimateService.active}
            instrumentation.runOnMainSync {activity.finish()}
            await("activity not destroyed") {activity.isDestroyed}
            instrumentation.sendStatus(0,Bundle().apply {putString("stream","CLIMATE_BACKGROUND_READY\n")})
            await("actual driving restriction not observed") {safety?.snapshot()?.let {it.carUxKnown && !it.setupAllowed && !it.parked}==true}
            assertTrue(safety!!.snapshot().permitsReceiver())
            assertTrue(VehicleClimateService.active)
            val app=context.applicationContext as WegoApplication
            val limited=(app.controller.vehicleAccountConnection ?: app.vehicleConnection).climateSocial()
            try {
                try {limited.readOverview {};fail("receiver acquired social read access")}
                catch(_: IllegalArgumentException) {}
            } finally {limited.close()}
            val manager=context.getSystemService(ActivityManager::class.java)
            assertTrue(manager.getRunningServices(100).any {it.service.className==VehicleClimateService::class.java.name && it.foreground})
            instrumentation.sendStatus(0,Bundle().apply {putString("stream","CLIMATE_DRIVING_BACKGROUND_ACTIVE\n")})
        } finally {
            instrumentation.runOnMainSync {context.stopService(Intent(context,VehicleClimateService::class.java));safety?.close()}
            receiverFixture.close()
            await("receiver did not stop") {!VehicleClimateService.active}
        }
    }
}
