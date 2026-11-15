package io.wegoh.app

import org.json.JSONArray
import org.json.JSONObject

internal data class VehicleControlArea(val id: String,val minimum: Double?=null,val maximum: Double?=null,val step: Double?=null) {
    fun json()=JSONObject().put("id",id).put("min",minimum ?: JSONObject.NULL)
        .put("max",maximum ?: JSONObject.NULL).put("step",step ?: JSONObject.NULL)
}
/** [zones] groups reported seats that one SDK area changes together; seats outside every zone are adjusted alone. */
internal data class VehicleControlSupport(val id: String,val revision: Int,val status: String,val available: Boolean,
    val areas: List<VehicleControlArea> = emptyList(),val zones: List<List<String>> = emptyList()) {
    fun json()=JSONObject().put("id",id).put("revision",revision).put("status",status)
        .put("available",available).put("areas",JSONArray(areas.map {it.json()}))
        .put("zones",JSONArray(zones.map {JSONArray(it)}))
}
internal fun vehicleControlSupport(property: ClimateProperty,reply: VehicleReply<ClimateCapability>): VehicleControlSupport {
    val action=checkNotNull(TRUSTED_CLIMATE_ACTIONS[property])
    fun result(status: String,areas: List<VehicleControlArea> = emptyList(),available: Boolean=areas.isNotEmpty(),
               zones: List<List<String>> = emptyList())=
        VehicleControlSupport(action.id,action.revision.toInt(),status,available,areas,zones)
    if(reply is VehicleReply.Failed)return result(if(reply.reason==VehicleFailure.UNSUPPORTED_PROPERTY)"known" else "unknown")
    val cap=(reply as VehicleReply.Value).value
    if(cap.access !in setOf(VehicleAccess.WRITE,VehicleAccess.READ_WRITE))return result("known")
    if(property==ClimateProperty.CABIN_LIGHT)return result("known",available=cap.lightSwitches.containsAll(setOf(VehicleLightSwitch.OFF,VehicleLightSwitch.ON)))
    if(property==ClimateProperty.WINDOW_POSITION) {
        val windows=cap.windows.filter {it!=DRIVER_WINDOW}
        val areas=windows.sortedBy {it.name}.mapNotNull {window->cap.windowBounds[window]?.takeIf {
            it.windowPosition(0)!=null && it.windowPosition(100)!=null
        }?.let {VehicleControlArea(window.name,0.0,100.0,1.0)}}
        return result(if(areas.isEmpty() && windows.isNotEmpty())"unknown" else "known",areas)
    }
    val numeric=property in setOf(ClimateProperty.TARGET_CELSIUS,ClimateProperty.FAN_LEVEL,ClimateProperty.SEAT_HEAT,ClimateProperty.SEAT_VENTILATION)
    // Remote control never targets the driver seat; seat-zone actions also skip SDK areas containing it.
    val carWide=property in CAR_WIDE_CLIMATE_PROPERTIES
    val eligible=cap.areas.filter {seat->seat!=DRIVER_SEAT && (carWide || cap.area(seat)?.seats?.contains(DRIVER_SEAT)!=true)}
    val candidates=eligible.sortedBy {it.name}.filter {cap.area(it)!=null}.mapNotNull {seat->
        if(!numeric) {
            if(property in setOf(ClimateProperty.READING_LIGHT,ClimateProperty.AMBIENT_LIGHT) &&
                cap.seatLightSwitches[seat]?.containsAll(setOf(VehicleLightSwitch.OFF,VehicleLightSwitch.ON))!=true)null
            else VehicleControlArea(seat.name)
        } else {
            val bounds=cap.bounds[seat]?.takeIf {it.valid()} ?: return@mapNotNull null
            val maximum=when(property){ClimateProperty.TARGET_CELSIUS->50.0;ClimateProperty.FAN_LEVEL->100.0;else->10.0}
            val low=maxOf(0.0,bounds.minimum);val high=minOf(maximum,bounds.maximum)
            if(low>high)return@mapNotNull null
            if(property==ClimateProperty.TARGET_CELSIUS) {
                val increment=cap.celsiusStep?.increment
                if(increment!=null && (!increment.isFinite() || increment<=0.0))return@mapNotNull null
                VehicleControlArea(seat.name,low,high,increment)
            } else {
                val minimum=kotlin.math.ceil(low);val max=kotlin.math.floor(high)
                if(minimum>max)null else VehicleControlArea(seat.name,minimum,max,1.0)
            }
        }
    }
    val candidateSeats=candidates.map {VehicleSeat.valueOf(it.id)}.toSet()
    // A setter receives the complete SDK area. Never advertise only its surviving
    // seats as an independent control when another affected seat was excluded.
    val areas=candidates.filter {candidate->
        val area=checkNotNull(cap.area(VehicleSeat.valueOf(candidate.id)))
        area.seats.all {(it in candidateSeats || (carWide && it==DRIVER_SEAT)) && cap.area(it)===area}
    }
    val reported=areas.map {VehicleSeat.valueOf(it.id)}
    val zones=reported.groupBy {checkNotNull(cap.area(it))}.values.filter {it.size>1}
        .map {seats->seats.sortedBy {it.ordinal}.map {it.name}}.sortedBy {VehicleSeat.valueOf(it.first()).ordinal}
    return result(if(numeric && areas.isEmpty() && eligible.isNotEmpty())"unknown" else "known",areas,zones=zones)
}
