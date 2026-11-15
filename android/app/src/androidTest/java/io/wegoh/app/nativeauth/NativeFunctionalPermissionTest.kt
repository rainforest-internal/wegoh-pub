package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase

@Suppress("DEPRECATION")
class NativeFunctionalPermissionTest: InstrumentationTestCase() {
    private fun permissions(revision: Long=1,purposes: Set<FunctionalPurpose> = setOf(FunctionalPurpose.ROOMS_READ),
        expires: Long=1000,device: String="a".repeat(32),grant: String="b".repeat(32)) =
        FunctionalPermissions(device,grant,revision,expires,purposes,1,"c".repeat(64))

    fun testCachedPermissionRequiresTheSameDeviceGrantAndUnexpiredBoundary() {
        val gate=FunctionalPermissionGate();val current=permissions()
        assertNull(gate.cached(current.deviceId,current.grantId,100))
        gate.replace(current)
        assertSame(current,gate.cached(current.deviceId,current.grantId,999))
        assertNull(gate.cached(current.deviceId,current.grantId,1000))
        assertNull(gate.cached("d".repeat(32),current.grantId,100))
        assertNull(gate.cached(current.deviceId,"d".repeat(32),100))
        val stamp=gate.stamp(FunctionalPurpose.ROOMS_READ,100)
        gate.clear()
        assertNull(gate.cached(current.deviceId,current.grantId,100))
        assertFalse(gate.current(stamp,101))
    }

    fun testReceiverAndAccountDefaultsChangeWithoutReplacingTheFunctionalRevision() {
        val gate = FunctionalPermissionGate()
        val base = setOf(FunctionalPurpose.ROOMS_READ)
        val receiver = FunctionalPurpose.DEVICE_COMMANDS_RECEIVE
        gate.replace(permissions(purposes=base))
        val before = gate.stamp(FunctionalPurpose.ROOMS_READ, 100)
        assertTrue(gate.replace(permissions(purposes=base + receiver)))
        assertFalse(gate.current(before, 100))
        val receiving = gate.stamp(receiver, 100)
        assertTrue(gate.replace(permissions(purposes=base)))
        assertFalse(gate.current(receiving, 100))
        assertTrue(runCatching { gate.replace(permissions(purposes=base + FunctionalPurpose.FRIENDS_MANAGE)) }.isFailure)

        val account = FunctionalPurpose.accountPurposes
        assertTrue(gate.replace(permissions(purposes=account + receiver)))
        val withDefaults = gate.stamp(FunctionalPurpose.HISTORY_READ, 100)
        assertTrue(runCatching { gate.replace(permissions(purposes=account + FunctionalPurpose.VEHICLE_LOCATION_REPORT)) }.isFailure)
        assertTrue(runCatching { gate.replace(permissions(purposes=base)) }.isFailure)
        assertTrue(gate.current(withDefaults, 100))
    }

    fun testConsentIsExplicitAndQueuedAuthorityExpires() {
        val gate=FunctionalPermissionGate()
        assertTrue(runCatching {gate.stamp(FunctionalPurpose.ROOMS_READ,100)}.exceptionOrNull() is FunctionalPermissionRequired)
        gate.replace(permissions(purposes=emptySet()))
        assertTrue(runCatching {gate.stamp(FunctionalPurpose.ROOMS_READ,100)}.exceptionOrNull() is FunctionalPermissionRequired)
        gate.replace(permissions(2))
        val allowed=gate.stamp(FunctionalPurpose.ROOMS_READ,100)
        assertTrue(gate.current(allowed,999))
        assertFalse(gate.current(allowed,1000))
        assertTrue(runCatching {gate.stamp(FunctionalPurpose.ROOMS_READ,1000)}.exceptionOrNull() is FunctionalPermissionRequired)
        assertTrue(runCatching {gate.stamp(FunctionalPurpose.ROOMS_INTERACT,100)}.exceptionOrNull() is FunctionalPermissionRequired)
        gate.replace(permissions(3,purposes=emptySet()))
        assertFalse(gate.current(allowed,101))
        gate.clear()
        assertFalse(gate.current(allowed,101))
        assertTrue(runCatching {FunctionalPurpose.fromWire("rooms:admin")}.isFailure)
    }

