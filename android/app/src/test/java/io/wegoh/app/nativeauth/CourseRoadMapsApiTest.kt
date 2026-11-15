package io.wegoh.app.nativeauth

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CourseRoadMapsApiTest {
    private fun value(path: String="[[37.5,127],[37.51,127.07],[37.6,127.1]]")=
        JSONObject("""{"distanceMeters":12000,"durationSeconds":1800,"path":$path}""")
    @Test fun keepsProviderRoadBendsInLatitudeLongitudeOrder() {
        val path=decodeCourseRoad(value())
        assertEquals(3,path.size);assertEquals(37.51,path[1].latitude,0.0);assertEquals(127.07,path[1].longitude,0.0)
    }
    @Test fun rejectsEmptyOversizedOrInvalidRoadInsteadOfStraightLineFallback() {
        for(path in listOf("[]","[[37.5,127]]","[[127,37.5],[127.1,37.6]]","[[true,127],[37.6,127.1]]",
            "[[37.5,127,1],[37.6,127.1]]","["+List(2001) {"[37.5,127]"}.joinToString(",")+"]")) {
            assertTrue(runCatching {decodeCourseRoad(value(path))}.isFailure)
        }
    }
    @Test fun rejectsUnknownFieldsAndInvalidMetrics() {
        assertTrue(runCatching {decodeCourseRoad(value().put("raw","private"))}.isFailure)
        assertTrue(runCatching {decodeCourseRoad(value().put("distanceMeters",-1))}.isFailure)
        assertTrue(runCatching {decodeCourseRoad(value().put("durationSeconds","1800"))}.isFailure)
    }
}
