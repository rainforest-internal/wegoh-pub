package io.wegoh.app.nativeauth

import android.os.SystemClock
import org.json.JSONObject
import java.io.Closeable
import java.time.Instant
import java.util.UUID

internal interface VehicleClimateTransport: Closeable {
    fun open(onInvalidated: ()->Unit,callback: (Result<Unit>)->Unit)
    fun current(claim: VehicleClimateNativeTransport.Claim?=null): Boolean
    fun inbox(callback: (Result<VehicleClimateNativeTransport.Inbox>)->Unit): Closeable
    fun claim(id: String,callback: (Result<VehicleClimateNativeTransport.Claim>)->Unit): Closeable
    fun ack(claim: VehicleClimateNativeTransport.Claim,stage: String,evidence: JSONObject,callback: (Result<Unit>)->Unit): Closeable
    fun release(claim: VehicleClimateNativeTransport.Claim) {}
}

internal interface VehicleClimateClient: Closeable {
    fun ready(): Boolean
    fun state(): String=if(ready())"ready" else "unavailable"
    fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit)
    fun adopt(epoch: Long,remainingMillis: Long,observer: NativeSocialObserver)
    fun invalidate()
    fun <T> call(request: NativeSocialRequest<T>,callback: (Result<T>)->Unit): Closeable
}

private class NativeClimateClient(private val client: NativeSocialClient): VehicleClimateClient {
    override fun ready()=client.status()==NativeSocialClient.State.READY
    override fun state()=client.status().name.lowercase()
    override fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit)=client.open(observer,callback)
    override fun adopt(epoch: Long,remainingMillis: Long,observer: NativeSocialObserver)=client.adoptClimateAcknowledgements(epoch,System.currentTimeMillis()+remainingMillis,observer)
    override fun invalidate()=client.authorityInvalidated("climate_host",connectionWide=false)
    override fun <T> call(request: NativeSocialRequest<T>,callback: (Result<T>)->Unit)=client.call(request,callback)
    override fun close()=client.close()
}

