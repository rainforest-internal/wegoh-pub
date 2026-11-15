package io.wegoh.app

import android.content.Context
import android.content.ContextWrapper
import android.test.InstrumentationTestCase
import java.io.File
import java.security.KeyStore
import java.util.UUID

@Suppress("DEPRECATION")
class LocalApiQaIsolationTest: InstrumentationTestCase() {
    fun testProgressAndVisitsKeepTheQaStorageAndKeyThroughApplicationContext() {
        val target=instrumentation.targetContext
        val prefix="qa-storage-test-"+UUID.randomUUID()
        val root=File(target.cacheDir,prefix).apply {mkdirs()}
        val base=object: ContextWrapper(target) {
            override fun getNoBackupFilesDir()=File(root,"original").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=target.getSharedPreferences("$prefix.$name",mode)
            override fun deleteSharedPreferences(name: String)=target.deleteSharedPreferences("$prefix.$name")
        }
        val profile="local_qa_"+UUID.randomUUID().toString().replace("-","").take(24)
        val qa=VehicleAppDependencies.QaContext(base,profile)
        val alias=VehicleAppDependencies.privateStoreAlias(qa)
        val original=File(base.noBackupFilesDir,"private/sentinel").apply {parentFile!!.mkdirs();writeText("synthetic original")}
        val originalPrefs=base.getSharedPreferences("visited_places",Context.MODE_PRIVATE)
        originalPrefs.edit().putString("places","[{\"id\":\"original\"}]").commit()
        try {
            assertSame(qa,qa.applicationContext)
            assertEquals("wegoh.private.v1.$profile",alias)
            assertFalse(qa.noBackupFilesDir.canonicalPath==base.noBackupFilesDir.canonicalPath)
            val pack=PackRepository(qa).list().first()
            qa.getSharedPreferences("pack_progress",Context.MODE_PRIVATE).edit()
                .putStringSet(pack.key,setOf(pack.stops.first().id)).commit()
            assertEquals(setOf(pack.stops.first().id),ProgressStore(qa).read(pack))
            assertEquals(0,VisitedPlaces(qa).list().length())
            assertTrue(VisitedPlaces(qa).record(pack,pack.stops.first()))
            assertEquals(1,VisitedPlaces(qa).list().length())
            assertEquals("synthetic original",original.readText())
            assertEquals("[{\"id\":\"original\"}]",originalPrefs.getString("places",null))
            assertEquals(listOf("sentinel"),File(base.noBackupFilesDir,"private").listFiles()!!.map {it.name})
        } finally {
            qa.deleteSharedPreferences("pack_progress")
            qa.deleteSharedPreferences("visited_places")
            base.deleteSharedPreferences("visited_places")
            root.deleteRecursively()
            KeyStore.getInstance("AndroidKeyStore").apply {load(null);deleteEntry(alias)}
        }
    }
}
