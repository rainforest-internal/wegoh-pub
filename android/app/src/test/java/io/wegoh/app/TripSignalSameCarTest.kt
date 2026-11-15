package io.wegoh.app

import io.wegoh.app.nativeauth.*
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TripSignalSameCarTest {
    private val car=TripCar("car-1","사용자D의 차","driver","사용자D",4,isMine=true,iRide=true,
        passengers=listOf(TripPassenger("rider","WegoH 팀원",false)),ordinal=1)
    private val other=TripCar("car-2","다른 차","driver-2","사용자B",4,isMine=false,iRide=false,passengers=emptyList(),ordinal=2)
    private fun trip(vararg cars: TripCar)=TripDetail("trip","가","",listOf(
        TripMember("driver","사용자D",true,true,true,carId="car-1"),
        TripMember("rider","WegoH 팀원",true,false,false,carId="car-1"),
        TripMember("driver-2","사용자B",true,false,false,carId="car-2")),cars.toList(),state="active")
    private fun signal(account: String,destination: SignalDestination?=null)=
        TripSignal("s-$account",account,TripSignalKind.CAFE,destination,"2026-11-15T03:23:00Z","valid",0,0,null)
    private val cafe=SignalDestination("카페",37.5,127.0)

    @Test
    fun sameCarPassengerRequestWithoutPlaceReachesDriver() {
        val trip=trip(car)
        assertTrue(trip.announcesSignal(signal("rider")))
        assertFalse(trip.announcesSignal(signal("rider",cafe)))
        assertFalse(trip.announcesSignal(signal("driver")))
        assertTrue(trip(car,other).announcesSignal(signal("driver-2",cafe)))
    }

    @Test
    fun passengerRequestIsLabelledWithTheCarTheyRide() {
        assertEquals("1호차 사용자D의 차",trip(car).signalCar(signal("rider"))?.numberedName)
        assertEquals("2호차 다른 차",trip(car,other).signalCar(signal("driver-2"))?.numberedName)
    }
}
