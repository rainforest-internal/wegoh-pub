package io.wegoh.app

import android.content.Intent
import android.test.InstrumentationTestCase
import android.test.InstrumentationTestRunner
import androidx.activity.compose.setContent
import io.wegoh.app.ui.WegoCarTheme
import io.wegoh.app.ui.WegoVehicleScreen
import android.view.accessibility.AccessibilityNodeInfo

/** End-to-end: a pack created outside this APK, actual HTTP, then actual Pleos SDKs. */
@Suppress("DEPRECATION")
class PublishedJourneyTests : InstrumentationTestCase() {
    private fun click(label: String) {
        fun find(node: AccessibilityNodeInfo?): AccessibilityNodeInfo? {
            if (node == null) return null
            if (node.text?.toString() == label || node.contentDescription?.toString() == label) return node
            for (index in 0 until node.childCount) find(node.getChild(index))?.let { return it }
            return null
        }
        val deadline = System.currentTimeMillis() + 10000
        while (System.currentTimeMillis() < deadline) {
            var node = find(instrumentation.uiAutomation.rootInActiveWindow)
            repeat(5) {
                node?.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SHOW_ON_SCREEN.id)
                if (node?.performAction(AccessibilityNodeInfo.ACTION_CLICK) == true) return
                node = node?.parent
            }
            Thread.sleep(250)
        }
        fail("UI button unavailable: $label")
    }
    private fun waitFor(label: String, seconds: Int, condition: () -> Boolean) {
        val deadline = System.currentTimeMillis() + seconds * 1000
        while (System.currentTimeMillis() < deadline) {
            var ready = false
            instrumentation.runOnMainSync { ready = condition() }
            if (ready) return
            Thread.sleep(250)
        }
        fail("Timed out: $label")
    }
    fun testPublishedWebPackDownloadsAndExecutes() {
        runPublishedJourney(reportOnly=false)
    }
    fun testPublishedWholeDepartureObservation() {
        runPublishedJourney(reportOnly=false,strictGuidance=false)
    }
    internal fun runPublishedJourney(reportOnly: Boolean,strictGuidance: Boolean=true) {
        val id = (instrumentation as InstrumentationTestRunner).arguments.getString("packId")
            ?: error("Supply -e packId <a published web pack>")
        val base=instrumentation.targetContext;val fixtureId="published-runtime-"+java.util.UUID.randomUUID()
        val dir=java.io.File(base.cacheDir,fixtureId).apply {mkdirs()}
        val isolated=object: android.content.ContextWrapper(base) {
            override fun getApplicationContext(): android.content.Context=this
            override fun getFilesDir()=java.io.File(dir,"files").apply {mkdirs()}
            override fun getNoBackupFilesDir()=java.io.File(dir,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name: String,mode: Int)=base.getSharedPreferences("$fixtureId-$name",mode)
            override fun deleteSharedPreferences(name: String)=base.deleteSharedPreferences("$fixtureId-$name")
        }
        fun originals()=PackRepository(base).list().sortedBy {it.key}.joinToString {it.key+ProgressStore(base).read(it).sorted().toString()}+VisitedPlaces(base).list().toString()
        val before=originals()
        var activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
        lateinit var controller: WegoController
        fun render() {instrumentation.runOnMainSync {activity.setContent {WegoCarTheme {WegoVehicleScreen(controller.state,
            onSelect=controller::select,onImport={},onStart={if(controller.consentLocation()) {
                controller.begin(controller.state.selectedKey!!)}},
            onStop=controller::stop,onNavigate={controller.requestNavigation(wholeCourse=true)},onReset=controller::reset,
            onBrowse=controller::loadPublished,onDownload=controller::downloadPublished,onShareVisits=controller::shareVisitedPlaces,onReport=controller::reportSelectedCourse)}}}}
        instrumentation.runOnMainSync {controller=WegoController(isolated,base.applicationContext);controller.setVisible(true)}
        render()
        try {
            waitFor("CarUxRestrictions",12) {controller.state.setupAllowed && controller.state.storageReady}
            click("둘러보기")
            waitFor("public catalogue",20) {!controller.state.catalogueBusy}
            assertNull(controller.state.error)
            val published=controller.state.published.firstOrNull {it.id==id} ?: error("Published pack not in catalogue")
            var rejected=false
            try {PublishedPacks().download(published.copy(checksum="0".repeat(64)))}catch(_: IllegalStateException) {rejected=true}
            assertTrue("Tampered expected hash must be rejected",rejected)
            click("${published.title} v${published.version} 다운로드")
            waitFor("verified pack download",20) {controller.state.downloading==null}
            assertNull(controller.state.error);assertEquals(published.key,controller.state.selectedKey)
            click("뒤로")
            assertTrue(PackRepository(isolated).list().any {it.key==published.key})
            val pack=controller.state.selected!!
            assertEquals(published.title,pack.title);assertEquals(2,pack.stops.size)
            if(!reportOnly) {
            click("도착 알림");click("동의하고 시작")
            waitFor("downloaded pack session",10) {controller.state.active || controller.state.error!=null}
            assertNull(controller.state.error)
            waitFor("real FusedLocation event from web pack",35) {controller.state.completed.contains(pack.stops.first().id)}
            assertEquals(1,controller.state.history.takeWhile {it!="SESSION_START"}.count {it.startsWith("EVENT_EXECUTED ")})
            click("출발")
            if(strictGuidance)waitFor("real NaviHelper callback from web pack",30) {
                controller.state.navigationPhase==NavigationPhase.ACTIVE}
            else {
                waitFor("whole-course request sent",12) {controller.state.history.any {it.contains("경로 요청 전송 내비에서 안내를 시작하세요")}}
                waitFor("bounded whole-course observation",20) {controller.state.navigationPhase in setOf(NavigationPhase.ACTIVE,NavigationPhase.OEM_GUIDANCE_REPORTED,NavigationPhase.FAILED)}
                java.io.File(base.cacheDir,"published-whole-course-observation.json").writeText(org.json.JSONObject()
                    .put("synthetic",true).put("virtualGps",true).put("wholeStopCount",pack.stops.size)
                    .put("requestSent",true).put("navigationPhase",controller.state.navigationPhase.name)
                    .put("strictReadback",controller.state.navigationPhase==NavigationPhase.ACTIVE)
                    .put("locationSource","FusedLocation").put("completedRecordsRetained",true).toString(2))
            }
            assertEquals(setOf(pack.stops.first().id),ProgressStore(isolated).read(pack))
            }
            instrumentation.runOnMainSync {controller.close();activity.finish()}
            activity=instrumentation.startActivitySync(Intent(base,MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)) as MainActivity
            instrumentation.runOnMainSync {controller=WegoController(isolated,base.applicationContext);controller.setVisible(true)}
            render();waitFor("isolated receipt restored",12) {controller.state.setupAllowed && controller.state.storageReady}
            assertEquals(published.key,controller.state.selectedKey)
            assertEquals(if(reportOnly)emptySet<String>() else setOf(pack.stops.first().id),controller.state.completed)
            if(!reportOnly) {
            click("더보기");click("방문 기록");click("공유")
            waitFor("consented synthetic local visit sharing",15) {!controller.state.sharingVisits}
            assertNull(controller.state.error);assertTrue(controller.state.message.contains("방문 기록을 이 PC"))
            assertEquals("Only this isolated synthetic visit can be sent",1,VisitedPlaces(isolated).list().length())
            }
            assertNotNull("Download provenance must survive restart",controller.state.reportOrigin)
            try {PublishedPacks().report(VerifiedPackOrigin(pack.id,pack.version,"0".repeat(64)),CourseReportReason.OTHER);fail("Wrong source checksum must reject reporting")}catch(expected: IllegalStateException) { }
            click("더보기");click("경로 신고");click("기타");click("신고")
            waitFor("actual synthetic course report",20) {controller.state.reportOutcome!=null && !controller.state.reportBusy}
            assertEquals(CourseReportOutcome.ACCEPTED,controller.state.reportOutcome)
            click("확인")
            val connection=java.net.URL(BuildConfig.PACK_API_BASE_URL+"/v1/packs/${pack.id}/versions/${pack.version}").openConnection() as java.net.HttpURLConnection
            try {assertEquals("Reported synthetic version must be quarantined",404,connection.responseCode)}finally {connection.disconnect()}
            java.io.File(base.cacheDir,if(reportOnly)"course-report-validation.json" else "published-sdk-validation.json").writeText(org.json.JSONObject().put("virtualGps",!reportOnly)
                .put("packId",pack.id).put("version",pack.version).put("checksum",published.checksum)
                .put("downloadVerified",true).put("originRestored",true).put("syntheticVisitsOnly",true).put("locationSdkExercised",!reportOnly)
                .put("actualReport202",true).put("quarantinedGetStatus",404).toString(2))

        } finally {
            instrumentation.runOnMainSync {controller.close();activity.finish()}
            assertEquals("Published SDK test must preserve original user courses/progress/visits",before,originals())
        }
    }
}
