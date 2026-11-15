package io.wegoh.app

import io.wegoh.app.nativeauth.DrivingScoreReport
import io.wegoh.app.nativeauth.ScoreReportAuthority
import java.io.Closeable

internal class CourseFinalUploads {
    private data class Stamp(val key: String,val authority: ScoreReportAuthority,val report: DrivingScoreReport)
    private val acknowledged=mutableSetOf<Stamp>()
    private val attempted=mutableSetOf<Stamp>()
    private val pending=linkedMapOf<Stamp,((Result<Unit>)->Unit)->Closeable>()
    private var generation=0L
    private var serial=0L
    private var inFlight: Stamp?=null
    private var request: Closeable?=null
    private var writing=false
    fun cancel() {generation++;request?.close();request=null;writing=false;inFlight=null;pending.clear();attempted.clear()}
    fun clear() {cancel();acknowledged.clear()}
    fun retryFailures() {attempted.retainAll(acknowledged+listOfNotNull(inFlight))}
    fun submit(key: String,authority: ScoreReportAuthority,report: DrivingScoreReport,
        send: ((Result<Unit>)->Unit)->Closeable,onSuccess: ()->Unit) {
        require(report.final)
        val stamp=Stamp(key,authority,report)
        if(stamp in acknowledged || !attempted.add(stamp))return
        pending[stamp]=send
        drain(onSuccess)
    }
    private fun drain(onSuccess: ()->Unit) {
        if(writing)return
        val entry=pending.entries.firstOrNull() ?: return
        val stamp=entry.key;val send=entry.value
        pending.remove(stamp);writing=true;inFlight=stamp
        val token=generation;val operation=++serial
        val handle=send {reply->
            if(token==generation && operation==serial) {
                writing=false;request=null;inFlight=null
                if(reply.isSuccess) {acknowledged.add(stamp);onSuccess()}
                drain(onSuccess)
            }
        }
        if(token==generation && operation==serial && writing)request=handle else handle.close()
    }
}
