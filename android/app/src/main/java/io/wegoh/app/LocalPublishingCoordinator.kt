package io.wegoh.app

import android.os.Handler
import android.os.Looper

internal class LocalPublishingCoordinator(private val repository: PackRepository,private val visits: VisitedPlaces,
    private val read: ()->WegoState,private val update: (WegoState)->Unit,private val privacyRevision: ()->Int,
    private val personal: (DrivePack)->Boolean,private val refresh: (String)->Unit,
    private val note: (String)->Unit,private val fail: (String)->Unit,private val log: (String)->Unit,
    private val publishedPacks: LocalPublishingApi=PublishedPacks()): AutoCloseable {
    private val main=Handler(Looper.getMainLooper())
    private val network=java.util.concurrent.Executors.newSingleThreadExecutor()
    private val privacyEpoch get()=privacyRevision()
    private var state: WegoState
        get()=read()
        set(value)=update(value)
    fun loadPublished() {
        if (!state.setupAllowed || !state.storageReady || state.active || state.catalogueBusy || state.downloading != null || state.accountCourses.downloading!=null) return
        state = state.copy(catalogueBusy = true, error = null)
        network.execute {
            val result = runCatching { publishedPacks.list() }
            main.post {
                state = state.copy(catalogueBusy = false)
                result.onSuccess { state = state.copy(published = it) }
                    .onFailure { fail("공개 경로를 불러오지 못했어요") }
            }
        }
    }
    fun downloadPublished(pack: PublishedPack) {
        if (!state.setupAllowed || !state.storageReady || state.active || state.catalogueBusy || state.downloading != null || state.accountCourses.downloading!=null) return
        state = state.copy(downloading = pack.key, error = null)
        val epoch=privacyEpoch
        network.execute {
            if(epoch!=privacyEpoch)return@execute
            val result = runCatching { publishedPacks.download(pack) }
            main.post {
                if(epoch!=privacyEpoch)return@post
                state = state.copy(downloading = null)
                if (!state.setupAllowed || state.active) {
                    note("경로 저장이 중단됐어요. 정차 후 다시 선택해 주세요")
                    return@post
                }
                result.onSuccess { bytes -> runCatching {
                    val imported = repository.importPublished(pack,bytes)
                    refresh(imported.key)
                    note("경로를 저장했어요")
                    log("PACK_DOWNLOADED")
                }.onFailure { fail("경로를 저장하지 못했어요") } }
                    .onFailure { fail("경로를 내려받지 못했어요") }
            }
        }
    }
    fun shareVisitedPlaces() {
        if (!state.setupAllowed || !state.storageReady || state.active || state.sharingVisits || state.visitedCount==0 || !state.visitSharingAllowed) return
        val records=runCatching {visits.list()}.getOrElse {fail("저장된 기록을 읽지 못했어요");return}
        state=state.copy(sharingVisits=true,error=null)
        val epoch=privacyEpoch
        network.execute {
            val result=runCatching {check(epoch==privacyEpoch);publishedPacks.shareVisits(records){epoch==privacyEpoch}}
            main.post {
                if(epoch!=privacyEpoch)return@post
                state=state.copy(sharingVisits=false)
                result.onSuccess { note("${it}개 방문 기록을 개발용 창작 공간에 공유했어요.") }
                    .onFailure { fail("방문 기록을 보내지 못했어요") }
            }
        }
    }
    fun reportSelectedCourse(reason: CourseReportReason) {
        if(!state.setupAllowed || !state.storageReady || state.active || state.reportBusy || !BuildConfig.DEBUG) {
            state=state.copy(reportOutcome=CourseReportOutcome.FAILED);return
        }
        val selected=state.selected
        val origin=selected?.takeUnless(personal)?.let {repository.verifiedOrigin(it)}
        if(origin==null){state=state.copy(reportOutcome=CourseReportOutcome.FAILED);return}
        val epoch=privacyEpoch
        state=state.copy(reportBusy=true,reportOutcome=null)
        network.execute {
            val result=runCatching {check(epoch==privacyEpoch);publishedPacks.report(origin,reason){epoch==privacyEpoch}}
            main.post {
                if(epoch!=privacyEpoch)return@post
                state=state.copy(reportBusy=false,reportOutcome=if(result.isSuccess)CourseReportOutcome.ACCEPTED else CourseReportOutcome.FAILED)
            }
        }
    }
    fun cancelPendingRequests()=publishedPacks.cancelPendingRequests()
    override fun close() {publishedPacks.cancelPendingRequests();network.shutdownNow()}
}
