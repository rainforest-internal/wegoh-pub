package io.wegoh.app

import android.test.InstrumentationTestCase
import java.io.ByteArrayInputStream
import org.json.JSONObject

@Suppress("DEPRECATION")
class PackRuntimeTests : InstrumentationTestCase() {
    private lateinit var context: android.content.Context
    override fun setUp() {
        super.setUp()
        val base=instrumentation.targetContext
        val id="pack-runtime-"+java.util.UUID.randomUUID()
        val dir=java.io.File(base.cacheDir,id).apply {mkdirs()}
        context=object: android.content.ContextWrapper(base) {
            override fun getApplicationContext(): android.content.Context=this
            override fun getFilesDir()=java.io.File(dir,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=java.io.File(dir,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences("$id-$name",mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences("$id-$name")
        }
    }
    private fun raw() = context.assets.open("packs/01-city-story.json").bufferedReader().use { it.readText() }
    private fun pack() = PackCodec.decode(raw())
    private fun reject(body: () -> Unit) {
        var failed = false
        try { body() } catch (_: Exception) { failed = true }
        assertTrue("Invalid input must fail", failed)
    }
    fun testPackValidation() {
        assertEquals(2, pack().stops.size)
        val invalid = JSONObject(raw()).put("schemaVersion", 99)
        reject { PackCodec.decode(invalid.toString()) }
        invalid.put("schemaVersion", 1).getJSONArray("stops").getJSONObject(0).put("latitude", 190)
        reject { PackCodec.decode(invalid.toString()) }
    }
    fun testRejectDuplicateAndUnknownAction() {
        val invalid = JSONObject(raw())
        val stops = invalid.getJSONArray("stops")
        stops.getJSONObject(1).put("id", stops.getJSONObject(0).getString("id"))
        reject { PackCodec.decode(invalid.toString()) }
        val unsupported = JSONObject(raw())
        unsupported.getJSONArray("stops").getJSONObject(0).getJSONObject("action").put("type", "execute_code")
        reject { PackCodec.decode(unsupported.toString()) }
    }
    fun testRejectOversizedInput() {
        reject { PackCodec.read(ByteArrayInputStream(ByteArray(PackCodec.MAX_BYTES + 1))) }
    }
    fun testOutOfOrderAndOutsideLocationsDoNotExecute() {
        val engine = PackEngine(pack())
        val second = pack().stops[1]
        assertNull(engine.candidate(second.latitude, second.longitude, 100000, 100000))
        assertNull(engine.candidate(0.0, 0.0, 100000, 100000))
        assertTrue(engine.completed.isEmpty())
    }
    fun testStaleFutureAndInvalidLocationsAreRejected() {
        val engine = PackEngine(pack()); val first = engine.pack.stops[0]
        assertNull(engine.candidate(first.latitude, first.longitude, 1, 100000))
        assertNull(engine.candidate(first.latitude, first.longitude, 120000, 100000))
        assertNull(engine.candidate(Double.NaN, first.longitude, 100000, 100000))
    }
    fun testReceiptPreventsDuplicateAfterRestore() {
        val pack = pack(); val first = pack.stops.first(); val engine = PackEngine(pack)
        assertEquals(first, engine.candidate(first.latitude, first.longitude, 100000, 100000))
        engine.mark(first.id)
        assertNull(engine.candidate(first.latitude, first.longitude, 100000, 100000))
        val restored = PackEngine(pack, engine.completed.toSet())
        assertNull(restored.candidate(first.latitude, first.longitude, 100000, 100000))
        val next = pack.stops[1]
        assertEquals(next, restored.candidate(next.latitude, next.longitude, 100000, 100000))
    }
    fun testProgressStorePersistsAndResetIsExplicit() {
        val pack = pack().copy(id = "test-progress-${System.nanoTime()}")
        assertTrue(ProgressStore(context).save(pack, setOf(pack.stops.first().id)))
        assertEquals(setOf(pack.stops.first().id), ProgressStore(context).read(pack))
        assertTrue(ProgressStore(context).reset(pack))
        assertTrue(ProgressStore(context).read(pack).isEmpty())
    }
    fun testImportPersistsAndRejectsVersionCollision() {
        val id = "test-import-${System.nanoTime()}"
        val json = JSONObject(raw()).put("id", id)
        val repository = PackRepository(context)
        val imported = repository.importPack(ByteArrayInputStream(json.toString().toByteArray()))
        assertTrue(PackRepository(context).list().any { it.key == imported.key })
        json.put("title", "다른 내용")
        reject { repository.importPack(ByteArrayInputStream(json.toString().toByteArray())) }
    }
}
