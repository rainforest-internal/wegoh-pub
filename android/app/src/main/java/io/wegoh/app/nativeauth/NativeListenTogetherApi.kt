package io.wegoh.app.nativeauth

import android.os.SystemClock
import java.io.Closeable
import org.json.JSONObject

/** Team-owned demo track every vehicle must hold byte-for-byte before it can join. */
data class ListenTogetherTrack(val id: String,val version: Int,val sha256: String,val durationMs: Long)

enum class ListenTogetherPhase { PREPARING, PLAYING, ENDED }
enum class ListenTogetherEndReason { HOST_ENDED, TRACK_FINISHED, EVERYONE_LEFT, TRIP_CLOSED }

data class ListenTogetherSession(val id: String,val revision: Long,val phase: ListenTogetherPhase,val deviceCount: Int,
    val joined: Boolean,val startAtMs: Long?,val endedReason: ListenTogetherEndReason?)

/** Server control state plus the local monotonic window in which the request was in flight. */
data class ListenTogetherSnapshot(val tripId: String,val available: Boolean,val serverTimeMs: Long,val host: Boolean,
    val minimumDevices: Int,val track: ListenTogetherTrack,val session: ListenTogetherSession?,
    val sentElapsedMs: Long=0,val receivedElapsedMs: Long=0)

interface ListenTogetherApi {
    fun read(tripId: String,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable
    fun participate(tripId: String,sessionId: String?,trackSha256: String,joined: Boolean,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable
    fun start(tripId: String,sessionId: String,revision: Long,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable
    fun end(tripId: String,sessionId: String,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable
}

internal class NativeListenTogetherApi(private val client: NativeSocialClient,
    private val elapsed: ()->Long=SystemClock::elapsedRealtime): ListenTogetherApi {
    private fun timed(tripId: String,exchange: ()->JSONObject): ListenTogetherSnapshot {
        val sent=elapsed()
        val value=exchange()
        val received=elapsed()
        return NativeListenTogetherCodec.snapshot(value,tripId).copy(sentElapsedMs=sent,receivedElapsedMs=received)
    }
    private fun write(tripId: String,suffix: String,body: JSONObject,callback: (Result<ListenTogetherSnapshot>)->Unit)=client.call(
        NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,setupRequired=true,
            diagnosticScope="trip.listen.write",realtime=true,fetch={api,token,permission,_->
                timed(tripId) {api.listenTogetherWrite(tripId,suffix,body,permission.revision,token)}}),callback)

    override fun read(tripId: String,callback: (Result<ListenTogetherSnapshot>)->Unit): Closeable = client.call(
        NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),setupRequired=true,diagnosticScope="trip.listen.read",realtime=true,fetch={api,token,_,_->
            timed(tripId) {api.listenTogether(tripId,token)}}),callback)
    override fun participate(tripId: String,sessionId: String?,trackSha256: String,joined: Boolean,callback: (Result<ListenTogetherSnapshot>)->Unit)=
        write(tripId,"/participation",NativeListenTogetherCodec.participationBody(sessionId,trackSha256,joined),callback)
    override fun start(tripId: String,sessionId: String,revision: Long,callback: (Result<ListenTogetherSnapshot>)->Unit)=
        write(tripId,"/start",NativeListenTogetherCodec.startBody(sessionId,revision),callback)
    override fun end(tripId: String,sessionId: String,callback: (Result<ListenTogetherSnapshot>)->Unit)=
        write(tripId,"/end",NativeListenTogetherCodec.endBody(sessionId),callback)
}

internal object NativeListenTogetherCodec {
    private val ID=Regex("[a-f0-9]{32}")
    private val SHA256=Regex("[a-f0-9]{64}")
    private const val TRACK_ID="wegoh-demo-01"
    private const val MAX_REVISION=2147483647L

    private fun fields(value: JSONObject,vararg names: String) {check(value.keys().asSequence().toSet()==names.toSet())}
    private fun whole(value: JSONObject,key: String,range: LongRange): Long {
        val raw=value.get(key);check(raw is Int || raw is Long)
        return (raw as Number).toLong().also {check(it in range)}
    }
    private fun flag(value: JSONObject,key: String): Boolean = value.get(key).also {check(it is Boolean)} as Boolean
    private fun text(value: JSONObject,key: String,pattern: Regex): String = value.get(key).also {check(it is String && pattern.matches(it))} as String

    fun snapshot(value: JSONObject,tripId: String): ListenTogetherSnapshot {
        check(ID.matches(tripId))
        fields(value,"tripId","available","serverTimeMs","host","minimumDevices","track","session")
        check(text(value,"tripId",ID)==tripId)
        val available=flag(value,"available")
        val track=value.getJSONObject("track").let {row->
            fields(row,"id","version","sha256","durationMs")
            check(row.get("id")==TRACK_ID)
            ListenTogetherTrack(TRACK_ID,whole(row,"version",1L..1L).toInt(),text(row,"sha256",SHA256),whole(row,"durationMs",1L..3600000L))
        }
        val session=if(value.isNull("session"))null else value.getJSONObject("session").let {row->
            fields(row,"id","revision","state","deviceCount","joined","startAtMs","endedReason")
            val phase=when(row.get("state")) {"preparing"->ListenTogetherPhase.PREPARING;"playing"->ListenTogetherPhase.PLAYING;"ended"->ListenTogetherPhase.ENDED;else->error("LISTEN_TOGETHER_STATE")}
            val startAt=if(row.isNull("startAtMs"))null else whole(row,"startAtMs",0L..Long.MAX_VALUE)
            val reason=if(row.isNull("endedReason"))null else when(row.get("endedReason")) {
                "host-ended"->ListenTogetherEndReason.HOST_ENDED;"track-finished"->ListenTogetherEndReason.TRACK_FINISHED
                "everyone-left"->ListenTogetherEndReason.EVERYONE_LEFT;"trip-closed"->ListenTogetherEndReason.TRIP_CLOSED
                else->error("LISTEN_TOGETHER_REASON")
            }
            check((phase==ListenTogetherPhase.PREPARING)==(startAt==null) || phase==ListenTogetherPhase.ENDED)
            check((phase==ListenTogetherPhase.ENDED)==(reason!=null))
            ListenTogetherSession(text(row,"id",ID),whole(row,"revision",1L..MAX_REVISION),phase,
                whole(row,"deviceCount",0L..1000L).toInt(),flag(row,"joined"),startAt,reason)
        }
        check(available || session==null)
        return ListenTogetherSnapshot(tripId,available,whole(value,"serverTimeMs",0L..Long.MAX_VALUE),flag(value,"host"),
            whole(value,"minimumDevices",2L..2L).toInt(),track,session)
    }

    fun participationBody(sessionId: String?,trackSha256: String,joined: Boolean): JSONObject {
        require((sessionId==null || ID.matches(sessionId)) && SHA256.matches(trackSha256))
        return JSONObject().put("sessionId",sessionId ?: JSONObject.NULL).put("trackSha256",trackSha256).put("joined",joined)
    }
    fun startBody(sessionId: String,revision: Long): JSONObject {
        require(ID.matches(sessionId) && revision in 1..MAX_REVISION)
        return JSONObject().put("sessionId",sessionId).put("revision",revision)
    }
    fun endBody(sessionId: String): JSONObject {
        require(ID.matches(sessionId))
        return JSONObject().put("sessionId",sessionId)
    }
}
