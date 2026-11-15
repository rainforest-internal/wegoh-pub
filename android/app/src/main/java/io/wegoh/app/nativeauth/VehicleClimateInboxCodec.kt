package io.wegoh.app.nativeauth

import org.json.JSONObject
import java.security.MessageDigest
import java.time.Instant

internal fun vehicleClimateInboxRoute(host: String,owner: String,permission: FunctionalPermissions): String {
    fun reference(value: String)=MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        .take(6).joinToString("") {"%02x".format(it.toInt() and 255)}
    return "climate.receiver: inbox requested host=$host account_ref=${reference(owner)} device_ref=${reference(permission.deviceId)} grant_ref=${reference(permission.grantId)} functional_revision=${permission.revision} token_source=connection_credentials"
}

internal fun decodeVehicleClimateInbox(value: JSONObject,diagnostics: (String)->Unit={}): VehicleClimateNativeTransport.Inbox {
    var received=-1
    var decoded=0
    var rowIndex=-1
    var reason="invalid_requests"
    try {
        val rows=value.getJSONArray("requests")
        received=rows.length()
        val serverTime=runCatching {Instant.parse(value.getString("serverNow")).toEpochMilli()}.getOrDefault(-1L)
        diagnostics("climate.receiver: inbox received received_rows=$received server_time_ms=$serverTime")
        reason="request_limit";check(received<=100)
        var nullRoom=0;var missingRoom=0;var otherRoom=0
        val requests=(0 until received).map {index->
            rowIndex=index;reason="invalid_row"
            val row=rows.getJSONObject(index)
            reason="invalid_request_id"
            val id=row.getString("id").also {check(Regex("[a-f0-9]{32}").matches(it))}
            reason="invalid_capability_id";val capability=row.getString("capabilityId")
            reason="invalid_capability_revision";val revision=row.getLong("capabilityRevision")
            val friend=row.has("roomId") && row.isNull("roomId")
            when {friend->nullRoom++;!row.has("roomId")->missingRoom++;else->otherRoom++}
            reason="invalid_stage";val stage=row.getString("stage")
            reason="invalid_created_at";val created=Instant.parse(row.getString("createdAt")).toEpochMilli()
            decoded++
            val requester=row.optString("requesterId").takeIf {Regex("team-[a-f0-9]{40}").matches(it)}
            val expires=runCatching {Instant.parse(row.getString("expiresAt")).toEpochMilli()}.getOrNull()
            VehicleClimateNativeTransport.Request(id,capability,revision,friend,stage,created,requester,expires)
        }
        rowIndex=-1;reason="duplicate_request_id"
        check(requests.map {it.id}.distinct().size==requests.size)
        reason="invalid_descriptors";val actions=value.getJSONArray("supportedControlActions")
        reason="descriptor_limit";check(actions.length()<=16)
        val descriptors=mutableMapOf<String,Long>()
        val labels=mutableMapOf<String,String>()
        for(i in 0 until actions.length()) {
            reason="invalid_descriptor"
            val action=actions.getJSONObject(i);val id=action.getString("id")
            val revision=action.getLong("revision")
            check(id.length in 1..80 && revision>0 && id !in descriptors)
            descriptors[id]=revision
            action.optString("label").takeIf {it.isNotBlank() && it.length<=80 && it.none {c->c.code<32}}?.let {labels[id]=it}
        }
        val queued=requests.count {it.stage=="queued"}
        diagnostics("climate.receiver: inbox parsed received_rows=$received decoded_rows=$decoded discarded_rows=0 room_null=$nullRoom room_missing=$missingRoom room_other=$otherRoom queued_rows=$queued other_stage_rows=${received-queued} descriptors=${descriptors.size}")
        return VehicleClimateNativeTransport.Inbox(requests,descriptors.toMap(),labels.toMap(),serverTime.takeIf {it>=0})
    } catch(error: Exception) {
        diagnostics("climate.receiver: inbox failed received_rows=$received decoded_rows=$decoded discarded_rows=$received row_index=$rowIndex reason=$reason response_rejected=true")
        throw error
    }
}
