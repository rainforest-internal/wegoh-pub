package io.wegoh.app

import org.junit.Assert.assertEquals
import org.junit.Test

class VehicleClimatePollingTest {
    @Test fun pendingCommandsAreCheckedPromptlyAfterACommandFinishes() {
        for(result in listOf(VehicleClimateHostResult.CONFIRMED,VehicleClimateHostResult.BLOCKED))
            assertEquals(250L,vehicleClimatePollDelay(result,true))
    }

    @Test fun idleAndUnavailableReceiversKeepTheNormalPollingInterval() {
        for(result in VehicleClimateHostResult.entries)assertEquals(2_000L,vehicleClimatePollDelay(result,false))
        assertEquals(2_000L,vehicleClimatePollDelay(VehicleClimateHostResult.NO_SUPPORTED_REQUEST,true))
        assertEquals(2_000L,vehicleClimatePollDelay(VehicleClimateHostResult.UNAVAILABLE,true))
        assertEquals(2_000L,vehicleClimatePollDelay(VehicleClimateHostResult.UNKNOWN,true))
    }
}
