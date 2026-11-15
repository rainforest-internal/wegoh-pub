package io.wegoh.app

internal enum class VehicleClimateHostResult { NO_SUPPORTED_REQUEST, BLOCKED, UNAVAILABLE, UNKNOWN, CONFIRMED }

internal fun vehicleClimatePollDelay(result: VehicleClimateHostResult,hasPendingRequests: Boolean): Long =
    if(hasPendingRequests && result in setOf(VehicleClimateHostResult.CONFIRMED,
        VehicleClimateHostResult.BLOCKED))250L else 2_000L
