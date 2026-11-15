package io.wegoh.app.ui

import io.wegoh.app.TripMicrophoneRequest
import io.wegoh.app.microphonePermissionNotice
import io.wegoh.app.tripMicrophoneRequest
import org.junit.Assert.*
import org.junit.Test

class TripInlineVoiceTextTest {
    private val listening=TripInlineVoiceUi(TripInlineVoicePhase.LISTENING)

    @Test fun missingMicrophoneAsksForPermissionInsteadOfConnection() {
        val text=tripInlineVoiceText(listening.copy(microphone=false),recordingRequested=false)
        assertEquals("마이크 허용",text.action)
        assertEquals(TRIP_VOICE_MICROPHONE_DETAIL,text.detail)
        assertTrue("The tap must reach the permission request",text.enabled && text.canStart)
        assertNotEquals("연결 확인",text.status)
    }

    @Test fun grantedMicrophoneRecords() {
        val text=tripInlineVoiceText(listening,recordingRequested=false)
        assertEquals("녹음",text.action)
        assertNull(text.detail)
    }

    @Test fun missingMicrophoneDoesNotHideConnectionOrReceiving() {
        val unavailable=tripInlineVoiceText(TripInlineVoiceUi(TripInlineVoicePhase.UNAVAILABLE,microphone=false),false)
        assertEquals("연결 확인",unavailable.action)
        val hearing=tripInlineVoiceText(TripInlineVoiceUi(TripInlineVoicePhase.HEARING,microphone=false),false)
        assertEquals("음성 재생 중",hearing.action)
    }

    @Test fun carBlocksWinOverMicrophone() {
        val text=tripInlineVoiceText(listening.copy(permitted=false,microphone=false,block=TripInlineVoiceBlock.PARK_REQUIRED),false)
        assertEquals("P단에서 이용",text.action)
        assertFalse(text.enabled)
    }

    @Test fun loadingNamesWhatIsBeingPrepared() {
        val text=tripInlineVoiceText(TripInlineVoiceUi(),recordingRequested=false)
        assertEquals("준비 중",text.action)
        assertEquals("음성 연결을 준비하고 있어요",text.detail)
        assertEquals("워키토키",TRIP_VOICE_TARGET)
    }

    @Test fun sideActionsAreLabeledAndNeverDuplicateTheMainAction() {
        val off=tripInlineVoiceText(listening,false).side
        assertEquals(TripInlineVoiceSide.OFF,off)
        assertEquals("끄기",off?.label)
        assertEquals("워키토키 끄기",off?.accessibility)
        assertEquals(TripInlineVoiceSide.RETRY,tripInlineVoiceText(TripInlineVoiceUi(TripInlineVoicePhase.UNAVAILABLE),false).side)
        assertNull("Turned off: the main button already turns it on",
            tripInlineVoiceText(TripInlineVoiceUi(TripInlineVoicePhase.OFF,participating=false),false).side)
        val preparing=tripInlineVoiceText(listening.copy(phase=TripInlineVoicePhase.REQUESTING),recordingRequested=true)
        assertEquals("취소",preparing.action)
        assertNull("The main button already cancels",preparing.side)
        val recorded=tripInlineVoiceText(listening.copy(phase=TripInlineVoicePhase.RECORDED),recordingRequested=true)
        assertEquals("보내기",recorded.action)
        assertEquals(TripInlineVoiceSide.CANCEL,recorded.side)
        assertEquals("녹음 취소",recorded.side?.accessibility)
        for(side in TripInlineVoiceSide.entries)assertTrue(side.label.isNotBlank() && side.label.length<=TRIP_VOICE_LABEL_CHARS)
    }

    @Test fun noticeFromPermissionResultIsShown() {
        val text=tripInlineVoiceText(listening.copy(microphone=false,notice=microphonePermissionNotice(false,blocked=true)),false)
        assertEquals("설정에서 마이크를 허용해 주세요",text.detail)
        assertEquals("다시 눌러 말해 주세요",microphonePermissionNotice(true,false))
        assertEquals(TRIP_VOICE_MICROPHONE_DETAIL,microphonePermissionNotice(false,false))
    }

    @Test fun permanentlyDeniedMicrophoneOpensSettingsInsteadOfAskingAgain() {
        assertEquals(TripMicrophoneRequest.SETTINGS,tripMicrophoneRequest(granted=false,blocked=true))
        assertEquals(TripMicrophoneRequest.ASK,tripMicrophoneRequest(granted=false,blocked=false))
        assertEquals(TripMicrophoneRequest.RECORD,tripMicrophoneRequest(granted=true,blocked=true))
        val text=tripInlineVoiceText(listening.copy(microphone=false,microphoneBlocked=true),recordingRequested=false)
        assertEquals("설정 열기",text.action)
        assertEquals(TRIP_VOICE_MICROPHONE_SETTINGS_DETAIL,text.detail)
        assertTrue("The tap must reach the settings shortcut",text.enabled && text.canStart)
        assertEquals("마이크 허용",tripInlineVoiceText(listening.copy(microphone=false),false).action)
    }

    @Test fun everyLabelFitsOneLineAndDetailThreeLines() {
        for(phase in TripInlineVoicePhase.entries)for(participating in listOf(true,false))for(microphone in listOf(true,false))
            for(blocked in listOf(true,false))for(requested in listOf(true,false))for(block in TripInlineVoiceBlock.entries.map {it as TripInlineVoiceBlock?}+null) {
                val ui=TripInlineVoiceUi(phase,participating,permitted=block==null,block=block,microphone=microphone,microphoneBlocked=blocked)
                val text=tripInlineVoiceText(ui,requested)
                assertTrue("${text.action} for $ui",text.action.length<=TRIP_VOICE_LABEL_CHARS)
                assertTrue("${text.detail} for $ui",(text.detail?.length ?: 0)<=24)
            }
    }
}
