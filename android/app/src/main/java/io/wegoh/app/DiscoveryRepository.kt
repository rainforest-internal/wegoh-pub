package io.wegoh.app

import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.nativeauth.WegoLog
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

data class AccountDiscoveryState(val status: AccountReadStatus=AccountReadStatus.CONNECTION_REQUIRED,
    val packs: List<PublishedPack> = emptyList(),val downloading: String?=null,val isCurrent: Boolean=true,
    val library: CourseLibrary?=null,val verifiedSelection: PublishedPack?=null)

internal class DiscoveryRepository(private val connection: VehicleConnection,private val events: AccountEvents,
    private val repository: PackRepository): Closeable {
    private val main=Handler(Looper.getMainLooper())
    private val worker=Executors.newSingleThreadExecutor()
    private val api=connection.discoveryApi
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    private var foreground=false
    private var setupAllowed=false
    private var activated=false
    private var attempted=false
    private var closed=false
    private var generation=0L
    private var boundary: VehicleConnection.DataBoundary?=null
    private var revision=-1L
    private var subscription: Closeable?=null
    private var retry: Runnable?=null
    private var retryAttempt=0
    private var retryEpoch=-1L
    private val mutableState=MutableStateFlow(AccountDiscoveryState())
    val states: StateFlow<AccountDiscoveryState> = mutableState.asStateFlow()
    val state get()=states.value
    private val snapshot=AccountReadSnapshot(connection,VehicleConnection.Scope.COURSES) {clear(AccountReadStatus.CONNECTION_REQUIRED)}
    private val observer=connection.observe {progress ->
        if(!closed && foreground && activated) {
            if(snapshot.invalidated()) {
                val authority=connection.readDisplayAuthority()
                cancelRetry(true);attempted=false
                clear(if(VehicleConnection.Scope.COURSES in authority.deniedOptionalScopes || authority.stage==VehicleConnection.Stage.CONNECTED && VehicleConnection.Scope.COURSES !in authority.approvedOptionalScopes)AccountReadStatus.PERMISSION_REQUIRED else AccountReadStatus.CONNECTION_REQUIRED)
                if(authority.stage!=VehicleConnection.Stage.CONNECTED)return@observe
            }
            if(retry!=null && retryEpoch!=connection.dataEpoch()) {cancelRetry(true);attempted=false;clear(AccountReadStatus.CONNECTION_REQUIRED)}
            if(boundary?.revision?.let {it!=connection.dataEpoch()}==true) {cancelRetry(true);attempted=false;clear(AccountReadStatus.CONNECTION_REQUIRED)}
            if(boundary!=null && (revision!=connection.dataStreamRevision() ||
                progress.stage==VehicleConnection.Stage.CONNECTED && boundary!=connection.verifiedDataBoundary())) {
                recover("snapshot_changed");return@observe
            }
            if(boundary!=null && progress.stage==VehicleConnection.Stage.CONNECTED && boundary!=connection.contentDataBoundary(VehicleConnection.Scope.COURSES)) {
                cancelRetry(true);attempted=true;clear(AccountReadStatus.PERMISSION_REQUIRED);return@observe
            }
            when(progress.stage) {
                VehicleConnection.Stage.CONNECTED -> if(setupAllowed) {
                    if(!approved()) {cancelRetry(true);clear(AccountReadStatus.PERMISSION_REQUIRED)} else if(!attempted)refresh()
                }
                VehicleConnection.Stage.CHECKING -> Unit
                VehicleConnection.Stage.UNAVAILABLE,VehicleConnection.Stage.RECOVERY_REQUIRED -> recover("account_unavailable")
                else -> {cancelRetry(true);attempted=false;clear(AccountReadStatus.CONNECTION_REQUIRED)}
            }
        }
    }
    private fun approved()=VehicleConnection.Scope.COURSES in connection.status().approvedOptionalScopes &&
        VehicleConnection.Scope.COURSES !in connection.status().deniedOptionalScopes
    private fun publish(value: AccountDiscoveryState) {mutableState.value=value}
    private fun log(message: String) {if(BuildConfig.DEBUG)android.util.Log.d("WegoH.Catalogue",message)}
    private fun cancelRetry(reset: Boolean=false) {
        retry?.let {main.removeCallbacks(it)};retry=null;retryEpoch=-1
        if(reset)retryAttempt=0
    }
    private fun recover(reason: String) {
        if(retry!=null)return
        attempted=true
        if(closed || !foreground || !setupAllowed || !activated) {clear(AccountReadStatus.UNAVAILABLE);return}
        val stage=connection.status().stage
        if(stage==VehicleConnection.Stage.CONNECTED && !approved()) {cancelRetry(true);clear(AccountReadStatus.PERMISSION_REQUIRED);return}
        if(stage !in setOf(VehicleConnection.Stage.CONNECTED,VehicleConnection.Stage.CHECKING,
            VehicleConnection.Stage.UNAVAILABLE,VehicleConnection.Stage.RECOVERY_REQUIRED)) {clear(AccountReadStatus.CONNECTION_REQUIRED);return}
        clear(AccountReadStatus.LOADING)
        if(retryAttempt>=3) {clear(AccountReadStatus.UNAVAILABLE);log("catalogue.retry: stopped reason=exhausted");return}
        val expected=generation;val epoch=connection.dataEpoch();val delay=1000L shl retryAttempt++
        retryEpoch=epoch
        log("catalogue.retry: scheduled reason=$reason attempt=$retryAttempt delay_ms=$delay")
        retry=Runnable {
            retry=null
            if(closed || !foreground || !setupAllowed || expected!=generation || epoch!=connection.dataEpoch())return@Runnable
            attempted=false;if(connection.status().stage==VehicleConnection.Stage.CONNECTED)refresh()
        }.also {main.postDelayed(it,delay)}
    }
    private fun clear(status: AccountReadStatus) {
        val retain=!closed && state.status==AccountReadStatus.READY && snapshot.canRetain() &&
            status in setOf(AccountReadStatus.LOADING,AccountReadStatus.UNAVAILABLE)
        generation++;boundary=null;revision=-1;subscription?.close();subscription=null
        if(retain)publish(state.copy(downloading=null,isCurrent=false)) else {snapshot.forget();publish(AccountDiscoveryState(status))}
    }
    fun setForeground(value: Boolean) {
        if(closed || foreground==value)return
        foreground=value
        if(!value) {cancelRetry(true);attempted=false;clear(AccountReadStatus.UNAVAILABLE)}
    }
    fun setSetupAllowed(value: Boolean) {
        setupAllowed=value
        if(!value && retry!=null) {cancelRetry();attempted=false;clear(AccountReadStatus.UNAVAILABLE)}
    }
    fun request(force: Boolean=false) {
        if(closed || !foreground || !setupAllowed)return
        if(!force && (state.status==AccountReadStatus.LOADING || state.status==AccountReadStatus.READY && state.isCurrent &&
            snapshot.canRetain() && boundary==connection.contentDataBoundary(VehicleConnection.Scope.COURSES) && revision==connection.dataStreamRevision()))return
        cancelRetry(true);activated=true;attempted=false
        if(connection.status().stage==VehicleConnection.Stage.CONNECTED)refresh() else if(force)connection.ensureConnected()
    }
    private fun current(expected: Long): Boolean {
        if(closed || !foreground || expected!=generation)return false
        if(boundary==null || boundary!=connection.verifiedDataBoundary() || revision!=connection.dataStreamRevision()) {
            recover("snapshot_changed");return false
        }
        if(boundary!=connection.contentDataBoundary(VehicleConnection.Scope.COURSES)) {
            cancelRetry(true);attempted=true;clear(AccountReadStatus.PERMISSION_REQUIRED);return false
        }
        return true
    }
    private fun refresh() {
        if(closed || !foreground || !setupAllowed || connection.status().stage!=VehicleConnection.Stage.CONNECTED)return
        if(!approved()) {clear(AccountReadStatus.PERMISSION_REQUIRED);return}
        val verified=connection.contentDataBoundary(VehicleConnection.Scope.COURSES) ?: return
        attempted=true;clear(AccountReadStatus.LOADING);boundary=verified;revision=connection.dataStreamRevision();val expected=generation
        val opened=events.subscribe(object: VehicleEventsListener {
            override fun onOpen() {if(current(expected))readCatalogue(expected)}
            override fun onEvent(event: VehicleEvent) {
                if(current(expected) && event.type=="invalidate" && event.resources.any {it in setOf("courses","devices","recommendations")}) {
                    attempted=false;clear(AccountReadStatus.UNAVAILABLE);refresh()
                }
            }
            override fun onUnavailable() {if(!closed && foreground && expected==generation)recover("events_closed")}
            override fun onClosed()=onUnavailable()
        })
        if(expected==generation)subscription=opened else opened.close()
    }
    private fun readCatalogue(expected: Long) {
        log("catalogue.read: started attempt=$retryAttempt")
        scope.launch {
            val result=apiResult {api.courseLibrary()}
            if(!current(expected))return@launch
            result.fold(onSuccess={document->worker.execute {
                val parsed=runCatching {CourseLibraryCodec.library(document.asObject())}
                main.post {
                    if(current(expected)) {
                        if(!setupAllowed) {attempted=false;clear(AccountReadStatus.UNAVAILABLE);return@post}
                        parsed.fold(onSuccess={library->cancelRetry(true);snapshot.remember(checkNotNull(boundary));
                            publish(AccountDiscoveryState(AccountReadStatus.READY,library.public.map {it.published},library=library));
                            log("catalogue.read: loaded count=${library.public.size}")},
                            onFailure={clear(AccountReadStatus.UNAVAILABLE);log("catalogue.read: failed reason=invalid_document")})
                    }
                }
            }},onFailure={if(it is VehicleConnection.ScopeRequired) {cancelRetry(true);clear(AccountReadStatus.PERMISSION_REQUIRED)}else recover("read_failed")})
        }
    }
    fun download(pack: PublishedPack,canStore: ()->Boolean,stored: (DrivePack)->Unit) {
        val blocked=when {
            closed->"closed";!foreground->"background";!setupAllowed->"setup_blocked"
            state.status!=AccountReadStatus.READY->"status_"+state.status.name.lowercase();!state.isCurrent->"stale"
            state.downloading!=null->"busy";!readable(pack)->"unreadable";!current(generation)->"generation";!canStore()->"cannot_store"
            else->null
        }
        if(blocked!=null) {WegoLog.w("WegoH","course.open: skipped reason=$blocked");return}
        WegoLog.i("WegoH","course.open: started")
        val expected=generation;publish(state.copy(downloading=pack.key,verifiedSelection=null))
        scope.launch {
            val result=apiResult {
                runCatching {CourseLibraryCodec.verifyPublicDetail(api.publicCourse(pack.id,pack.version).asObject(),pack)}
                    .onFailure {WegoLog.w("WegoH","course.open: detail rejected type=${it.javaClass.simpleName}")}.getOrThrow()
                if(!(current(expected) && setupAllowed && canStore())) {
                    WegoLog.w("WegoH","course.open: store blocked current=${current(expected)} setup=$setupAllowed store=${canStore()}");error("store blocked")
                }
                api.packVersion(pack.id,pack.version)
            }
            if(!current(expected))return@launch
            result.fold(onSuccess={document->worker.execute {
                val verified=runCatching {document.bytes().also {repository.verifyPublished(pack,it)}}
                main.post {
                    if(current(expected)) {
                        if(!setupAllowed || !canStore() || !readable(pack)) {clear(AccountReadStatus.UNAVAILABLE);return@post}
                        verified.fold(onSuccess={bytes ->
                            runCatching {repository.importPublished(pack,bytes)}.fold(onSuccess={saved ->
                                publish(state.copy(downloading=null,verifiedSelection=pack));stored(saved)
                            },onFailure={WegoLog.w("WegoH","course.open: import failed type=${it.javaClass.simpleName}");clear(AccountReadStatus.UNAVAILABLE)})
                        },onFailure={WegoLog.w("WegoH","course.open: verify failed type=${it.javaClass.simpleName}");clear(AccountReadStatus.UNAVAILABLE)})
                    }
                }
            }},onFailure={WegoLog.w("WegoH","course.open: request failed type=${it.javaClass.simpleName}")
                clear(if(it is VehicleConnection.ScopeRequired)AccountReadStatus.PERMISSION_REQUIRED else AccountReadStatus.UNAVAILABLE)})
        }
    }
    private fun readable(pack: PublishedPack)=pack in (state.library?.readablePacks ?: state.packs)
    override fun close() {if(!closed){closed=true;scope.cancel();cancelRetry(true);clear(AccountReadStatus.CONNECTION_REQUIRED);observer.close();worker.shutdownNow()}}
    companion object {
        fun parse(value: JSONObject): List<PublishedPack> {
            val rows=value.getJSONArray("packs");check(rows.length()<=100)
            val packs=(0 until rows.length()).map {index ->
                val item=rows.getJSONObject(index)
                fun text(key: String,max: Int): String {
                    val field=item.get(key);check(field is String && field.isNotBlank() && field.length<=max && field.none {it.code<32 && it !in "\n\r\t"})
                    return field
                }
                val id=text("id",80);check(id.matches(Regex("[a-z0-9][a-z0-9_-]{0,79}")))
                val version=item.get("version");check(version is Int && version>0)
                val count=item.get("stopCount");check(count is Int && count in 1..3)
                val checksum=text("checksum",64);check(checksum.matches(Regex("[a-f0-9]{64}")))
                PublishedPack(id,version,text("title",100),text("author",80),text("description",500),count,checksum)
            }
            check(packs.map {it.key}.distinct().size==packs.size)
            return packs
        }
    }
}
