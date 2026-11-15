package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import java.security.SecureRandom

/** Private one-time pre-release data conversion, not an old public protocol.
 * Original ciphertext/AAD/key/identity remain untouched; only current public1
 * requests may leave the migrated store. Old private purposes never resume.
 */
internal object NativeConnectionMigration {
    private fun clone(value: JSONObject)=JSONObject(value.toString())
    private fun id()=ByteArray(16).also {SecureRandom().nextBytes(it)}.joinToString("") {"%02x".format(it.toInt() and 255)}
    private fun counter(value: Any): Long {
        check(value is Int || value is Long) {"NATIVE_STATE_MIGRATION_INVALID"}
        return (value as Number).toLong().also {check(it in 1..9007199254740990L) {"NATIVE_STATE_MIGRATION_INVALID"}}
    }
    fun fresh(root: JSONObject): JSONObject = JSONObject().put("version",1)
        .put("installationId",root.getString("installationId")).put("identityInitialized",true).put("publicContract",1)
        .put("access",JSONObject().put("epoch",1L).put("phase","ready").put("outbox",JSONArray()))

    fun convert(root: JSONObject, expectedKey: String): JSONObject {
        val marker=root.opt("publicContract")
        if(marker!=null) {
            check((marker is Int || marker is Long) && (marker as Number).toLong()==1L &&
                root.has("access") && !root.has("accessV2") && !root.has("credentials")) {"NATIVE_STATE_MIGRATION_INVALID"}
            return clone(root)
        }
        check(!root.has("access")) {"NATIVE_STATE_MIGRATION_INVALID"}
        val previous=root.optJSONObject("accessV2")
        val next=fresh(root)
        val state=next.getJSONObject("access").put("epoch",if(previous==null) 1L else counter(previous.get("epoch"))+1)
            .put("phase","locked")
        previous?.optJSONObject("certificate")?.let {
            check(it.getString("installationKeyId")==expectedKey) {"NATIVE_STATE_MIGRATION_INVALID"}
            state.put("certificate",clone(it))
        }
        val outbox=state.getJSONArray("outbox")
        val pendingByGrant=mutableMapOf<String,JSONObject>()
        fun append(request: JSONObject, staged: JSONObject?=null) {
            check(request.keys().asSequence().toSet()==setOf("authorizationVersion","operationId","grantId","revokeCapability")) {"NATIVE_STATE_MIGRATION_INVALID"}
            val version=request.get("authorizationVersion")
            check((version is Int || version is Long) && (version as Number).toLong()==2L) {"NATIVE_STATE_MIGRATION_INVALID"}
            val grant=request.getString("grantId");val cap=NativeAccessCodec.secret(request.get("revokeCapability"))
            check(Regex("[a-f0-9]{32}").matches(grant) && Regex("[A-Za-z0-9_-]{43}").matches(cap)) {"NATIVE_STATE_MIGRATION_INVALID"}
            val item=pendingByGrant[grant]?.also {
                check(it.getJSONObject("request").getString("revokeCapability")==cap) {"NATIVE_STATE_MIGRATION_INVALID"}
            } ?: JSONObject().put("request",JSONObject().put("authorizationVersion",1)
                .put("operationId",id()).put("grantId",grant).put("revokeCapability",cap)).also {
                    pendingByGrant[grant]=it;outbox.put(it)
                }
            staged?.let {
                check(it.getString("installationKeyId")==expectedKey) {"NATIVE_STATE_MIGRATION_INVALID"}
                item.optJSONObject("stagedCertificate")?.let {old ->
                    check(NativeAccessCodec.canonical(old).contentEquals(NativeAccessCodec.canonical(it))) {"NATIVE_STATE_MIGRATION_INVALID"}
                }
                item.put("stagedCertificate",clone(it))
            }
        }
        previous?.optJSONArray("outbox")?.let {old ->
            check(old.length()<=128) {"NATIVE_STATE_MIGRATION_INVALID"}
            for(i in 0 until old.length()) {val item=old.getJSONObject(i);append(item.getJSONObject("request"),item.optJSONObject("stagedCertificate"))}
        }
        previous?.optJSONObject("credentials")?.let {credential ->
            check(credential.getString("installationKeyId")==expectedKey) {"NATIVE_STATE_MIGRATION_INVALID"}
            val staged=previous.optJSONObject("renewal")?.let {renewal ->
                renewal.optJSONObject("stagedCertificate")?.also {
                    check(renewal.getJSONObject("request").getString("grantId")==credential.getString("grantId")) {"NATIVE_STATE_MIGRATION_INVALID"}
                }
            }
            append(JSONObject().put("authorizationVersion",2).put("operationId",id())
                .put("grantId",credential.getString("grantId")).put("revokeCapability",credential.getString("revokeCapability")),staged)
        }
        previous?.optJSONObject("authorization")?.let {auth ->
            val grant=auth.optJSONObject("response")?.optString("grantId")
            if(!grant.isNullOrEmpty() && auth.has("revokeCapability")) append(JSONObject().put("authorizationVersion",2)
                .put("operationId",id()).put("grantId",grant).put("revokeCapability",auth.getString("revokeCapability")),auth.optJSONObject("stagedCertificate"))
        }
        state.put("phase",if(outbox.length()>0) "revoke_pending" else "locked")
        return next
    }
}
