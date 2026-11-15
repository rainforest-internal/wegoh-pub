package io.wegoh.app.ui

import io.wegoh.app.nativeauth.TripCar
import org.junit.Assert.*
import org.junit.Test

class TripCarRoleLabelTest {
    private val car=TripCar("car","우리 차","driver","운전자",3,isMine=false,iRide=false,passengers=emptyList())

    @Test fun everyScreenNamesMyCarTheSameWay() {
        assertEquals("내 차",tripCarRoleLabel(car.copy(isMine=true)))
        assertEquals("내가 탄 차",tripCarRoleLabel(car.copy(iRide=true)))
        assertNull(tripCarRoleLabel(car))
    }
}
