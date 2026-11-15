package io.wegoh.app

import ai.pleos.playground.navi.helper.NaviHelper
import ai.pleos.playground.navi.helper.listener.NaviHelperEventListener
import ai.pleos.playground.navi.data.*
import ai.pleos.playground.navi.constants.WaypointIndex
import android.car.Car
import android.car.VehicleGear
import android.car.VehiclePropertyIds
import android.car.hardware.CarPropertyValue
import android.car.hardware.property.CarPropertyManager
import android.content.Context
import android.os.Handler
import android.os.Looper
import io.wegoh.app.nativeauth.TripLoadDiagnostics
import java.io.Closeable

internal class TripGearObserver(context: Context,private val changed: (TripGear)->Unit): Closeable {
    private var properties: CarPropertyManager?=null
    private var listener: CarPropertyManager.CarPropertyEventCallback?=null
    private var closed=false
    private var generation=0L
    private val car=runCatching {Car.createCar(context.applicationContext,Handler(Looper.getMainLooper()),Car.CAR_WAIT_TIMEOUT_DO_NOT_WAIT) {vehicle,ready->
        val token=++generation
        detach();changed(TripGear.UNKNOWN)
        if(ready && !closed)runCatching {
            val manager=vehicle.getCarManager(Car.PROPERTY_SERVICE) as CarPropertyManager
            properties=manager
            val observer=object: CarPropertyManager.CarPropertyEventCallback {
                override fun onChangeEvent(value: CarPropertyValue<*>) {
                    if(closed || token!=generation || value.propertyId!=VehiclePropertyIds.GEAR_SELECTION)return
                    changed(if(value.status!=CarPropertyValue.STATUS_AVAILABLE)TripGear.UNKNOWN else when(value.value) {
                        VehicleGear.GEAR_PARK->TripGear.PARK
                        VehicleGear.GEAR_DRIVE->TripGear.DRIVE
                        else->TripGear.OTHER
                    })
                }
                override fun onErrorEvent(propertyId: Int,areaId: Int) {if(!closed && token==generation)changed(TripGear.UNKNOWN)}
            }
            listener=observer
            check(manager.registerCallback(observer,VehiclePropertyIds.GEAR_SELECTION,CarPropertyManager.SENSOR_RATE_ONCHANGE))
            observer.onChangeEvent(manager.getProperty<Int>(VehiclePropertyIds.GEAR_SELECTION,0))
        }.onFailure {detach();changed(TripGear.UNKNOWN)}
    }}.getOrNull()
    private fun detach() {listener?.let {runCatching {properties?.unregisterCallback(it)}};listener=null;properties=null}
    override fun close() {closed=true;generation++;detach();runCatching {car?.disconnect()};changed(TripGear.UNKNOWN)}
}

