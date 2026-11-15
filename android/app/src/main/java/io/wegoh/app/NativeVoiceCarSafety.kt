package io.wegoh.app

import android.car.Car
import android.car.drivingstate.CarUxRestrictionsManager
import android.car.drivingstate.CarUxRestrictions
import android.content.Context
import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.NativeVoiceAudioSafety
import java.io.Closeable

/** App-owned ordinary CarUx observation; no new car permission or hidden power-state API.
 * [drivingOptimized] hosts live in a distractionOptimized activity and offer only one large click target
 * (record, then send or cancel) with audio playback: Pleos CarUx flags restrict keyboard, setup, filtering, video and text/transcript
 * display, none of which this control shows, so any CarUx state that was actually read permits it.
 * Other hosts stay parked-only (unrestricted CarUx). Unknown CarUx always fails closed.
 * This is not an OEM Suspend observer.
 */
internal class NativeVoiceCarSafety(context: Context, private val drivingOptimized: Boolean = false,
    private val changed: (NativeVoiceAudioSafety) -> Unit): Closeable {
    private var manager: CarUxRestrictionsManager? = null
    private var generation = 0L
    private var foreground = false
    private var allowed: Boolean? = null
    private var closed = false
    private fun publish() = changed(NativeVoiceAudioSafety(foreground && !closed, allowed))
    private val car = runCatching { Car.createCar(context.applicationContext, Handler(Looper.getMainLooper()),
        Car.CAR_WAIT_TIMEOUT_DO_NOT_WAIT) { vehicle, ready ->
        val token = ++generation
        runCatching { manager?.unregisterListener() }; manager = null; allowed = null
        publish()
        if (ready && !closed) runCatching {
            val ux = vehicle.getCarManager(Car.CAR_UX_RESTRICTION_SERVICE) as CarUxRestrictionsManager
            manager = ux
            ux.registerListener { restrictions ->
                if (!closed && token == generation && manager === ux) {
                    allowed = permits(restrictions)
                    publish()
                }
            }
            val current = ux.currentCarUxRestrictions
            allowed = permits(current)
            publish()
        }.onFailure {
            generation++; runCatching { manager?.unregisterListener() }; manager = null; allowed = null; publish()
        }
    } }.getOrNull()
    private fun permits(restrictions: CarUxRestrictions) = nativeVoiceCarUxPermits(drivingOptimized,
        restrictions.isRequiresDistractionOptimization, restrictions.activeRestrictions)
    /** Call on main thread from the actual foreground lifecycle, never from a stored preference. */
    fun setForeground(visible: Boolean) { check(Looper.myLooper() == Looper.getMainLooper()); foreground = visible && !closed; publish() }
    override fun close() {
        check(Looper.myLooper() == Looper.getMainLooper())
        closed = true; foreground = false; allowed = null; generation++; publish()
        runCatching { manager?.unregisterListener() }; manager = null
        runCatching { car?.disconnect() }
    }
}

/** Pure decision for a CarUx state that was actually read. */
internal fun nativeVoiceCarUxPermits(drivingOptimized: Boolean, requiresDistractionOptimization: Boolean, activeRestrictions: Int) =
    drivingOptimized || !requiresDistractionOptimization && activeRestrictions == CarUxRestrictions.UX_RESTRICTIONS_BASELINE
