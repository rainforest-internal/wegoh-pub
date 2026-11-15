package io.wegoh.app

import android.content.Intent
import android.os.SystemClock
import android.test.InstrumentationTestCase
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

@Suppress("DEPRECATION")
class VehicleClimateSdkProbeTest: InstrumentationTestCase() {
    private fun <T> main(block: ()->T): T {
        val result=AtomicReference<T>();val error=AtomicReference<Throwable>()
        instrumentation.runOnMainSync {try {result.set(block())}catch(failure: Throwable){error.set(failure)}}
        error.get()?.let {throw it};return result.get()
    }
    private fun <T> reply(call: ((VehicleReply<T>)->Unit)->Unit): VehicleReply<T> {
        val latch=CountDownLatch(1);val result=AtomicReference<VehicleReply<T>>()
        main {call {result.set(it);latch.countDown()}}
        assertTrue("Actual Vehicle SDK callback did not arrive",latch.await(12,TimeUnit.SECONDS))
        return result.get()
    }
    fun testTemperatureAppliesAndRestoresActualProvider() {
        val context=instrumentation.targetContext
        val activity=instrumentation.startActivitySync(Intent(context,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as SafFrameworkHarnessActivity
        val sdk=main {VehicleHardwareSdkAdapter(context)}
        val report=JSONObject().put("scope","actual-product-temperature-setter-getter-controller").put("restored",false)
        var capability: ClimateCapability?=null;var original: Float?=null
        try {
            assertTrue(main {sdk.initialize()} is VehicleReply.Value)
            capability=(reply<ClimateCapability> {sdk.climateCapability(ClimateProperty.TARGET_CELSIUS,it)} as VehicleReply.Value).value
            val target=ClimateTarget.Celsius(VehicleSeat.ROW_1_LEFT,22.5f)
            original=((reply<ClimateReading> {sdk.readClimate(target,capability!!,it)} as VehicleReply.Value).value as ClimateReading.Celsius).value
            assertNotNull("Original temperature required before any write",original)
            assertTrue("Actual temperature setter failed",reply<Unit> {sdk.setClimate(target,capability!!,it)} is VehicleReply.Value)
            val reading=(reply<ClimateReading> {sdk.readClimate(target,capability!!,it)} as VehicleReply.Value).value as ClimateReading.Celsius
            assertEquals("Independent getter must match requested temperature",22.5f,reading.value)
            report.put("originalTemperature",original).put("temperatureReadback",reading.value)
            File(context.filesDir,"vehicle-climate-sdk-temperature.json").writeText(report.toString(2))
            Thread.sleep(3000)
        } finally {
            if(original!=null && capability!=null) {
                val target=ClimateTarget.Celsius(VehicleSeat.ROW_1_LEFT,original!!)
                reply<Unit> {sdk.setClimate(target,capability!!,it)}
                val restored=reply<ClimateReading> {sdk.readClimate(target,capability!!,it)}
                report.put("restored",restored is VehicleReply.Value && (restored.value as? ClimateReading.Celsius)?.value==original)
            }
            File(context.filesDir,"vehicle-climate-sdk-temperature.json").writeText(report.toString(2))
            main {sdk.close();activity.finish()}
            assertTrue("Actual temperature must be restored",report.optBoolean("restored"))
        }
    }
    fun testCurrentDeviceReceiverAuthorityReadOnly() {
        val context=instrumentation.targetContext
        val activity=instrumentation.startActivitySync(Intent(context,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as SafFrameworkHarnessActivity
        val app=context.applicationContext as WegoApplication
        val connection=app.controller.vehicleAccountConnection ?: app.vehicleConnection
        val report=JSONObject().put("scope","current-device-authority-read-only")
        try {
            val ready=SystemClock.elapsedRealtime()+15000
            while(SystemClock.elapsedRealtime()<ready && connection.verifiedDataBoundary()==null)Thread.sleep(100)
            report.put("connected",connection.verifiedDataBoundary()!=null)
            val receiverDone=CountDownLatch(1)
            main {connection.readCommandReceiver {result->
                result.fold(onSuccess={report.put("receiverEnabled",it.enabled).put("receiverRevision",it.revision)},
                    onFailure={report.put("receiverReadFailed",true)})
                receiverDone.countDown()
            }}
            assertTrue("Receiver state read callback missing",receiverDone.await(30,TimeUnit.SECONDS))
            val permissionDone=CountDownLatch(1)
            main {connection.readFunctionalPermissions {result->
                result.fold(onSuccess={report.put("commandsReceiveApproved",it.allows(io.wegoh.app.nativeauth.FunctionalPurpose.DEVICE_COMMANDS_RECEIVE))
                    .put("functionalRevision",it.revision)},onFailure={report.put("functionalReadFailed",true)})
                permissionDone.countDown()
            }}
            assertTrue("Functional state read callback missing",permissionDone.await(30,TimeUnit.SECONDS))
        } finally {
            File(context.filesDir,"vehicle-climate-current-authority.json").writeText(report.toString(2))
            main {activity.finish()}
        }
    }
    fun testFanPowerConditionWithActualProviderAndRestore() {
        val context=instrumentation.targetContext
        val activity=instrumentation.startActivitySync(Intent(context,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as SafFrameworkHarnessActivity
        val report=JSONObject().put("scope","actual-sdk-fan-power-condition");val errors=JSONArray()
        val sdk=main {VehicleHardwareSdkAdapter(context,VehicleSdkFailureDecoder {error->
            errors.put(JSONObject().put("class",error.javaClass.name).put("message",error.message?.take(300)))
            VehicleFailure.UNDEFINED
        })}
        var fanCap: ClimateCapability?=null;var powerCap: ClimateCapability?=null
        var oldFan: Int?=null;var oldPower: Boolean?=null
        val seat=VehicleSeat.ROW_1_LEFT
        try {
            assertTrue(main {sdk.initialize()} is VehicleReply.Value)
            fanCap=(reply<ClimateCapability> {sdk.climateCapability(ClimateProperty.FAN_LEVEL,it)} as VehicleReply.Value).value
            powerCap=(reply<ClimateCapability> {sdk.climateCapability(ClimateProperty.GLOBAL_POWER,it)} as VehicleReply.Value).value
            val fan=ClimateTarget.Fan(seat,4);val power=ClimateTarget.GlobalPower(seat,true)
            oldFan=((reply<ClimateReading> {sdk.readClimate(fan,fanCap!!,it)} as VehicleReply.Value).value as ClimateReading.Fan).value
            oldPower=((reply<ClimateReading> {sdk.readClimate(power,powerCap!!,it)} as VehicleReply.Value).value as ClimateReading.GlobalPower).enabled
            assertNotNull(oldFan);assertNotNull(oldPower)
            report.put("originalFan",oldFan).put("originalPower",oldPower)
            val initialSet=reply<Unit> {sdk.setClimate(fan,fanCap!!,it)}
            report.put("fanSetterWithOriginalPower",if(initialSet is VehicleReply.Failed)initialSet.reason.name else "accepted")
            val powerSet=reply<Unit> {sdk.setClimate(power,powerCap!!,it)}
            report.put("powerSetter",if(powerSet is VehicleReply.Failed)powerSet.reason.name else "accepted")
            val readPower=reply<ClimateReading> {sdk.readClimate(power,powerCap!!,it)}
            report.put("powerReadback",if(readPower is VehicleReply.Value)(readPower.value as ClimateReading.GlobalPower).enabled else JSONObject.NULL)
            val poweredSet=reply<Unit> {sdk.setClimate(fan,fanCap!!,it)}
            report.put("fanSetterWithPowerOn",if(poweredSet is VehicleReply.Failed)poweredSet.reason.name else "accepted")
            val readFan=reply<ClimateReading> {sdk.readClimate(fan,fanCap!!,it)}
            report.put("fanReadback",if(readFan is VehicleReply.Value)(readFan.value as ClimateReading.Fan).value else JSONObject.NULL)
            report.put("sdkErrors",errors)
            File(context.filesDir,"vehicle-climate-sdk-power.json").writeText(report.toString(2))
            instrumentation.sendStatus(0,android.os.Bundle().apply {putString("stream","CLIMATE_POWER_CONDITION_OBSERVED; restoring after observation window\n")})
            Thread.sleep(15000)
        } finally {
            if(oldFan!=null && fanCap!=null)reply<Unit> {sdk.setClimate(ClimateTarget.Fan(seat,oldFan!!),fanCap!!,it)}
            if(oldPower!=null && powerCap!=null)reply<Unit> {sdk.setClimate(ClimateTarget.GlobalPower(seat,oldPower!!),powerCap!!,it)}
            val finalFan=if(fanCap!=null)reply<ClimateReading> {sdk.readClimate(ClimateTarget.Fan(seat,oldFan ?: 3),fanCap!!,it)} else null
            val finalPower=if(powerCap!=null)reply<ClimateReading> {sdk.readClimate(ClimateTarget.GlobalPower(seat,oldPower ?: false),powerCap!!,it)} else null
            val restoredFan=(finalFan as? VehicleReply.Value)?.value as? ClimateReading.Fan
            val restoredPower=(finalPower as? VehicleReply.Value)?.value as? ClimateReading.GlobalPower
            report.put("restoredFan",restoredFan?.value).put("restoredPower",restoredPower?.enabled)
            report.put("restored",oldFan==restoredFan?.value && oldPower==restoredPower?.enabled).put("sdkErrors",errors)
            File(context.filesDir,"vehicle-climate-sdk-power.json").writeText(report.toString(2))
            main {sdk.close();activity.finish()}
            assertTrue("Controller baseline must be restored",report.optBoolean("restored"))
        }
    }
    fun testAllRegisteredActualCapabilitiesReadOnly() {
        val context=instrumentation.targetContext
        val activity=instrumentation.startActivitySync(Intent(context,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as SafFrameworkHarnessActivity
        val sdk=main {VehicleHardwareSdkAdapter(context)}
        val report=JSONObject().put("scope","actual-sdk-registered-capabilities-read-only").put("setterCalls",0)
        try {
            assertTrue(main {sdk.initialize()} is VehicleReply.Value)
            val rows=JSONArray()
            for((property,action) in TRUSTED_CLIMATE_ACTIONS) {
                val row=JSONObject().put("action",action.id).put("property",property.name)
                when(val result=reply<ClimateCapability> {sdk.climateCapability(property,it)}) {
                    is VehicleReply.Failed->row.put("failure",result.reason.name)
                    is VehicleReply.Value->{
                        val cap=result.value
                        row.put("access",cap.access.name).put("seats",JSONArray(cap.areas.map {it.name}))
                        row.put("sdkAreaSeats",JSONArray(cap.seatAreas.map {JSONArray(it.seats.map {seat->seat.name})}))
                        row.put("windows",JSONArray(cap.windows.map {it.name}))
                        row.put("bounds",JSONObject().apply {cap.bounds.forEach {(seat,b)->put(seat.name,JSONArray(listOf(b.minimum,b.maximum)))}})
                        row.put("windowBounds",JSONObject().apply {cap.windowBounds.forEach {(window,b)->put(window.name,JSONArray(listOf(b.minimum,b.maximum)))}})
                        row.put("celsiusStep",cap.celsiusStep?.let {JSONObject().put("minimum",it.minimum).put("maximum",it.maximum).put("increment",it.increment)} ?: JSONObject.NULL)
                        row.put("lightSwitches",JSONArray(cap.lightSwitches.map {it.name}))
                        row.put("seatLightSwitches",JSONObject().apply {cap.seatLightSwitches.forEach {(seat,values)->put(seat.name,JSONArray(values.map {it.name}))}})
                    }
                }
                rows.put(row)
            }
            report.put("actions",rows)
        } finally {
            File(context.filesDir,"vehicle-climate-all-capabilities.json").writeText(report.toString(2))
            main {sdk.close();activity.finish()}
        }
    }
    fun testCapabilitySessionCloseDoesNotInterruptCommandSdkSession() {
        val context=instrumentation.targetContext
        val command=main {VehicleHardwareSdkAdapter(context)}
        val observer=main {VehicleHardwareSdkAdapter(context)}
        try {
            assertTrue(main {command.initialize()} is VehicleReply.Value)
            val cap=(reply<ClimateCapability> {command.climateCapability(ClimateProperty.TARGET_CELSIUS,it)} as VehicleReply.Value).value
            assertTrue(main {observer.initialize()} is VehicleReply.Value)
            assertTrue(reply<ClimateCapability> {observer.climateCapability(ClimateProperty.FAN_LEVEL,it)} is VehicleReply.Value)
            main {observer.close()}
            val read=reply<ClimateReading> {command.readClimate(ClimateTarget.Celsius(VehicleSeat.ROW_1_LEFT,22.5f),cap,it)}
            assertTrue("Closing capability observer must not disconnect command SDK",read is VehicleReply.Value)
            assertNotNull((read as VehicleReply.Value).value.let {it as ClimateReading.Celsius}.value)
        } finally {main {observer.close();command.close()}}
    }
    fun testActualCapabilityAndTemperatureBaseline() {
        val context=instrumentation.targetContext
        val activity=instrumentation.startActivitySync(Intent(context,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as SafFrameworkHarnessActivity
        val sdk=main {VehicleHardwareSdkAdapter(context)}
        val report=JSONObject().put("scope","actual-pleos-product-adapter-read-only").put("setterCalls",0)
        try {
            val init=main {sdk.initialize()};assertTrue("Actual SDK initialize failed",init is VehicleReply.Value)
            val results=JSONArray()
            for(property in listOf(ClimateProperty.TARGET_CELSIUS,ClimateProperty.FAN_LEVEL)) {
                val capability=reply<ClimateCapability> {sdk.climateCapability(property,it)}
                val row=JSONObject().put("property",property.name)
                when(capability) {
                    is VehicleReply.Failed->row.put("failure",capability.reason.name)
                    is VehicleReply.Value->{
                        val cap=capability.value
                        row.put("access",cap.access.name).put("areas",JSONArray(cap.areas.map {it.name}))
                        row.put("bounds",JSONObject().apply {cap.bounds.forEach {(seat,bounds)->
                            put(seat.name,JSONObject().put("minimum",bounds.minimum).put("maximum",bounds.maximum))
                        }})
                        row.put("sdkAreaSeats",JSONArray(cap.seatAreas.map {JSONArray(it.seats.map {seat->seat.name})}))
                        val reads=JSONObject()
                        for(seat in listOf(VehicleSeat.ROW_1_LEFT,VehicleSeat.ROW_1_RIGHT,VehicleSeat.ROW_2_LEFT)) {
                            val target=if(property==ClimateProperty.TARGET_CELSIUS)ClimateTarget.Celsius(seat,22.5f) else ClimateTarget.Fan(seat,4)
                            val reading=reply<ClimateReading> {sdk.readClimate(target,cap,it)}
                            reads.put(seat.name,when(reading) {
                                is VehicleReply.Failed->JSONObject().put("failure",reading.reason.name)
                                is VehicleReply.Value->JSONObject().put("reading",when(val value=reading.value){
                                    is ClimateReading.Celsius->value.value
                                    is ClimateReading.Fan->value.value
                                    else->value.toString()
                                })
                            })
                        }
                        row.put("reads",reads)
                    }
                }
                results.put(row)
            }
            report.put("capabilities",results)
        } finally {
            main {sdk.close();activity.finish()}
            File(context.filesDir,"vehicle-climate-sdk-read-only.json").writeText(report.toString(2))
        }
        val temp=report.getJSONArray("capabilities").getJSONObject(0)
        val rearSupported=(0 until temp.getJSONArray("areas").length()).any {temp.getJSONArray("areas").getString(it)=="ROW_2_LEFT"}
        val rearRead=temp.getJSONObject("reads").getJSONObject("ROW_2_LEFT")
        if(rearSupported)assertTrue(rearRead.has("reading"))
        else assertEquals("UNSUPPORTED_AREA",rearRead.getString("failure"))
    }
}
