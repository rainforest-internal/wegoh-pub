package io.wegoh.app

import android.content.Context
import android.content.Intent
import android.test.InstrumentationTestCase
import androidx.activity.result.contract.ActivityResultContracts
import java.io.File

/** Real OS cancellation on the supplied Automotive document stub, not picker-success evidence. */
@Suppress("DEPRECATION")
class LocalCourseImportTests: InstrumentationTestCase() {
    private fun bytes(root: File)=root.walkTopDown().filter {it.isFile}.associate {
        it.relativeTo(root).path to java.security.MessageDigest.getInstance("SHA-256").digest(it.readBytes()).toList()
    }
    fun testAutomotiveDocumentStubCancelsWithoutChangingRecords() {
        val base=instrumentation.targetContext
        val contract=ActivityResultContracts.OpenDocument()
        val types=arrayOf("application/json","text/plain","application/octet-stream")
        val resolved=contract.createIntent(base,types).resolveActivity(base.packageManager)
        assertNotNull("The actual OS must resolve the document request",resolved)
        assertEquals("com.android.car.frameworkpackagestubs",resolved!!.packageName)
        assertTrue("Record actual provided OS document stub",resolved.className.contains("DocumentsUIStubWithResult"))
        val namespace="local-import-cancel-"+java.util.UUID.randomUUID()
        val root=File(base.cacheDir,namespace).apply {check(mkdirs())}
        val isolated=object: android.content.ContextWrapper(base) {
            override fun getApplicationContext(): Context=this
            override fun getFilesDir()=File(root,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=File(root,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences("$namespace-$name",mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences("$namespace-$name")
        }
        val original=bytes(base.noBackupFilesDir)
        // AndroidX may update its profile marker after an APK replacement. It is
        // runtime metadata; every user-owned file remains covered byte-for-byte.
        val originalFiles=bytes(base.filesDir).filterKeys {it!="profileInstalled"}
        val owner=instrumentation.startActivitySync(Intent(base,SafFrameworkHarnessActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)) as SafFrameworkHarnessActivity
        var controller: WegoController?=null
        var launcher: androidx.activity.result.ActivityResultLauncher<Array<String>>?=null
        var callbacks=0;var returnedUri: android.net.Uri?=null
        val callback=java.util.concurrent.CountDownLatch(1)
        var result: LocalCourseImportResult?=null
        try {
            instrumentation.runOnMainSync {controller=WegoController(isolated,base.applicationContext)}
            val model=controller!!
            val before=bytes(isolated.noBackupFilesDir)
            val selected=model.state.selectedKey
            instrumentation.runOnMainSync {
                val importer=LocalCourseImport(model,owner.contentResolver)
                // Cancellation itself must be a no-op even when setup is blocked.
                launcher=owner.activityResultRegistry.register(namespace,contract) {uri ->
                    val stateBefore=model.state
                    callbacks++;returnedUri=uri;result=importer.accept(uri)
                    assertEquals(stateBefore,model.state)
                    callback.countDown()
                }
                launcher!!.launch(types)
            }
            assertTrue("Actual OS cancellation callback",callback.await(8,java.util.concurrent.TimeUnit.SECONDS))
            assertEquals(1,callbacks);assertNull(returnedUri)
            assertEquals(LocalCourseImportResult.CANCELLED,result)
            assertEquals(selected,model.state.selectedKey)
            assertEquals(before,bytes(isolated.noBackupFilesDir))
            File(root,"result.json").writeText(org.json.JSONObject()
                .put("resolvedComponent",resolved.flattenToShortString()).put("nativePickerSupported",false)
                .put("nativePickerSuccess",false).put("cancelProtectionPassed",true)
                .put("actualCallbacks",callbacks).put("protectedBytesUnchanged",original==bytes(base.noBackupFilesDir))
                .put("scope","Actual OS stub cancellation; no successful document selection or full MainActivity UI verification").toString(2))
        } finally {
            instrumentation.runOnMainSync {launcher?.unregister();controller?.close();owner.finish()}
            assertEquals(original,bytes(base.noBackupFilesDir))
            assertEquals(originalFiles,bytes(base.filesDir).filterKeys {it!="profileInstalled"})
        }
    }
}
