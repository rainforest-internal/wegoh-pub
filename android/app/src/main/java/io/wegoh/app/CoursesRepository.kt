package io.wegoh.app

import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.nativeauth.VehicleEvent
import io.wegoh.app.nativeauth.VehicleEventsListener
import java.io.Closeable
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.concurrent.Executors
import org.json.JSONObject

data class AccountCourse(val published: PublishedPack,val available: Boolean,val tags: List<String> = emptyList())
enum class AccountCourseStatus { CONNECTION_REQUIRED, PERMISSION_REQUIRED, LOADING, READY, UNAVAILABLE }
data class AccountCourseState(val status: AccountCourseStatus=AccountCourseStatus.CONNECTION_REQUIRED,
    val courses: List<AccountCourse> = emptyList(),val selected: DrivePack?=null,val downloading: String?=null,val isCurrent: Boolean=true)

internal class CoursesRepository(private val connection: VehicleConnection,private val repository: PackRepository,feed: AccountEvents?=null,
    private val changed: (AccountCourseState)->Unit): Closeable {
    private val main=Handler(Looper.getMainLooper())
    private val worker=Executors.newSingleThreadExecutor()
    private val events=feed ?: AccountEvents(connection)
    private val ownsEvents=feed==null
    private var generation=0L
    private val api=connection.coursesApi
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    private var foreground=false
    private var setupAllowed=false
    private var closed=false
    private val previews=linkedMapOf<Pair<String,String?>,DrivePack>()
    private var attempted=false
    private var activated=false
    private var boundary: VehicleConnection.DataBoundary?=null
    private var streamRevision=-1L
    private var socket: Closeable?=null
    private val mutableState=MutableStateFlow(AccountCourseState())
    val states: StateFlow<AccountCourseState> = mutableState.asStateFlow()
    val state get()=states.value
    private val snapshot=AccountReadSnapshot(connection,VehicleConnection.Scope.COURSES) {clear(AccountCourseStatus.CONNECTION_REQUIRED)}
    private val observer=connection.observe { progress ->
        if(!closed && foreground && activated) {
            if(snapshot.invalidated()) {
                val authority=connection.readDisplayAuthority()
                attempted=false
                clear(if(VehicleConnection.Scope.COURSES in authority.deniedOptionalScopes || authority.stage==VehicleConnection.Stage.CONNECTED && VehicleConnection.Scope.COURSES !in authority.approvedOptionalScopes)AccountCourseStatus.PERMISSION_REQUIRED else AccountCourseStatus.CONNECTION_REQUIRED)
                if(authority.stage!=VehicleConnection.Stage.CONNECTED)return@observe
            }
        if(boundary?.let {it.revision!=connection.dataEpoch()}==true) {attempted=false;clear(AccountCourseStatus.CONNECTION_REQUIRED)}
        if(boundary!=null && progress.stage==VehicleConnection.Stage.CONNECTED && boundary!=connection.accountDataBoundary()) {
            attempted=true;clear(AccountCourseStatus.PERMISSION_REQUIRED);return@observe
        }
        if(boundary!=null && streamRevision!=connection.dataStreamRevision()) {
            attempted=true;clear(AccountCourseStatus.UNAVAILABLE);return@observe
        }
        when(progress.stage) {
            VehicleConnection.Stage.CONNECTED -> if(setupAllowed) {
                if(VehicleConnection.Scope.COURSES !in progress.approvedOptionalScopes || VehicleConnection.Scope.COURSES in progress.deniedOptionalScopes)
                    clear(AccountCourseStatus.PERMISSION_REQUIRED)
                else if(!attempted) refresh()
            }
            VehicleConnection.Stage.CHECKING -> Unit
            VehicleConnection.Stage.UNAVAILABLE,VehicleConnection.Stage.RECOVERY_REQUIRED -> clear(AccountCourseStatus.UNAVAILABLE)
            else -> {attempted=false;clear(AccountCourseStatus.CONNECTION_REQUIRED)}
        }
        }
    }
    internal fun storageKey(): String? = snapshot.storageKey().takeIf {foreground && state.status==AccountCourseStatus.READY}
    internal fun canDisplaySelection()=state.isCurrent && boundary!=null && boundary==connection.accountDataBoundary() &&
        streamRevision==connection.dataStreamRevision() && storageKey()!=null && foreground
    internal fun canUse(): Boolean {
        val status=connection.status()
        return canDisplaySelection() && setupAllowed && status.stage==VehicleConnection.Stage.CONNECTED &&
            VehicleConnection.Scope.COURSES in status.approvedOptionalScopes && VehicleConnection.Scope.COURSES !in status.deniedOptionalScopes
    }
    private fun publish(value: AccountCourseState) {mutableState.value=value;changed(value)}
    private fun clear(status: AccountCourseStatus) {
        val retain=!closed && state.status==AccountCourseStatus.READY && snapshot.canRetain() &&
            status in setOf(AccountCourseStatus.LOADING,AccountCourseStatus.UNAVAILABLE)
        previews.clear()
        generation++;boundary=null;streamRevision=-1;socket?.close();socket=null
        if(retain)publish(state.copy(downloading=null,isCurrent=false)) else {snapshot.forget();publish(AccountCourseState(status))}
    }
    fun setForeground(value: Boolean) {
        if(closed || foreground==value)return
        foreground=value
        if(!value) {attempted=false;clear(AccountCourseStatus.UNAVAILABLE)}
    }
    fun setSetupAllowed(value: Boolean) {
        if(closed || setupAllowed==value)return
        setupAllowed=value
    }
    fun request(force: Boolean=false) {
        activated=true
        if(force && connection.status().stage!=VehicleConnection.Stage.CONNECTED) {connection.ensureConnected();return}
        if(!force && (state.status==AccountCourseStatus.LOADING || state.status==AccountCourseStatus.READY && state.isCurrent &&
            snapshot.canRetain() && boundary==connection.accountDataBoundary() && streamRevision==connection.dataStreamRevision()))return
        refresh()
    }
    fun refresh() {
        if(closed || !foreground || !setupAllowed)return
        activated=true
        val status=connection.status()
        if(status.stage!=VehicleConnection.Stage.CONNECTED)return
        if(VehicleConnection.Scope.COURSES !in status.approvedOptionalScopes || VehicleConnection.Scope.COURSES in status.deniedOptionalScopes) {
            clear(AccountCourseStatus.PERMISSION_REQUIRED);return
        }
        val verified=connection.accountDataBoundary() ?: return
        attempted=true;clear(AccountCourseStatus.LOADING);boundary=verified;streamRevision=connection.dataStreamRevision()
        val expected=generation
        openEvents(expected)
    }
    private fun readCatalogue(expected: Long) {
        scope.launch {
            val result=apiResult {api.courses()}
            if(!current(expected))return@launch
            result.fold(onSuccess={document -> worker.execute {
                val parsed=runCatching {parse(document.asObject())}
                main.post {
                    if(streamCurrent(expected)) {
                        if(!setupAllowed) {attempted=false;clear(AccountCourseStatus.UNAVAILABLE);return@post}
                        if(boundary!=connection.accountDataBoundary()) {clear(AccountCourseStatus.UNAVAILABLE);return@post}
                        parsed.fold(onSuccess={courses ->
                        snapshot.remember(checkNotNull(boundary));publish(AccountCourseState(AccountCourseStatus.READY,courses))
                    },onFailure={clear(AccountCourseStatus.UNAVAILABLE)})
                    }
                }
            }},onFailure={failure -> clear(if(failure is VehicleConnection.ScopeRequired)AccountCourseStatus.PERMISSION_REQUIRED else AccountCourseStatus.UNAVAILABLE)})
        }
    }
    fun select(course: AccountCourse) {
        if(!canUse() || closed || state.status!=AccountCourseStatus.READY || state.downloading!=null ||
            !course.available || course !in state.courses)return
        previews[course.published.key to course.published.checksum]?.let {publish(state.copy(selected=it,downloading=null));return}
        val expected=generation
        publish(state.copy(downloading=course.published.key))
        scope.launch {
            val result=apiResult {api.originalPackVersion(course.published.id,course.published.version)}
            if(!current(expected))return@launch
            result.fold(onSuccess={payload -> worker.execute {
                val decoded=runCatching {repository.accountCourse(course.published,payload.bytes())}
                main.post {
                    if(streamCurrent(expected)) {
                        if(!setupAllowed) {attempted=false;clear(AccountCourseStatus.UNAVAILABLE);return@post}
                        if(boundary!=connection.accountDataBoundary()) {clear(AccountCourseStatus.UNAVAILABLE);return@post}
                        decoded.fold(onSuccess={pack -> previews[course.published.key to course.published.checksum]=pack;if(previews.size>20)previews.remove(previews.keys.first());publish(state.copy(selected=pack,downloading=null))},onFailure={clear(AccountCourseStatus.UNAVAILABLE)})
                    }
                }
            }},onFailure={failure ->clear(if(failure is VehicleConnection.ScopeRequired)AccountCourseStatus.PERMISSION_REQUIRED else AccountCourseStatus.UNAVAILABLE)})
        }
    }
    fun restoreExecution(pack: DrivePack,checksum: String): Boolean {
        if(!canUse() || state.selected!=null || state.courses.none {it.available && it.published.key==pack.key && it.published.checksum==checksum})return false
        publish(state.copy(selected=pack));return true
    }
    private fun current(expected: Long)=!closed && foreground && expected==generation && boundary?.revision==connection.dataEpoch()
    private fun streamCurrent(expected: Long): Boolean {
        if(!current(expected))return false
        if(streamRevision!=connection.dataStreamRevision()) {attempted=true;clear(AccountCourseStatus.UNAVAILABLE);return false}
        return true
    }
    private fun openEvents(expected: Long) {
        socket=events.subscribe(object: VehicleEventsListener {
            override fun onOpen() {if(streamCurrent(expected))readCatalogue(expected)}
            override fun onEvent(event: VehicleEvent) {
                if(streamCurrent(expected) && event.type=="invalidate" && event.resources.any {it=="courses" || it=="devices"}) {
                    attempted=false;clear(AccountCourseStatus.UNAVAILABLE);refresh()
                }
            }
            override fun onClosed() {if(current(expected))clear(AccountCourseStatus.UNAVAILABLE)}
            override fun onUnavailable() {if(current(expected))clear(AccountCourseStatus.UNAVAILABLE)}
        })
    }
    override fun close() {
        if(closed)return
        closed=true;scope.cancel();snapshot.forget();generation++;socket?.close();socket=null;if(ownsEvents)events.close();observer.close();worker.shutdownNow()
        publish(AccountCourseState())
    }
    companion object {
        const val SOURCE="계정 경로"
        fun parse(value: JSONObject): List<AccountCourse> {
            val rows=value.getJSONArray("packs");check(rows.length()<=1000)
            val result=(0 until rows.length()).map { index ->
                val item=rows.getJSONObject(index)
                fun text(name: String,max: Int): String {
                    val text=item.get(name);check(text is String && text.isNotBlank() && text.length<=max && text.none {it.code<32});return text
                }
                val id=text("id",80);check(id.matches(Regex("[a-z0-9][a-z0-9_-]{0,79}")))
                val version=item.get("version");check(version is Int && version>0)
                val count=item.get("stopCount");check(count is Int && count in 1..3)
                val checksum=text("checksum",64);check(checksum.matches(Regex("[a-f0-9]{64}")))
                val published=PublishedPack(id,version,text("title",100),text("author",80),text("description",500),count,checksum)
                val tags=if(!item.has("tags"))emptyList() else item.getJSONArray("tags").let {rows->
                    check(rows.length()<=100)
                    (0 until rows.length()).map {index->rows.get(index).also {
                        check(it is String && it.isNotBlank() && it.length<=80 && it.none {char->char.isISOControl()})
                    } as String}
                }
                AccountCourse(published,item.getString("state")=="approved",tags)
            }
            check(result.map {it.published.key}.distinct().size==result.size)
            return result
        }
    }
}
