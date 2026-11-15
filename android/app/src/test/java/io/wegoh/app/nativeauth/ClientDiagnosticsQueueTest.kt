package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ClientDiagnosticsQueueTest {
    private fun event(index: Int,kind: String="network_error")=ClientDiagnosticEvent(kind,"GET","/v1/native/trips/{id}",
        "%032x".format(index+1),"%032x".format(index+1001),null,null,null,index.toLong())

    @Test fun sameFailureWhilePendingIsOneReport() {
        val queue=ClientDiagnosticsQueue()
        assertTrue(queue.offer(event(0)))
        assertFalse(queue.offer(event(1)))
        assertTrue(queue.offer(event(2,"timeout")))
        assertEquals(1,queue.dropped)
        assertEquals(2,queue.take().size)
        assertTrue("sent reports no longer suppress the next one",queue.offer(event(3)))
    }

    @Test fun capacityAndBatchesStayWithinServerLimits() {
        val queue=ClientDiagnosticsQueue(40)
        // Distinct statuses make distinct reports.
        (0 until 45).forEach {queue.offer(ClientDiagnosticEvent("invalid_response","GET","/v1/social/trips/{id}/signals",
            "%032x".format(it+1),"%032x".format(it+1),100+it,"segments[0].items[12].courseId","unknown",600_000))}
        assertEquals(5,queue.dropped)
        val first=queue.take()
        assertEquals(ClientDiagnosticsQueue.MAX_EVENTS,first.size)
        assertTrue(ClientDiagnosticsQueue.body(first).size<=ClientDiagnosticsQueue.MAX_BYTES)
        assertEquals(20,queue.take().size)
        assertTrue(queue.isEmpty())
    }

    @Test fun anUndeliveredBatchReturnsInFront() {
        val queue=ClientDiagnosticsQueue(3)
        queue.offer(event(0));queue.offer(event(1,"timeout"))
        val batch=queue.take()
        queue.offer(event(2,"invalid_response"))
        queue.restore(batch)
        assertEquals(listOf("network_error","timeout","invalid_response"),queue.take().map {it.kind})
    }

    @Test fun bodyUsesOnlyServerFields() {
        val body=JSONObject(String(ClientDiagnosticsQueue.body(listOf(ClientDiagnosticEvent("invalid_response","GET",
            "/v1/native/trips/{id}","a".repeat(32),"b".repeat(32),200,"routePlan","missing",42))),Charsets.UTF_8))
        assertEquals(setOf("events"),body.keySet())
        val row=body.getJSONArray("events").getJSONObject(0)
        // server/client_diagnostics.py FIELDS
        assertTrue(row.keySet().all {it in setOf("kind","method","route","requestId","traceId","status","decodePath","decodeRule","elapsedMs")})
        assertEquals(200,row.getInt("status"))
        assertFalse(JSONObject(String(ClientDiagnosticsQueue.body(listOf(event(0))),Charsets.UTF_8))
            .getJSONArray("events").getJSONObject(0).has("status"))
    }
}
