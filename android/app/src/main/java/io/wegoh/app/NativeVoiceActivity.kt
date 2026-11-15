package io.wegoh.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.SystemClock
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import io.wegoh.app.nativeauth.*
import io.wegoh.app.ui.*

/** Parked, visible walkie-talkie. Turning it on, every talk turn and every reconnect is an explicit tap;
 * listening resumes by itself only inside the turn the user switched on. No background recording. */
class NativeVoiceActivity: ComponentActivity() {
    private val app get() = application as WegoApplication
    private val connection get() = app.controller.vehicleAccountConnection ?: app.vehicleConnection
    private var voice: NativeVoiceClient? = null
    private var session: NativeVoiceSession? = null
    private var safety: NativeVoiceCarSafety? = null
    private lateinit var windows: CarWindowVisibility
    private var permitted by mutableStateOf(false)
    private var ui by mutableStateOf(WalkieUi())
    private var references: List<VoiceRoomReference> = emptyList()
    private var cursor: VoiceRoomCursor? = null
    private var selected: VoiceRoomReference? = null
    private var epoch = 0
    private var joining = false
    private var paging = false
    private var on = false
    private var armedAt: Long? = null
    private var opened = false
    private val invalidationReloads = InvalidationReloads()
    private var microphoneAsked = false
    private val microphone = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        // A late answer never starts a transmission or a session; the next tap does.
        show(ui.phase, if (granted) {
            if (on) "말하기를 눌러 주세요" else "워키토키를 켜 주세요"
        } else "말하려면 마이크 권한을 허용해 주세요")
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        safety = NativeVoiceCarSafety(this) { value ->
            val next = value.permits()
            voice?.updateSafety(value.foreground, value.carUxAllowed)
            if (!next && permitted) drop(null)
            permitted = next
            if (next && !opened) { opened = true; connect() }
        }
        windows = CarWindowVisibility(this) {
            app.controller.setVisible(it.visible, this, it.focused)
            safety?.setForeground(it.visible && it.focused)
        }
        val actions = WalkieActions(back={ finish() }, retry=::connect, choose=::choose, more=::page,
            rooms={ if (!on && !joining) show(WalkiePhase.CHOOSE) }, power={ if (on) drop(null) else turnOn() }, talk=::talk)
        setContent {
            BackHandler { finish() }
            ProvideCarWindowVisibility(windows) { WegoCarTheme { WalkieTalkiePage(ui.copy(restricted=!permitted), actions) } }
        }
    }
    private fun room(value: VoiceRoomReference) = WalkieRoom(value.roomId, value.name,
        VoiceDirection.RECEIVE in value.availableDirections, VoiceDirection.TRANSMIT in value.availableDirections)
    private fun show(phase: WalkiePhase, notice: String? = null) {
        ui = ui.copy(phase=phase, notice=notice, room=selected?.let(::room), rooms=references.map(::room), hasMore=cursor != null, locked=joining)
    }
    private fun connect() {
        if (!permitted) return
        voice?.close(); epoch++; session = null; joining = false; paging = false; on = false; armedAt = null
        references = emptyList(); cursor = null; selected = null
        val own = connection.voice(); voice = own
        own.updateSafety(true, true)
        show(WalkiePhase.LOADING)
        own.open(object: NativeVoiceObserver {
            override fun onInvalidated() {
                if (voice !== own) return
                epoch++; session?.close(); session = null; joining = false; paging = false; on = false; armedAt = null
                references = emptyList(); cursor = null; selected = null
                show(WalkiePhase.UNAVAILABLE, "연결이 끊겼어요. 다시 연결해 주세요")
                // 권한 교체만으로 끊긴 경우 다시 연결한다(녹음은 시작하지 않는다).
                if (permitted) invalidationReloads.take()?.let { connect() }
            }
        }) {
            if (voice !== own) return@open
            val trip = intent.getStringExtra(TRIP_ID)
            if (it.isFailure) show(WalkiePhase.UNAVAILABLE) else if (trip == null) page() else trip(own, trip)
        }
    }
    private fun trip(own: NativeVoiceClient, id: String) {
        own.tripRoom(id, intent.getStringExtra(TRIP_TITLE).orEmpty()) {
            if (voice !== own) return@tripRoom
            it.fold(onSuccess={ value ->
                if (value.availableDirections.isEmpty()) { show(WalkiePhase.GUIDE); return@fold }
                references = listOf(value); selected = value; invalidationReloads.reset()
                show(WalkiePhase.OFF)
            }, onFailure={ error -> when {
                consent(error) -> show(WalkiePhase.GUIDE)
                (error as? NativeVoiceFailure)?.kind == NativeVoiceFailure.Kind.STALE ->
                    show(WalkiePhase.UNAVAILABLE, "여행을 시작하면 워키토키를 쓸 수 있어요")
                else -> show(WalkiePhase.UNAVAILABLE)
            } })
        }
    }
    private fun page() {
        if (!permitted) return
        val own = voice ?: return
        if (paging) return
        val first = cursor == null && references.isEmpty()
        paging = true
        own.listRooms(cursor) {
            if (voice !== own) return@listRooms
            paging = false
            it.fold(onSuccess={ result ->
                references = references + result.items; cursor = result.nextCursor; invalidationReloads.reset()
                if (!first) { show(WalkiePhase.CHOOSE); return@fold }
                val title = intent.getStringExtra(TRIP_TITLE)
                val match = references.filter { room -> room.name == title }
                selected = match.singleOrNull() ?: references.singleOrNull()?.takeIf { cursor == null }
                show(when { references.isEmpty() -> WalkiePhase.GUIDE; selected == null -> WalkiePhase.CHOOSE; else -> WalkiePhase.OFF })
            }, onFailure={ error -> show(if (consent(error)) WalkiePhase.GUIDE else WalkiePhase.UNAVAILABLE) })
        }
    }
    private fun consent(error: Throwable) = (error as? NativeVoiceFailure)?.kind in
        setOf(NativeVoiceFailure.Kind.CONSENT_REQUIRED, NativeVoiceFailure.Kind.FORBIDDEN)
    private fun choose(value: WalkieRoom) {
        if (on || joining) return
        selected = references.firstOrNull { it.roomId == value.id } ?: return
        show(WalkiePhase.OFF)
    }
    private fun microphoneGranted() = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    private fun turnOn() {
        val room = selected ?: return
        if (!permitted || on || joining) return
        if (VoiceDirection.TRANSMIT in room.availableDirections && !microphoneGranted() && !microphoneAsked) {
            microphoneAsked = true; microphone.launch(Manifest.permission.RECORD_AUDIO); return
        }
        on = true
        settle(null)
    }
    /** Returns to the resting state of a switched-on walkie-talkie: listening when this car may listen. */
    private fun settle(notice: String?) {
        val room = selected
        if (!on || room == null) { show(if (room == null) WalkiePhase.CHOOSE else WalkiePhase.OFF, notice); return }
        if (joining) { show(WalkiePhase.CONNECTING, notice); return }
        if (VoiceDirection.RECEIVE in room.availableDirections) join(room, VoiceDirection.RECEIVE, notice)
        else show(WalkiePhase.LISTENING, notice)
    }
    private fun join(room: VoiceRoomReference, direction: VoiceDirection, notice: String? = null) {
        val own = voice ?: return
        val mine = ++epoch
        joining = true
        show(if (direction == VoiceDirection.RECEIVE) WalkiePhase.CONNECTING else WalkiePhase.CALLING, notice)
        own.join(room, direction, object: NativeVoiceSessionObserver {
            override fun onState(state: NativeVoiceSession.State) { if (voice === own && epoch == mine) changed(direction, state) }
        }) {
            if (voice !== own) { it.getOrNull()?.close(); return@join }
            joining = false
            if (epoch != mine) { it.getOrNull()?.close(); settle(ui.notice); return@join }
            it.fold(onSuccess={ value -> session = value; changed(direction, value.status()) }, onFailure={ error ->
                epoch++; session = null; on = false; armedAt = null
                if (consent(error)) show(WalkiePhase.GUIDE) else show(WalkiePhase.UNAVAILABLE, "워키토키에 연결하지 못했어요")
            })
        }
    }
    private fun changed(direction: VoiceDirection, state: NativeVoiceSession.State) {
        if (direction == VoiceDirection.RECEIVE) when (state) {
            NativeVoiceSession.State.JOINING -> show(WalkiePhase.CONNECTING, ui.notice)
            NativeVoiceSession.State.RECEIVING -> show(WalkiePhase.HEARING)
            NativeVoiceSession.State.CLOSED -> drop("연결이 끊겼어요. 다시 켜 주세요")
            else -> show(WalkiePhase.LISTENING, ui.notice)
        } else when (state) {
            NativeVoiceSession.State.JOINING, NativeVoiceSession.State.REQUESTING -> show(WalkiePhase.CALLING)
            NativeVoiceSession.State.TRANSMITTING -> show(WalkiePhase.TALKING)
            NativeVoiceSession.State.BUSY -> finishTalk("다른 사람이 말하고 있어요")
            NativeVoiceSession.State.READY -> {
                val tapped = armedAt; armedAt = null
                when {
                    tapped == null -> finishTalk(null)
                    SystemClock.elapsedRealtime() - tapped > TALK_TAP_VALID_MS -> finishTalk("연결이 늦어 말하기를 취소했어요")
                    session?.requestTransmit() != true -> finishTalk("지금은 말할 수 없어요. 다시 눌러 주세요")
                    else -> show(WalkiePhase.CALLING)
                }
            }
            else -> finishTalk(if (ui.phase == WalkiePhase.TALKING) null else "지금은 말할 수 없어요. 다시 눌러 주세요")
        }
    }
    private fun talk() {
        val room = selected ?: return
        if (!permitted || !on) return
        if (ui.phase == WalkiePhase.TALKING) { finishTalk(null); return }
        if (joining || ui.phase != WalkiePhase.LISTENING || VoiceDirection.TRANSMIT !in room.availableDirections) return
        if (!microphoneGranted()) { microphoneAsked = true; microphone.launch(Manifest.permission.RECORD_AUDIO); return }
        epoch++; session?.close(); session = null
        armedAt = SystemClock.elapsedRealtime()
        join(room, VoiceDirection.TRANSMIT)
    }
    private fun finishTalk(notice: String?) {
        armedAt = null; epoch++; session?.close(); session = null
        settle(notice)
    }
    private fun drop(notice: String?) {
        on = false; armedAt = null; epoch++; session?.close(); session = null
        if (ui.phase !in setOf(WalkiePhase.LOADING, WalkiePhase.GUIDE, WalkiePhase.UNAVAILABLE, WalkiePhase.CHOOSE)) show(WalkiePhase.OFF, notice)
    }
    override fun onDestroy() {
        epoch++; voice?.close(); voice = null; safety?.close(); safety = null
        windows.close(); super.onDestroy()
    }
    companion object {
        const val TRIP_ID = "tripId"
        const val TRIP_TITLE = "tripTitle"
        private const val TALK_TAP_VALID_MS = 6000L
    }
}
