package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase
import java.io.File
import java.security.KeyStore
import org.json.JSONArray
import org.json.JSONObject

/** New isolated profiles only: original encrypted bytes and Keystore identity survive. */
class NativeConnectionMigrationTest: InstrumentationTestCase() {
    private fun await(check: ()->Boolean) {
        val until=android.os.SystemClock.uptimeMillis()+7000
        while(android.os.SystemClock.uptimeMillis()<until) {if(check())return;Thread.sleep(20)}
        fail("Synthetic public1 migration timeout")
    }
    fun testEncryptedConversionPreservesSameIdentityAndOnlyRevokeCapability() {
        val context=instrumentation.targetContext
        val profile="migration_"+java.util.UUID.randomUUID().toString().replace("-","").take(24)
        val store=NativeConnectionState(context,profile);store.initialize()
        val original=store.read();val identity=NativeDeviceIdentity(context,original.getString("installationId"));identity.initialize()
        val key=identity.installationKeyId();val csr=identity.csrPem()
        val grant="b".repeat(32);val cap=NativeAccessCodec.encode(ByteArray(32) {3})
        original.put("identityInitialized",true).put("accessV2",JSONObject().put("epoch",7L).put("phase","connected")
            .put("outbox",JSONArray()).put("certificate",JSONObject().put("installationKeyId",key).put("certificateSha256","c".repeat(64)).put("generation",1))
            .put("credentials",JSONObject().put("installationKeyId",key).put("grantId",grant).put("revokeCapability",cap)
                .put("accessToken","never-forward-this-access").put("refreshToken","never-forward-this-refresh"))
            .put("authorization",JSONObject().put("verifier","never-forward-this-verifier").put("request",JSONObject().put("authorizationVersion",2))))
        store.write(original)
        val file=File(context.noBackupFilesDir,"wegoh.native.state.$profile.enc");val before=file.readBytes()
        // Simulate interruption after archive creation and before atomic conversion.
        val archived=store.preservePrePublicV1()
        assertTrue(File(file.path+".pre-public1").readBytes().contentEquals(before))
        var connection=VehicleConnection.existingProfile(context,profile)
        try {
            await {store.read().has("publicContract")}
            val current=store.read();val state=current.getJSONObject("access")
            assertEquals(1,current.getInt("publicContract"));assertEquals(archived,current.getString("prePublicV1SourceSha256"))
            assertEquals(8L,state.getLong("epoch"));assertEquals("revoke_pending",state.getString("phase"))
            assertFalse(current.has("accessV2"));assertFalse(state.has("credentials"));assertFalse(state.has("authorization"))
            assertFalse(state.toString().contains("never-forward-this"))
            val request=state.getJSONArray("outbox").getJSONObject(0).getJSONObject("request")
            assertEquals(setOf("authorizationVersion","operationId","grantId","revokeCapability"),request.keys().asSequence().toSet())
            assertEquals(1,request.getInt("authorizationVersion"));assertEquals(grant,request.getString("grantId"));assertEquals(cap,request.getString("revokeCapability"))
            assertEquals(key,identity.installationKeyId());assertEquals(csr,identity.csrPem())
            assertTrue(File(file.path+".pre-public1").readBytes().contentEquals(before))
            await {connection.status().stage!=VehicleConnection.Stage.CHECKING}
            assertEquals(VehicleConnection.Stage.REMOTE_REVOCATION_PENDING,connection.status().stage)
            val requestId=request.getString("operationId");connection.close()
            connection=VehicleConnection.existingProfile(context,profile)
            await {connection.status().stage!=VehicleConnection.Stage.CHECKING}
            assertEquals(requestId,store.read().getJSONObject("access").getJSONArray("outbox").getJSONObject(0).getJSONObject("request").getString("operationId"))
            assertTrue(File(file.path+".pre-public1").readBytes().contentEquals(before))
            assertTrue(KeyStore.getInstance("AndroidKeyStore").apply{load(null)}.containsAlias("wegoh.native."+current.getString("installationId")))
        } finally {connection.close()}
    }
    fun testRenewalPublicCandidateSurvivesDuplicateGrantWithoutPrivateProof() {
        val key="a".repeat(64);val grant="b".repeat(32);val cap=NativeAccessCodec.encode(ByteArray(32){4})
        val request=JSONObject().put("authorizationVersion",2).put("operationId","c".repeat(32)).put("grantId",grant).put("revokeCapability",cap)
        val staged=JSONObject().put("installationKeyId",key).put("certificateSha256","d".repeat(64)).put("certificatePem","synthetic-public-leaf")
        val root=JSONObject().put("version",1).put("installationId","e".repeat(32)).put("accessV2",JSONObject()
            .put("epoch",3L).put("outbox",JSONArray().put(JSONObject().put("request",request)))
            .put("credentials",JSONObject().put("installationKeyId",key).put("grantId",grant).put("revokeCapability",cap))
            .put("renewal",JSONObject().put("request",JSONObject().put("grantId",grant)).put("stagedCertificate",staged)
                .put("verifier","must-stay-archived").put("recoveryCapability","must-stay-archived")))
        val original=root.toString()
        val current=NativeConnectionMigration.convert(root,key).getJSONObject("access")
        val pending=current.getJSONArray("outbox");assertEquals(1,pending.length())
        assertEquals(staged.toString(),pending.getJSONObject(0).getJSONObject("stagedCertificate").toString())
        assertFalse(current.toString().contains("must-stay-archived"));assertEquals(original,root.toString())
        root.getJSONObject("accessV2").getJSONObject("renewal").getJSONObject("request").put("grantId","f".repeat(32))
        try {NativeConnectionMigration.convert(root,key);fail("Cross-grant staged leaf accepted")}catch(expected: IllegalStateException){}
        root.getJSONObject("accessV2").getJSONObject("renewal").getJSONObject("request").put("grantId",grant)
        root.getJSONObject("accessV2").getJSONObject("renewal").getJSONObject("stagedCertificate").put("installationKeyId","f".repeat(64))
        try {NativeConnectionMigration.convert(root,key);fail("Cross-key staged leaf accepted")}catch(expected: IllegalStateException){}
    }
    fun testAmbiguousOrInvalidOldStateFailsClosed() {
        val root=JSONObject().put("version",1).put("installationId","a".repeat(32))
            .put("access",JSONObject()).put("accessV2",JSONObject().put("epoch",1))
        try {NativeConnectionMigration.convert(root,"b".repeat(64));fail("Mixed state accepted")}catch(expected: IllegalStateException){}
        root.remove("access");root.getJSONObject("accessV2").put("epoch",1.5)
        try {NativeConnectionMigration.convert(root,"b".repeat(64));fail("Fractional epoch accepted")}catch(expected: IllegalStateException){}
        root.getJSONObject("accessV2").put("epoch",1L).put("outbox",JSONArray().put(JSONObject().put("request",JSONObject()
            .put("authorizationVersion",2).put("operationId","c".repeat(32)).put("grantId","d".repeat(32)).put("revokeCapability","invalid"))))
        try {NativeConnectionMigration.convert(root,"b".repeat(64));fail("Invalid capability accepted")}catch(expected: Exception){}
    }
}
