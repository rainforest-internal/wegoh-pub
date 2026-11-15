package io.wegoh.app

import io.wegoh.app.nativeauth.*
import java.io.Closeable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

internal data class TripMusicSourceItem(val source: TripSavedPlaylistSource,val title: String,val provider: String,val url: String="") {
    val key get()=source.playlistId+":"+source.trackId
}
internal enum class TripMusicStatus { IDLE, LOADING, READY, UNAVAILABLE, PERMISSION_REQUIRED }

/** Result of handing a saved music link to another app. [code] is the only part written to the log; the URL never is. */
internal enum class TripMusicOpen(val code: String,val notice: String?) {
    OPENED("opened",null),
    RESTRICTED("restricted","정차 중에만 열 수 있어요"),
    NO_HANDLER("no_handler","이 차에서 링크를 열 수 있는 앱이 없어요"),
    FAILED("failed","음악 링크를 열지 못했어요")
}

/**
 * Starts the link only while setup is allowed and classifies a start failure. The exception message is not logged
 * because ActivityNotFoundException carries the intent, including the link.
 */
internal fun openTripMusicLink(setupAllowed: Boolean,log: (String)->Unit,start: ()->Unit): TripMusicOpen {
    val result=if(!setupAllowed)TripMusicOpen.RESTRICTED else try {start();TripMusicOpen.OPENED} catch(error: RuntimeException) {
        if(error is android.content.ActivityNotFoundException)TripMusicOpen.NO_HANDLER else TripMusicOpen.FAILED
    }
    if(result!=TripMusicOpen.OPENED)log("trip.music.open: failed reason=${result.code}")
    return result
}
/** A short in-app notice that other members recommended tracks. [sequence] lets the UI time each one out once. */
internal data class TripMusicAnnouncement(val text: String,val sequence: Int)
internal data class TripMusicState(val status: TripMusicStatus=TripMusicStatus.IDLE,val collection: TripMusicCollection?=null,
    val sourceStatus: TripMusicStatus=TripMusicStatus.IDLE,val sources: List<TripMusicSourceItem> = emptyList(),
    val adding: String?=null,val notice: String?=null,val addedSequence: Int=0,val refreshing: Boolean=false,
    val playing: String?=null,val moving: String?=null,val announcement: TripMusicAnnouncement?=null) {
    val writing get()=adding!=null || playing!=null || moving!=null
}

/** Items other members added since [previous]; never announces the first load or this account's own additions. */
internal fun tripMusicAnnouncement(previous: TripMusicCollection?,next: TripMusicCollection,sequence: Int): TripMusicAnnouncement? {
    if(previous==null)return null
    val known=previous.items.map {it.id}.toSet()
    val added=next.items.filter {it.id !in known && it.addedById!=next.viewerId}
    val first=added.firstOrNull() ?: return null
    val text=if(added.size==1)"${first.addedByName}님이 음악을 추천했어요"
        else "일행이 음악을 추천했어요"
    return TripMusicAnnouncement(text,sequence)
}

internal interface TripMusicGateway: Closeable {
    val current: Boolean
    fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit)
    fun read(callback: (Result<TripMusicCollection>)->Unit): Closeable
    fun sources(callback: (Result<List<TripMusicSourceItem>>)->Unit): Closeable
    fun add(source: TripSavedPlaylistSource,rights: Boolean,review: Boolean,callback: (Result<TripMusicCollection>)->Unit): Closeable
    fun play(itemId: String,callback: (Result<TripMusicCollection>)->Unit): Closeable
    fun move(itemId: String,afterId: String?,callback: (Result<TripMusicCollection>)->Unit): Closeable
}

internal class TripMusicRepository(private val tripId: String,private val gateway: ()->TripMusicGateway): Closeable {
    private val mutable=MutableStateFlow(TripMusicState())
    val states=mutable.asStateFlow()
    val state get()=states.value
    private var client: TripMusicGateway?=null
    private var read: Closeable?=null
    private var ownRead: Closeable?=null
    private var write: Closeable?=null
    private var generation=0L
    private var reading=0L
    private var sourcesGeneration=0L
    private var available=false
    private var closed=false
    private var dirty=false
    private var announced=0
    private val invalidationReloads=InvalidationReloads()
    private val leases=mutableListOf<Lease>()

