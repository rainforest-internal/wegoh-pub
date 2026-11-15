package io.wegoh.app

import io.wegoh.app.nativeauth.VehicleConnection
import java.io.Closeable

internal class AccountCourseRun(private val connection: VehicleConnection,val pack: DrivePack,
    val published: PublishedPack,private val boundary: VehicleConnection.DataBoundary,private val invalidated: ()->Unit): Closeable {
    val storageKey get()=boundary.storageKey
    private var monitor: VehicleConnection.CourseExecutionMonitor?=null
    private var closed=false
    fun start(ready: (Boolean)->Unit) {
        connection.monitorCourseExecution(boundary,{
            if(!closed) {close();invalidated()}
        }) {result ->
            if(closed) {result.getOrNull()?.close();return@monitorCourseExecution}
            result.fold(onSuccess={monitor=it;ready(isCurrent())},onFailure={close();ready(false)})
        }
    }
    fun isCurrent()=!closed && monitor?.isCurrent()==true
    override fun close() {if(!closed){closed=true;monitor?.close();monitor=null}}
}
