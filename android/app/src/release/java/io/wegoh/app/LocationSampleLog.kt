package io.wegoh.app

import ai.pleos.playground.location.fused.model.LocationData

@Suppress("UNUSED_PARAMETER")
internal class LocationSampleLog {
    fun received(data: LocationData,receivedAtMillis: Long,receivedElapsedMillis: Long) = Unit
}
