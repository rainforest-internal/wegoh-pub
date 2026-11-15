package io.wegoh.app

import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import android.test.InstrumentationTestCase
import java.util.concurrent.CopyOnWriteArrayList

/** Actual AAOS public focus contexts. Not real telephone/Gleo/emergency hardware. */
@Suppress("DEPRECATION")
class AudioPolicyTests: InstrumentationTestCase() {
    private lateinit var activity: MainActivity
    private lateinit var audio: AudioManager
    private val requests=mutableListOf<AudioFocusRequest>()
    override fun setUp() {
        super.setUp()
        activity=instrumentation.startActivitySync(Intent(instrumentation.targetContext,MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        audio=activity.getSystemService(AudioManager::class.java)
        instrumentation.waitForIdleSync()
    }
    private fun focus(usage: Int,gain: Int,name: String,events: MutableList<String>): Int {
        var result=-1
        instrumentation.runOnMainSync {
            val request=AudioFocusRequest.Builder(gain).setAudioAttributes(AudioAttributes.Builder().setUsage(usage).build())
                .setOnAudioFocusChangeListener({events.add("$name:$it")},Handler(Looper.getMainLooper())).build()
            requests.add(request);result=audio.requestAudioFocus(request)
        }
        return result
    }
    private fun release() {instrumentation.runOnMainSync{requests.forEach {audio.abandonAudioFocusRequest(it)};requests.clear()};Thread.sleep(150)}
    fun testPublicMusicNavigationCallAndVoiceFocusMatrix() {
        val events=CopyOnWriteArrayList<String>()
        assertEquals(AudioManager.AUDIOFOCUS_REQUEST_GRANTED,focus(AudioAttributes.USAGE_MEDIA,AudioManager.AUDIOFOCUS_GAIN,"music",events))
        assertEquals(AudioManager.AUDIOFOCUS_REQUEST_GRANTED,focus(AudioAttributes.USAGE_ASSISTANCE_NAVIGATION_GUIDANCE,AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK,"navigation",events))
        assertEquals(AudioManager.AUDIOFOCUS_REQUEST_GRANTED,focus(AudioAttributes.USAGE_ASSISTANT,AudioManager.AUDIOFOCUS_GAIN_TRANSIENT,"voice",events))
        val deadline=System.currentTimeMillis()+5000
        fun musicLostFocus()=events.any {it=="music:${AudioManager.AUDIOFOCUS_LOSS_TRANSIENT}" || it=="music:${AudioManager.AUDIOFOCUS_LOSS}"}
        while(System.currentTimeMillis()<deadline && !musicLostFocus())Thread.sleep(20)
        assertTrue("Voice takes music focus; callbacks=$events",musicLostFocus())
        release();events.clear()
        assertEquals(AudioManager.AUDIOFOCUS_REQUEST_GRANTED,focus(AudioAttributes.USAGE_VOICE_COMMUNICATION,AudioManager.AUDIOFOCUS_GAIN_TRANSIENT,"call",events))
        assertEquals(AudioManager.AUDIOFOCUS_REQUEST_FAILED,focus(AudioAttributes.USAGE_MEDIA,AudioManager.AUDIOFOCUS_GAIN,"rejected-music",events))
        release()
    }
    fun testCueAbandonsOnVoiceLossAndDoesNotRestartAfterPeerRelease() {
        val events=CopyOnWriteArrayList<String>();val cue=ArrivalCue(activity)
        try {
            instrumentation.runOnMainSync {cue.play {events.add(it)}}
            assertTrue("Actual chime starts with focus",events.contains("AUDIO_STARTED"))
            assertEquals(AudioManager.AUDIOFOCUS_REQUEST_GRANTED,focus(AudioAttributes.USAGE_ASSISTANT,AudioManager.AUDIOFOCUS_GAIN_TRANSIENT,"voice",events))
            val end=System.currentTimeMillis()+2500
            while(System.currentTimeMillis()<end && !events.contains("AUDIO_FOCUS_RELEASED"))Thread.sleep(20)
            assertTrue("Focus loss must interrupt before natural completion: $events",events.contains("AUDIO_FOCUS_RELEASED"))
            instrumentation.runOnMainSync {assertFalse(cue.active);assertFalse(cue.ownsFocus)}
            release();Thread.sleep(700)
            assertEquals(1,events.count {it=="AUDIO_STARTED"})
            instrumentation.runOnMainSync {assertFalse(cue.active);assertFalse(cue.ownsFocus)}
        }finally{instrumentation.runOnMainSync{cue.stop()}}
    }
    override fun tearDown(){release();if(::activity.isInitialized)instrumentation.runOnMainSync{activity.finish()};super.tearDown()}
}
