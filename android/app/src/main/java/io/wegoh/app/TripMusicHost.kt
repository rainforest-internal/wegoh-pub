package io.wegoh.app

import androidx.compose.runtime.*
import io.wegoh.app.nativeauth.TripDetail
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.ui.*
import java.io.Closeable

/**
 * One music connection for the trip being viewed, shared by the parked music page and the
 * now-playing bar on the trip and driving screens so both show the same list and notices.
 */
internal class TripMusicSessions(private val gateway: (String)->TripMusicGateway): Closeable {
    private var tripId: String?=null
    private var repository: TripMusicRepository?=null
    fun repository(trip: String): TripMusicRepository {
        repository?.takeIf {tripId==trip}?.let {return it}
        repository?.close()
        tripId=trip
        return TripMusicRepository(trip) {gateway(trip)}.also {repository=it}
    }
    override fun close(){repository?.close();repository=null;tripId=null}
}

@Composable
internal fun rememberTripMusicSessions(connection: VehicleConnection): TripMusicSessions {
    val sessions=remember(connection) {TripMusicSessions {trip->NativeTripMusicGateway(connection,trip)}}
    DisposableEffect(sessions) {onDispose {sessions.close()}}
    return sessions
}

@Composable
internal fun TripMusicHost(sessions: TripMusicSessions,connection: VehicleConnection,trip: TripDetail,allowed: Boolean,onBack: ()->Unit,
    onConnection: ()->Unit,onOpen: (String)->TripMusicOpen) {
    val listen=rememberListenTogether(connection,trip,allowed)
    val listenState by listen.states.collectAsState()
    TripMusicBoundPage(sessions.repository(trip.id),trip.title,allowed,onBack,onConnection,onOpen,currentTripDisplay(trip)?.music?.djName,
        listenTogether={enabled->if(listenState.offered)ListenTogetherCard(listenState,enabled,onJoin=listen::join,
            onLeave=listen::leave,onStart=listen::start,onEnd=listen::endForEveryone)})
}

@Composable
internal fun TripMusicBoundPage(repository: TripMusicRepository,title: String,allowed: Boolean,onBack: ()->Unit,
    onConnection: ()->Unit,onOpen: (String)->TripMusicOpen,djName: String?=null,listenTogether: (@Composable (Boolean)->Unit)?=null) {
    val state by repository.states.collectAsState()
    val window=LocalCarWindowVisibility.current
    val currentAllowed by rememberUpdatedState(allowed)
    val lease=remember(repository) {repository.lease()}
    DisposableEffect(repository,window) {
        val observation=window?.observe {lease.available=currentAllowed && it.visible}
        onDispose {observation?.close();lease.close()}
    }
    SideEffect {lease.available=allowed && window?.state?.visible==true}
    fun canInteract()=currentAllowed && window?.state?.let {it.visible && it.focused}==true
    TripMusicPage(title,state,canInteract(),onBack,onRefresh={if(canInteract())repository.refresh()},
        onSources={if(canInteract())repository.loadSources()},onAdd={item->if(canInteract())repository.add(item)},
        onPlay={item->if(canInteract())repository.play(item,onOpen)},onPlayNext={if(canInteract())repository.playNext(onOpen)},
        onQueueNext={item->if(canInteract())repository.queueNext(item)},
        onDismissAnnouncement=repository::dismissAnnouncement,
        onConnection={if(canInteract())onConnection()},djName=djName,listenTogether=listenTogether)
}

/**
 * The trip and driving screens' now-playing bar. It stays readable while driving and offers only the
 * playback controls allowed for music while driving: play/pause and next on the car's active player.
 */
@Composable
internal fun TripMusicBarHost(sessions: TripMusicSessions,trip: TripDetail,onOpen: (()->Unit)?,
    modifier: androidx.compose.ui.Modifier) {
    val context=androidx.compose.ui.platform.LocalContext.current
    val repository=sessions.repository(trip.id)
    val state by repository.states.collectAsState()
    val window=LocalCarWindowVisibility.current
    val lease=remember(repository) {repository.lease()}
    DisposableEffect(repository,window) {
        val observation=window?.observe {lease.available=it.visible}
        onDispose {observation?.close();lease.close()}
    }
    SideEffect {lease.available=window?.state?.visible==true}
    val focused=window?.state?.let {it.visible && it.focused}==true
    TripMusicNowPlayingBar(state,focused,onOpen,repository::dismissAnnouncement,
        onMediaKey={keyCode->dispatchCarMediaKey(context,keyCode)},modifier=modifier)
}
