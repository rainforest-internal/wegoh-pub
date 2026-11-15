package io.wegoh.app.nativeauth

import org.json.JSONObject
import java.time.Instant

internal object NativeTripDisplayCodec {
    private fun text(value: JSONObject,key: String): String?=if(value.isNull(key))null else value.getString(key).also {
        check(it.length<=300 && it.none {char->char.isISOControl()})
    }
    private fun number(value: JSONObject,key: String): Double {
        val raw=value.get(key);check(raw is Number)
        return raw.toDouble().also {check(it.isFinite() && it>=0)}
    }
    private fun count(value: JSONObject,key: String): Int {
        val raw=value.get(key);check(raw is Int || raw is Long)
        return (raw as Number).toLong().also {check(it in 0L..10000L)}.toInt()
    }
    fun read(value: JSONObject,requestedAtElapsedMillis: Long=android.os.SystemClock.elapsedRealtime()): TripDisplay {
        val lifetime=java.time.Duration.between(Instant.parse(value.getString("serverNow")),Instant.parse(value.getString("validUntil"))).toMillis()
        check(lifetime in 0..30000)
        val timeline=value.getJSONArray("timeline").also {check(it.length()<=512)}
        val companions=value.getJSONArray("companions").also {check(it.length()<=20)}
        return TripDisplay(List(timeline.length()) {index->val row=timeline.getJSONObject(index)
            TripTimelineEntry(checkNotNull(text(row,"id")),checkNotNull(text(row,"name")),checkNotNull(text(row,"kind")),
                checkNotNull(text(row,"at")).also {Instant.parse(it)})},
            if(value.isNull("visitCount"))null else count(value,"visitCount"),
            value.optJSONObject("metrics")?.let {TripMetrics(number(it,"distanceKm"),number(it,"drivingSeconds"))},
            value.optJSONObject("music")?.let {TripMusic(text(it,"name"),text(it,"currentTitle"),count(it,"trackCount"),text(it,"djName"))},
            List(companions.length()) {index->val row=companions.getJSONObject(index)
                val id=checkNotNull(text(row,"carId")).also {check(Regex("[a-f0-9]{32}").matches(it))}
                val direction=text(row,"direction")?.also {check(it in setOf("ahead","behind"))}
                val distance=if(row.isNull("distanceMeters"))null else number(row,"distanceMeters")
                check((distance==null)==(direction==null))
                TripCompanionPosition(id,text(row,"label"),distance,direction)},
            requestedAtElapsedMillis+lifetime,text(value,"endedAt")?.also {Instant.parse(it)})
    }
}
