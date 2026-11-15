package io.wegoh.app.nativeauth

import android.test.InstrumentationTestCase
import java.io.File
import java.security.KeyStore
import org.json.JSONObject

/** Damage only newly-created isolated synthetic state/key; never product data. */
class NativeInstallationRecoveryTest: InstrumentationTestCase() {
    private fun await(check: ()->Boolean) {
        val end=android.os.SystemClock.uptimeMillis()+7000
        while(android.os.SystemClock.uptimeMillis()<end){if(check())return;Thread.sleep(20)}
        fail("Isolated installation recovery timeout")
    }
    fun testContextWrappersCannotCreateTwoOwnersOfSameApplicationProfile() {
        val context=instrumentation.targetContext
        val profile="wrapper_test_"+java.util.UUID.randomUUID().toString().replace("-","").take(20)
        fun wrapped(name: String)=object: android.content.ContextWrapper(context) {
            override fun getNoBackupFilesDir()=File(context.noBackupFilesDir,name)
        }
        val first=VehicleConnection.existingProfile(wrapped("synthetic-a"),profile)
        try {
            try {VehicleConnection.existingProfile(wrapped("synthetic-b"),profile);fail("Duplicate actual owner accepted")}
            catch(expected: IllegalStateException) {assertEquals("NATIVE_CONNECTION_ALREADY_OPEN",expected.message)}
        } finally {first.close()}
    }
    fun testExplicitNewInstallationPreservesOldCipherAndDoesNotRestoreLostIdentity() {
        val context=instrumentation.targetContext
        val profile="loss_test_"+java.util.UUID.randomUUID().toString().replace("-","").take(20)
        val original=NativeConnectionState(context,profile);original.initialize()
        val root=original.read();val oldId=root.getString("installationId")
        val old=NativeDeviceIdentity(context,oldId);old.initialize();root.put("identityInitialized",true);original.write(root)
        val cipher=File(context.noBackupFilesDir,"wegoh.native.state.$profile.enc")
        val bytes=cipher.readBytes();val keys=KeyStore.getInstance("AndroidKeyStore").apply {load(null)}
        // Delete only the synthetic AES key just created above, preserving old RSA/cipher.
        keys.deleteEntry("wegoh.native.state.$profile")
        var connection=VehicleConnection.existingProfile(context,profile)
        try {
            connection.setSetupAllowed(true);connection.setForeground(true)
            await {connection.status().canRegisterAgain}
            assertTrue(cipher.readBytes().contentEquals(bytes));assertTrue(keys.containsAlias("wegoh.native.$oldId"))
            assertFalse(keys.containsAlias("wegoh.native.state.$profile"))
            connection.setSetupAllowed(false);connection.registerNewInstallation();Thread.sleep(100)
            assertTrue(cipher.readBytes().contentEquals(bytes));assertFalse(keys.containsAlias("wegoh.native.state.$profile"))
            connection.setSetupAllowed(true);connection.registerNewInstallation()
            await {connection.status().stage==VehicleConnection.Stage.READY}
            assertTrue(cipher.readBytes().contentEquals(bytes));assertTrue(keys.containsAlias("wegoh.native.$oldId"))
            val prefix="selection_"+NativeDeviceIdentity.sha256(profile.toByteArray()).take(24)
            val selection=NativeConnectionState(context,prefix+"_1").read()
            val fresh=selection.getString("activeProfile");val state=NativeConnectionState(context,fresh).read()
            assertFalse(state.getString("installationId")==oldId)
            assertFalse(state.getJSONObject("access").has("credentials"));assertFalse(state.getJSONObject("access").has("authorization"))
            connection.close()
            // A missing selector file must fail closed, not choose an older identity.
            val selectorFile=File(context.noBackupFilesDir,"wegoh.native.state.${prefix}_1.enc")
            val selectorBytes=selectorFile.readBytes();val kept=File(selectorFile.path+".synthetic-preserved")
            assertTrue(selectorFile.renameTo(kept))
            connection=VehicleConnection.existingProfile(context,profile)
            connection.setSetupAllowed(true);connection.setForeground(true)
            await {connection.status().canRegisterAgain}
            assertTrue(kept.readBytes().contentEquals(selectorBytes))
            connection.registerNewInstallation()
            await {connection.status().stage==VehicleConnection.Stage.READY}
            assertTrue(kept.readBytes().contentEquals(selectorBytes));assertTrue(keys.containsAlias("wegoh.native.state.${prefix}_1"))
            val newer=NativeConnectionState(context,prefix+"_2").read().getString("activeProfile")
            assertFalse(newer==fresh)
        } finally {connection.close()}
    }
}
