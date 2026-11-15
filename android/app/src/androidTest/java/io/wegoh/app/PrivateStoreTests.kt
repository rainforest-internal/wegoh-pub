package io.wegoh.app

import android.content.Context
import android.content.ContextWrapper
import android.test.InstrumentationTestCase
import java.io.File
import java.util.UUID

/** Synthetic isolated files only: original app records are never cleaned by these tests. */
@Suppress("DEPRECATION")
class PrivateStoreTests: InstrumentationTestCase() {
    private lateinit var isolated: Context
    override fun setUp() {
        super.setUp()
        val id="policy-test-"+UUID.randomUUID()
        val base=instrumentation.targetContext
        val dir=File(base.cacheDir,id).apply {mkdirs()}
        isolated=object: ContextWrapper(base) {
            override fun getNoBackupFilesDir()=File(dir,"no-backup").apply {mkdirs()}
            override fun getFilesDir()=File(dir,"files").apply {mkdirs()}
            override fun getApplicationContext(): Context=this
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences("$id-$name",mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences("$id-$name")
        }
    }
    fun testAuthenticatedEncryptionAndRestart() {
        val alias="wegoh.test."+UUID.randomUUID()
        val store=PrivateStore(isolated,alias)
        val payload="SYNTHETIC_PRIVATE_PLACE_37.5"
        store.write("visits",payload)
        val file=File(isolated.noBackupFilesDir,"private/visits")
        val first=file.readBytes()
        assertFalse(first.toString(Charsets.UTF_8).contains(payload))
        assertEquals(payload,PrivateStore(isolated,alias).read("visits"))
        store.write("visits",payload)
        assertFalse("Unique random IV",first.contentEquals(file.readBytes()))
        File(isolated.noBackupFilesDir,"private/progress").writeBytes(file.readBytes())
        try {store.read("progress");fail("AAD must reject file swapping")}catch(expected: java.security.GeneralSecurityException) { }
        val raw=file.readBytes();raw[raw.lastIndex]=(raw.last().toInt() xor 1).toByte();file.writeBytes(raw)
        try {store.read("visits");fail("Corruption must not become empty data")}catch(expected: java.security.GeneralSecurityException) { }
    }
    fun testVerifiedMigrationPreservesReceiptsAndEncryptsRecoveryCopy() {
        val pack=PackRepository(instrumentation.targetContext).list().first()
        val prefs=isolated.getSharedPreferences("pack_progress",Context.MODE_PRIVATE)
        assertTrue(prefs.edit().putStringSet(pack.key,setOf(pack.stops.first().id)).commit())
        assertEquals(setOf(pack.stops.first().id),ProgressStore(isolated).read(pack))
        assertFalse(isolated.getSharedPreferences("pack_progress",Context.MODE_PRIVATE).contains(pack.key))
        val store=PrivateStore(isolated)
        val archive=store.names().single{it.startsWith("legacy-progress-")}
        assertTrue(store.read(archive)!!.contains(pack.stops.first().id))
        assertTrue(ProgressStore(isolated).save(pack,pack.stops.map{it.id}.toSet()))
        assertEquals(pack.stops.size,ProgressStore(isolated).read(pack).size)
        assertTrue("Recovery copy remains encrypted",File(isolated.noBackupFilesDir,"private/$archive").readText().contains(pack.stops.first().id).not())
    }
    fun testConsentPauseAndExplicitWithdrawalDoNotResurrectLegacyRecords() {
        val store=PrivateStore(isolated)
        store.write("settings",org.json.JSONObject().put("locationConsentVersion",1).toString())
        store.write("visits","[{\"id\":\"synthetic-visit\"}]")
        val settings=PrivateSettings(isolated)
        assertFalse("Updated notice requires renewed explicit consent",settings.consented())
        assertTrue(store.exists("visits"))
        settings.consent();assertTrue(settings.consented())
        settings.revoke();assertFalse(settings.consented())
        assertTrue("Pause retains records",store.exists("visits"))
        store.write("progress","{}")
        store.write("pack-synthetic-1","{}")
        store.write("legacy-progress-recovery","SYNTHETIC_RECOVERY")
        isolated.getSharedPreferences("visited_places",Context.MODE_PRIVATE).edit().putString("places","[{}]").commit()
        isolated.getSharedPreferences("pack_progress",Context.MODE_PRIVATE).edit().putStringSet("synthetic@1",setOf("stop")).commit()
        isolated.getSharedPreferences("pack_selection",Context.MODE_PRIVATE).edit().putString("selected","synthetic@1").commit()
        File(isolated.filesDir,"packs").apply {mkdirs()}.resolve("legacy.json").writeText("SYNTHETIC_LEGACY")
        LocalPrivacy.withdrawAndDelete(isolated)
        assertFalse(PrivateSettings(isolated).consented())
        assertEquals(listOf("settings"),store.names())
        assertFalse(File(isolated.filesDir,"packs/legacy.json").exists())
        assertEquals(0,VisitedPlaces(isolated).list().length())
        assertTrue(isolated.getSharedPreferences("pack_progress",Context.MODE_PRIVATE).all.isEmpty())
        assertTrue(isolated.getSharedPreferences("pack_selection",Context.MODE_PRIVATE).all.isEmpty())
        assertFalse(PackRepository(isolated).list().any {it.id=="synthetic"})
        assertTrue("Bundled courses remain available",PackRepository(isolated).list().isNotEmpty())
    }
    fun testDownloadedOriginRequiresExactVerifiedBytesAndSurvivesRestart() {
        val json=org.json.JSONObject(instrumentation.targetContext.assets.open("packs/01-city-story.json").bufferedReader().use {it.readText()}).put("id","synthetic-origin")
        val bytes=json.toString().toByteArray(Charsets.UTF_8);val pack=PackCodec.decode(bytes.toString(Charsets.UTF_8))
        val hash=java.security.MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it.toInt() and 255)}
        val published=PublishedPack(pack.id,pack.version,pack.title,pack.author,pack.description,pack.stops.size,hash)
        val repo=PackRepository(isolated)
        repo.importPack(java.io.ByteArrayInputStream(bytes))
        assertNull("Manual import cannot acquire public reporting identity",repo.verifiedOrigin(pack))
        try {repo.importPublished(published.copy(checksum="0".repeat(64)),bytes);fail("Unverified download provenance accepted")}catch(expected: IllegalStateException) { }
        assertNull(repo.verifiedOrigin(pack))
        repo.importPublished(published,bytes)
        assertEquals(VerifiedPackOrigin(pack.id,pack.version,hash),PackRepository(isolated).verifiedOrigin(pack))
        val store=PrivateStore(isolated)
        store.write("pack-${pack.id}-${pack.version}",json.put("title","SYNTHETIC_CHANGED").toString())
        assertNull("Changed stored bytes cannot report somebody else's version",PackRepository(isolated).verifiedOrigin(pack))
        assertNotNull("Provenance rejection must not erase stored content",store.read("pack-${pack.id}-${pack.version}"))
    }
    fun testStrictSchemaRejectsCoercionAndUnknownActions() {
        val raw=instrumentation.targetContext.assets.open("packs/01-city-story.json").bufferedReader().use{it.readText()}
        for(change in listOf<(org.json.JSONObject)->Unit>(
            {it.put("version",1.5)}, {it.put("version","1")}, {it.put("schemaVersion",true)},
            {it.getJSONArray("stops").getJSONObject(0).put("latitude","37.5")},
            {it.getJSONArray("stops").getJSONObject(0).getJSONObject("action").put("command","unsafe")}
        )) {
            val json=org.json.JSONObject(raw);change(json)
            try {PackCodec.decode(json.toString());fail("Invalid/coerced schema accepted")}catch(expected: IllegalArgumentException) { }
        }
    }
    fun testReleaseRejectsUnprotectedAndEmbeddedCredentialsEndpoints() {
        for(url in listOf("http://127.0.0.1:18081","http://example.org","https://user:secret@example.org","https://example.org/?token=secret","https://example.org/#secret")) {
            try {DistributionPolicy.endpoint(url,false);fail("Unsafe release URL: $url")}catch(expected: IllegalArgumentException) { }
        }
        assertEquals("https://example.org",DistributionPolicy.endpoint("https://example.org/",false))
        assertEquals("http://127.0.0.1:18081",DistributionPolicy.endpoint("http://127.0.0.1:18081",true))
    }
    fun testFailedWriteKeepsDurableReceipt() {
        val pack=PackRepository(instrumentation.targetContext).list().first()
        val store=ProgressStore(isolated)
        val receipt=setOf(pack.stops.first().id)
        assertTrue(store.save(pack,receipt))
        assertFalse(store.save(pack,setOf("x".repeat(1048577))))
        assertEquals(receipt,ProgressStore(isolated).read(pack))
    }
    fun testVisitsNeverSilentlyDiscardEarlierRecords() {
        val pack=PackRepository(instrumentation.targetContext).list().first()
        val store=PrivateStore(isolated)
        val records=org.json.JSONArray()
        repeat(100) {records.put(org.json.JSONObject().put("id","synthetic-$it"))}
        store.write("visits",records.toString())
        assertTrue(VisitedPlaces(isolated).record(pack,pack.stops.first()))
        assertEquals(101,VisitedPlaces(isolated).list().length())
        val full=org.json.JSONArray()
        repeat(1000){full.put(org.json.JSONObject().put("id","synthetic-$it"))}
        store.write("visits",full.toString())
        assertFalse(VisitedPlaces(isolated).record(pack,pack.stops.first()))
        assertEquals(full.toString(),VisitedPlaces(isolated).list().toString())
    }
}
