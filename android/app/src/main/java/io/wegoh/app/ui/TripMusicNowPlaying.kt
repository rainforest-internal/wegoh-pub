package io.wegoh.app.ui

import android.content.Context
import android.media.AudioManager
import android.view.KeyEvent
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import io.wegoh.app.TripMusicAnnouncement
import io.wegoh.app.TripMusicState
import io.wegoh.app.TripMusicStatus
import io.wegoh.app.nativeauth.TripMusicCollection
import io.wegoh.app.nativeauth.TripDetail
import kotlinx.coroutines.delay

/** Provided by the activity so trip screens can show the shared now-playing bar without new parameters. */
internal val LocalTripMusicBar=staticCompositionLocalOf<(@Composable (TripDetail,(()->Unit)?,Modifier)->Unit)?> {null}

internal const val TRIP_MUSIC_ANNOUNCEMENT_MILLIS=6_000L

/**
 * Sends a media key to the car's active media session. This is the public AudioManager path, so it
 * needs no notification-listener or media-control permission and never brings another app forward.
 */
internal fun dispatchCarMediaKey(context: Context,keyCode: Int): Boolean = runCatching {
    val audio=context.getSystemService(AudioManager::class.java) ?: return false
    audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN,keyCode))
    audio.dispatchMediaKeyEvent(KeyEvent(KeyEvent.ACTION_UP,keyCode))
    true
}.getOrDefault(false)

internal fun tripMusicPlayingLines(collection: TripMusicCollection): Pair<String,List<String>>? {
    val (playback,item)=collection.playing ?: return null
    val openedBy=if(playback.startedById==collection.viewerId)"내 차에서 열었어요" else "${playback.startedByName}님이 열었어요"
    return item.title to listOf("${item.addedByName} 추가",openedBy)
}

@Composable
internal fun TripMusicAnnouncementBanner(announcement: TripMusicAnnouncement?,onDismiss: (Int)->Unit) {
    val current=announcement ?: return
    LaunchedEffect(current.sequence) {delay(TRIP_MUSIC_ANNOUNCEMENT_MILLIS);onDismiss(current.sequence)}
    CarCard(tone=CarCardTone.SOFT,padding=PaddingValues(CarTokens.SpaceMedium)) {
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
            CarIcon(CarSymbol.Music,color=LocalCarPalette.current.accent)
            TripText(current.text,Modifier.weight(1f),style=CarType.Label,maxLines=2)
        }
    }
}

@Composable
private fun rememberMusicActive(context: Context,visible: Boolean): State<Boolean> {
    val active=remember {mutableStateOf(false)}
    LaunchedEffect(context,visible) {
        active.value=false
        if(!visible)return@LaunchedEffect
        val audio=context.getSystemService(AudioManager::class.java)
        while(true) {active.value=audio?.isMusicActive==true;delay(1_000)}
    }
    return active
}

@Composable
internal fun TripMusicNowPlayingBar(state: TripMusicState,controls: Boolean,onOpen: (()->Unit)?,
    onDismissAnnouncement: (Int)->Unit,onMediaKey: (Int)->Boolean,modifier: Modifier=Modifier) {
    val context=LocalContext.current
    val window=LocalCarWindowVisibility.current
    val currentControls by rememberUpdatedState(controls)
    val currentOpen by rememberUpdatedState(onOpen)
    val currentMediaKey by rememberUpdatedState(onMediaKey)
    var attached by remember {mutableStateOf(false)}
    DisposableEffect(Unit) {attached=true;onDispose {attached=false}}
    fun canControl()=attached && currentControls && window?.state?.let {it.visible && it.focused}==true
    fun sendMediaKey(keyCode: Int) {if(canControl())currentMediaKey(keyCode)}
    val musicActive by rememberMusicActive(context,window?.state?.visible==true)
    val collection=state.collection?.takeIf {state.status==TripMusicStatus.READY}
    val lines=collection?.let(::tripMusicPlayingLines)
    Column(modifier,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
        CarCard(tone=CarCardTone.OUTLINED,padding=PaddingValues(CarTokens.SpaceMedium)) {
            Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium),verticalAlignment=Alignment.CenterVertically) {
                CarIcon(CarSymbol.Music,color=LocalCarPalette.current.accent)
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    TripText(if(lines!=null)"마지막으로 연 음악" else "여행 음악",style=CarType.Caption,secondary=true)
                    if(lines!=null) {
                        TripText(lines.first,style=CarType.Label,maxLines=1)
                        CarMetadata(lines.second,style=CarType.Caption)
                    } else collection?.let {TripText("링크 ${it.items.size}개",style=CarType.Label)}
                }
                Column(horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.spacedBy(CarTokens.SpaceSmall)) {
                    TripText("내 차 음악",style=CarType.Caption,secondary=true)
                    Row(horizontalArrangement=Arrangement.spacedBy(CarTokens.SpaceMedium)) {
                        CarIconAction(if(musicActive)"내 차 음악 일시정지" else "내 차 음악 재생",if(musicActive)CarSymbol.Pause else CarSymbol.Play,
                            {sendMediaKey(KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE)},canControl())
                        CarIconAction("내 차 음악 다음 곡",CarSymbol.SkipNext,{sendMediaKey(KeyEvent.KEYCODE_MEDIA_NEXT)},canControl())
                        if(onOpen!=null)CarIconAction("여행 음악 열기",CarSymbol.More,{if(canControl())currentOpen?.invoke()},canControl())
                    }
                }
            }
        }
        TripMusicAnnouncementBanner(state.announcement,onDismissAnnouncement)
    }
}
