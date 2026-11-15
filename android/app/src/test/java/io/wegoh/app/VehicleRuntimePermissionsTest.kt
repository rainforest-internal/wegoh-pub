package io.wegoh.app

import org.junit.Assert.*
import org.junit.Test

class VehicleRuntimePermissionsTest {
    @Test fun readsCurrentDeviceGrantsIndependently() {
        val granted=setOf("android.permission.ACCESS_FINE_LOCATION","android.permission.ACCESS_COARSE_LOCATION",
            "pleos.car.permission.FUSED_LOCATION","android.car.permission.CAR_SPEED")
        val state=readVehicleRuntimePermissions {it in granted}
        assertTrue(state.preciseLocation)
        assertTrue(state.approximateLocation)
        assertTrue(state.vehicleLocation)
        assertTrue(state.vehicleSpeed)
        assertFalse(state.microphone)
    }

    @Test fun approximateLocationDoesNotImplyOtherPermissions() {
        val state=readVehicleRuntimePermissions {it=="android.permission.ACCESS_COARSE_LOCATION"}
        assertFalse(state.preciseLocation)
        assertTrue(state.approximateLocation)
        assertFalse(state.vehicleLocation)
        assertFalse(state.vehicleSpeed)
        assertFalse(state.microphone)
    }

    @Test fun deniedAndChangedGrantsAreNotCached() {
        val grants=mutableSetOf<String>()
        assertEquals(VehicleRuntimePermissions(false,false,false,false,false),readVehicleRuntimePermissions {it in grants})
        grants+="android.permission.RECORD_AUDIO"
        assertTrue(readVehicleRuntimePermissions {it in grants}.microphone)
        grants.clear()
        assertFalse(readVehicleRuntimePermissions {it in grants}.microphone)
    }
}
