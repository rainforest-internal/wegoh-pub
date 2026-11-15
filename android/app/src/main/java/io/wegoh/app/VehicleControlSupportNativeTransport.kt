package io.wegoh.app

import io.wegoh.app.nativeauth.*

import org.json.JSONArray
import org.json.JSONObject
import java.io.Closeable
import java.time.Instant

internal class VehicleControlSupportNativeTransport(connection: VehicleConnection): VehicleControlSupportTransport {
    private val client=connection.climateSocial()
    private var receiver: CommandReceiver?=null
    private var pending: Closeable?=null
    override fun open(onInvalidated: ()->Unit,callback: (Result<Unit>)->Unit) {
        client.open(object: NativeSocialObserver {
            override fun onInvalidated() {onInvalidated()}
            override fun onConnectionLost() {onInvalidated()}
            override fun onResourcesChanged(resources: Set<String>) {if("devices" in resources)onInvalidated()}
        }) {opened->
            if(opened.isFailure) {callback(opened);return@open}
            pending=client.call(NativeSocialRequest(setOf(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE),fetch={api,token,permission,_->
                CommandReceiver.decode(api.commandReceiver(token),permission.deviceId,permission.grantId).also {check(it.enabled)}
            })) {read->receiver=read.getOrNull();callback(read.map {})}
        }
    }
    override fun publish(actions: List<VehicleControlSupport>,callback: (Result<Unit>)->Unit): Closeable {
        val current=checkNotNull(receiver)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE),mutation=true,
            fetch={api,token,permission,_->
                check(current.enabled && current.deviceId==permission.deviceId && current.grantId==permission.grantId)
                val body=JSONObject().put("functionalRevision",permission.revision).put("receiverRevision",current.revision)
                    .put("actions",JSONArray(actions.map {it.json()}))
                val response=api.controlSupport(body,token)
                check(response.keys().asSequence().toSet()==setOf("status","observedAt","expiresAt"))
                check(response.getString("status")=="accepted")
                val observed=Instant.parse(response.getString("observedAt"))
                val expires=Instant.parse(response.getString("expiresAt"))
                check(expires.isAfter(observed) && !expires.isAfter(observed.plusSeconds(90)))
            }),callback)
    }
    override fun close() {pending?.close();pending=null;receiver=null;client.close()}
}