    fun testRevisionCannotMutateOrReviveCapturedWork() {
        val gate=FunctionalPermissionGate();gate.replace(permissions(3))
        val original=gate.stamp(FunctionalPurpose.ROOMS_READ,100)
        assertTrue(runCatching {gate.replace(permissions(2))}.isFailure)
        assertTrue(runCatching {gate.replace(permissions(3,purposes=setOf(FunctionalPurpose.ROOMS_INTERACT)))}.isFailure)
        assertTrue(runCatching {gate.replace(permissions(3,expires=2000))}.isFailure)
        assertTrue(gate.current(original,101))
        val mutable=mutableSetOf(FunctionalPurpose.ROOMS_READ)
        val snapshot=permissions(4,purposes=mutable);mutable.add(FunctionalPurpose.ROOMS_INTERACT)
        gate.replace(snapshot)
        assertFalse(snapshot.allows(FunctionalPurpose.ROOMS_INTERACT))
        assertFalse(gate.current(original,101))
        assertTrue(runCatching {(snapshot.approvedPurposes as MutableSet).clear()}.isFailure)
        gate.replace(permissions(1,grant="d".repeat(32)))
        assertFalse(gate.current(original,101))
    }

    fun testDrivingScoreSharingRequiresAnExplicitNewConsentRevision() {
        val score=FunctionalPurpose.DRIVING_SCORE_REPORT
        assertFalse(score in FunctionalPurpose.accountPurposes)
        val gate=FunctionalPermissionGate()
        gate.replace(permissions(purposes=FunctionalPurpose.accountPurposes))
        assertTrue(runCatching {gate.stamp(score,100)}.exceptionOrNull() is FunctionalPermissionRequired)
        assertTrue(runCatching {gate.replace(permissions(purposes=FunctionalPurpose.accountPurposes+score))}.isFailure)
        gate.replace(permissions(2,purposes=FunctionalPurpose.accountPurposes+score))
        val granted=gate.stamp(score,100)
        assertTrue(gate.current(granted,101))
        gate.replace(permissions(3,purposes=FunctionalPurpose.accountPurposes))
        assertFalse(gate.current(granted,102))
    }

    fun testCurrentPresentationRejectsOlderPayloadsWithoutChangingAuthority() {
        val wire=org.json.JSONObject(instrumentation.targetContext.assets.open("native_access_wire.json").bufferedReader().use {it.readText()})
        val contract=wire.getJSONObject("functional");val codec=NativeFunctionalCodec(contract)
        fun body()=
            org.json.JSONObject().put("authorizationVersion",1).put("deviceId","a".repeat(32)).put("grantId","b".repeat(32))
                .put("revision",1).put("expiresAt",2000).put("approvedPurposes",org.json.JSONArray().put("rooms:read"))
                .put("functionalDisclosureVersion",codec.disclosureVersion)
                .put("functionalDisclosureSha256",contract.getString("disclosureSha256"))
                .put("approvedDisclosureVersion",3)
        fun decode(value: org.json.JSONObject)=codec.permissions(value,"a".repeat(32),"b".repeat(32),2000000,1000000)
        val gate=FunctionalPermissionGate()
        val current=decode(body())
        gate.replace(current)
        val before=gate.stamp(FunctionalPurpose.ROOMS_READ,1000000)
        assertEquals(codec.disclosureVersion,current.disclosureVersion)
        assertEquals(3,current.approvedDisclosureVersion)
        val previous=contract.getJSONArray("previousDisclosures")
        for(index in 0 until previous.length()) {
            val old=previous.getJSONObject(index)
            val payload=body().put("functionalDisclosureVersion",old.getInt("version"))
                .put("functionalDisclosureSha256",old.getString("sha256"))
            assertTrue(runCatching {gate.replace(decode(payload))}.isFailure)
            assertTrue(gate.current(before,1000001))
        }
        assertNull(decode(body().put("approvedDisclosureVersion",org.json.JSONObject.NULL)).approvedDisclosureVersion)
    }

    fun testCanonicalSnapshotIsClosedAndBoundToExactLiveGrant() {
        val wire=org.json.JSONObject(instrumentation.targetContext.assets.open("native_access_wire.json").bufferedReader().use {it.readText()})
        val contract=wire.getJSONObject("functional");val codec=NativeFunctionalCodec(contract)
        fun body()=org.json.JSONObject().put("authorizationVersion",1).put("deviceId","a".repeat(32)).put("grantId","b".repeat(32))
            .put("revision",1).put("expiresAt",2000).put("approvedPurposes",org.json.JSONArray().put("friends:read").put("rooms:read"))
            .put("functionalDisclosureVersion",contract.getInt("disclosureVersion"))
            .put("functionalDisclosureSha256",contract.getString("disclosureSha256"))
            .put("approvedDisclosureVersion",4)
        fun decode(value: org.json.JSONObject)=codec.permissions(value,"a".repeat(32),"b".repeat(32),2000000,1000000)
        assertEquals(setOf(FunctionalPurpose.FRIENDS_READ,FunctionalPurpose.ROOMS_READ),decode(body()).approvedPurposes)
        assertTrue(decode(body().put("revision",0).put("approvedPurposes",org.json.JSONArray())).approvedPurposes.isEmpty())
        val invalid=listOf<Pair<String,Any>>(
            "authorizationVersion" to true,"revision" to true,"revision" to 1.5,"revision" to 2147483648L,
            "deviceId" to "d".repeat(32),"grantId" to "d".repeat(32),"expiresAt" to 0,"expiresAt" to 2001,
            "functionalDisclosureVersion" to contract.getInt("disclosureVersion")+1,"functionalDisclosureSha256" to "f".repeat(64),
            "approvedPurposes" to org.json.JSONArray().put("rooms:admin"),
            "approvedPurposes" to org.json.JSONArray().put("rooms:read").put("friends:read"),
            "approvedPurposes" to org.json.JSONArray().put("rooms:read").put("rooms:read"),
            "extraAuthority" to true)
        for((field,value) in invalid)assertTrue("Invalid functional DTO field: $field",runCatching {decode(body().put(field,value))}.isFailure)
        assertTrue(runCatching {decode(body().put("revision",0))}.isFailure)
        val canonical=body().toString().toByteArray(Charsets.UTF_8)
        assertEquals(2,decode(StrictNativeJson.parse(canonical,65536)).approvedPurposes.size)
        val duplicate=body().toString().dropLast(1)+",\"revision\":2}"
        assertTrue(runCatching {StrictNativeJson.parse(duplicate.toByteArray(Charsets.UTF_8),65536)}.isFailure)
    }

