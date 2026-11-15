package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class TripDrivingVersusCodecTest {
    private val car="a".repeat(32)
    private fun course(state: String="final",score: Any=90)=JSONObject().put("packId","coast").put("version",1).put("state",state).put("score",score)
    private fun response()=JSONObject().put("kind","safe-driving-versus").put("automatic",true).put("state","pending")
        .put("reason","final-reports-pending").put("winnerCarIds",JSONArray()).put("tied",false)
        .put("cars",JSONArray().put(JSONObject().put("carId",car).put("name","사용자A의 차").put("participating",true)
            .put("state","ready").put("averageScore",90.0).put("measuredCourseCount",1).put("courses",JSONArray().put(course()))))
    @Test fun totalScoreUsesSeparateScopeAndDoesNotInventACourseAverage() {
        val value=response().put("scope","trip")
        value.getJSONArray("cars").getJSONObject(0).apply {
            put("averageScore",JSONObject.NULL).put("measuredCourseCount",0).put("courses",JSONArray())
            put("totalScore",85).put("final",false)
        }
        val result=TripDrivingVersusCodec.read(value)
        assertEquals("trip",result.scope);assertEquals(85,result.cars.single().totalScore)
        assertNull(result.cars.single().averageScore);assertTrue(result.cars.single().courses.isEmpty())
        value.getJSONArray("cars").getJSONObject(0).put("totalScore",101)
        assertTrue(runCatching {TripDrivingVersusCodec.read(value)}.isFailure)
    }
    @Test fun serverStateAndWinnersAreKeptWithoutComputingFromRoundedMeans() {
        val value=response()
        assertEquals("pending",TripDrivingVersusCodec.read(value).state)
        value.put("state","final").put("reason",JSONObject.NULL).put("winnerCarIds",JSONArray().put(car))
        val result=TripDrivingVersusCodec.read(value)
        assertEquals(listOf(car),result.winnerCarIds);assertFalse(result.tied)
        assertEquals(90.0,result.cars.single().averageScore!!,0.0)
        assertEquals(90,result.cars.single().courses.single().score)
    }
    @Test fun absentMeasurementsAndUnavailableSharingStayDistinct() {
        val missing=response()
        missing.getJSONArray("cars").getJSONObject(0).apply {
            put("state","pending").put("averageScore",JSONObject.NULL).put("measuredCourseCount",0)
            put("courses",JSONArray().put(course("pending",JSONObject.NULL)))
        }
        val pending=TripDrivingVersusCodec.read(missing).cars.single()
        assertEquals("pending",pending.courses.single().state);assertNull(pending.averageScore)
        val partial=response().put("state","unavailable").put("reason","sharing-unavailable")
        partial.getJSONArray("cars").getJSONObject(0).apply {
            put("state","sharing-unavailable").put("averageScore",JSONObject.NULL)
            getJSONArray("courses").put(course("sharing-unavailable",JSONObject.NULL).put("packId","other"))
        }
        val hidden=TripDrivingVersusCodec.read(partial)
        assertTrue(hidden.winnerCarIds.isEmpty());assertNull(hidden.cars.single().averageScore)
        assertEquals(1,hidden.cars.single().measuredCourseCount)
    }
    @Test fun strictDtoRejectsExtraDataAndInventedWinnerOrMeasurement() {
        for(value in listOf(response().put("speedSamples",JSONArray()),response().put("automatic",false),
            response().put("winnerCarIds",JSONArray().put(car)),response().put("tied",true),response().apply {
                getJSONArray("cars").getJSONObject(0).put("averageScore",101)
            },response().apply {getJSONArray("cars").getJSONObject(0).put("measuredCourseCount",true)},response().apply {
                getJSONArray("cars").getJSONObject(0).getJSONArray("courses").getJSONObject(0).put("score",90.5)
            }))assertTrue(runCatching {TripDrivingVersusCodec.read(value)}.isFailure)
    }
}
