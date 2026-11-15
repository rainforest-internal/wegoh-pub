package io.wegoh.app

import ai.pleos.playground.location.fused.model.LocationData
import android.util.Log

internal class LocationSampleLog {
    private var lastCallbackElapsed: Long?=null
    private var lastLogElapsed: Long?=null
    private var lastLatitude: Double?=null
    private var lastLongitude: Double?=null
    private var lastSdkTimestamp: Long?=null

    @Synchronized
    fun received(data: LocationData,receivedAtMillis: Long,receivedElapsedMillis: Long) {
        val sinceCallback=lastCallbackElapsed?.let {receivedElapsedMillis-it}
        lastCallbackElapsed=receivedElapsedMillis
        if(lastLogElapsed?.let {receivedElapsedMillis-it<1000}==true)return
        val coordinatesChanged=lastLatitude?.let {it!=data.latitude || lastLongitude!=data.longitude}
        val timestampChanged=lastSdkTimestamp?.let {it!=data.timestampMillis}
        val assumedEpochAge=data.timestampMillis.takeIf {it>0}?.let {receivedAtMillis-it}
        Log.d("WegoH-Location","location.sample: received source=FusedLocation latitude=${data.latitude} longitude=${data.longitude} sdk_timestamp_ms=${data.timestampMillis} received_at_ms=$receivedAtMillis received_elapsed_ms=$receivedElapsedMillis since_last_callback_ms=$sinceCallback coordinates_changed_since_log=$coordinatesChanged sdk_timestamp_changed_since_log=$timestampChanged sdk_timestamp_basis=undocumented epoch_age_assumption_ms=$assumedEpochAge")
        lastLogElapsed=receivedElapsedMillis
        lastLatitude=data.latitude;lastLongitude=data.longitude;lastSdkTimestamp=data.timestampMillis
    }
}
