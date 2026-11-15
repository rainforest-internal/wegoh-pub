package io.wegoh.app.nativeauth

import android.os.SystemClock
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import android.util.Base64
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

class CommandReceiverConnectionTest : InstrumentationTestCase() {
    private fun awaitStage(connection: VehicleConnection, stage: VehicleConnection.Stage) {
        val deadline = SystemClock.elapsedRealtime() + 30_000
        while (connection.status().stage != stage && SystemClock.elapsedRealtime() < deadline) {
            Thread.sleep(30)
        }
        assertEquals(stage, connection.status().stage)
    }

    private fun readResult(operation: ((Result<CommandReceiver>) -> Unit) -> Unit): Result<CommandReceiver> {
        val response = AtomicReference<Result<CommandReceiver>>()
        val latch = CountDownLatch(1)
        operation { result -> response.set(result); latch.countDown() }
        assertTrue("Timed out waiting for vehicle receiver", latch.await(12, TimeUnit.SECONDS))
        return response.get()
    }

    fun testEnablingReceiverDoesNotRetainCachedDenial() {
        val args=(instrumentation as InstrumentationTestRunner).arguments
        val ca=String(Base64.decode(args.getString("ca"),Base64.DEFAULT),Charsets.US_ASCII)
        val profile="receiver_cache_"+UUID.randomUUID().toString().replace("-","").take(24)
        val connection=VehicleConnection.synthetic(instrumentation.targetContext,profile,
            args.getString("port")!!.toInt(),NativeDeviceIdentity.parseCertificates(ca).single())
        try {
            connection.setForeground(true);connection.setSetupAllowed(true)
            awaitStage(connection,VehicleConnection.Stage.READY)
            connection.start("Receiver cache integration")
            awaitStage(connection,VehicleConnection.Stage.CONNECTED)
            val before=readResult(connection::readCommandReceiver).getOrThrow()
            val paused=if(before.enabled)readResult {connection.setCommandReceiver(before,false,it)}.getOrThrow() else before
            val permissions=AtomicReference<FunctionalPermissions>();val permissionDone=CountDownLatch(1)
            connection.readFunctionalPermissions {result->permissions.set(result.getOrThrow());permissionDone.countDown()}
            assertTrue(permissionDone.await(12,TimeUnit.SECONDS))
            val denied=permissions.get();assertFalse(denied.allows(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE))
            val resumed=readResult {connection.setCommandReceiver(paused,true,it)}.getOrThrow()
            assertTrue(resumed.enabled)
            val field=connection.javaClass.getDeclaredField("functionalGate").apply {isAccessible=true}
            val gate=field.get(connection) as FunctionalPermissionGate
            val cached=gate.cached(denied.deviceId,denied.grantId,System.currentTimeMillis())
            assertTrue("Receiver enabled but next command still uses a cached consent denial",cached==null || cached.allows(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE))
            val fresh=AtomicReference<FunctionalPermissions>();val freshDone=CountDownLatch(1)
            connection.readFunctionalPermissions {result->fresh.set(result.getOrThrow());freshDone.countDown()}
            assertTrue(freshDone.await(12,TimeUnit.SECONDS))
            assertTrue(fresh.get().allows(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE))
        } finally {connection.close()}
    }

    fun testPausedReceiverCanBeEnabledOnTheSameVehicle() {
        val args = (instrumentation as InstrumentationTestRunner).arguments
        val ca = String(Base64.decode(args.getString("ca"), Base64.DEFAULT), Charsets.US_ASCII)
        val profile = "receiver_test_" + UUID.randomUUID().toString().replace("-", "").take(24)
        val connection = VehicleConnection.synthetic(instrumentation.targetContext, profile,
            args.getString("port")!!.toInt(), NativeDeviceIdentity.parseCertificates(ca).single())
        try {
            connection.setForeground(true)
            connection.setSetupAllowed(true)
            awaitStage(connection, VehicleConnection.Stage.READY)
            connection.start("Receiver integration")
            awaitStage(connection, VehicleConnection.Stage.CONNECTED)

            val before = readResult(connection::readCommandReceiver).getOrThrow()
            assertTrue(before.enabled)
            val paused = readResult { connection.setCommandReceiver(before, false, it) }.getOrThrow()
            assertFalse(paused.enabled)
            assertEquals(paused, readResult(connection::readCommandReceiver).getOrThrow())
            assertTrue(readResult { connection.setCommandReceiver(before, true, it) }.isFailure)
            assertEquals(paused, readResult(connection::readCommandReceiver).getOrThrow())
            val resumed = readResult { connection.setCommandReceiver(paused, true, it) }.getOrThrow()
            assertTrue(resumed.enabled)
            assertEquals(resumed, readResult(connection::readCommandReceiver).getOrThrow())
        } finally {
            connection.close()
        }
    }
}
