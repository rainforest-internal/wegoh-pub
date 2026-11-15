package io.wegoh.app

import android.test.InstrumentationTestCase
import androidx.compose.runtime.saveable.SaverScope
import kotlinx.coroutines.launch
import io.wegoh.app.ui.AppDestination
import io.wegoh.app.ui.AppNavigator
import io.wegoh.app.ui.PlatformRoutes

@Suppress("DEPRECATION")
class ArchitectureTest: InstrumentationTestCase() {
    fun testTypedNavigationRestoresAndHandlesBack() {
        assertTrue(PlatformRoutes.titles.keys.all {AppDestination.fromId(it)!=null})
        val navigator=AppNavigator(AppDestination.DISCOVER)
        navigator.push(AppDestination.FRIENDS);navigator.push(AppDestination.PROFILE)
        navigator.push(AppDestination.PROFILE)
        val scope=object: SaverScope {override fun canBeSaved(value: Any)=true}
        val saved=with(AppNavigator.Saver) {scope.save(navigator)}!!
        val restored=AppNavigator.Saver.restore(saved)!!
        assertEquals(AppDestination.PROFILE,restored.current)
        assertTrue(restored.back());assertEquals(AppDestination.FRIENDS,restored.current)
        assertTrue(restored.back());assertEquals(AppDestination.DISCOVER,restored.current)
        assertFalse(restored.back())
        assertEquals(AppDestination.FRIENDS,AppNavigator.Saver.restore("friends")!!.current)
        restored.root(AppDestination.ROOM_ENDED);assertFalse(restored.canGoBack)
        assertEquals(AppDestination.DISCOVER,AppNavigator.Saver.restore(listOf("removed-route"))!!.current)
    }
    fun testUnknownDestinationCannotBePushed() {
        assertNull(AppDestination.fromId("not-a-route"))
        try {AppDestination.require("not-a-route");fail("Unknown route accepted")}
        catch(expected: IllegalArgumentException) { }
    }
    fun testCancelledApiReadDropsLateResponse()=kotlinx.coroutines.runBlocking {
        var received=false
        lateinit var reply: (Result<String>)->Unit
        val api=object: io.wegoh.app.nativeauth.ProfileApi {
            override fun readDisplayName(callback: (Result<String>)->Unit) {reply=callback}
            override fun updateDisplayName(name: String,expectedName: String,callback: (Result<String>)->Unit)=error("Not used")
        }
        val job=launch {api.displayName();received=true}
        kotlinx.coroutines.yield()
        job.cancel();job.join();reply(Result.success("Late private response"))
        assertFalse(received)
    }

}
