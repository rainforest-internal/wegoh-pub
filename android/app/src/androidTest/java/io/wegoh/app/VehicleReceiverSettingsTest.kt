package io.wegoh.app

import android.content.Context
import android.content.SharedPreferences
import android.test.InstrumentationTestCase
import io.wegoh.app.nativeauth.CommandReceiver
import java.util.UUID

@Suppress("DEPRECATION")
class VehicleReceiverSettingsTest: InstrumentationTestCase() {
    private lateinit var preferences: SharedPreferences
    private lateinit var fileName: String

    override fun setUp() {
        super.setUp()
        fileName = "receiver_test_" + UUID.randomUUID()
        preferences = instrumentation.targetContext.getSharedPreferences(fileName, Context.MODE_PRIVATE)
    }

    override fun tearDown() {
        instrumentation.targetContext.deleteSharedPreferences(fileName)
        super.tearDown()
    }

    private inner class Fixture {
        val server = CommandReceiver("a".repeat(32), "b".repeat(32), 4, false)
        var epoch = 1L
        val reads = ArrayDeque<(Result<CommandReceiver>) -> Unit>()
        val writes = mutableListOf<Pair<CommandReceiver, Boolean>>()
        val replies = ArrayDeque<(Result<CommandReceiver>) -> Unit>()
        val starts = mutableListOf<Boolean>()
        val settings = VehicleReceiverSettings(preferences, {epoch}, reads::addLast, {previous, enabled, callback ->
            writes.add(previous to enabled)
            replies.addLast(callback)
        }, starts::add)
    }

    fun testPreviouslyDisabledCarNeedsExplicitConfirmedEnable() = instrumentation.runOnMainSync {
        val h = Fixture()
        h.settings.refresh()
        h.reads.removeFirst()(Result.success(h.server))
        assertFalse(h.settings.enabled)
        assertEquals(h.server.deviceId,h.settings.deviceId)
        assertTrue(h.writes.isEmpty())
        assertFalse(true in h.starts)

        h.settings.setEnabled(true)
        assertEquals(listOf(h.server to true), h.writes)
        assertFalse(true in h.starts)
        h.replies.removeFirst()(Result.success(h.server.copy(revision=5, enabled=true)))
        assertTrue(h.settings.enabled)
        assertTrue(true in h.starts)

        h.settings.setEnabled(false)
        assertEquals(false, h.starts.last())
        assertFalse(h.settings.enabled)
    }

    fun testLegacyLocalStopWinsOverServerAndStaleEnableCannotRestart() = instrumentation.runOnMainSync {
        preferences.edit().putBoolean("enabled", false).commit()
        val h = Fixture()
        h.settings.refresh()
        h.reads.removeFirst()(Result.success(h.server.copy(enabled=true)))
        assertFalse(h.settings.enabled)
        assertFalse(h.writes.any { it.second })
        assertFalse(true in h.starts)

        assertEquals(listOf(h.server.copy(enabled=true) to false), h.writes)
        h.replies.removeFirst()(Result.success(h.server.copy(revision=5)))
        h.settings.setEnabled(true)
        val enable = h.replies.removeFirst()
        h.epoch++
        assertNull(h.settings.deviceId)
        h.settings.connectionChanged()
        enable(Result.success(h.server.copy(revision=6, enabled=true)))
        assertFalse(h.settings.enabled)
        assertFalse(true in h.starts)
    }

    fun testLostEnableResponseKeepsServiceOffUntilExplicitRetry() = instrumentation.runOnMainSync {
        val h = Fixture()
        h.settings.refresh()
        h.reads.removeFirst()(Result.success(h.server))
        h.settings.setEnabled(true)
        h.replies.removeFirst()(Result.failure(java.io.IOException("connection lost")))
        val alreadyEnabled = h.server.copy(enabled=true, revision=5)
        h.reads.removeFirst()(Result.success(alreadyEnabled))
        assertFalse(h.settings.enabled)
        assertFalse(true in h.starts)
        assertEquals(1, h.writes.size)

        h.settings.setEnabled(true)
        assertEquals(alreadyEnabled to true, h.writes.last())
        h.replies.removeFirst()(Result.success(alreadyEnabled))
        assertTrue(h.settings.enabled)
    }
}
