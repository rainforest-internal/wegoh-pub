package io.wegoh.app

import io.wegoh.app.nativeauth.VehicleClimateNativeTransport
import io.wegoh.app.nativeauth.VehicleClimateTransport
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.Closeable

class VehicleClimateHostTest {
    @Test fun existingInboxAndAcknowledgementsPublishOneRequestFromQueuedToApplied() {
        val h=Harness()
        h.transport.rows=listOf(request("visible-request","queued",1))
        h.transport.holdClaim=true
        h.poll()
        assertEquals(VehicleRemoteResult.QUEUED,h.history.entriesFor(h.boundary).single().result)
        h.transport.pendingClaim!!.invoke()
        val entries=h.history.entriesFor(h.boundary)
        assertEquals(1,entries.size);assertEquals("visible-request",entries.single().requestId)
        assertEquals(VehicleRemoteResult.APPLIED,entries.single().result)
        assertEquals(listOf("received","sdk-accepted","state-confirmed"),h.transport.acks)
    }
    @Test fun onlyOldestQueuedFriendCommandIsClaimed() {
        val h=Harness()
        h.transport.rows=listOf(request("claimed","delivered",0),request("new","queued",20),request("old","queued",10))
        h.poll()
        assertEquals(listOf("old"),h.transport.claims)
        assertEquals(listOf("received","sdk-accepted","state-confirmed"),h.transport.acks)
        assertEquals(listOf(VehicleClimateHostResult.CONFIRMED),h.results)
        assertTrue(h.host.hasPendingRequests)
        assertEquals(1,h.hardware.writes)
    }

    @Test fun deliveredCommandsDoNotCauseAClaimLoopOrFastPolling() {
        val h=Harness()
        h.transport.rows=listOf(request("held","delivered",1),request("read","received",2),request("set","sdk-accepted",3))
        repeat(3) {h.poll()}
        assertTrue(h.transport.claims.isEmpty())
        assertTrue(h.results.all {it==VehicleClimateHostResult.NO_SUPPORTED_REQUEST})
        assertFalse(h.host.hasPendingRequests)
        assertEquals(1,h.hardware.initializes)
    }

    @Test fun oneSuccessfulRequestDoesNotTriggerFastPolling() {
        val h=Harness();h.transport.rows=listOf(request("only","queued",1));h.poll()
        assertEquals(VehicleClimateHostResult.CONFIRMED,h.results.single())
        assertFalse(h.host.hasPendingRequests)
    }

    @Test fun restoredReceiverResumesInboxAfterOpenWasRejectedDuringRevalidation() {
        val h=Harness();h.poll()
        h.transport.suspended=true;h.poll()
        assertEquals(VehicleClimateHostResult.UNAVAILABLE,h.results.last())
        assertEquals(0,h.hardware.writes)
        h.transport.suspended=false
        h.transport.rows=listOf(request("pending","queued",1));h.poll()
        assertEquals(VehicleClimateHostResult.CONFIRMED,h.results.last())
        assertEquals(listOf("pending"),h.transport.claims)
        assertEquals(2,h.transport.opens)
        assertEquals(1,h.hardware.writes)
    }

    @Test fun rejectedCommandSpeedsUpOnlyAfterItsTerminalAckSucceeds() {
        for(failedAck in listOf(false,true)) {
            val h=Harness();h.transport.rows=listOf(request("first","queued",1),request("next","queued",2))
            h.hardware.capabilityFailure=VehicleFailure.UNSUPPORTED_AREA
            if(failedAck)h.transport.failedAck="rejected"
            h.poll()
            assertEquals(!failedAck,h.host.hasPendingRequests)
            assertEquals(0,h.hardware.writes)
        }
    }

    @Test fun failedClaimAndFailedReceivedAckKeepNormalPolling() {
        for(failClaim in listOf(false,true)) {
            val h=Harness();h.transport.rows=listOf(request("first","queued",1),request("next","queued",2))
            h.transport.failClaim=failClaim
            if(!failClaim)h.transport.failedAck="received"
            h.poll()
            assertEquals(VehicleClimateHostResult.UNAVAILABLE,h.results.single())
            assertFalse(h.host.hasPendingRequests)
            assertEquals(0,h.hardware.writes)
        }
    }

    @Test fun lateClaimReplyCannotFinishAnotherPollAfterInvalidation() {
        val h=Harness();h.transport.rows=listOf(request("old","queued",1));h.transport.holdClaim=true
        h.poll();val old=checkNotNull(h.transport.pendingClaim)
        h.transport.invalidate()
        h.transport.rows=listOf(request("new","queued",2));h.poll()
        old()
        assertEquals(listOf(VehicleClimateHostResult.BLOCKED),h.results)
        assertEquals(0,h.hardware.writes)
        checkNotNull(h.transport.pendingClaim).invoke()
        assertEquals(listOf(VehicleClimateHostResult.BLOCKED,VehicleClimateHostResult.CONFIRMED),h.results)
        assertEquals(1,h.hardware.writes)
    }

