package io.wegoh.app.nativeauth

import org.junit.Assert.*
import org.junit.Test

class VehicleClimateInboxTest {
    private fun request(id: String,stage: String,created: Long,friend: Boolean=true)=
        VehicleClimateNativeTransport.Request(id,"hvac.fan",1,friend,stage,created)

    @Test fun alreadyClaimedCommandsAreNotClaimedAgain() {
        val rows=listOf(request("new","queued",1),request("claimed","delivered",2),
            request("received","received",3),request("accepted","sdk-accepted",4))
        val inbox=VehicleClimateNativeTransport.Inbox(rows,mapOf("hvac.fan" to 1L))
        assertEquals(listOf("new"),inbox.queuedFriendRequests().map {it.id})
    }

    @Test fun oldestQueuedFriendRequestRunsFirst() {
        val inbox=VehicleClimateNativeTransport.Inbox(listOf(request("latest","queued",30),
            request("middle","queued",20),request("first","queued",10),request("room","queued",0,false)),emptyMap())
        assertEquals(listOf("first","middle","latest"),inbox.queuedFriendRequests().map {it.id})
    }

    @Test fun terminalAndUnknownStagesCannotEnterTheQueue() {
        val rows=listOf("state-confirmed","rejected","unknown","expired","cancelled","future-stage")
            .mapIndexed {i,stage->request("$i",stage,i.toLong())}
        assertTrue(VehicleClimateNativeTransport.Inbox(rows,emptyMap()).queuedFriendRequests().isEmpty())
    }
}
