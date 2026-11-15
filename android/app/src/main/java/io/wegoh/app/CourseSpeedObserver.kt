package io.wegoh.app

import android.car.Car
import android.car.VehiclePropertyIds
import android.car.hardware.CarPropertyValue
import android.car.hardware.property.CarPropertyManager
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.io.Closeable
import kotlin.math.abs

internal class CourseSpeedObserver(context: Context,private val changed: (Long,Double?)->Unit): Closeable {
    private val main=Handler(Looper.getMainLooper())
    private var manager: CarPropertyManager?=null
    private var listener: CarPropertyManager.CarPropertyEventCallback?=null
    private var closed=false
    private var generation=0
    private val car=runCatching {Car.createCar(context.applicationContext,main,Car.CAR_WAIT_TIMEOUT_DO_NOT_WAIT) {vehicle,ready->
        val token=++generation
        val reconnecting=manager!=null
        detach();if(reconnecting || !ready)changed(SystemClock.elapsedRealtime(),null)
        if(ready && !closed)runCatching {
            val properties=vehicle.getCarManager(Car.PROPERTY_SERVICE) as CarPropertyManager
            manager=properties
            val config=checkNotNull(properties.getCarPropertyConfig(VehiclePropertyIds.PERF_VEHICLE_SPEED))
            val callback=object: CarPropertyManager.CarPropertyEventCallback {
                override fun onChangeEvent(value: CarPropertyValue<*>) {
                    if(closed || token!=generation || value.propertyId!=VehiclePropertyIds.PERF_VEHICLE_SPEED)return
                    val time=value.timestamp/1_000_000
                    val age=SystemClock.elapsedRealtime()-time
                    val metersPerSecond=(value.value as? Number)?.toDouble()
                    changed(time,if(value.status==CarPropertyValue.STATUS_AVAILABLE && age in 0..1000)
                        metersPerSecond?.takeIf {it.isFinite()}?.let {abs(it)*3.6} else null)
                }
                override fun onErrorEvent(propertyId: Int,areaId: Int) {
                    if(!closed && token==generation && propertyId==VehiclePropertyIds.PERF_VEHICLE_SPEED)
                        changed(SystemClock.elapsedRealtime(),null)
                }
            }
            listener=callback
            val rate=5f.coerceIn(config.minSampleRate,config.maxSampleRate.coerceAtLeast(config.minSampleRate))
            check(properties.registerCallback(callback,VehiclePropertyIds.PERF_VEHICLE_SPEED,rate))
        }.onFailure {detach();changed(SystemClock.elapsedRealtime(),null)}
    }}.getOrElse {changed(SystemClock.elapsedRealtime(),null);null}
    private fun detach() {listener?.let {runCatching {manager?.unregisterCallback(it)}};listener=null;manager=null}
    override fun close() {closed=true;generation++;detach();runCatching {car?.disconnect()}}
}
