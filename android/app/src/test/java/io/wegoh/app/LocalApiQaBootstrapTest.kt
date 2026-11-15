package io.wegoh.app

import io.wegoh.app.nativeauth.StrictNativeJson
import org.junit.Assert.*
import org.junit.Test

class LocalApiQaBootstrapTest {
    @Test fun strictBusinessJSONIntegersConfigureTheActualBootstrapPortRange() {
        val value=StrictNativeJson.parseBusiness("""{"format":1,"port":55753,"eventsPort":55754}""".toByteArray())
        assertEquals(1,VehicleAppDependencies.bootstrapInteger(value,"format",1,1))
        assertEquals(55753,VehicleAppDependencies.bootstrapInteger(value,"port",1024,65535))
        assertEquals(55754,VehicleAppDependencies.bootstrapInteger(value,"eventsPort",1024,65535))
    }
    @Test fun portRejectsBooleanDecimalStringAndOutOfRangeValues() {
        for(raw in listOf("true","1024.0","\"1024\"","1023","65536","9223372036854775807")) {
            val value=StrictNativeJson.parseBusiness("{\"port\":$raw}".toByteArray())
            try {VehicleAppDependencies.bootstrapInteger(value,"port",1024,65535);fail("Accepted invalid port: $raw")}
            catch(expected: IllegalStateException) { }
        }
    }
    @Test fun formatRequiresTheExactCurrentIntegerVersion() {
        for(raw in listOf("true","1.0","\"1\"","0","2")) {
            val value=StrictNativeJson.parseBusiness("{\"format\":$raw}".toByteArray())
            try {VehicleAppDependencies.bootstrapInteger(value,"format",1,1);fail("Accepted invalid version: $raw")}
            catch(expected: IllegalStateException) { }
        }
    }
}
