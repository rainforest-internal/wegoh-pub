package io.wegoh.app.ui

import io.wegoh.app.DrivePack
import io.wegoh.app.Stop
import io.wegoh.app.WegoState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class RestrictedPackProgressTest {
    private val pack=DrivePack("city-story",1,"도시 이야기","WegoH","",
        listOf(Stop("a","첫 번째 만남",37.5,127.0,100f,"도착"),Stop("b","두 번째 장소",37.6,127.1,100f,"도착")))
    private val waiting=WegoState(packs=listOf(pack),selectedKey=pack.key,policy="차량 연결 대기")

    @Test
    fun selectedPackIsHiddenUntilItRuns() {
        assertNull(restrictedPackProgress(waiting))
        assertEquals("두 번째 장소" to "1 / 2",restrictedPackProgress(waiting.copy(active=true,completed=setOf("a"))))
        assertEquals("도착" to "2 / 2",restrictedPackProgress(waiting.copy(active=true,completed=setOf("a","b"))))
    }
}
