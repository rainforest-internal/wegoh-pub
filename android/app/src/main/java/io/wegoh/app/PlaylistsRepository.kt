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
import java.net.URL
import java.util.concurrent.Executors
import org.json.JSONObject

data class PlaylistSummary(val id: String,val name: String,val revision: Long,val count: Int)
data class PlaylistTrack(val id: String,val title: String,val url: String,val host: String)
data class PlaylistDetail(val summary: PlaylistSummary,val tracks: List<PlaylistTrack>)
enum class AccountPlaylistStatus { CONNECTION_REQUIRED, PERMISSION_REQUIRED, LOADING, READY, UNAVAILABLE }
data class AccountPlaylistState(val status: AccountPlaylistStatus=AccountPlaylistStatus.CONNECTION_REQUIRED,
    val items: List<PlaylistSummary> = emptyList(),val selected: PlaylistDetail?=null,val opening: String?=null,val isCurrent: Boolean=true)

internal class PlaylistsRepository(private val connection: VehicleConnection,private val events: AccountEvents): Closeable {
    private val main=Handler(Looper.getMainLooper())
    private val worker=Executors.newSingleThreadExecutor()
    private val api=connection.playlistsApi
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
    private val details=linkedMapOf<Pair<String,Long>,PlaylistDetail>()
    private val mutableState=MutableStateFlow(AccountPlaylistState())
    val states: StateFlow<AccountPlaylistState> = mutableState.asStateFlow()
    val state get()=states.value
    private val snapshot=AccountReadSnapshot(connection,VehicleConnection.Scope.PLAYLISTS) {clear(AccountPlaylistStatus.CONNECTION_REQUIRED)}
    private val observer=connection.observe {progress ->
        if(!closed && foreground && activated) {
            if(snapshot.invalidated()) {
                val authority=connection.readDisplayAuthority()
                attempted=false
                clear(if(VehicleConnection.Scope.PLAYLISTS in authority.deniedOptionalScopes || authority.stage==VehicleConnection.Stage.CONNECTED && VehicleConnection.Scope.PLAYLISTS !in authority.approvedOptionalScopes)AccountPlaylistStatus.PERMISSION_REQUIRED else AccountPlaylistStatus.CONNECTION_REQUIRED)
                if(authority.stage!=VehicleConnection.Stage.CONNECTED)return@observe
            }
            if(boundary?.revision?.let {it!=connection.dataEpoch()}==true) {attempted=false;clear(AccountPlaylistStatus.CONNECTION_REQUIRED)}
            if(boundary!=null && progress.stage==VehicleConnection.Stage.CONNECTED && boundary!=connection.contentDataBoundary(VehicleConnection.Scope.PLAYLISTS)) {
                attempted=true;clear(AccountPlaylistStatus.PERMISSION_REQUIRED);return@observe
            }
            if(boundary!=null && revision!=connection.dataStreamRevision()) {
                attempted=true;clear(AccountPlaylistStatus.UNAVAILABLE);return@observe
            }
            when(progress.stage) {
                VehicleConnection.Stage.CONNECTED -> if(setupAllowed) {
                    if(VehicleConnection.Scope.PLAYLISTS !in progress.approvedOptionalScopes || VehicleConnection.Scope.PLAYLISTS in progress.deniedOptionalScopes)
                        clear(AccountPlaylistStatus.PERMISSION_REQUIRED)
                    else if(!attempted)refresh()
                }
                VehicleConnection.Stage.CHECKING -> Unit
                VehicleConnection.Stage.UNAVAILABLE,VehicleConnection.Stage.RECOVERY_REQUIRED -> clear(AccountPlaylistStatus.UNAVAILABLE)
                else -> {attempted=false;clear(AccountPlaylistStatus.CONNECTION_REQUIRED)}
            }
        }
    }
    private fun publish(value: AccountPlaylistState) {mutableState.value=value}
    private fun clear(status: AccountPlaylistStatus) {
        val retain=!closed && state.status==AccountPlaylistStatus.READY && snapshot.canRetain() &&
            status in setOf(AccountPlaylistStatus.LOADING,AccountPlaylistStatus.UNAVAILABLE)
        details.clear()
        generation++;boundary=null;revision=-1;subscription?.close();subscription=null
        if(retain)publish(state.copy(opening=null,isCurrent=false)) else {snapshot.forget();publish(AccountPlaylistState(status))}
    }
    fun setForeground(value: Boolean) {
        if(closed || foreground==value)return
        foreground=value
        if(!value) {attempted=false;clear(AccountPlaylistStatus.UNAVAILABLE)}
    }
    fun setSetupAllowed(value: Boolean) {setupAllowed=value}
    fun request(force: Boolean=false) {
        if(closed || !foreground || !setupAllowed)return
        if(!force && (state.status==AccountPlaylistStatus.LOADING || state.status==AccountPlaylistStatus.READY && state.isCurrent &&
            snapshot.canRetain() && boundary==connection.contentDataBoundary(VehicleConnection.Scope.PLAYLISTS) && revision==connection.dataStreamRevision()))return
        activated=true;attempted=false
        if(connection.status().stage==VehicleConnection.Stage.CONNECTED)refresh() else if(force)connection.ensureConnected()
    }
    private fun current(expected: Long): Boolean {
        if(closed || !foreground || expected!=generation || boundary?.revision!=connection.dataEpoch())return false
        if(boundary!=connection.contentDataBoundary(VehicleConnection.Scope.PLAYLISTS) || revision!=connection.dataStreamRevision()) {
            attempted=true;clear(AccountPlaylistStatus.UNAVAILABLE);return false
        }
        return true
    }
    private fun refresh() {
        if(closed || !foreground || !setupAllowed)return
        val status=connection.status()
        if(status.stage!=VehicleConnection.Stage.CONNECTED)return
        if(VehicleConnection.Scope.PLAYLISTS !in status.approvedOptionalScopes || VehicleConnection.Scope.PLAYLISTS in status.deniedOptionalScopes) {
            clear(AccountPlaylistStatus.PERMISSION_REQUIRED);return
        }
        val verified=connection.contentDataBoundary(VehicleConnection.Scope.PLAYLISTS) ?: return
        attempted=true;clear(AccountPlaylistStatus.LOADING);boundary=verified;revision=connection.dataStreamRevision()
        val expected=generation
        subscription=events.subscribe(object: VehicleEventsListener {
            override fun onOpen() {if(current(expected))readCatalogue(expected)}
            override fun onEvent(event: VehicleEvent) {
                if(current(expected) && event.type=="invalidate" && event.resources.any {it=="playlists" || it=="devices"}) {
                    attempted=false;clear(AccountPlaylistStatus.UNAVAILABLE);refresh()
                }
            }
            override fun onClosed() {if(!closed && foreground && expected==generation)clear(AccountPlaylistStatus.UNAVAILABLE)}
            override fun onUnavailable()=onClosed()
        })
    }
    private fun readCatalogue(expected: Long) {
        scope.launch {
            val result=apiResult {api.playlists()}
            if(!current(expected))return@launch
            result.fold(onSuccess={document ->worker.execute {
                val parsed=runCatching {parseCatalogue(document.asObject())}
                main.post {
                    if(current(expected)) {
                        if(!setupAllowed) {attempted=false;clear(AccountPlaylistStatus.UNAVAILABLE);return@post}
                        parsed.fold(onSuccess={snapshot.remember(checkNotNull(boundary));publish(AccountPlaylistState(AccountPlaylistStatus.READY,it))},onFailure={clear(AccountPlaylistStatus.UNAVAILABLE)})
                    }
                }
            }},onFailure={clear(if(it is VehicleConnection.ScopeRequired)AccountPlaylistStatus.PERMISSION_REQUIRED else AccountPlaylistStatus.UNAVAILABLE)})
        }
    }
    fun select(item: PlaylistSummary) {
        if(!canUse() || item !in state.items || state.opening!=null)return
        details[item.id to item.revision]?.let {publish(state.copy(selected=it,opening=null));return}
        val expected=generation
        publish(state.copy(selected=null,opening=item.id))
        scope.launch {
            val result=apiResult {api.playlist(item.id)}
            if(!current(expected))return@launch
            result.fold(onSuccess={document ->worker.execute {
                val parsed=runCatching {parseDetail(document.asObject()).also {check(it.summary.id==item.id && it.summary.revision>=item.revision)}}
                main.post {
                    if(current(expected)) {
                        if(!setupAllowed) {attempted=false;clear(AccountPlaylistStatus.UNAVAILABLE);return@post}
                        parsed.fold(onSuccess={detail ->details[item.id to detail.summary.revision]=detail;if(details.size>50)details.remove(details.keys.first());publish(state.copy(items=state.items.map {if(it.id==item.id)detail.summary else it},selected=detail,opening=null))},
                            onFailure={clear(AccountPlaylistStatus.UNAVAILABLE)})
                    }
                }
            }},onFailure={clear(if(it is VehicleConnection.ScopeRequired)AccountPlaylistStatus.PERMISSION_REQUIRED else AccountPlaylistStatus.UNAVAILABLE)})
        }
    }
    private fun canUse()=foreground && setupAllowed && !closed && state.isCurrent && state.status==AccountPlaylistStatus.READY &&
        boundary!=null && boundary==connection.contentDataBoundary(VehicleConnection.Scope.PLAYLISTS) && revision==connection.dataStreamRevision() &&
        connection.status().stage==VehicleConnection.Stage.CONNECTED
    fun link(playlist: String,version: Long,track: String): String? {
        if(!canUse())return null
        val detail=state.selected ?: return null
        if(detail.summary.id!=playlist || detail.summary.revision!=version)return null
        return detail.tracks.firstOrNull {it.id==track}?.url
    }
    override fun close() {if(!closed){closed=true;scope.cancel();clear(AccountPlaylistStatus.CONNECTION_REQUIRED);observer.close();worker.shutdownNow()}}
    companion object {
        private fun space(char: Char)=char.isWhitespace() || char=='\u0085'
        private fun text(value: JSONObject,key: String,max: Int): String {
            val field=value.get(key);check(field is String && field.any {!space(it)} && field.codePointCount(0,field.length)<=max && field.none {it.code<32})
            return field
        }
        private fun id(value: JSONObject)=text(value,"id",32).also {check(it.matches(Regex("[a-f0-9]{32}")))}
        fun parseDetail(value: JSONObject): PlaylistDetail {
            val playlistId=id(value);val name=text(value,"name",80)
            val version=value.get("revision");check(version is Int || version is Long)
            val revision=(version as Number).toLong();check(revision in 1..9007199254740991L)
            val rows=value.getJSONArray("tracks");check(rows.length()<=100)
            val tracks=(0 until rows.length()).map {index ->
                val item=rows.getJSONObject(index);val trackId=id(item);val title=text(item,"title",120);val address=text(item,"url",2048)
                check(address.none(::space))
                val url=URL(address);val uri=url.toURI()
                check(url.protocol.equals("https",true) && url.host.isNotBlank() && url.userInfo==null && uri.rawUserInfo==null && url.port in setOf(-1,443))
                PlaylistTrack(trackId,title,address,url.host)
            }
            check(tracks.map {it.id}.distinct().size==tracks.size)
            return PlaylistDetail(PlaylistSummary(playlistId,name,revision,tracks.size),tracks)
        }
        fun parseCatalogue(value: JSONObject): List<PlaylistSummary> {
            val rows=value.getJSONArray("playlists");check(rows.length()<=100)
            val summaries=(0 until rows.length()).map {parseDetail(rows.getJSONObject(it)).summary}
            check(summaries.map {it.id}.distinct().size==summaries.size)
            return summaries
        }
    }
}
