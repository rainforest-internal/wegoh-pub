package io.wegoh.app

import android.content.SharedPreferences
import io.wegoh.app.nativeauth.CommandReceiver
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VehicleReceiverDefaultTest {
    private class MemoryPreferences: SharedPreferences {
        val values=mutableMapOf<String,Any?>()
        override fun getAll()=values.toMutableMap()
        override fun getString(key: String?,defValue: String?)=values[key] as? String ?: defValue
        override fun getStringSet(key: String?,defValues: MutableSet<String>?)=defValues
        override fun getInt(key: String?,defValue: Int)=values[key] as? Int ?: defValue
        override fun getLong(key: String?,defValue: Long)=values[key] as? Long ?: defValue
        override fun getFloat(key: String?,defValue: Float)=values[key] as? Float ?: defValue
        override fun getBoolean(key: String?,defValue: Boolean)=values[key] as? Boolean ?: defValue
        override fun contains(key: String?)=key in values
        override fun registerOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) {}
        override fun unregisterOnSharedPreferenceChangeListener(listener: SharedPreferences.OnSharedPreferenceChangeListener?) {}
        override fun edit(): SharedPreferences.Editor=object: SharedPreferences.Editor {
            private val pending=mutableMapOf<String,Any?>()
            override fun putString(key: String,value: String?)=apply {pending[key]=value}
            override fun putStringSet(key: String,values: MutableSet<String>?)=apply {pending[key]=values}
            override fun putInt(key: String,value: Int)=apply {pending[key]=value}
            override fun putLong(key: String,value: Long)=apply {pending[key]=value}
            override fun putFloat(key: String,value: Float)=apply {pending[key]=value}
            override fun putBoolean(key: String,value: Boolean)=apply {pending[key]=value}
            override fun remove(key: String)=apply {pending[key]=null}
            override fun clear()=apply {values.clear()}
            override fun commit(): Boolean {apply();return true}
            override fun apply() {values.putAll(pending)}
        }
    }
    private class Fixture(val preferences: MemoryPreferences=MemoryPreferences()) {
        val reads=ArrayDeque<(Result<CommandReceiver>)->Unit>()
        val writes=mutableListOf<Boolean>()
        val replies=ArrayDeque<(Result<CommandReceiver>)->Unit>()
        val settings=VehicleReceiverSettings(preferences,{1L},reads::addLast,{_,enabled,callback->writes.add(enabled);replies.addLast(callback)},{})
    }
    private val first=CommandReceiver("a".repeat(32),"b".repeat(32),1,true)
    private val second=CommandReceiver("a".repeat(32),"c".repeat(32),1,true)

    @Test fun newConnectionAfterLogoutStartsWithReceivingOn() {
        val h=Fixture()
        h.settings.refresh();h.reads.removeFirst()(Result.success(first))
        assertTrue(h.settings.enabled)
        h.settings.stopLocally()
        assertFalse(h.settings.enabled)

        val next=Fixture(h.preferences)
        next.settings.refresh();next.reads.removeFirst()(Result.success(second))
        assertTrue(next.writes.isEmpty())
        assertTrue(next.settings.enabled)

        val serverOff=Fixture(h.preferences.also {it.values["grantId"]="b".repeat(32);it.values["enabled"]=false})
        serverOff.settings.refresh();serverOff.reads.removeFirst()(Result.success(second.copy(enabled=false)))
        assertEquals(listOf(true),serverOff.writes)
        serverOff.replies.removeFirst()(Result.success(second.copy(revision=2,enabled=true)))
        assertTrue(serverOff.settings.enabled)
    }

    @Test fun sameConnectionRestartKeepsTheChosenOff() {
        val h=Fixture()
        h.settings.refresh();h.reads.removeFirst()(Result.success(first))
        h.settings.setEnabled(false)
        assertEquals(listOf(false),h.writes)
        h.replies.removeFirst()(Result.success(first.copy(revision=2,enabled=false)))

        val restarted=Fixture(h.preferences)
        restarted.settings.refresh();restarted.reads.removeFirst()(Result.success(first.copy(revision=2,enabled=false)))
        assertTrue(restarted.writes.isEmpty())
        assertFalse(restarted.settings.enabled)
    }
}