    fun testFunctionalTransportAllowsOnlyTheTopLevelNullableApprovalProof() {
        val wire=org.json.JSONObject(instrumentation.targetContext.assets.open("native_access_wire.json").bufferedReader().use {it.readText()})
        val contract=wire.getJSONObject("functional");val codec=NativeFunctionalCodec(contract)
        fun body()=org.json.JSONObject().put("authorizationVersion",1).put("deviceId","a".repeat(32)).put("grantId","b".repeat(32))
            .put("revision",0).put("expiresAt",2000).put("approvedPurposes",org.json.JSONArray())
            .put("functionalDisclosureVersion",codec.disclosureVersion).put("functionalDisclosureSha256",contract.getString("disclosureSha256"))
            .put("approvedDisclosureVersion",org.json.JSONObject.NULL)
        fun parse(text: String)=StrictNativeJson.parseFunctional(text.toByteArray(Charsets.UTF_8),65536)
        fun decode(value: org.json.JSONObject)=codec.permissions(value,"a".repeat(32),"b".repeat(32),2000000,1000000)
        val raw=body().toString()
        val parsed=parse(raw)
        assertEquals(9,parsed.length());assertTrue(parsed.isNull("approvedDisclosureVersion"))
        assertNull(decode(parsed).approvedDisclosureVersion)
        assertTrue(runCatching {StrictNativeJson.parse(raw.toByteArray(Charsets.UTF_8),65536)}.isFailure)
        val previous=contract.getJSONArray("previousDisclosures")
        for(version in listOf(2,3)) {
            val old=(0 until previous.length()).map {previous.getJSONObject(it)}.single {it.getInt("version")==version}
            val legacy=body().apply {
                remove("approvedDisclosureVersion");put("functionalDisclosureVersion",version)
                put("functionalDisclosureSha256",old.getString("sha256"))
            }
            val snapshot=parse(legacy.toString())
            assertEquals(8,snapshot.length());assertTrue(runCatching {decode(snapshot)}.isFailure)
        }
        val invalid=listOf(
            body().put("revision",org.json.JSONObject.NULL).toString(),
            body().put("extra",org.json.JSONObject.NULL).toString(),
            body().put("approvedPurposes",org.json.JSONArray().put(org.json.JSONObject.NULL)).toString(),
            body().put("extra",org.json.JSONObject().put("approvedDisclosureVersion",org.json.JSONObject.NULL)).toString(),
            body().put("approvedDisclosureVersion",org.json.JSONArray().put(org.json.JSONObject.NULL)).toString(),
            body().put("approvedDisclosureVersion",org.json.JSONObject().put("approvedDisclosureVersion",org.json.JSONObject.NULL)).toString(),
            raw.replace("\"revision\":0","\"revision\":0.0"),
            body().put("approvedDisclosureVersion",3.5).toString(),
            raw.dropLast(1)+",\"revision\":0}",
            raw.dropLast(1)+",\"approvedDisclosureVersion\":null}",
            "{\"extra\":"+"[".repeat(24)+"0"+"]".repeat(24)+"}")
        for(text in invalid)assertTrue(runCatching {parse(text)}.isFailure)
        assertTrue(runCatching {decode(parse(body().put("approvedDisclosureVersion",true).toString()))}.isFailure)
        assertTrue(runCatching {StrictNativeJson.parseFunctional(raw.toByteArray(Charsets.UTF_8),raw.toByteArray(Charsets.UTF_8).size-1)}.isFailure)
        assertTrue(runCatching {StrictNativeJson.parseFunctional(byteArrayOf(0xc3.toByte(),0x28))}.isFailure)
    }
}
