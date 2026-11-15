package io.wegoh.app.nativeauth

import java.util.concurrent.Callable
import java.util.concurrent.ExecutionException
import java.util.concurrent.ExecutorService

/**
 * Two lanes for native calls. Ordinary calls keep running on the connection's single worker, which also owns every
 * account state change (session refresh, permission recheck, recovery). Time-bound calls run on their own serial lane
 * so they never wait behind periodic reads queued on the worker; they hand account state work back to the worker
 * and wait for it, so that work stays serialized with everything else.
 */
internal class NativeCallLanes(private val shared: ExecutorService,private val realtime: ExecutorService) {
    fun execute(realtime: Boolean,task: Runnable)=(if(realtime)this.realtime else shared).execute(task)

    /** Runs [block] on the shared worker after the work already queued there and returns its result. */
    fun <T> onShared(block: ()->T): T = try {shared.submit(Callable {block()}).get()}
        catch(failure: ExecutionException) {throw failure.cause ?: failure}

    fun shutdown() {shared.shutdown();realtime.shutdown()}
}
