package io.wegoh.app

import ai.pleos.playground.vehicle.api.model.area.SeatArea
import ai.pleos.playground.vehicle.api.model.capability.AccessType
import ai.pleos.playground.vehicle.api.model.capability.AreaBounds
import ai.pleos.playground.vehicle.constant.area.SeatValue
import ai.pleos.playground.vehicle.constant.control.LightSwitch
import org.junit.Assert.*
import org.junit.Test

class VehicleSeatCapabilityTest {
    @Test fun sdkDiagnosticsKeepOnlyNumericFailureCodes() {
        assertEquals("-7",VehicleHardwareSdkAdapter.failureCode(Exception("-7")))
        for(message in listOf(null,"private-token", "failed -7 private-token", "2147483648", "7\nprivate-token"))
            assertEquals("unavailable",VehicleHardwareSdkAdapter.failureCode(Exception(message)))
    }

    private val front=SeatArea(SeatValue.ROW_1_LEFT,SeatValue.ROW_1_RIGHT)
    private val cabin=SeatArea(SeatValue.ROW_1_LEFT,SeatValue.ROW_1_RIGHT,
        SeatValue.ROW_2_LEFT,SeatValue.ROW_2_CENTER,SeatValue.ROW_2_RIGHT)

    @Test fun fanPreservesReportedAreaAndBoundsForEitherFrontSeat() {
        val capability=VehicleHardwareSdkAdapter.seatBounds(AccessType.READ_WRITE,mapOf(front to AreaBounds(1,8)))
        assertEquals(1,capability.seatAreas.size)
        assertEquals(setOf(VehicleSeat.ROW_1_LEFT,VehicleSeat.ROW_1_RIGHT),capability.areas)
        for(seat in capability.areas) {
            assertSame(front,VehicleHardwareSdkAdapter.area(seat,capability))
            assertEquals(ClimateBounds(1.0,8.0),capability.bounds[seat])
        }
        assertNull(VehicleHardwareSdkAdapter.area(VehicleSeat.ROW_2_LEFT,capability))
    }

    @Test fun powerAcAndAirCleanerKeepOneReportedCabinArea() {
        val capability=VehicleHardwareSdkAdapter.seatCapability(AccessType.READ_WRITE,listOf(cabin))
        assertEquals(1,capability.seatAreas.size)
        assertEquals(5,capability.areas.size)
        for(seat in capability.areas)assertSame(cabin,VehicleHardwareSdkAdapter.area(seat,capability))
        assertNull(VehicleHardwareSdkAdapter.area(VehicleSeat.ROW_3_LEFT,capability))
    }

    @Test fun ambientLightPreservesReportedAreaAndSwitches() {
        val capability=VehicleHardwareSdkAdapter.seatLights(AccessType.READ_WRITE,
            mapOf(cabin to listOf(LightSwitch.OFF,LightSwitch.ON)))
        for(seat in capability.areas) {
            assertSame(cabin,VehicleHardwareSdkAdapter.area(seat,capability))
            assertEquals(setOf(VehicleLightSwitch.OFF,VehicleLightSwitch.ON),capability.seatLightSwitches[seat])
        }
    }

    @Test fun distinctAreasStayDistinctAndOverlappingAreasAreRejected() {
        val left=SeatArea(SeatValue.ROW_1_LEFT)
        val right=SeatArea(SeatValue.ROW_1_RIGHT)
        val separate=VehicleHardwareSdkAdapter.seatBounds(AccessType.READ_WRITE,
            mapOf(left to AreaBounds(1,8),right to AreaBounds(1,4)))
        assertSame(left,VehicleHardwareSdkAdapter.area(VehicleSeat.ROW_1_LEFT,separate))
        assertSame(right,VehicleHardwareSdkAdapter.area(VehicleSeat.ROW_1_RIGHT,separate))
        assertEquals(ClimateBounds(1.0,4.0),separate.bounds[VehicleSeat.ROW_1_RIGHT])
        val ambiguous=VehicleHardwareSdkAdapter.seatCapability(AccessType.READ_WRITE,listOf(front,left))
        assertNull(VehicleHardwareSdkAdapter.area(VehicleSeat.ROW_1_LEFT,ambiguous))
        assertSame(front,VehicleHardwareSdkAdapter.area(VehicleSeat.ROW_1_RIGHT,ambiguous))
    }

    @Test fun emptyAndNonSdkCapabilitiesNeverFabricateAnSdkArea() {
        val empty=VehicleHardwareSdkAdapter.seatCapability(AccessType.READ_WRITE,emptyList())
        assertNull(VehicleHardwareSdkAdapter.area(VehicleSeat.ROW_1_LEFT,empty))
        val synthetic=ClimateCapability(VehicleAccess.READ_WRITE,setOf(VehicleSeat.ROW_1_LEFT))
        assertNull(VehicleHardwareSdkAdapter.area(VehicleSeat.ROW_1_LEFT,synthetic))
    }
}