    @Test fun diagnosticsReportStagesWithoutAccountClaimOrLeaseIdentifiers() {
        val h=Harness();h.transport.rows=listOf(request("secret-command","queued",1));h.poll()
        val log=h.logs.joinToString("\n")
        assertTrue(log.contains("climate.receiver: polled"))
        assertTrue(log.contains("climate.receiver: claimed"))
        assertTrue(log.contains("climate.receiver: applied"))
        assertTrue(log.contains("remaining_ms="))
        for(secret in listOf("secret-command","private-owner","private-device","private-lease"))assertFalse(log.contains(secret))
    }

    @Test fun inboxSelectionLogsOneReasonForEachExcludedRow() {
        val h=Harness()
        h.transport.rows=listOf(
            VehicleClimateNativeTransport.Request("room","hvac.fan",1,false,"queued",1),
            request("delivered","delivered",2),
            VehicleClimateNativeTransport.Request("unknown","unknown.action",1,true,"queued",3),
            VehicleClimateNativeTransport.Request("old","hvac.fan",2,true,"queued",4),
            VehicleClimateNativeTransport.Request("unadvertised","hvac.power",1,true,"queued",5),
            request("eligible","queued",6))
        h.poll()
        val log=h.logs.single {it.contains("climate.receiver: polled")}
        assertTrue(log.contains("received_rows=6 queued=1 skipped=5"))
        for(reason in listOf("not_friend","not_queued","untrusted_action","request_revision","descriptor_revision"))
            assertTrue(log.contains("discarded_$reason=1"))
        assertEquals(listOf("eligible"),h.transport.claims)
    }

    @Test fun driverSeatCommandIsRejectedBeforeAnyWrite() {
        val h=Harness();h.transport.rows=listOf(request("driver","queued",1))
        h.transport.arguments=JSONObject().put("seat","ROW_1_LEFT").put("value",4)
        h.poll()
        assertEquals(VehicleClimateHostResult.BLOCKED,h.results.single())
        assertEquals(listOf("received","rejected"),h.transport.acks)
        assertEquals(0,h.hardware.writes)
        assertEquals(VehicleRemoteResult.REJECTED,h.history.entriesFor(h.boundary).single().result)
        assertEquals("{}",h.transport.evidence.last())
    }

    @Test fun cabinLightIsDrivingBlockedButRunsFromTheParkedReceiver() {
        val h=Harness()
        h.safety=VehicleClimateSafety(foreground=false,parked=false,carUxKnown=true,setupAllowed=false,suspended=false,receiverActive=true)
        h.transport.action="light.cabin";h.transport.arguments=JSONObject().put("value",true)
        h.transport.rows=listOf(VehicleClimateNativeTransport.Request("cabin","light.cabin",1,true,"queued",1))
        h.poll()
        assertEquals(VehicleClimateHostResult.BLOCKED,h.results.single())
        assertEquals(0,h.hardware.writes)
        assertEquals(VehicleRemoteResult.DRIVING_BLOCKED,h.history.entriesFor(h.boundary).single().result)
        // The server keeps the driving reason so the request log and the phone show the same result.
        assertEquals(listOf("received","rejected"),h.transport.acks)
        assertEquals(JSONObject().put("reason",DRIVING_RESTRICTED_REASON).toString(),h.transport.evidence.last())
        // Parked with only the receiver service running (remote screen closed) still turns the cabin light on.
        h.safety=VehicleClimateSafety(foreground=false,parked=true,carUxKnown=true,setupAllowed=true,suspended=false,receiverActive=true)
        h.transport.rows=listOf(VehicleClimateNativeTransport.Request("parked","light.cabin",1,true,"queued",2))
        h.poll()
        assertEquals(VehicleClimateHostResult.CONFIRMED,h.results.last())
        assertEquals(1,h.hardware.writes)
    }

