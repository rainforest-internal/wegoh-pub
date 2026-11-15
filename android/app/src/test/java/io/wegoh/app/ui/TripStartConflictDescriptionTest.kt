package io.wegoh.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TripStartConflictDescriptionTest {
    @Test
    fun completingMatchesTheFinishPopupSentences() {
        assertEquals("모든 차의 주행을 끝내고 기록을 저장해요. 완료한 여행은 다시 시작할 수 없어요.",tripStartConflictDescription(completing=true,leaving=false))
        assertEquals("다른 일행의 여행은 계속돼요.",tripStartConflictDescription(completing=false,leaving=true))
    }

    @Test
    fun everySentenceEndsWithAPeriod() {
        listOf(true to false,false to true,true to true).forEach {(completing,leaving)->
            val text=tripStartConflictDescription(completing,leaving)
            assertTrue(text,text.split(". ").all {it.isNotBlank()} && text.endsWith("."))
        }
    }
}