    /** One screen that shows this trip's music. The repository stays connected while any lease is available. */
    inner class Lease: Closeable {
        var available=false
            set(value) {field=value;syncLeases()}
        override fun close() {leases.remove(this);syncLeases()}
    }
    fun lease()=Lease().also {leases+=it}
    private fun syncLeases()=setAvailable(leases.any {it.available})
    private fun apply(collection: TripMusicCollection): Boolean {
        if(collection.tripId!=tripId){unavailable();return false}
        val announcement=tripMusicAnnouncement(state.collection,collection,announced+1)
        if(announcement!=null)announced++
        invalidationReloads.reset()
        mutable.value=state.copy(status=TripMusicStatus.READY,collection=collection,refreshing=false,
            announcement=announcement ?: state.announcement)
        return true
    }
    fun dismissAnnouncement(sequence: Int) {
        if(state.announcement?.sequence==sequence)mutable.value=state.copy(announcement=null)
    }
    private fun current(token: Long,own: TripMusicGateway)=!closed && available && generation==token && client===own && own.current
    private fun cancel() {
        generation++;reading++;sourcesGeneration++
        read?.close();ownRead?.close();write?.close();client?.close()
        read=null;ownRead=null;write=null;client=null;dirty=false
    }
    fun setAvailable(value: Boolean) {
        if(closed || available==value)return
        available=value
        if(value)refresh() else {cancel();mutable.value=TripMusicState()}
    }
    fun refresh() {
        if(closed || !available || state.writing)return
        val existing=client
        if(existing?.current==true){readCollection(existing,generation);return}
        cancel();val token=generation
        val own=gateway();client=own
        mutable.value=TripMusicState(status=TripMusicStatus.LOADING)
        own.open(object: NativeSocialObserver {
            override fun onInvalidated() {
                if(client!==own || token!=generation)return
                cancel();mutable.value=TripMusicState(status=TripMusicStatus.UNAVAILABLE)
                // 권한 교체만으로 끊긴 경우 화면이 남아 있으면 다시 연다.
                if(available && !closed)invalidationReloads.take()?.let {refresh()}
            }
            override fun onConnectionLost()=onInvalidated()
            override fun onResourcesChanged(resources: Set<String>) {
                if(!current(token,own))return
                if(resources.any {it in setOf("rooms","friends","devices","playlists","music","trip.$tripId.music","trip.$tripId.detail")}) {
                    if(resources.any {it in setOf("playlists","devices")}){sourcesGeneration++;ownRead?.close();mutable.value=state.copy(sourceStatus=TripMusicStatus.IDLE,sources=emptyList())}
                    if(state.writing || state.refreshing)dirty=true else readCollection(own,token)
                }
            }
        }) {result->
            if(client!==own || token!=generation || closed || !available)return@open
            result.fold(onSuccess={if(own.current)readCollection(own,token) else unavailable()},onFailure={unavailable()})
        }
    }
    private fun unavailable() {cancel();mutable.value=TripMusicState(status=TripMusicStatus.UNAVAILABLE)}
    private fun readCollection(own: TripMusicGateway,token: Long) {
        read?.close();val serial=++reading;dirty=false
        mutable.value=state.copy(status=if(state.collection!=null)TripMusicStatus.READY else TripMusicStatus.LOADING,refreshing=true)
        read=own.read {result->
            if(!current(token,own) || serial!=reading)return@read
            result.fold(onSuccess={collection->
                if(apply(collection) && dirty)readCollection(own,token)
            },onFailure={mutable.value=state.copy(status=TripMusicStatus.UNAVAILABLE,collection=null,
                refreshing=false,announcement=null)})
        }
    }
    fun loadSources() {
        val own=client ?: return
        if(!current(generation,own) || state.writing || state.refreshing)return
        ownRead?.close();val token=generation;val serial=++sourcesGeneration
        mutable.value=state.copy(sourceStatus=TripMusicStatus.LOADING,sources=emptyList())
        ownRead=own.sources {result->
            if(!current(token,own) || serial!=sourcesGeneration)return@sources
            result.fold(onSuccess={mutable.value=state.copy(sourceStatus=TripMusicStatus.READY,sources=it)},onFailure={error->
                val denied=error is VehicleConnection.ScopeRequired || (error as? NativeSocialFailure)?.kind==NativeSocialFailure.Kind.FORBIDDEN ||
                    (error as? NativeApiClient.Failure)?.status==403
                mutable.value=state.copy(sourceStatus=if(denied)TripMusicStatus.PERMISSION_REQUIRED else TripMusicStatus.UNAVAILABLE,sources=emptyList())
            })
        }
    }
    fun add(item: TripMusicSourceItem) {
        val own=client ?: return
        if(!current(generation,own) || state.writing || state.refreshing || state.status!=TripMusicStatus.READY ||
            state.collection?.canAdd!=true || state.sourceStatus!=TripMusicStatus.READY || item !in state.sources)return
        val token=generation
        mutable.value=state.copy(adding=item.key,notice=null)
        write=own.add(item.source,true,true) {result->
            if(!current(token,own))return@add
            mutable.value=state.copy(adding=null)
            result.fold(onSuccess={collection->
                if(!apply(collection))return@fold
                mutable.value=state.copy(addedSequence=state.addedSequence+1)
                if(dirty)readCollection(own,token)
            },onFailure={error->
                val conflict=(error as? NativeSocialFailure)?.kind==NativeSocialFailure.Kind.CONFLICT || (error as? NativeApiClient.Failure)?.status==409
                mutable.value=state.copy(notice=if(conflict)"내 음악이 바뀌었어요. 목록을 확인해 주세요" else "추가하지 못했어요. 다시 시도해 주세요")
                if(conflict)loadSources()
                if(dirty)readCollection(own,token)
            })
        }
    }
    private fun ready(own: TripMusicGateway)=current(generation,own) && !state.writing && !state.refreshing &&
        state.status==TripMusicStatus.READY
    /** Opens the saved music link, then records which item this car last opened. */
    fun play(item: TripSavedPlaylist,openLink: (String)->TripMusicOpen) {
        val own=client ?: return
        if(!ready(own) || item !in state.collection?.items.orEmpty())return
        mutable.value=state.copy(notice=null)
        val opened=openLink(item.url)
        if(opened!=TripMusicOpen.OPENED){mutable.value=state.copy(notice=opened.notice);return}
        val token=generation
        mutable.value=state.copy(playing=item.id)
        write=own.play(item.id) {result->
            if(!current(token,own))return@play
            mutable.value=state.copy(playing=null)
            result.fold(onSuccess={if(apply(it) && dirty)readCollection(own,token)},onFailure={
                mutable.value=state.copy(notice="연 음악을 일행에게 알리지 못했어요")
                readCollection(own,token)
            })
        }
    }
    /** The item after this car's current one in the trip order; the first item when nothing has been played. */
    fun nextItem(): TripSavedPlaylist? {
        val collection=state.collection ?: return null
        val index=collection.mine?.let {mine->collection.items.indexOfFirst {it.id==mine.itemId}} ?: -1
        return if(index<0)collection.items.firstOrNull() else collection.items.getOrNull(index+1)
    }
    fun playNext(openLink: (String)->TripMusicOpen) {
        val own=client ?: return
        if(!ready(own))return
        val next=nextItem()
        if(next==null){mutable.value=state.copy(notice="다음 음악 링크가 없어요");return}
        play(next,openLink)
    }
    /** Moves [item] after this car's last opened item, or to the top before any link is opened. DJ and owner only. */
    fun queueNext(item: TripSavedPlaylist) {
        val own=client ?: return
        val collection=state.collection
        if(!ready(own) || collection?.canReorder!=true || item !in collection.items)return
        val after=collection.mine?.itemId?.takeIf {it!=item.id && collection.items.any {row->row.id==it}}
        val ids=collection.items.map {it.id}
        if(ids.indexOf(item.id)==(after?.let {ids.indexOf(it)+1} ?: 0))return
        val token=generation
        mutable.value=state.copy(moving=item.id,notice=null)
        write=own.move(item.id,after) {result->
            if(!current(token,own))return@move
            mutable.value=state.copy(moving=null)
            result.fold(onSuccess={if(apply(it) && dirty)readCollection(own,token)},onFailure={error->
                val denied=(error as? NativeSocialFailure)?.kind==NativeSocialFailure.Kind.FORBIDDEN || (error as? NativeApiClient.Failure)?.status==403
                mutable.value=state.copy(notice=if(denied)"DJ나 여행 만든 사람만 순서를 바꿀 수 있어요" else "순서를 바꾸지 못했어요. 목록을 확인해 주세요")
                readCollection(own,token)
            })
        }
    }
    override fun close(){if(!closed){closed=true;available=false;cancel();mutable.value=TripMusicState()}}
}
