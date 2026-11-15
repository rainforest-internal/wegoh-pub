package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class VehicleProfileCodecTest {
    private val device="a".repeat(32)
    private fun profile(vararg extra: Pair<String,Any>)=JSONObject().put("deviceId",device).put("plateNumber","123가4567")
        .put("name","").put("defaultName","사용자A의 차").put("revision",1).apply {extra.forEach {(key,value)->put(key,value)}}
    private fun rejects(value: JSONObject) {
        try {decodeVehicleProfile(value,device);fail("invalid vehicle profile must fail")} catch(_: IllegalStateException) {}
    }

    @Test fun unnamedVehicleShowsTheServerDefaultName() {
        val value=decodeVehicleProfile(profile(),device)
        assertEquals(VehicleProfile("123가4567","","사용자A의 차",1),value)
        assertEquals("사용자A의 차",value.displayName)
    }

    @Test fun ownerChosenNameWins() {
        assertEquals("주말 🚗 차",decodeVehicleProfile(profile("name" to "주말 🚗 차"),device).displayName)
    }

    @Test fun closedShapeAndNameRulesAreChecked() {
        rejects(profile().apply {remove("name")})
        rejects(profile().apply {remove("defaultName")})
        rejects(profile("extra" to 1))
        rejects(profile("name" to " 앞 공백"))
        rejects(profile("name" to "가".repeat(21)))
        rejects(profile("name" to "줄\n바꿈"))
        rejects(profile("defaultName" to ""))
        rejects(profile("deviceId" to "b".repeat(32)))
    }

    @Test fun nameRuleMatchesServer() {
        assertTrue(VehicleProfile.validName(""))
        assertTrue(VehicleProfile.validName("가".repeat(20)))
        assertTrue(VehicleProfile.validName("🚗".repeat(20)))
        assertFalse(VehicleProfile.validName("🚗".repeat(21)))
        assertFalse(VehicleProfile.validName("출근​차"))
        assertFalse(VehicleProfile.validName("출근 차"))
        assertFalse(VehicleProfile.validName("출근 차 "))
    }
}
