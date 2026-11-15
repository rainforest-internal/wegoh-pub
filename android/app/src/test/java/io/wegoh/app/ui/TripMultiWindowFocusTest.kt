package io.wegoh.app.ui

import io.wegoh.app.nativeauth.NativeVoiceAudioSafety
import io.wegoh.app.tripVoiceFocusLost
import io.wegoh.app.tripVoiceForeground
import io.wegoh.app.withSafety
import org.junit.Assert.*
import org.junit.Test

/** Pleos 멀티 윈도우: WegoH 창이 보이고 RESUMED인 채 포커스만 내비 창에 있는 경우. */
class TripMultiWindowFocusTest {
    private val besideNavigation=CarWindowState(visible=true,focused=false)
    private val touched=CarWindowState(visible=true,focused=true)
    private val hidden=CarWindowState(visible=false,focused=false)

    @Test fun voiceStaysConnectedWhileNavigationHasFocus() {
        assertTrue(tripVoiceForeground(window=besideNavigation,shown=true))
        val ui=TripInlineVoiceUi(TripInlineVoicePhase.LISTENING).withSafety(NativeVoiceAudioSafety(foreground=true,carUxAllowed=true),tripAllowed=true)
        assertTrue(ui.permitted)
        assertNull("The card must not fall back to SCREEN_INACTIVE",ui.block)
    }

    @Test fun voiceStillDisconnectsWhenWindowIsNotVisible() {
        assertFalse(tripVoiceForeground(hidden,shown=true))
        assertFalse(tripVoiceForeground(null,shown=true))
        assertFalse(tripVoiceForeground(besideNavigation,shown=false))
        val ui=TripInlineVoiceUi(TripInlineVoicePhase.OFF).withSafety(NativeVoiceAudioSafety(foreground=false,carUxAllowed=true),true)
        assertEquals(TripInlineVoiceBlock.SCREEN_INACTIVE,ui.block)
    }

    /** 여행 다시 읽기(isCurrent=false)는 연결을 끊는 화면 조건이 아니다. 조작만 TRIP_STATE로 막는다. */
    @Test fun tripReloadBlocksControlsWithoutDisconnecting() {
        assertTrue(tripVoiceForeground(window=touched,shown=true))
        val ui=TripInlineVoiceUi(TripInlineVoicePhase.LISTENING,participating=true)
            .withSafety(NativeVoiceAudioSafety(foreground=true,carUxAllowed=true),tripAllowed=false)
        assertFalse(ui.permitted)
        assertEquals(TripInlineVoiceBlock.TRIP_STATE,ui.block)
        assertEquals("Connection phase is kept while the trip reloads",TripInlineVoicePhase.LISTENING,ui.phase)
    }

    @Test fun drivingRestrictionIsUnchangedByFocus() {
        val ui=TripInlineVoiceUi(TripInlineVoicePhase.LISTENING).withSafety(NativeVoiceAudioSafety(foreground=true,carUxAllowed=false),true)
        assertFalse(ui.permitted)
        assertEquals(TripInlineVoiceBlock.PARK_REQUIRED,ui.block)
    }

    @Test fun onlyLosingFocusEndsRecording() {
        assertTrue(tripVoiceFocusLost(touched,besideNavigation))
        assertTrue(tripVoiceFocusLost(touched,hidden))
        assertFalse("First observation is not a focus loss",tripVoiceFocusLost(null,besideNavigation))
        assertFalse(tripVoiceFocusLost(besideNavigation,besideNavigation))
        assertFalse("Touching WegoH to start recording gains focus",tripVoiceFocusLost(besideNavigation,touched))
        assertFalse(tripVoiceFocusLost(touched,touched))
    }

    @Test fun handRaiseShowsInVisibleWindowWithoutFocus() {
        assertTrue(showsTripSignalOverlay(besideNavigation))
        assertTrue(showsTripSignalOverlay(touched))
        assertTrue(showsTripSignalOverlay(null))
        assertFalse(showsTripSignalOverlay(hidden))
    }
}
