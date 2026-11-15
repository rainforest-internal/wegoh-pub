package io.wegoh.app

import android.app.ActivityManager
import android.app.Dialog
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.SystemClock
import android.test.InstrumentationTestCase
import android.widget.TextView
import androidx.lifecycle.Lifecycle
import io.wegoh.app.nativeauth.VehicleClimateNativeTransport
import io.wegoh.app.nativeauth.VehicleClimateTransport
import org.json.JSONObject
import java.io.Closeable

@Suppress("DEPRECATION")
class VehicleClimateForegroundTest: InstrumentationTestCase() {
    private fun main(block: ()->Unit) {
        var failure: Throwable?=null
        instrumentation.runOnMainSync {try {block()} catch(error: Throwable) {failure=error}}
        failure?.let {throw it}
    }
    private fun await(label: String,diagnostic: (()->String)?=null,condition: ()->Boolean) {
        val deadline=SystemClock.elapsedRealtime()+20_000
        while(SystemClock.elapsedRealtime()<deadline) {
            var ready=false;main {ready=condition()}
            if(ready)return
            Thread.sleep(50)
        }
        var detail=""
        if(diagnostic!=null)main {detail="; "+diagnostic()}
        fail(label+detail)
    }
    private fun field(owner: Any,name: String)=owner.javaClass.getDeclaredField(name).apply {isAccessible=true}
    private val actions=listOf(
        "hvac.temperature" to JSONObject().put("seat","ROW_1_RIGHT").put("value",22.5),
        "hvac.fan" to JSONObject().put("seat","ROW_1_RIGHT").put("value",3),
        "hvac.power" to JSONObject().put("seat","ROW_1_RIGHT").put("value",true),
        "hvac.ac" to JSONObject().put("seat","ROW_1_RIGHT").put("value",false),
        "hvac.air_cleaner" to JSONObject().put("seat","ROW_1_RIGHT").put("value",true),
        "seat.heat" to JSONObject().put("seat","ROW_1_RIGHT").put("value",3),
        "seat.ventilation" to JSONObject().put("seat","ROW_1_RIGHT").put("value",0),
        "window.position" to JSONObject().put("window","ROW_1_RIGHT").put("value",37),
        "light.cabin" to JSONObject().put("value",false),
        "light.reading" to JSONObject().put("seat","ROW_1_RIGHT").put("value",true),
        "light.ambient" to JSONObject().put("seat","ROW_1_RIGHT").put("value",false)
    )

