package io.wegoh.app

import android.app.Activity
import android.car.Car
import android.car.drivingstate.CarUxRestrictionsManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import java.util.concurrent.CountDownLatch

/** Isolated diagnostic host; no product account, network, storage, microphone or vehicle setter. */
class VehicleReadOnlyQaActivity: Activity() {
    @Volatile var resumed = false
        private set
    @Volatile var uxKnown = false
        private set
    @Volatile var unrestricted = false
        private set
    @Volatile var activeRestrictions: Int? = null
        private set
    val uxObserved = CountDownLatch(1)
    private var car: Car? = null
    private var manager: CarUxRestrictionsManager? = null
    private var closed = false
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        car = Car.createCar(applicationContext, Handler(Looper.getMainLooper()), Car.CAR_WAIT_TIMEOUT_DO_NOT_WAIT) { vehicle,ready ->
            if (closed) return@createCar
            if (!ready) {
                uxKnown=false; unrestricted=false
            } else try {
                val value=vehicle.getCarManager(Car.CAR_UX_RESTRICTION_SERVICE) as CarUxRestrictionsManager
                manager=value
                value.registerListener { restriction ->
                    if (!closed) {
                        activeRestrictions=restriction.activeRestrictions
                        unrestricted=!restriction.isRequiresDistractionOptimization
                        uxKnown=true;uxObserved.countDown()
                    }
                }
                val restriction=value.currentCarUxRestrictions
                activeRestrictions=restriction.activeRestrictions
                unrestricted=!restriction.isRequiresDistractionOptimization
                uxKnown=true;uxObserved.countDown()
            } catch(_: Exception) { uxKnown=false;unrestricted=false;uxObserved.countDown() }
        }
    }
    override fun onResume() { super.onResume();resumed=true }
    override fun onPause() { resumed=false;super.onPause() }
    override fun onDestroy() {
        closed=true;resumed=false;uxKnown=false;unrestricted=false
        runCatching { manager?.unregisterListener() };manager=null
        runCatching { car?.disconnect() };car=null
        super.onDestroy()
    }
}
