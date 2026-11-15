package io.wegoh.app

import android.Manifest

internal data class VehicleRuntimePermissions(
    val preciseLocation: Boolean,
    val approximateLocation: Boolean,
    val vehicleLocation: Boolean,
    val vehicleSpeed: Boolean,
    val microphone: Boolean,
)

internal fun readVehicleRuntimePermissions(granted: (String)->Boolean) = VehicleRuntimePermissions(
    preciseLocation=granted(Manifest.permission.ACCESS_FINE_LOCATION),
    approximateLocation=granted(Manifest.permission.ACCESS_COARSE_LOCATION),
    vehicleLocation=granted("pleos.car.permission.FUSED_LOCATION"),
    vehicleSpeed=granted("android.car.permission.CAR_SPEED"),
    microphone=granted(Manifest.permission.RECORD_AUDIO),
)