/** Authenticated receiver API; current device, room and explicit grant checks stay server-owned. */
internal class VehicleClimateNativeTransport(
    private val client: VehicleClimateClient,private val acknowledgementClient: ()->VehicleClimateClient,
    private val dataEpoch: ()->Long,private val baseCurrent: (Long)->Boolean,
    private val elapsed: ()->Long = SystemClock::elapsedRealtime,
    private val diagnostics: (String)->Unit={WegoLog.i("WegoClimate",it)}
): VehicleClimateTransport {
    constructor(connection: VehicleConnection):this(NativeClimateClient(connection.climateSocial()),
        {NativeClimateClient(connection.climateSocial())},connection::dataEpoch,connection::climateBaseCurrent)
    private var replies: VehicleClimateClient?=null
    private var activeClaim: Claim?=null
    @Volatile private var epoch=-1L
    private var invalidated: ()->Unit={}
    @Volatile private var closed=false
    class Request(val id: String,val capabilityId: String,val revision: Long,val friendRemote: Boolean,
        val stage: String,val createdAtMillis: Long,val requesterId: String?=null,val expiresAtMillis: Long?=null)
    class Inbox(val requests: List<Request>,val descriptors: Map<String,Long>,val labels: Map<String,String> = emptyMap(),val serverNowMillis: Long?=null) {
        fun queuedFriendRequests()=requests.filter {it.friendRemote && it.stage=="queued"}
            .sortedBy {it.createdAtMillis}
    }
    class Claim(
        val id: String,val ownerId: String,val deviceId: String,val grantId: String,
        val capabilityId: String,val revision: Long,val leaseId: String,
        val arguments: JSONObject,val deadlineElapsedMillis: Long,val epoch: Long,
        val requesterId: String?=null
    ) {
        override fun toString()="VehicleClimateClaim(redacted)"
    }
    override fun open(onInvalidated: ()->Unit,callback: (Result<Unit>)->Unit) {
        invalidated=onInvalidated
        diagnostics("climate.receiver: transport opening client_state=${client.state()}")
        client.open(object: NativeSocialObserver {
            override fun onResourcesChanged(resources: Set<String>) {
                diagnostics("climate.receiver: transport changed source=resource_event devices=${"devices" in resources}")
                if("devices" in resources && activeClaim!=null)this.onInvalidated()
            }
            override fun onConnectionLost() {
                val retained=activeClaim?.let(::current)==true
                diagnostics("climate.receiver: transport disconnected source=connection_lost claim_retained=$retained")
                if(!retained)this.onInvalidated()
            }
            override fun onInvalidated() {
                diagnostics("climate.receiver: transport invalidated client_state=${client.state()}")
                invalidate()
            }
        }) {result->
            diagnostics("climate.receiver: transport open completed success=${result.isSuccess} client_state=${client.state()}")
            if(result.isSuccess)epoch=dataEpoch();callback(result)
        }
    }
    override fun current(claim: Claim?)=!closed && epoch>=0 && baseCurrent(epoch) &&
        if(claim==null)client.ready() else claim===activeClaim && replies?.ready()==true && claim.epoch==epoch && elapsed()<claim.deadlineElapsedMillis
    override fun inbox(callback: (Result<Inbox>)->Unit): Closeable = client.call(NativeSocialRequest(
        setOf(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE),fetch={api,token,permission,owner->
            WegoLog.i("WegoClimate",vehicleClimateInboxRoute(api.deviceCommandHost(),owner,permission))
            val value=api.deviceCommandExchange("GET","/v1/device/command-inbox",null,token)
            decodeVehicleClimateInbox(value) {WegoLog.i("WegoClimate",it)}
        }),callback)
    override fun claim(id: String,callback: (Result<Claim>)->Unit): Closeable {
        identifier(id)
        val queuedAt=elapsed()
        val expected=epoch
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE),mutation=true,
            fetch={api,token,permission,owner->
                val started=elapsed()
                WegoLog.i("WegoClimate","climate.receiver: claim started preflight_ms=${started-queuedAt}")
                val value=api.deviceCommandExchange("POST","/v1/device/requests/$id/claim",
                    JSONObject().put("claimId",event()).put("functionalRevision",permission.revision),token)
                check(value.has("roomId") && value.isNull("roomId") && value.getString("id")==id && value.getString("ownerId")==owner &&
                    value.getString("targetDeviceId")==permission.deviceId && value.getString("stage")=="delivered")
                val serverNow=Instant.parse(value.getString("serverNow")).toEpochMilli()
                val deadline=vehicleClimateLeaseDeadline(started,serverNow,
                    Instant.parse(value.getString("leaseExpiresAt")).toEpochMilli(),permission.expiresAtMillis)
                val now=elapsed()
                WegoLog.i("WegoClimate","climate.receiver: claim loaded http_ms=${now-started} remaining_ms=${deadline-now}")
                val lease=value.getString("leaseId");check(lease.length in 1..100)
                Claim(id,owner,permission.deviceId,permission.grantId,value.getString("capabilityId"),
                    value.getLong("capabilityRevision"),lease,JSONObject(value.getJSONObject("arguments").toString()),
                    deadline,expected,value.getString("requesterId"))
            })) {result->
                val adopted=result.mapCatching {claim->
                    check(current() && claim.epoch==epoch && claim.deadlineElapsedMillis>elapsed() && activeClaim==null)
                    val channel=acknowledgementClient()
                    activeClaim=claim;replies=channel
                    try {channel.adopt(epoch,claim.deadlineElapsedMillis-elapsed(),object: NativeSocialObserver {
                        override fun onInvalidated() {if(replies===channel)invalidate()}
                        override fun onResourcesChanged(resources: Set<String>) {if("devices" in resources && replies===channel)invalidate()}
                    })} catch(error: Exception) {release(claim);throw error}
                    claim
                }
                callback(adopted)
            }
    }
    override fun ack(claim: Claim,stage: String,evidence: JSONObject,callback: (Result<Unit>)->Unit): Closeable {
        require(stage in setOf("received","sdk-accepted","state-confirmed","rejected","unknown"))
        val frozen=JSONObject(evidence.toString())
        val queuedAt=elapsed()
        val channel=replies
        if(channel==null || !current(claim)) {
            callback(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.STALE)));return Closeable {}
        }
        return channel.call(NativeSocialRequest(setOf(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE),mutation=true,climateAcknowledgement=true,
            fetch={api,token,permission,owner->
                val started=elapsed()
                WegoLog.i("WegoClimate","climate.receiver: ack started stage=$stage preflight_ms=${started-queuedAt} remaining_ms=${claim.deadlineElapsedMillis-started}")
                check(current(claim) && owner==claim.ownerId && permission.deviceId==claim.deviceId &&
                    permission.grantId==claim.grantId)
                val value=api.deviceCommandExchange("POST","/v1/device/requests/"+claim.id+"/ack",
                    JSONObject().put("ackId",event()).put("leaseId",claim.leaseId).put("stage",stage)
                        .put("evidence",frozen).put("functionalRevision",permission.revision),token)
                check(value.getString("id")==claim.id && value.getString("stage")==stage)
                val now=elapsed()
                WegoLog.i("WegoClimate","climate.receiver: ack loaded stage=$stage http_ms=${now-started} remaining_ms=${claim.deadlineElapsedMillis-now}")
                Unit
            }),callback)
    }
    override fun release(claim: Claim) {
        if(activeClaim!==claim)return
        activeClaim=null;val old=replies;replies=null;old?.close()
    }
    private fun invalidate() {
        val wasCurrent=epoch>=0
        epoch=-1;activeClaim?.let(::release)
        if(client.ready())client.invalidate()
        if(wasCurrent)invalidated()
    }
    override fun close() {closed=true;invalidate();client.close()}
    companion object {
        private fun identifier(value: String)=value.also {require(Regex("[a-f0-9]{32}").matches(it))}
        private fun event()=UUID.randomUUID().toString().replace("-","")
    }
}
