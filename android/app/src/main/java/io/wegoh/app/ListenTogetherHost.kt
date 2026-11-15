package io.wegoh.app

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.annotation.OptIn
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import io.wegoh.app.ui.CarWindowVisibility
import io.wegoh.app.ui.LocalCarWindowVisibility
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.ExoPlayer
import io.wegoh.app.nativeauth.*
import java.io.Closeable
import java.security.MessageDigest
import java.util.concurrent.Executors

/** Demo track bundled only in debug builds; release builds carry no file and never offer the feature. */
internal object ListenTogetherTrackAsset {
    const val PATH="listen-together/wegoh-demo-01.wav"
    const val URI="asset:///$PATH"
    fun sha256(context: Context): String? = runCatching {
        val digest=MessageDigest.getInstance("SHA-256")
        context.assets.open(PATH).use {input->
            val buffer=ByteArray(64*1024)
            while(true){val read=input.read(buffer);if(read<0)break;digest.update(buffer,0,read)}
        }
        digest.digest().joinToString("") {"%02x".format(it)}
    }.getOrNull()
}

internal class NativeListenTogetherGateway(private val connection: VehicleConnection,private val tripId: String): ListenTogetherGateway {
    private val social=connection.tripSocial()
    private val api=NativeListenTogetherApi(social)
    private val epoch=connection.dataEpoch()
    private var closed=false
    override val current get()=!closed && connection.dataEpoch()==epoch && social.status()==NativeSocialClient.State.READY
    override fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit)=social.open(observer,callback)
    override fun read(callback: (Result<ListenTogetherSnapshot>)->Unit)=api.read(tripId,callback)
    override fun participate(sessionId: String?,trackSha256: String,joined: Boolean,callback: (Result<ListenTogetherSnapshot>)->Unit)=
        api.participate(tripId,sessionId,trackSha256,joined,callback)
    override fun start(sessionId: String,revision: Long,callback: (Result<ListenTogetherSnapshot>)->Unit)=api.start(tripId,sessionId,revision,callback)
    override fun end(sessionId: String,callback: (Result<ListenTogetherSnapshot>)->Unit)=api.end(tripId,sessionId,callback)
    override fun close(){if(!closed){closed=true;social.close()}}
}

internal class MainListenTogetherTimer: ListenTogetherTimer {
    private val main=Handler(Looper.getMainLooper())
    override val elapsedMs get()=SystemClock.elapsedRealtime()
    override fun post(delayMs: Long,action: ()->Unit): Closeable {
        val task=Runnable(action)
        main.postDelayed(task,delayMs.coerceAtLeast(0))
        return Closeable {main.removeCallbacks(task)}
    }
}

/** Media3 player for the bundled file. Media3 owns audio focus, so Pleos focus policy pauses, ducks or stops it. */
@OptIn(UnstableApi::class)
internal class Media3ListenTogetherPlayer(context: Context): ListenTogetherPlayer {
    private val player=ExoPlayer.Builder(context.applicationContext)
        .setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(),true)
        .setHandleAudioBecomingNoisy(true).build()
    private var prepared=false
    override var listener: ListenTogetherPlayer.Listener?=null
    override val positionMs get()=player.currentPosition
    override val suspended get()=player.playWhenReady && player.playbackSuppressionReason!=Player.PLAYBACK_SUPPRESSION_REASON_NONE
    init {
        player.addListener(object: Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) {listener?.onPlaying(isPlaying)}
            override fun onPlaybackStateChanged(playbackState: Int) {if(playbackState==Player.STATE_ENDED)listener?.onEnded()}
            override fun onPlayerError(error: PlaybackException) {listener?.onError()}
            override fun onPlayWhenReadyChanged(playWhenReady: Boolean,reason: Int) {
                if(!playWhenReady && reason in setOf(Player.PLAY_WHEN_READY_CHANGE_REASON_AUDIO_FOCUS_LOSS,
                        Player.PLAY_WHEN_READY_CHANGE_REASON_AUDIO_BECOMING_NOISY))listener?.onStoppedBySystem()
            }
        })
    }
    override fun prepare() {
        if(prepared)return
        prepared=true
        player.setMediaItem(MediaItem.fromUri(ListenTogetherTrackAsset.URI))
        player.prepare()
    }
    override fun playFrom(positionMs: Long) {
        prepare();player.seekTo(positionMs);player.play()
        // A denied focus request leaves playWhenReady false: this vehicle stays silent and leaves on its own.
        if(!player.playWhenReady)listener?.onStoppedBySystem()
    }
    override fun seekTo(positionMs: Long)=player.seekTo(positionMs)
    override fun stop() {player.pause();player.seekTo(0)}
    override fun close() {listener=null;player.release()}
}

/** Feeds the repository the gear, CarUx and window facts it needs before any audio may play. */
private class ListenTogetherEnvironment(context: Context,private val repository: ListenTogetherRepository): Closeable {
    var allowed=false
    var window: CarWindowVisibility?=null
    private var safety: ClimateCarSafety?=null
    private val main=Handler(Looper.getMainLooper())
    private val hashing=Executors.newSingleThreadExecutor()
    init {
        safety=ClimateCarSafety(context) {publish()}
        hashing.execute {val sha=ListenTogetherTrackAsset.sha256(context);main.post {repository.setTrack(sha)}}
    }
    fun publish() {
        val car=safety?.snapshot()
        val state=window?.state
        repository.setEnvironment(allowed && state?.visible==true,state?.focused==true,
            car?.takeIf {it.carUxKnown}?.parked,car?.takeIf {it.carUxKnown}?.let {it.setupAllowed && allowed})
    }
    override fun close() {hashing.shutdownNow();repository.close();safety?.close();safety=null}
}

@Composable
internal fun rememberListenTogether(connection: VehicleConnection,trip: TripDetail,allowed: Boolean): ListenTogetherRepository {
    val context=LocalContext.current
    val window=LocalCarWindowVisibility.current
    val repository=remember(connection,trip.id) {
        ListenTogetherRepository({NativeListenTogetherGateway(connection,trip.id)},{Media3ListenTogetherPlayer(context)},MainListenTogetherTimer()) {
            WegoLog.i("WegoH","listen.sync $it")
        }
    }
    val environment=remember(repository) {ListenTogetherEnvironment(context,repository)}
    DisposableEffect(environment) {onDispose {environment.close()}}
    DisposableEffect(environment,window) {
        environment.window=window
        val observation=window?.observe {environment.publish()}
        onDispose {observation?.close()}
    }
    SideEffect {environment.allowed=allowed;environment.window=window;environment.publish()}
    return repository
}
