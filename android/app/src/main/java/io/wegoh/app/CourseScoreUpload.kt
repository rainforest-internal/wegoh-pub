package io.wegoh.app

import io.wegoh.app.nativeauth.DrivingScoreReport
import java.io.Closeable

internal fun CourseDrivingResult.report(final: Boolean=false)=DrivingScoreReport(score,accelerations,brakings,score!=null,final)

internal class CourseScoreUploads {
    private data class Stamp(val key: String,val score: Int?,val measurable: Boolean)
    private var generation=0L
    private var serial=0L
    private var context: String?=null
    private var observed: Stamp?=null
    private var pending: DrivingScoreReport?=null
    private var writing=false
    private var request: Closeable?=null
    fun clear() {
        generation++;request?.close();request=null;writing=false;context=null;observed=null;pending=null
    }
    fun update(key: String,report: DrivingScoreReport,send: (DrivingScoreReport,(Result<Unit>)->Unit)->Closeable) {
        if(context!=key) {clear();context=key}
        val stamp=Stamp(key,report.score,report.measurable)
        if(observed==stamp)return
        observed=stamp;pending=report
        drain(send)
    }
    private fun drain(send: (DrivingScoreReport,(Result<Unit>)->Unit)->Closeable) {
        if(writing)return
        val value=pending ?: return
        pending=null;writing=true
        val token=generation;val operation=++serial
        val handle=send(value) {
            if(token==generation && operation==serial) {writing=false;request=null;drain(send)}
        }
        if(token==generation && operation==serial && writing)request=handle else handle.close()
    }
}
