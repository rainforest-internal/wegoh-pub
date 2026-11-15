package io.wegoh.app.nativeauth

import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class NativeFunctionalCodecTest {
    private fun contract()=JSONObject(File("src/main/assets/native_access_wire.json").readText())
        .getJSONObject("functional")
    private val device="a".repeat(32)
    private val grant="b".repeat(32)
    private fun response(contract: JSONObject)=JSONObject()
        .put("authorizationVersion",1).put("deviceId",device).put("grantId",grant)
        .put("revision",1).put("expiresAt",2000).put("approvedPurposes",JSONArray().put("rooms:read"))
        .put("functionalDisclosureVersion",contract.getInt("disclosureVersion"))
        .put("functionalDisclosureSha256",contract.getString("disclosureSha256"))
        .put("approvedDisclosureVersion",3)
    private fun decode(codec: NativeFunctionalCodec,value: JSONObject)=
        codec.permissions(value,device,grant,2000000,1000000)

    @Test fun currentPresentationPreservesTheOriginalApprovalWithoutGrantingPurposes() {
        val contract=contract();val codec=NativeFunctionalCodec(contract)
        val value=decode(codec,response(contract))
        assertEquals(contract.getJSONObject("nativePresentation").getInt("currentVersion"),value.disclosureVersion)
        assertEquals(3,value.approvedDisclosureVersion)
        assertEquals(setOf(FunctionalPurpose.ROOMS_READ),value.approvedPurposes)
        assertFalse(value.allows(FunctionalPurpose.DRIVING_SCORE_REPORT))
        assertNull(decode(codec,response(contract).put("approvedDisclosureVersion",JSONObject.NULL)).approvedDisclosureVersion)
    }

    @Test fun earlierPresentationsAreRejectedEvenWithTheirAuthenticFrozenHashes() {
        val contract=contract();val codec=NativeFunctionalCodec(contract)
        val previous=contract.getJSONArray("previousDisclosures")
        for(index in 0 until previous.length()) {
            val old=previous.getJSONObject(index)
            val value=response(contract).put("functionalDisclosureVersion",old.getInt("version"))
                .put("functionalDisclosureSha256",old.getString("sha256"))
            assertTrue("Reject old presentation ${old.getInt("version")}",runCatching {decode(codec,value)}.isFailure)
            value.remove("approvedDisclosureVersion")
            assertTrue(runCatching {decode(codec,value)}.isFailure)
        }
    }

    @Test fun currentPayloadRequiresExactProofFieldsIdentityAndExpiry() {
        val contract=contract();val codec=NativeFunctionalCodec(contract)
        val invalid=listOf<Pair<String,Any>>(
            "functionalDisclosureVersion" to true,
            "functionalDisclosureVersion" to contract.getInt("disclosureVersion")+1,
            "functionalDisclosureSha256" to "f".repeat(64),
            "approvedDisclosureVersion" to true,
            "approvedDisclosureVersion" to 0,
            "approvedDisclosureVersion" to contract.getInt("disclosureVersion")+1,
            "deviceId" to "d".repeat(32),"grantId" to "d".repeat(32),
            "expiresAt" to 1000,"expiresAt" to 2001)
        for((field,value) in invalid)assertTrue(field,runCatching {decode(codec,response(contract).put(field,value))}.isFailure)
        assertTrue(runCatching {decode(codec,response(contract).apply {remove("approvedDisclosureVersion")})}.isFailure)
    }

    @Test fun bundledCurrentDisclosureMustMatchItsRegistryAndPresentation() {
        val modified=contract()
        modified.getJSONArray("purposeRegistry").getJSONObject(0).put("label","Changed current disclosure")
        assertTrue(runCatching {NativeFunctionalCodec(modified)}.isFailure)
        val mismatched=contract()
        mismatched.getJSONObject("nativePresentation").put("currentVersion",mismatched.getInt("disclosureVersion")-1)
        assertTrue(runCatching {NativeFunctionalCodec(mismatched)}.isFailure)
    }

    @Test fun sameRevisionCannotExchangeDisclosureHashOrApprovalAndReviveQueuedWork() {
        val contract=contract();val codec=NativeFunctionalCodec(contract)
        val current=decode(codec,response(contract));val gate=FunctionalPermissionGate()
        gate.replace(current)
        val queued=gate.stamp(FunctionalPurpose.ROOMS_READ,1000000)
        fun changed(version: Int=current.disclosureVersion,hash: String=current.disclosureSha256,approved: Int?=3)=
            FunctionalPermissions(device,grant,current.revision,current.expiresAtMillis,current.approvedPurposes,version,hash,approved)
        for(next in listOf(changed(version=current.disclosureVersion-1),changed(hash="f".repeat(64)),changed(approved=null))) {
            assertTrue(runCatching {gate.replace(next)}.isFailure)
            assertTrue(gate.current(queued,1000001))
        }
        val renewed=decode(codec,response(contract).put("revision",2).put("approvedDisclosureVersion",codec.disclosureVersion))
        assertTrue(gate.replace(renewed));assertFalse(gate.current(queued,1000001))
        assertEquals(current.approvedPurposes,renewed.approvedPurposes)
    }
}
