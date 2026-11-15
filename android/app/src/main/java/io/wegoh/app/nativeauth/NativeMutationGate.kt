package io.wegoh.app.nativeauth

import java.io.Closeable
import java.io.IOException
import java.io.OutputStream

internal class NativeMutationGate {
    private var allowed=false
    private var generation=0L
    private val permits=mutableSetOf<Permit>()
    fun setAllowed(value: Boolean) {
        val cancelled=synchronized(this) {
            if(allowed==value)return
            allowed=value;generation++
            if(value)emptyList() else permits.toList()
        }
        cancelled.forEach {it.close()}
    }
    @Synchronized fun permit(current: ()->Boolean,onWrite: ()->Unit): Permit =
        Permit(generation,current,onWrite).also {permits.add(it)}

    inner class Permit internal constructor(private val expected: Long,private val current: ()->Boolean,
        private val onWrite: ()->Unit): Closeable {
        private var cancelled=false
        private var disconnect: (() -> Unit)?=null
        private fun checkCurrent() {
            if(cancelled || !allowed || expected!=generation || !current())throw IOException("NATIVE_WRITE_CANCELLED")
        }
        fun write(bytes: ByteArray,open: ()->OutputStream,abort: ()->Unit) {
            try {
                synchronized(this@NativeMutationGate) {checkCurrent();disconnect=abort}
                open().use {stream->
                    synchronized(this@NativeMutationGate) {checkCurrent();onWrite();stream.write(bytes)}
                }
            } catch(error: Throwable) {abort();throw error}
            finally {synchronized(this@NativeMutationGate) {disconnect=null}}
        }
        override fun close() {
            val abort=synchronized(this@NativeMutationGate) {
                cancelled=true;permits.remove(this);disconnect.also {disconnect=null}
            }
            abort?.let {runCatching(it)}
        }
    }
}
