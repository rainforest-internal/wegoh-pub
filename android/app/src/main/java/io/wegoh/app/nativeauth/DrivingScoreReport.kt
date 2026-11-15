package io.wegoh.app.nativeauth

import org.json.JSONObject

data class DrivingScoreReport(val score: Int?,val accelerations: Int,val brakings: Int,val measurable: Boolean,val final: Boolean) {
    init {
        require(accelerations>=0 && brakings>=0)
        val expected=100-minOf(100L,(accelerations.toLong()+brakings)*5).toInt()
        require(if(measurable)score==expected else score==null)
    }
    internal fun body()=JSONObject().put("drivingScore",JSONObject()
        .put("score",score ?: JSONObject.NULL).put("accelerations",accelerations).put("brakings",brakings)
        .put("measurable",measurable).put("final",final))
}
