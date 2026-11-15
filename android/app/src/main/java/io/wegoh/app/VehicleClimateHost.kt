package io.wegoh.app

import io.wegoh.app.nativeauth.WegoLog
import android.content.Context
import io.wegoh.app.nativeauth.NativeSocialFailure
import io.wegoh.app.nativeauth.VehicleClimateNativeTransport
import io.wegoh.app.nativeauth.VehicleClimateTransport
import io.wegoh.app.nativeauth.VehicleConnection
import org.json.JSONObject

internal data class VehicleClimateSafety(val foreground: Boolean,val parked: Boolean,
    val carUxKnown: Boolean,val setupAllowed: Boolean,val suspended: Boolean,
    val receiverActive: Boolean=false) {
    fun permitsReceiver()=receiverActive && carUxKnown && !suspended
}

/**
 * Host-only bridge from authenticated, explicitly granted server claims to actual Pleos HVAC.
 * Local descriptors are supplied by the host's reviewed configuration. Neither server JSON nor
 * SDK capability data can register an action. Empty configuration performs no claim or write.
 */
internal class VehicleClimateHost(
    private val safety: ()->VehicleClimateSafety,
    actions: Map<ClimateProperty,TrustedClimateAction>,
    private val port: VehicleHardwarePort,
    private val transport: VehicleClimateTransport,
    private val history: VehicleRemoteHistory,
    private val senderName: (String)->String?={null},
    private val lane: VehicleOperationLane=AndroidVehicleOperationLane(),
    private val diagnostics: (String)->Unit={WegoLog.i("WegoClimate",it)}
): AutoCloseable {
    constructor(context: Context,connection: VehicleConnection,history: VehicleRemoteHistory,safety: ()->VehicleClimateSafety,
        actions: Map<ClimateProperty,TrustedClimateAction> = TRUSTED_CLIMATE_ACTIONS,
        port: VehicleHardwarePort=VehicleHardwareSdkAdapter(context),
        transport: VehicleClimateTransport=VehicleClimateNativeTransport(connection),
        senderName: (String)->String?={null}): this(safety,actions,port,transport,history,senderName)

    private val hardware=VehicleHardwareSession(port)
    private val actions=actions.toMap()
    private var claimHistoryToken: VehicleRemoteHistory.Token?=null
    private var inboxHistoryToken: VehicleRemoteHistory.Token?=null
    private var executor: VehicleClimateCommandExecutor?=null
    private var claim: VehicleClimateNativeTransport.Claim?=null
    private var lease: VehicleCommandLease?=null
    private var completion: ((VehicleClimateHostResult)->Unit)?=null
    private var review: ((ClimateTarget,(Boolean)->Unit)->Unit)?=null
    private var reviewTimeout: VehicleCancellation?=null
    private var closed=false
    private var attempted=false
    private var acking=false
    private val acknowledgements=java.util.ArrayDeque<Pair<String,JSONObject>>()
    private var outcome: VehicleClimateHostResult?=null
    private var commandOutcome: VehicleCommandOutcome?=null
    private var drivingBlocked=false
    private var moreQueuedRequests=false
    private var pollId=0L
    private var pollStarted=0L
    private var phase="idle"
    var hasPendingRequests=false
        private set

    init { lane.dispatch { hardware.start() } }

    /** One direct friend command per call; the receiver service owns scheduling and consent. */
    fun checkPending(review: (ClimateTarget,(Boolean)->Unit)->Unit,callback: (VehicleClimateHostResult)->Unit)=lane.dispatch {
        if(completion==null)hasPendingRequests=false
        if(closed || completion!=null || !safe()) {callback(VehicleClimateHostResult.BLOCKED);return@dispatch}
        if(actions.isEmpty()) {callback(VehicleClimateHostResult.NO_SUPPORTED_REQUEST);return@dispatch}
        pollId++;pollStarted=lane.nowElapsedMillis();phase="session";moreQueuedRequests=false
        val initialized=hardware.start()
        if(initialized is VehicleReply.Failed) {
            trace("failed","reason=${initialized.reason.name.lowercase()}")
            callback(VehicleClimateHostResult.UNAVAILABLE);return@dispatch
        }
        completion=callback;this.review=review;attempted=false;outcome=null;commandOutcome=null;drivingBlocked=false
        val currentPoll=pollId
        trace("poll started")
        if(transport.current())readInbox()
        else {
            phase="transport_open"
            transport.open({lane.dispatch {trace("failed","reason=transport_invalidated");invalidate()} }) {result->
                if(!current(currentPoll))return@open
                trace(if(result.isSuccess)"transport opened" else "failed",failure(result))
                if(result.isSuccess && safe())readInbox() else finish(VehicleClimateHostResult.UNAVAILABLE)
            }
        }
    }
    private fun readInbox() {
        val currentPoll=pollId
        val historyToken=history.captureToken();inboxHistoryToken=historyToken
        phase="inbox"
        transport.inbox {result->
            if(!current(currentPoll))return@inbox
            val inbox=result.getOrNull()
            if(inbox==null || !safe()) {history.clearPending(historyToken);trace("failed",failure(result));finish(VehicleClimateHostResult.UNAVAILABLE);return@inbox}
            val supported=actions.filterValues {inbox.descriptors[it.id]?.toString()==it.revision}
            history.pending(historyToken,vehiclePendingEntries(inbox,lane.nowElapsedMillis(),senderName,
                supported.values.associate {it.id to it.revision}))
            val pending=mutableListOf<VehicleClimateNativeTransport.Request>()
            val skipped=linkedMapOf("not_friend" to 0,"not_queued" to 0,"untrusted_action" to 0,
                "request_revision" to 0,"descriptor_revision" to 0)
            for(row in inbox.requests) {
                val trusted=actions.values.firstOrNull {it.id==row.capabilityId}
                val reason=when {
                    !row.friendRemote->"not_friend"
                    row.stage!="queued"->"not_queued"
                    trusted==null->"untrusted_action"
                    trusted.revision!=row.revision.toString()->"request_revision"
                    inbox.descriptors[row.capabilityId]?.toString()!=trusted.revision->"descriptor_revision"
                    else->null
                }
                if(reason==null)pending+=row else skipped[reason]=skipped.getValue(reason)+1
            }
            pending.sortBy {it.createdAtMillis}
            trace("polled","received_rows=${inbox.requests.size} queued=${pending.size} skipped=${inbox.requests.size-pending.size} "+
                skipped.entries.joinToString(" ") {"discarded_${it.key}=${it.value}"})
            val request=pending.firstOrNull()
            if(request==null) {finish(VehicleClimateHostResult.NO_SUPPORTED_REQUEST);return@inbox}
            moreQueuedRequests=pending.size>1
            phase="claim"
            transport.claim(request.id) {claimed->
                if(!current(currentPoll))return@claim
                val value=claimed.getOrNull()
                if(value==null || !safe() || !transport.current(value)) {
                    val reason=if(claimed.isFailure)failure(claimed) else "reason=claim_not_current"
                    trace("failed","$reason claim_remaining_ms=${value?.let {it.deadlineElapsedMillis-lane.nowElapsedMillis()} ?: -1}")
                    finish(VehicleClimateHostResult.UNAVAILABLE);return@claim
                }
                claim=value
                trace("claimed")
                claimHistoryToken=history.captureToken(value.epoch)
                val property=supported.entries.singleOrNull {it.value.id==value.capabilityId && it.value.revision==value.revision.toString()}?.key
                val target=property?.let {decode(it,value.arguments)}
                history.advance(claimHistoryToken,value.id,value.requesterId?.let(senderName),target?.let(::vehicleRemoteAction) ?: "리모컨 조작",
                    VehicleRemoteResult.DELIVERED,value.deadlineElapsedMillis)
                if(target==null) {
                    commandOutcome=VehicleCommandOutcome(VehicleCommandState.BLOCKED,VehicleFailure.INVALID_VALUE)
                    outcome=VehicleClimateHostResult.BLOCKED;enqueue("rejected",JSONObject());return@claim
                }
                lease=VehicleCommandLease(value.id,value.ownerId,value.deviceId,value.grantId,
                    "device-commands:receive",value.leaseId,value.capabilityId,value.revision.toString(),value.epoch,value.deadlineElapsedMillis)
                reviewTimeout=lane.schedule((value.deadlineElapsedMillis-lane.nowElapsedMillis()).coerceAtLeast(1)) {
                    if(claim===value) {trace("failed","reason=review_timeout");commandOutcome=VehicleCommandOutcome(VehicleCommandState.FAILED,VehicleFailure.TIMEOUT);invalidate()}
                }
                phase="review"
                review?.invoke(target) { approved->lane.dispatch decision@{
                    if(completion==null || claim!==value)return@decision
                    reviewTimeout?.cancel();reviewTimeout=null
                    if(!safe() || !transport.current(value)) {finish(VehicleClimateHostResult.BLOCKED);return@decision}
                    if(!approved) {
                        commandOutcome=VehicleCommandOutcome(VehicleCommandState.BLOCKED,VehicleFailure.CANCELLED)
                        outcome=VehicleClimateHostResult.BLOCKED;enqueue("rejected",JSONObject());return@decision
                    }
                // Server validates current explicit device + room grants again on this ACK.
                phase="ack_received"
                trace("ack queued","stage=received")
                transport.ack(value,"received",JSONObject()) {ack->
                    if(!current(currentPoll) || claim!==value)return@ack
                    trace(if(ack.isSuccess)"acknowledged" else "failed","stage=received ${failure(ack)}")
                    if(ack.isFailure || !safe() || !transport.current(value)) {
                        if(ack.isSuccess)trace("failed","reason=ack_not_current")
                        finish(VehicleClimateHostResult.UNAVAILABLE);return@ack
                    }
                    val command=VehicleClimateCommandExecutor(port,lane,::authority,supported)
                    history.advance(claimHistoryToken,value.id,value.requesterId?.let(senderName),vehicleRemoteAction(target),
                        VehicleRemoteResult.RECEIVED,value.deadlineElapsedMillis)
                    executor=command
                    command.execute(requireNotNull(lease),target,{stage->
                        phase=stage.name.lowercase();trace("sdk advanced")
                        if(stage==VehicleCommandStage.SETTER_READY)attempted=true
                        if(stage==VehicleCommandStage.SDK_ACCEPTED) {
                            history.advance(claimHistoryToken,value.id,value.requesterId?.let(senderName),vehicleRemoteAction(target),
                                VehicleRemoteResult.PROCESSING,value.deadlineElapsedMillis)
                            enqueue("sdk-accepted",evidence("pleos-vehicle-setter-v1",value,target))
                        }
                    }) {result->
                        if(!current(currentPoll) || claim!==value)return@execute
                        commandOutcome=result
                        trace(if(result.state==VehicleCommandState.TARGET_CONFIRMED)"applied" else "failed",
                            "state=${result.state.name.lowercase()} reason=${result.reason?.name?.lowercase() ?: "none"} attempted=${result.mayHaveExecuted} readback_attempts=${result.readbackAttempts} readback_wait_ms=${result.readbackWaitMillis ?: -1}")
                        val state=safety()
                        drivingBlocked=result.state==VehicleCommandState.BLOCKED && result.reason==VehicleFailure.EXPIRED_AUTHORITY &&
                            state.carUxKnown && !state.parked && !state.suspended && state.receiverActive &&
                            DRIVING_RECEIVER_CLIMATE_ACTIONS[target.property]==null
                        outcome=when(result.state) {
                            VehicleCommandState.TARGET_CONFIRMED->VehicleClimateHostResult.CONFIRMED
                            VehicleCommandState.UNKNOWN->VehicleClimateHostResult.UNKNOWN
                            VehicleCommandState.BLOCKED,VehicleCommandState.UNSUPPORTED->VehicleClimateHostResult.BLOCKED
                            else->VehicleClimateHostResult.UNAVAILABLE
                        }
                        val stage=if(result.state==VehicleCommandState.TARGET_CONFIRMED)"state-confirmed"
                            else if(result.mayHaveExecuted)"unknown" else "rejected"
                        val proof=if(stage=="state-confirmed")evidence("pleos-vehicle-getter-v1",value,target)
                            .put("receivedAtElapsedMillis",result.readbackReceivedAtElapsedMillis)
                            .put("capturedAtMillis",JSONObject.NULL)
                            else if(stage=="rejected")vehicleRejectionEvidence(vehicleRemoteResult(result,drivingBlocked))
                            else JSONObject()
                        enqueue(stage,proof)
                    }
                }
                } }
            }
        }
    }
    private fun enqueue(stage: String,evidence: JSONObject) {
        acknowledgements.add(stage to evidence);drain()
    }
    private fun drain() {
        if(acking || completion==null)return
        val next=acknowledgements.poll()
        if(next==null) {outcome?.let(::finish);return}
        val current=claim
        if(current==null || !transport.current(current)) {invalidate();return}
        acking=true
        trace("ack queued","stage=${next.first}")
        transport.ack(current,next.first,next.second) {result->
            if(completion==null || claim!==current)return@ack
            acking=false
            trace(if(result.isSuccess)"acknowledged" else "failed","stage=${next.first} ${failure(result)}")
            if(result.isFailure)invalidate() else {
                if(next.first in setOf("state-confirmed","rejected"))hasPendingRequests=moreQueuedRequests
                drain()
            }
        }
    }
    private fun authority(): VehicleCommandAuthority {
        val state=safety()
        return VehicleCommandAuthority(lease?.takeIf {claim?.let(transport::current)==true},
            state.foreground,state.parked,state.carUxKnown,state.setupAllowed,state.suspended,state.receiverActive)
    }
    private fun safe()=runCatching {safety().let {it.permitsReceiver()}}.getOrDefault(false)
    /** Call on foreground/CarUx/Park/Suspend changes; no inverse setter is sent. */
    fun authorityChanged()=lane.dispatch {if(!safe())invalidate() else executor?.authorityChanged()}
    private fun invalidate() {
        history.clearPending(inboxHistoryToken)
        lease=null
        executor?.authorityChanged()
        finish(if(attempted)VehicleClimateHostResult.UNKNOWN else VehicleClimateHostResult.BLOCKED)
    }
    private fun finish(result: VehicleClimateHostResult) {
        if(result !in setOf(VehicleClimateHostResult.CONFIRMED,VehicleClimateHostResult.BLOCKED))hasPendingRequests=false
        if(completion!=null)trace("finished","result=${result.name.lowercase()} more_queued=$hasPendingRequests")
        val callback=completion;completion=null;review=null;reviewTimeout?.cancel();reviewTimeout=null
        val received=claim
        received?.let(transport::release)
        if(callback!=null && received!=null) {
            val property=actions.entries.singleOrNull {it.value.id==received.capabilityId}?.key
            val target=property?.let {decode(it,received.arguments)}
            val expired=lane.nowElapsedMillis()>=received.deadlineElapsedMillis
            val details=commandOutcome ?: VehicleCommandOutcome(when(result) {
                VehicleClimateHostResult.CONFIRMED->VehicleCommandState.TARGET_CONFIRMED
                VehicleClimateHostResult.UNKNOWN->VehicleCommandState.UNKNOWN
                else->VehicleCommandState.BLOCKED
            },when {
                expired->VehicleFailure.TIMEOUT
                result==VehicleClimateHostResult.UNAVAILABLE->VehicleFailure.DISCONNECTED
                else->null
            },attempted)
            history.record(claimHistoryToken,received.requesterId?.let(senderName),target?.let(::vehicleRemoteAction) ?: "리모컨 조작",
                vehicleRemoteResult(details,drivingBlocked),details.mayHaveExecuted,requestId=received.id)
        }
        lease=null;claim=null;claimHistoryToken=null;outcome=null;acknowledgements.clear();acking=false
        executor?.close();executor=null
        hardware.failed(commandOutcome?.reason)
        callback?.invoke(result)
    }
    override fun close()=lane.dispatch {closed=true;invalidate();hardware.close();transport.close()}

    private fun current(expectedPoll: Long)=!closed && completion!=null && pollId==expectedPoll
    private fun failure(result: Result<*>): String {
        val error=result.exceptionOrNull() ?: return "reason=none"
        val failure=error as? NativeSocialFailure
        return "reason=${failure?.kind?.name?.lowercase() ?: "unavailable"} status=${failure?.httpStatus ?: 0}"
    }
    private fun trace(event: String,details: String="") {
        val now=lane.nowElapsedMillis()
        val action=actions.values.firstOrNull {it.id==claim?.capabilityId}?.id ?: "none"
        diagnostics("climate.receiver: $event poll=$pollId phase=$phase action=$action elapsed_ms=${now-pollStarted} remaining_ms=${claim?.let {it.deadlineElapsedMillis-now} ?: -1} $details")
    }

    private fun decode(property: ClimateProperty,args: JSONObject): ClimateTarget?=runCatching {
        decodeClimateTarget(property,args.keys().asSequence().associateWith { args.get(it) })
    }.getOrNull()
    private fun evidence(kind: String,claim: VehicleClimateNativeTransport.Claim,target: ClimateTarget)=
        JSONObject(target.arguments()).put("kind",kind).put("requestId",claim.id)
            .put("property",target.property.name).put("value",claim.arguments.get("value"))
}