    fun testServiceUsesActualWindowLifecycleAndWithdrawsPendingCommands() {
        val context=instrumentation.targetContext
        val app=context.applicationContext as WegoApplication
        val activity=instrumentation.startActivitySync(Intent(context,VehicleClimateActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as VehicleClimateActivity
        val receiverFixture=app.simulateApprovedReceiver()
        var service: VehicleClimateService?=null
        var safety: ClimateCarSafety?=null
        var dialog: Dialog?=null
        val hardware=Hardware()
        val transport=Transport(actions.map {it.first})
        val parkedActions=actions.filter {it.first in setOf("seat.heat","seat.ventilation")}
        val cabinLight=actions.single {it.first=="light.cabin"}
        val drivingActions=actions-parkedActions.toSet()-cabinLight
        val binding=object: ServiceConnection {
            override fun onServiceConnected(name: ComponentName,binder: IBinder) {service=(binder as VehicleClimateService.ReceiverBinder).service}
            override fun onServiceDisconnected(name: ComponentName) {service=null}
        }
        var bound=false
        fun poll(action: Pair<String,JSONObject>)=main {
            transport.offer(action)
            val receiver=checkNotNull(service)
            val poll=field(receiver,"poll").get(receiver) as Runnable
            poll.run()
            (field(receiver,"handler").get(receiver) as Handler).removeCallbacks(poll)
        }
        fun expectStage(stage: String) {main {assertEquals(stage,transport.stages.lastOrNull())}}
        fun loseFocus() {
            main {dialog=Dialog(activity).apply {setContentView(TextView(activity).apply {text="Focus regression fixture"});show()}}
            await("dialog focus did not revoke service foreground") {dialog?.window?.decorView?.hasWindowFocus()==true && safety?.snapshot()?.foreground==false}
        }
        fun regainFocus() {main {dialog?.dismiss();dialog=null};await("window focus did not restore service foreground") {safety?.snapshot()?.foreground==true}}
        fun background(phase: String="idle") {
            var accepted=false
            main {accepted=activity.moveTaskToBack(true)}
            await("task background did not revoke service foreground",diagnostic={
                val window=field(activity,"windows").get(activity) as io.wegoh.app.ui.CarWindowVisibility
                "phase=$phase moveTaskToBack=$accepted lifecycle=${activity.lifecycle.currentState} multiWindow=${activity.isInMultiWindowMode} focus=${activity.hasWindowFocus()} window=${window.state} safetyForeground=${safety?.snapshot()?.foreground} ack=${transport.stages.lastOrNull()}"
            }) {
                val window=field(activity,"windows").get(activity) as io.wegoh.app.ui.CarWindowVisibility
                val inactive= !activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)
                accepted && (!activity.hasWindowFocus() || inactive) &&
                    (!inactive || !window.state.visible) && !window.state.focused && safety?.snapshot()?.foreground==false
            }
        }
        fun foreground() {
            main {context.getSystemService(ActivityManager::class.java).appTasks.first {it.taskInfo.taskId==activity.taskId}.moveToFront()}
            await("resumed Activity did not restore service foreground") {
                activity.lifecycle.currentState==Lifecycle.State.RESUMED && activity.hasWindowFocus() && safety?.snapshot()?.foreground==true
            }
        }
        try {
            await("Activity did not become visible and focused") {activity.hasWindowFocus() && activity.window.decorView.isShown}
            main {bound=context.bindService(Intent(context,VehicleClimateService::class.java),binding,Context.BIND_AUTO_CREATE);assertTrue(bound)}
            await("receiver not bound") {service!=null}
            main {
                val receiver=checkNotNull(service)
                safety=field(receiver,"safety").get(receiver) as ClimateCarSafety
                assertTrue("service missed the already focused window",safety!!.snapshot().foreground)
                val hostField=field(receiver,"host")
                (hostField.get(receiver) as VehicleClimateHost).close()
                val connection=app.controller.vehicleAccountConnection ?: app.vehicleConnection
                val host=VehicleClimateHost(context,connection,app.controller.remoteHistoryFor(connection),
                    safety={safety!!.snapshot()},port=hardware,transport=transport)
                assertEquals(TRUSTED_CLIMATE_ACTIONS,field(host,"actions").get(host))
                assertEquals(actions.map {it.first}.toSet(),TRUSTED_CLIMATE_ACTIONS.values.map {it.id}.toSet())
                assertEquals(drivingActions.map {it.first}.toSet(),DRIVING_RECEIVER_CLIMATE_ACTIONS.values.map {it.id}.toSet())
                hostField.set(receiver,host)
                context.startForegroundService(Intent(context,VehicleClimateService::class.java))
            }
            await("receiver did not observe actual Park and CarUx baseline") {
                safety?.snapshot()?.let {it.foreground && it.parked && it.setupAllowed && it.permitsReceiver()}==true
            }
            actions.forEach {poll(it);expectStage("state-confirmed")}
            assertEquals(1,hardware.initializes)
            assertEquals(0,hardware.closes)
            loseFocus()
            drivingActions.forEach {poll(it);expectStage("state-confirmed")}
            poll(cabinLight);expectStage("state-confirmed")
            for(action in parkedActions) {
                val checks=hardware.checks;val writes=hardware.writes
                poll(action);expectStage("rejected")
                assertEquals(checks,hardware.checks);assertEquals(writes,hardware.writes)
            }
            regainFocus()
            for(transition in listOf("focus","task-background"))for(phase in listOf("capability","setter","getter")) {
                main {hardware.hold=phase}
                val writes=hardware.writes
                poll(actions.single {it.first=="seat.heat"})
                main {assertNotNull("phase was not pending: $phase",hardware.pending)}
                if(transition=="focus")loseFocus() else background(phase)
                expectStage(if(phase=="capability")"rejected" else "unknown")
                assertEquals(writes+if(phase=="capability")0 else 1,hardware.writes)
                val acknowledged=transport.stages.toList();val reads=hardware.reads
                if(transition=="focus")regainFocus() else foreground()
                main {hardware.release()}
                assertEquals(acknowledged,transport.stages);assertEquals(reads,hardware.reads)
                assertEquals(writes+if(phase=="capability")0 else 1,hardware.writes)
            }
            for(phase in listOf("capability","setter","getter")) {
                main {hardware.hold=phase}
                val writes=hardware.writes
                poll(actions.single {it.first=="seat.heat"})
                main {assertNotNull("phase was not pending: $phase",hardware.pending);safety!!.setReceiverActive(false)}
                expectStage(if(phase=="capability")"rejected" else "unknown")
                assertEquals(writes+if(phase=="capability")0 else 1,hardware.writes)
                val acknowledged=transport.stages.toList();val reads=hardware.reads
                main {safety!!.setReceiverActive(true);hardware.release()}
                assertEquals(acknowledged,transport.stages);assertEquals(reads,hardware.reads)
                assertEquals(writes+if(phase=="capability")0 else 1,hardware.writes)
            }
            background()
            drivingActions.forEach {poll(it);expectStage("state-confirmed")}
            poll(cabinLight);expectStage("state-confirmed")
            parkedActions.forEach {poll(it);expectStage("rejected")}
            foreground()
            main {hardware.hold="getter"}
            poll(actions.single {it.first=="seat.heat"})
            instrumentation.sendStatus(0,Bundle().apply {putString("stream","UX_READY_PARKED\n")})
            await("actual Drive and CarUx restriction not observed") {safety?.snapshot()?.let {!it.parked && it.carUxKnown && !it.setupAllowed}==true}
            expectStage("unknown")
            val lateGetter=hardware.pending
            main {hardware.pending=null;hardware.hold=null}
            drivingActions.forEach {poll(it);expectStage("state-confirmed")}
            for(action in parkedActions+cabinLight) {
                val checks=hardware.checks;val writes=hardware.writes
                poll(action);expectStage("rejected")
                assertEquals(checks,hardware.checks);assertEquals(writes,hardware.writes)
            }
            for(phase in listOf("capability","setter","getter")) {
                main {hardware.hold=phase}
                val writes=hardware.writes
                poll(actions.single {it.first=="hvac.power"})
                main {assertNotNull("driving phase was not pending: $phase",hardware.pending);safety!!.setReceiverActive(false)}
                expectStage(if(phase=="capability")"rejected" else "unknown")
                assertEquals(writes+if(phase=="capability")0 else 1,hardware.writes)
                val acknowledged=transport.stages.toList();val reads=hardware.reads
                main {safety!!.setReceiverActive(true);hardware.release()}
                assertEquals(acknowledged,transport.stages);assertEquals(reads,hardware.reads)
                assertEquals(writes+if(phase=="capability")0 else 1,hardware.writes)
            }
            main {safety!!.setReceiverActive(false)}
            for(action in actions) {
                val checks=hardware.checks;val writes=hardware.writes;val reads=hardware.reads
                poll(action)
                main {assertTrue("inactive receiver acknowledged "+action.first,transport.stages.isEmpty())}
                assertEquals(checks,hardware.checks);assertEquals(writes,hardware.writes);assertEquals(reads,hardware.reads)
            }
            main {safety!!.setReceiverActive(true)}
            drivingActions.forEach {poll(it);expectStage("state-confirmed")}
            (parkedActions+cabinLight).forEach {poll(it);expectStage("rejected")}
            instrumentation.sendStatus(0,Bundle().apply {putString("stream","UX_READY_RESTRICTED\n")})
            await("Park and setup authority not restored") {safety?.snapshot()?.let {it.parked && it.setupAllowed && it.foreground}==true}
            val acknowledged=transport.stages.toList()
            main {lateGetter?.invoke()}
            assertEquals(acknowledged,transport.stages)
            poll(actions.single {it.first=="seat.heat"});expectStage("state-confirmed")
        } finally {
            main {
                dialog?.dismiss()
                if(bound)context.unbindService(binding)
                context.stopService(Intent(context,VehicleClimateService::class.java))
                activity.finish()
            }
            receiverFixture.close()
            await("receiver did not close") {!VehicleClimateService.active}
            main {safety?.let {assertFalse(it.snapshot().foreground);assertFalse(it.snapshot().receiverActive)}}
        }
    }

    private class Hardware: VehicleHardwarePort {
        var checks=0;var writes=0;var reads=0
        var initializes=0;var closes=0
        var hold: String?=null
        var pending: (()->Unit)?=null
        private val capability=ClimateCapability(VehicleAccess.READ_WRITE,VehicleSeat.entries.toSet(),
            VehicleSeat.entries.associateWith {ClimateBounds(0.0,100.0)},
            windows=VehicleWindow.entries.toSet(),windowBounds=VehicleWindow.entries.associateWith {ClimateBounds(0.0,100.0)},
            lightSwitches=setOf(VehicleLightSwitch.ON,VehicleLightSwitch.OFF),
            seatLightSwitches=VehicleSeat.entries.associateWith {setOf(VehicleLightSwitch.ON,VehicleLightSwitch.OFF)})
        private fun deliver(phase: String,block: ()->Unit) {if(hold==phase)pending=block else block()}
        fun release() {val reply=pending;pending=null;hold=null;reply?.invoke()}
        override fun initialize(): VehicleReply<Unit> { initializes++;return VehicleReply.Value(Unit) }
        override fun climateCapability(property: ClimateProperty,callback: (VehicleReply<ClimateCapability>)->Unit) {
            checks++;deliver("capability") {callback(VehicleReply.Value(capability))}
        }
        override fun setClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<Unit>)->Unit) {
            writes++;deliver("setter") {callback(VehicleReply.Value(Unit))}
        }
        override fun readClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<ClimateReading>)->Unit) {
            fun light(value: Boolean)=if(value)VehicleLightSwitch.ON else VehicleLightSwitch.OFF
            val reading=when(target) {
                is ClimateTarget.Celsius->ClimateReading.Celsius(target.value)
                is ClimateTarget.Fan->ClimateReading.Fan(target.value)
                is ClimateTarget.GlobalPower->ClimateReading.GlobalPower(target.enabled)
                is ClimateTarget.Ac->ClimateReading.Ac(target.value)
                is ClimateTarget.AirCleaner->ClimateReading.AirCleaner(target.value)
                is ClimateTarget.SeatHeat->ClimateReading.SeatHeat(target.value)
                is ClimateTarget.SeatVentilation->ClimateReading.SeatVentilation(target.value)
                is ClimateTarget.WindowPosition->ClimateReading.WindowPosition(target.value)
                is ClimateTarget.CabinLight->ClimateReading.CabinLight(light(target.value))
                is ClimateTarget.ReadingLight->ClimateReading.ReadingLight(light(target.value))
                is ClimateTarget.AmbientLight->ClimateReading.AmbientLight(light(target.value))
            }
            reads++;deliver("getter") {callback(VehicleReply.Value(reading))}
        }
        override fun telemetryCapability(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleAccess>)->Unit)=error("Unexpected telemetry")
        override fun readTelemetry(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleTelemetryValue?>)->Unit)=error("Unexpected telemetry")
        override fun close() { closes++ }
    }
    private class Transport(private val actionIds: List<String>): VehicleClimateTransport {
        private var offered: VehicleClimateNativeTransport.Claim?=null
        private var current: VehicleClimateNativeTransport.Claim?=null
        private var sequence=0
        private var opened=false
        val stages=mutableListOf<String>()
        fun offer(action: Pair<String,JSONObject>) {
            stages.clear()
            offered=VehicleClimateNativeTransport.Claim("command-${++sequence}","owner","device","grant",action.first,1,
                "lease-$sequence",action.second,SystemClock.elapsedRealtime()+10_000,1)
        }
        override fun open(onInvalidated: ()->Unit,callback: (Result<Unit>)->Unit) {opened=true;callback(Result.success(Unit))}
        override fun current(claim: VehicleClimateNativeTransport.Claim?)=opened && (claim==null || claim===current && SystemClock.elapsedRealtime()<claim.deadlineElapsedMillis)
        override fun inbox(callback: (Result<VehicleClimateNativeTransport.Inbox>)->Unit): Closeable {
            callback(Result.success(VehicleClimateNativeTransport.Inbox(offered?.let {listOf(VehicleClimateNativeTransport.Request(it.id,it.capabilityId,it.revision,true,"queued",0))}.orEmpty(),actionIds.associateWith {1L})))
            return Closeable {}
        }
        override fun claim(id: String,callback: (Result<VehicleClimateNativeTransport.Claim>)->Unit): Closeable {
            val claim=checkNotNull(offered);check(claim.id==id);current=claim;offered=null
            callback(Result.success(claim));return Closeable {}
        }
        override fun ack(claim: VehicleClimateNativeTransport.Claim,stage: String,evidence: JSONObject,callback: (Result<Unit>)->Unit): Closeable {
            check(current(claim));stages+=stage;callback(Result.success(Unit));return Closeable {}
        }
        override fun close() {opened=false;current=null}
    }
}
