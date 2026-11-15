package io.wegoh.app

import android.car.Car
import android.car.VehicleGear
import android.car.VehiclePropertyIds
import android.car.drivingstate.CarUxRestrictions
import android.car.drivingstate.CarUxRestrictionsManager
import android.car.hardware.CarPropertyValue
import android.car.hardware.property.CarPropertyManager
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.PowerManager

internal class ClimateCarSafety(context: Context,private val changed: ()->Unit): AutoCloseable {
    private var properties: CarPropertyManager?=null
    private var ux: CarUxRestrictionsManager?=null
    private var parked: Boolean?=null
    private var allowed: Boolean?=null
    private var foreground=false
    private var receiverActive=false
    private var closed=false
    private var generation=0L
    private val power=context.getSystemService(PowerManager::class.java)
    private var listener: CarPropertyManager.CarPropertyEventCallback?=null
    private val car=Car.createCar(context.applicationContext,Handler(Looper.getMainLooper()),Car.CAR_WAIT_TIMEOUT_DO_NOT_WAIT) { vehicle,ready->
        val token=++generation
        detach();parked=null;allowed=null;changed()
        if(ready && !closed)runCatching {
            val restrictions=vehicle.getCarManager(Car.CAR_UX_RESTRICTION_SERVICE) as CarUxRestrictionsManager
            ux=restrictions
            fun update(value: CarUxRestrictions) {
                if(!closed && generation==token) {allowed=!value.isRequiresDistractionOptimization && value.activeRestrictions==CarUxRestrictions.UX_RESTRICTIONS_BASELINE;changed()}
            }
            restrictions.registerListener(::update);update(restrictions.currentCarUxRestrictions)
            val manager=vehicle.getCarManager(Car.PROPERTY_SERVICE) as CarPropertyManager
            properties=manager
            val observer=object: CarPropertyManager.CarPropertyEventCallback {
                override fun onChangeEvent(value: CarPropertyValue<*>) {
                    if(!closed && generation==token && value.propertyId==VehiclePropertyIds.GEAR_SELECTION) {
                        parked=if(value.status==CarPropertyValue.STATUS_AVAILABLE)value.value==VehicleGear.GEAR_PARK else null;changed()
                    }
                }
                override fun onErrorEvent(propertyId: Int,areaId: Int) {if(generation==token){parked=null;changed()}}
            }
            listener=observer
            check(manager.registerCallback(observer,VehiclePropertyIds.GEAR_SELECTION,CarPropertyManager.SENSOR_RATE_ONCHANGE))
            observer.onChangeEvent(manager.getProperty<Int>(VehiclePropertyIds.GEAR_SELECTION,0))
        }.onFailure {detach();parked=null;allowed=null;changed()}
    }
    fun setForeground(value: Boolean) {foreground=value && !closed;changed()}
    fun setReceiverActive(value: Boolean) {receiverActive=value && !closed;changed()}
    fun snapshot()=VehicleClimateSafety(foreground && !closed,parked==true,allowed!=null,allowed==true,!power.isInteractive,receiverActive && !closed)
    private fun detach() {
        listener?.let {runCatching {properties?.unregisterCallback(it)}};listener=null;properties=null
        runCatching {ux?.unregisterListener()};ux=null
    }
    override fun close() {closed=true;foreground=false;generation++;detach();parked=null;allowed=null;changed();car.disconnect()}
}
