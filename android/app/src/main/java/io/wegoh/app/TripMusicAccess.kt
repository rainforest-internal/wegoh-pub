package io.wegoh.app

import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.*
import java.io.Closeable
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

internal class NativeTripMusicGateway(private val connection: VehicleConnection,private val tripId: String): TripMusicGateway {
    private val social=connection.tripSocial()
    private val api=NativeTripMusicApi(social)
    private val epoch=connection.dataEpoch()
    private val worker=Executors.newSingleThreadExecutor()
    private val main=Handler(Looper.getMainLooper())
    private var closed=false
    private var observer: NativeSocialObserver?=null
    private var ownBoundary: VehicleConnection.DataBoundary?=null
    private var observedBoundary=connection.contentDataBoundary(VehicleConnection.Scope.PLAYLISTS)
    private var observedRevision=connection.dataStreamRevision()
    private val accountObserver=connection.observe {
        val boundary=connection.contentDataBoundary(VehicleConnection.Scope.PLAYLISTS)
        val revision=connection.dataStreamRevision()
        if(boundary!=observedBoundary || revision!=observedRevision) {
            observedBoundary=boundary;observedRevision=revision;ownBoundary=null
            if(!closed)observer?.onResourcesChanged(setOf("playlists"))
        }
    }
    override val current get()=!closed && connection.dataEpoch()==epoch && social.status()==NativeSocialClient.State.READY
    override fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit){this.observer=observer;social.open(observer,callback)}
    override fun read(callback: (Result<TripMusicCollection>)->Unit)=api.read(tripId,callback)
    override fun add(source: TripSavedPlaylistSource,rights: Boolean,review: Boolean,callback: (Result<TripMusicCollection>)->Unit): Closeable {
        if(ownBoundary==null || ownBoundary!=connection.contentDataBoundary(VehicleConnection.Scope.PLAYLISTS)) {
            callback(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.FORBIDDEN)));return Closeable {}
        }
        return api.add(tripId,source,rights,review,callback)
    }
    override fun play(itemId: String,callback: (Result<TripMusicCollection>)->Unit)=api.play(tripId,itemId,callback)
    override fun move(itemId: String,afterId: String?,callback: (Result<TripMusicCollection>)->Unit)=api.move(tripId,itemId,afterId,callback)
    override fun sources(callback: (Result<List<TripMusicSourceItem>>)->Unit): Closeable {
        val cancelled=AtomicBoolean(false)
        val boundary=connection.contentDataBoundary(VehicleConnection.Scope.PLAYLISTS)
        val revision=connection.dataStreamRevision()
        connection.playlistsApi.readPlaylists {result->
            if(!current || cancelled.get())return@readPlaylists
            result.fold(onSuccess={document->worker.execute {
                val parsed=runCatching {
                    val rows=document.asObject().getJSONArray("playlists");check(rows.length()<=100)
                    val lists=(0 until rows.length()).map {PlaylistsRepository.parseDetail(rows.getJSONObject(it))}
                    check(lists.map {it.summary.id}.distinct().size==lists.size)
                    lists.flatMap {list->list.tracks.map {track->TripMusicSourceItem(
                        TripSavedPlaylistSource(list.summary.id,list.summary.revision,track.id),track.title,playlistProvider(track.host),track.url)}}
                }
                main.post {
                    if(current && !cancelled.get() && boundary!=null && boundary==connection.contentDataBoundary(VehicleConnection.Scope.PLAYLISTS) && revision==connection.dataStreamRevision()) {
                        ownBoundary=boundary;callback(parsed)
                    }
                }
            }},onFailure={if(current && !cancelled.get())callback(Result.failure(it))})
        }
        return Closeable {cancelled.set(true)}
    }
    override fun close(){if(!closed){closed=true;ownBoundary=null;observer=null;accountObserver.close();social.close();worker.shutdownNow()}}
}

internal fun playlistProvider(host: String)=when(host.lowercase(java.util.Locale.ROOT)) {
    "melon.com","www.melon.com","m.melon.com","m2.melon.com","kko.to","kko.kakao.com"->"멜론"
    "open.spotify.com","spotify.link"->"Spotify"
    "music.youtube.com"->"YouTube Music"
    "youtube.com","www.youtube.com","m.youtube.com","youtu.be"->"YouTube"
    else->"음악 링크"
}
