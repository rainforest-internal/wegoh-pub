package io.wegoh.app

import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.SystemClock
import android.test.InstrumentationTestCase
import io.wegoh.vehiclesmoke.BuildConfig
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Real provider reads in an isolated QA application; never a product grant or control test. */
@Suppress("DEPRECATION")
class VehicleReadOnlySdkTest: InstrumentationTestCase() {
    private val report=JSONObject().put("scope","isolated-read-only-sdk-observation")
        .put("expectedReadPermissions",BuildConfig.EXPECT_READ_PERMISSIONS)
        .put("setterCalls",0).put("safetyScore",JSONObject.NULL)
        .put("providerPermissionErrorClassified",false)

    fun testActualReadOnlyCallbacks() {
        var activity: VehicleReadOnlyQaActivity?=null
        var port: VehicleHardwareSdkAdapter?=null
        var reader: VehicleTelemetryReader?=null
        var passed=false
        try {
            val context=instrumentation.targetContext
            assertEquals("Only the isolated diagnostic package may run this probe","io.wegoh.vehiclesmoke",context.packageName)
            activity=instrumentation.startActivitySync(Intent().setClassName(context.packageName,
                VehicleReadOnlyQaActivity::class.java.name).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as VehicleReadOnlyQaActivity
            val host=activity
            assertTrue("CarUx callback unavailable",host.uxObserved.await(10,TimeUnit.SECONDS))
            report.put("carUxKnown",host.uxKnown).put("carUxUnrestricted",host.unrestricted)
                .put("carUxActiveRestrictions",host.activeRestrictions ?: JSONObject.NULL).put("activityResumed",host.resumed)
            assertTrue("Unknown/restricted/background state blocks SDK probe",
                host.uxKnown && host.unrestricted && host.activeRestrictions==0 && host.resumed)
            val statuses=JSONObject()
            for (permission in listOf("CAR_CLIMATE","CAR_DRIVE","CAR_ENERGY")) {
                val actual=context.packageManager.checkPermission("pleos.car.permission."+permission,context.packageName)==PackageManager.PERMISSION_GRANTED
                statuses.put(permission,actual)
                assertEquals("Manifest permission transition not observed: "+permission,BuildConfig.EXPECT_READ_PERMISSIONS,actual)
            }
            report.put("packageManagerReadPermissions",statuses)
            val sdk=onMain { VehicleHardwareSdkAdapter(context) };port=sdk
            val initialized=onMain { sdk.initialize() }
            report.put("initializeReturned",initialized is VehicleReply.Value)
            assertTrue("SDK initialization invocation failed; no service-ready inference",initialized is VehicleReply.Value)
            val lane=AndroidVehicleOperationLane()
            val scope=VehicleTelemetryReadScope("isolated-qa","isolated-qa-device","root-leased-local-sdk-read",1,
                SystemClock.elapsedRealtime()+30_000)
            val samplesReader=onMain {
                VehicleTelemetryReader(sdk,lane,{
                    VehicleTelemetryReadAuthority(
                        if(host.uxKnown && host.unrestricted && host.activeRestrictions==0)scope else null,
                        host.resumed,false)
                })
            };reader=samplesReader
            val completed=CountDownLatch(1)
            val received=AtomicReference<VehicleTelemetrySnapshot>()
            onMain { samplesReader.read(scope) { received.set(it);completed.countDown() } }
            assertTrue("Typed telemetry watchdog expired",completed.await(12,TimeUnit.SECONDS))
            val snapshot=received.get()
            val samples=JSONArray()
            for ((signal,sample) in snapshot.samples) {
                samples.put(JSONObject().put("signal",signal.name).put("quality",sample.quality.name)
                    .put("valuePresent",sample.value!=null).put("failure",sample.failure?.name ?: JSONObject.NULL)
                    .put("receivedAtElapsedMillis",sample.receivedAtElapsedMillis)
                    .put("capturedAtMillis",sample.capturedAtMillis ?: JSONObject.NULL).put("source",sample.source))
                assertNull("Receipt time must not be fabricated as capture time",sample.capturedAtMillis)
            }
            report.put("telemetry",samples)
            val available=snapshot.samples.values.count { it.quality==VehicleSampleQuality.AVAILABLE && it.value!=null }
            report.put("availableTelemetryCount",available)
            assertNull(snapshot.safetyScore)
            if (BuildConfig.EXPECT_READ_PERMISSIONS) {
                // A positive requires actual provider data, not just a passed API invocation.
                assertTrue("No supported valid getter callback; preserve failed-positive",available>0)
                val at=SystemClock.elapsedRealtime()
                Thread.sleep(20)
                val aged=snapshot.at(SystemClock.elapsedRealtime(),0)
                assertTrue(aged.samples.values.none { it.quality==VehicleSampleQuality.AVAILABLE })
                report.put("actualReceiptAgingChecked",SystemClock.elapsedRealtime()>=at+20)
                val climate=JSONArray()
                for(property in listOf(ClimateProperty.TARGET_CELSIUS,ClimateProperty.FAN_LEVEL,ClimateProperty.GLOBAL_POWER)) {
                    val cap=observe<ClimateCapability>(host) { callback -> sdk.climateCapability(property,callback) }
                    val row=JSONObject().put("property",property.name).put("capability",replyName(cap))
                    if(cap is VehicleReply.Value) {
                        row.put("access",cap.value.access.name).put("singleSeatCount",cap.value.areas.size)
                        if(cap.value.access in setOf(VehicleAccess.READ,VehicleAccess.READ_WRITE)) {
                            val seat=cap.value.areas.firstOrNull()
                            if(seat!=null) {
                                val target=when(property) {
                                    ClimateProperty.TARGET_CELSIUS->ClimateTarget.Celsius(seat,cap.value.bounds[seat]?.minimum?.toFloat() ?: 0f)
                                    ClimateProperty.FAN_LEVEL->ClimateTarget.Fan(seat,cap.value.bounds[seat]?.minimum?.toInt() ?: 0)
                                    ClimateProperty.GLOBAL_POWER->ClimateTarget.GlobalPower(seat,false)
                                    else->error("Unsupported smoke property")
                                }
                                val reading=observe<ClimateReading>(host) { callback -> sdk.readClimate(target,cap.value,callback) }
                                row.put("getter",replyName(reading))
                                row.put("valuePresent",reading is VehicleReply.Value && when(val value=reading.value) {
                                    is ClimateReading.Celsius->value.value!=null
                                    is ClimateReading.Fan->value.value!=null
                                    is ClimateReading.GlobalPower->value.enabled!=null
                                    else->false
                                })
                            }
                        }
                    }
                    climate.put(row)
                }
                report.put("hvacCapabilities",climate)

            } else {
                assertEquals("Read data exposed despite absent requested normal permissions",0,available)
                // Explicit negative diagnostic call, not a production unsupported-feature invocation.
                val deniedGetter=observe<VehicleTelemetryValue?>(host) { callback ->
                    sdk.readTelemetry(VehicleTelemetrySignal.BRAKE_PRESSED,callback)
                }
                report.put("deniedDirectBrakeGetter",replyName(deniedGetter))
                assertTrue("Provider getter unexpectedly supplied data without declared read permission",
                    deniedGetter is VehicleReply.Failed)
            }
            onMain { samplesReader.close();sdk.close() };reader=null;port=null
            report.put("ownerClosed",true)
            passed=true
        } finally {
            onMain { reader?.close();port?.close();activity?.finish() }
            report.put("actualSuccess",passed).put("completedAtElapsedMillis",SystemClock.elapsedRealtime())
            instrumentation.sendStatus(0,Bundle().apply { putString("vehicleReadOnlyReport",report.toString()) })
        }
    }

    private fun <T> observe(host: VehicleReadOnlyQaActivity,start: ((VehicleReply<T>)->Unit)->Unit): VehicleReply<T> {
        val done=CountDownLatch(1)
        val once=AtomicBoolean(false)
        val result=AtomicReference<VehicleReply<T>>()
        onMain {
            check(host.resumed && host.uxKnown && host.unrestricted && host.activeRestrictions==0)
            start { reply -> if(once.compareAndSet(false,true)) { result.set(reply);done.countDown() } }
        }
        assertTrue("Provider read callback watchdog expired",done.await(8,TimeUnit.SECONDS))
        assertTrue("CarUx/foreground lost during read",host.resumed && host.uxKnown && host.unrestricted && host.activeRestrictions==0)
        return result.get()
    }
    private fun replyName(reply: VehicleReply<*>)=when(reply) {
        is VehicleReply.Value -> "callback-value"
        is VehicleReply.Failed -> "callback-failure:"+reply.reason.name
    }
    private fun <T> onMain(block: ()->T): T {
        val value=AtomicReference<T>()
        val failure=AtomicReference<Throwable>()
        instrumentation.runOnMainSync { try { value.set(block()) } catch(error: Throwable) { failure.set(error) } }
        failure.get()?.let { throw it }
        return value.get()
    }
}