    private class Harness {
        val lane=Lane()
        val boundary=io.wegoh.app.nativeauth.VehicleConnection.DataBoundary(1,"qa-device",emptySet(),1_000_000)
        val history=VehicleRemoteHistory({lane.nowElapsedMillis()},{boundary})
        val transport=Transport()
        val hardware=Hardware()
        val logs=mutableListOf<String>()
        val results=mutableListOf<VehicleClimateHostResult>()
        var safety=VehicleClimateSafety(true,true,true,true,false,true)
        val host=VehicleClimateHost({safety},TRUSTED_CLIMATE_ACTIONS,
            hardware,transport,history,lane=lane,diagnostics={logs+=it})
        fun poll()=host.checkPending({_,approve->approve(true)}) {results+=it}
    }
    private class Lane: VehicleOperationLane {
        override fun dispatch(block: ()->Unit)=block()
        override fun nowElapsedMillis()=100L
        override fun schedule(delayMillis: Long,block: ()->Unit)=VehicleCancellation {}
    }
    private class Hardware: VehicleHardwarePort {
        var initializes=0
        var writes=0
        var capabilityFailure: VehicleFailure?=null
        override fun initialize(): VehicleReply<Unit> {initializes++;return VehicleReply.Value(Unit)}
        override fun close() {}
        override fun climateCapability(property: ClimateProperty,callback: (VehicleReply<ClimateCapability>)->Unit) {
            callback(capabilityFailure?.let {VehicleReply.Failed(it)} ?: VehicleReply.Value(ClimateCapability(VehicleAccess.READ_WRITE,
                setOf(VehicleSeat.ROW_1_LEFT,VehicleSeat.ROW_1_RIGHT),
                mapOf(VehicleSeat.ROW_1_LEFT to ClimateBounds(1.0,8.0),VehicleSeat.ROW_1_RIGHT to ClimateBounds(1.0,8.0)),
                lightSwitches=setOf(VehicleLightSwitch.OFF,VehicleLightSwitch.ON))))
        }
        override fun setClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<Unit>)->Unit) {writes++;callback(VehicleReply.Value(Unit))}
        override fun readClimate(target: ClimateTarget,capability: ClimateCapability,callback: (VehicleReply<ClimateReading>)->Unit)=
            callback(VehicleReply.Value(if(target is ClimateTarget.CabinLight)ClimateReading.CabinLight(VehicleLightSwitch.ON) else ClimateReading.Fan(4)))
        override fun telemetryCapability(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleAccess>)->Unit)=error("unexpected telemetry")
        override fun readTelemetry(signal: VehicleTelemetrySignal,callback: (VehicleReply<VehicleTelemetryValue?>)->Unit)=error("unexpected telemetry")
    }
    private class Transport: VehicleClimateTransport {
        var rows=emptyList<VehicleClimateNativeTransport.Request>()
        val claims=mutableListOf<String>()
        val acks=mutableListOf<String>()
        val evidence=mutableListOf<String>()
        var failClaim=false
        var failedAck: String?=null
        var holdClaim=false
        var pendingClaim: (()->Unit)?=null
        var suspended=false
        var opens=0
        var action="hvac.fan"
        var arguments: JSONObject=JSONObject().put("seat","ROW_1_RIGHT").put("value",4)
        private var invalidated: ()->Unit={}
        private var opened=false
        private var active: VehicleClimateNativeTransport.Claim?=null
        override fun open(onInvalidated: ()->Unit,callback: (Result<Unit>)->Unit) {
            opens++
            if(opened || suspended) {callback(Result.failure(IllegalStateException()));return}
            invalidated=onInvalidated;opened=true;callback(Result.success(Unit))
        }
        override fun current(claim: VehicleClimateNativeTransport.Claim?)=opened && !suspended && (claim==null || claim===active)
        override fun close() {opened=false}
        fun invalidate() {opened=false;invalidated()}
        override fun inbox(callback: (Result<VehicleClimateNativeTransport.Inbox>)->Unit): Closeable {
            callback(Result.success(VehicleClimateNativeTransport.Inbox(rows,mapOf("hvac.fan" to 1L,"light.cabin" to 1L))));return Closeable {}
        }
        override fun claim(id: String,callback: (Result<VehicleClimateNativeTransport.Claim>)->Unit): Closeable {
            claims+=id
            val claim=VehicleClimateNativeTransport.Claim(id,"private-owner","private-device","grant",action,1,
                "private-lease",arguments,10_000,1)
            active=claim
            val reply={callback(if(failClaim)Result.failure(IllegalStateException()) else Result.success(claim))}
            if(holdClaim)pendingClaim=reply else reply()
            return Closeable {}
        }
        override fun ack(claim: VehicleClimateNativeTransport.Claim,stage: String,evidence: JSONObject,callback: (Result<Unit>)->Unit): Closeable {
            acks+=stage;this.evidence+=evidence.toString();callback(if(stage==failedAck)Result.failure(IllegalStateException()) else Result.success(Unit));return Closeable {}
        }
    }
    private companion object {
        fun request(id: String,stage: String,created: Long)=VehicleClimateNativeTransport.Request(id,"hvac.fan",1,true,stage,created)
    }
}