internal class TripNavigationSession(private val context: Context,private val canNavigate: ()->Boolean,
    private val locateBlock: ()->String?,private val update: (TripNavigationUpdate)->Unit,private val failed: ()->Unit,
    private val diagnostics: TripLocationDiagnostics=TripLocationDiagnostics(write=TripLoadDiagnostics::write)): Closeable {
    private val main=Handler(Looper.getMainLooper())
    private fun canLocate()=locateBlock()==null
    private var navigation: NavigationClient?=null
    private var location: LocationClient?=null
    private var helper: NaviHelper?=null
    private var listener: NaviHelperEventListener?=null
    private var connected=false
    private var stops: List<TripRouteStop> = emptyList()
    private var foreground=false
    private var generation=0L
    private var commandGeneration=0L
    private var lastLocationAt=0L
    private val positions=TripPositionSources()
    private var publishedPosition: TripPosition?=null
    private var positionPublished=false
    private fun positionUpdate(now: Long=System.currentTimeMillis()): TripNavigationUpdate {
        val point=positions.current(now)
        publishedPosition=point;positionPublished=true
        return TripNavigationUpdate(position=point,receivedAtMillis=now,positionUnavailable=point==null)
    }
    private fun refreshPosition() {
        val now=System.currentTimeMillis()
        if(!positionPublished || positions.current(now)!=publishedPosition)update(positionUpdate(now))
    }
    private var destination: DestinationInfo?=null
    private var waypoints: List<WaypointInfo>?=null
    private val poll=object: Runnable {
        override fun run() {
            if(!foreground || stops.isEmpty())return
            val blocked=locateBlock()
            if(blocked==null){observe();requestNavi();refreshPosition()} else {diagnostics.dropped("blocked_$blocked");releaseObservation()}
            main.postDelayed(this,1500)
        }
    }
    fun monitor(route: List<TripRouteStop>) {
        stops=route
        if(stops.isEmpty()){close();return}
        main.removeCallbacks(poll)
        if(foreground)main.post(poll)
    }
    fun start(stop: TripRouteStop): Boolean {
        if(!foreground || !canNavigate() || !canLocate() || !stop.canNavigate)return false
        navigation?.release();navigation=null
        val token=++commandGeneration
        return runCatching {
            navigation=NavigationClient(context,report={},canRequest={token==commandGeneration && foreground && canNavigate()},onPhase={phase->
                if(phase==NavigationPhase.FAILED)main.post {if(token==commandGeneration){navigation?.release();navigation=null;failed()}}
            }).also {client->client.request(DrivePack("trip-destination",1,stop.name,"","",listOf(
                Stop("destination",stop.name,checkNotNull(stop.lat),checkNotNull(stop.lng),300f,""))))}
            true
        }.getOrElse {navigation?.release();navigation=null;false}
    }
    private fun observe() {
        if(helper==null) {
            val candidate=NaviHelper(context.applicationContext)
            helper=candidate
            val token=generation
            fun receive(reading: ()->TripNavigationUpdate?) {main.post {
                if(token==generation && helper===candidate && foreground && canLocate())reading()?.let(update)
            }}
            val events=object: NaviHelperEventListener {
                override fun onCurrentLocationInfo(info: CurrentLocationInfo)=receive {
                    val point=TripPosition(info.latitude,info.longitude,info.heading)
                    positions.navi(point,System.currentTimeMillis())
                    if(point.valid)diagnostics.accepted("navi",point) else diagnostics.dropped("invalid",detail="source=navi")
                    positionUpdate()
                }
                override fun onDestinationInfo(info: DestinationInfo)=receive {
                    destination=info;routeUpdate()
                }
                override fun onWayPointInfo(items: List<WaypointInfo>)=receive {
                    waypoints=items;routeUpdate()
                }
                override fun onDestinationArrived(info: DestinationArrivedInfo)=receive {
                    destination?.let {TripNavigationUpdate(targets=listOf(naviTarget(it.latitude,it.longitude,it.remainDistance,it.remainTime)),arrived=true)}
                }
                override fun onWayPointArrived(info: WaypointArrivedInfo)=receive {
                    val index=if(info.index==WaypointIndex.FIRST)0 else 1
                    waypoints?.getOrNull(index)?.let {TripNavigationUpdate(targets=listOf(naviTarget(it.latitude,it.longitude,it.remainDistance,it.remainTime)),arrived=true)}
                }
                override fun onDrivingInfo(info: DrivingInfo)=receive {requestNavi();null}
                override fun onError(errorCode: ai.pleos.playground.navi.constants.NaviErrorCode)=receive {
                    positions.navi(null,0);positionUpdate()
                }
                override fun onDestinationChanged() {main.post {if(helper===candidate){destination=null;waypoints=null;requestNavi()}}}
            }
            listener=events
            runCatching {candidate.initialize(onConnected={main.post {
                if(helper===candidate && token==generation && foreground && canLocate())runCatching {
                    candidate.addListener(events);connected=true;requestNavi()
                }
            }},onFailed={main.post {if(helper===candidate){connected=false;helper=null;positions.navi(null,0);refreshPosition();runCatching {candidate.release()}}}})}
                .onFailure {helper=null;runCatching {candidate.release()}}
        }
        if(location==null) {
            val token=generation
            val candidate=LocationClient(context,{data->main.post {
                val now=System.currentTimeMillis()
                val point=TripPosition(data.latitude,data.longitude,data.heading.toDouble())
                val blocked=locateBlock()
                val drop=when {
                    token!=generation->"superseded"
                    !foreground->"background"
                    blocked!=null->"blocked_$blocked"
                    else->tripFusedLocationDrop(now,data.timestampMillis,lastLocationAt,0,point)
                }
                if(drop==null){lastLocationAt=data.timestampMillis;positions.fused(point,data.timestampMillis);diagnostics.accepted("fused",point);update(positionUpdate(now))}
                else diagnostics.dropped(drop,point,"source=fused age_ms=${now-data.timestampMillis}")
            }},report={reason->main.post {
                if(token==generation) {
                    diagnostics.dropped(if(reason==LocationUnavailableReason.NO_DATA)"fused_empty" else "fused_error")
                    positions.fused(null,0);refreshPosition()
                }
            }})
            location=startTripLocation(candidate,{it.start()},{it.release()})
            if(location==null)diagnostics.dropped("fused_start_failed")
        }
    }
    private fun naviTarget(lat: Double,lng: Double,meters: Int,seconds: Int)=TripNavigationTarget(lat,lng,
        meters.toDouble().takeIf {meters>=0 && (meters>0 || seconds>0)},seconds.takeIf {it>=0})
    private fun routeUpdate(): TripNavigationUpdate? {
        val end=destination ?: return null
        val via=waypoints ?: return null
        return TripNavigationUpdate(targets=via.map {naviTarget(it.latitude,it.longitude,it.remainDistance,it.remainTime)}+
            naviTarget(end.latitude,end.longitude,end.remainDistance,end.remainTime))
    }
    private fun requestNavi() {
        if(!connected || !foreground || !canLocate())return
        runCatching {helper?.getCurrentLocationInfo()}
        runCatching {helper?.getDestinationInfo()}
        runCatching {helper?.getWaypointInfo()}
    }
    private fun releaseObservation() {
        generation++;connected=false
        positions.clear();update(positionUpdate())
        location?.release();location=null
        listener?.let {runCatching {helper?.removeListener(it)}};listener=null
        runCatching {helper?.release()};helper=null;destination=null;waypoints=null;lastLocationAt=0
    }
    fun setForeground(value: Boolean) {
        foreground=value;main.removeCallbacks(poll)
        if(!value){releaseObservation();commandGeneration++;navigation?.release();navigation=null}
        else if(stops.isNotEmpty())main.post(poll)
    }
    override fun close() {main.removeCallbacks(poll);stops=emptyList();releaseObservation();commandGeneration++;navigation?.release();navigation=null}
}
