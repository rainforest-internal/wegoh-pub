package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/** A refused trip response travels the production path to the report body: the exchange's closing
 * NativeNetLog.finish (as NativeApiClient.exchange's finally runs it), TripLoadDiagnostics.decode,
 * NativeNetLog's default reporter and ClientDiagnostics' background sender. Nothing is replaced.
 * NativeApiClient.exchange itself needs API 29+ and a non-main Looper, which JVM tests do not have.
 */
class ClientDiagnosticsPathTest {
    private val trip="0123456789abcdef0123456789abcdef"
    private val bodies=LinkedBlockingQueue<ByteArray>()
    private val sender=ClientDiagnostics.Sender {bodies.add(it);true}
    private val sink=NativeNetLog.sink
    private val logcat=WegoLog.logcat

    @After fun detach() {ClientDiagnostics.detach(sender);NativeNetLog.sink=sink;WegoLog.logcat=logcat;NativeNetLog.forget()}

    @Test fun aRefusedTripFieldIsSentAsOneInvalidResponseReport() {
        NativeNetLog.sink={};WegoLog.logcat={_,_,_->}
        ClientDiagnostics.attach(sender)
        val net=NativeNetLog.start("GET","/v1/native/trips/$trip").also {it.status=200}
        val failure=NativeTripFieldFailure("routePlan")
        assertThrows(NativeTripFieldFailure::class.java) {
            TripLoadDiagnostics.decode("trip.detail",trip,"GET /v1/native/trips/{id}") {
                NativeNetLog.finish(net,null)
                throw failure
            }
        }
        assertEquals(ClientFailure("invalid_field","GET /v1/native/trips/{id}"),ClientDiagnostics.failure("trip.detail"))

        val body=bodies.poll(15,TimeUnit.SECONDS) ?: error("no report sent")
        val text=String(body,Charsets.UTF_8)
        val event=JSONObject(text).getJSONArray("events").getJSONObject(0)
        assertEquals("invalid_response",event.getString("kind"))
        assertEquals("GET",event.getString("method"))
        assertEquals("/v1/native/trips/{id}",event.getString("route"))
        assertEquals(net.requestId,event.getString("requestId"))
        assertEquals(net.traceId,event.getString("traceId"))
        assertEquals(200,event.getInt("status"))
        assertEquals("routePlan",event.getString("decodePath"))
        assertEquals("unknown",event.getString("decodeRule"))
        assertFalse(text.contains(trip))
        assertTrue(bodies.isEmpty())
    }
}
