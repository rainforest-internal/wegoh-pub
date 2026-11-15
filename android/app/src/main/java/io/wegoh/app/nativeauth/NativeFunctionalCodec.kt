package io.wegoh.app.nativeauth

import org.json.JSONObject

/** Consumes the generated canonical contract. Credential scopes never imply purposes. */
internal class NativeFunctionalCodec(private val contract: JSONObject) {
    private val registry=contract.getJSONArray("purposeRegistry")
    val disclosureVersion=contract.getJSONObject("nativePresentation").get("currentVersion").let {
        check(it is Int || it is Long)
        (it as Number).toLong().also {version->check(version in 1..Int.MAX_VALUE.toLong())}.toInt()
    }
    private val currentPurposes=(0 until registry.length()).map {registry.getJSONObject(it).getString("id")}.toSet()
    private val disclosureSha256=contract.getString("disclosureSha256")
    init {
        check(contract.getLong("schemaVersion")==1L && contract.get("functionalRevisionIsCredentialEpoch")==false)
        val ids=(0 until registry.length()).map {registry.getJSONObject(it).also {row->check(row.get("default")== (row.getString("id")=="device-commands:receive"))}.getString("id")}
        check(ids==ids.distinct().sorted() && ids.toSet()==FunctionalPurpose.entries.map {it.wire}.toSet())
        check(contract.getLong("revisionMaximum")==Int.MAX_VALUE.toLong())
        check((contract.get("disclosureVersion") is Int || contract.get("disclosureVersion") is Long) &&
            contract.getLong("disclosureVersion")==disclosureVersion.toLong())
        check(Regex("[a-f0-9]{64}").matches(disclosureSha256))
        check(NativeDeviceIdentity.sha256(NativeAccessCodec.canonical(
            JSONObject().put("version",disclosureVersion).put("purposes",registry)))==disclosureSha256)
        check(contract.getJSONObject("apis").getJSONObject("nativeGet").getString("path")=="/v1/device/functional-permissions")
        val presentation=contract.getJSONObject("nativePresentation")
        check(presentation.getJSONArray("currentAdditionalResponseFields").toString()=="[\"approvedDisclosureVersion\"]")
    }
    fun permissions(value: JSONObject,deviceId: String,grantId: String,grantExpiry: Long,now: Long): FunctionalPermissions {
        val fields=contract.getJSONObject("apis").getJSONObject("nativeGet").getJSONObject("responseFields").keys().asSequence().toSet()
        val rawVersion=value.get("functionalDisclosureVersion")
        check(rawVersion is Int || rawVersion is Long)
        check((rawVersion as Number).toLong()==disclosureVersion.toLong())
        check(value.keys().asSequence().toSet()==fields+"approvedDisclosureVersion" &&
            (value.get("authorizationVersion") is Int || value.get("authorizationVersion") is Long) && value.getLong("authorizationVersion")==1L)
        for((field,expected) in listOf("deviceId" to deviceId,"grantId" to grantId)) {
            check(value.get(field) is String && value.getString(field)==expected && Regex("[a-f0-9]{32}").matches(expected))
        }
        fun integer(field: String,max: Long): Long {
            val raw=value.get(field);check(raw is Int || raw is Long)
            return (raw as Number).toLong().also {check(it in 0..max)}
        }
        val revision=integer("revision",Int.MAX_VALUE.toLong())
        val expires=integer("expiresAt",Long.MAX_VALUE/1000)*1000
        check(expires>now && expires<=grantExpiry)
        val version=integer("functionalDisclosureVersion",Int.MAX_VALUE.toLong()).toInt()
        val hash=value.get("functionalDisclosureSha256");check(hash is String)
        check(hash==disclosureSha256) {"NATIVE_FUNCTIONAL_DISCLOSURE_INVALID"}
        val list=value.getJSONArray("approvedPurposes");check(list.length()<=currentPurposes.size)
        val names=(0 until list.length()).map {check(list.get(it) is String);list.getString(it)}
        check(names==names.distinct().sorted() && names.all {it in currentPurposes} && (revision!=0L || names.isEmpty()))
        val purposes=names.map {FunctionalPurpose.fromWire(it)}.toSet()
        val approved=if(value.isNull("approvedDisclosureVersion"))null else
            integer("approvedDisclosureVersion",disclosureVersion.toLong()).toInt().also {check(it>0)}
        return FunctionalPermissions(deviceId,grantId,revision,expires,purposes,version,hash,approved)
    }
}
