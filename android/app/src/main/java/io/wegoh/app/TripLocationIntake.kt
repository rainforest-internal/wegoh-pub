package io.wegoh.app

import java.util.Locale

/**
 * One location policy for an active trip: the vehicle marker, remaining distance and arrival
 * (TripNavigationSession) and the companion share (TripLocationObservation) all use the car's
 * location only while the app is in the foreground, after the in-app location consent and the
 * runtime permissions. Returns why location is blocked, or null when it may be used.
 */
internal fun tripLocationBlock(foreground: Boolean,consented: Boolean,permitted: Boolean): String? = when {
    !foreground->"background"
    !consented->"no_consent"
    !permitted->"no_permission"
    else->null
}

/** Ask for the location consent once when the active trip screen of the user's own car opens. */
internal fun tripLocationPromptNeeded(screenTrip: String?,selectedTrip: String?,declined: Set<String>,
    setupAllowed: Boolean,storageReady: Boolean,courseActive: Boolean,consented: Boolean): Boolean =
    screenTrip!=null && screenTrip==selectedTrip && screenTrip !in declined &&
        setupAllowed && storageReady && !courseActive && !consented

/** Why a Pleos fused fix is not used for the vehicle marker, or null when it is accepted. */
internal fun tripFusedLocationDrop(now: Long,timestampMillis: Long,lastLocationAt: Long,lastNaviAt: Long,point: TripPosition): String? = when {
    !point.valid->"invalid"
    timestampMillis<=lastLocationAt->"not_newer"
    now-timestampMillis<0->"future"
    now-timestampMillis>15000->"stale"
    lastNaviAt!=0L && now-lastNaviAt<=5000->"navi_recent"
    else->null
}

/**
 * Field diagnostics for the vehicle position path. Each kind of message (accepted source or
 * drop reason) is written at most once per [intervalMillis]. Coordinates are rounded to three
 * decimals (about 100 m) so the log does not keep a precise track.
 */
internal class TripLocationDiagnostics(private val now: ()->Long = System::currentTimeMillis,
    private val intervalMillis: Long=10000,private val write: (String)->Unit) {
    private val lastAt=mutableMapOf<String,Long>()
    fun accepted(source: String,point: TripPosition)=emit("accepted source=$source",point,null)
    fun dropped(reason: String,point: TripPosition?=null,detail: String?=null)=emit("dropped reason=$reason",point,detail)
    private fun emit(key: String,point: TripPosition?,detail: String?) {
        val time=now()
        if(lastAt[key]?.let {time-it in 0 until intervalMillis}==true)return
        lastAt[key]=time
        val where=point?.let {" lat=${round(it.latitude)} lng=${round(it.longitude)}"}.orEmpty()
        write("trip.vehicle.location: $key"+detail?.let {" $it"}.orEmpty()+where)
    }
    private fun round(value: Double)=String.format(Locale.US,"%.3f",value)
}
