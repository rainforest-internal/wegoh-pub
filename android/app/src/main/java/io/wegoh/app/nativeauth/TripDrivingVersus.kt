package io.wegoh.app.nativeauth

import org.json.JSONArray
import org.json.JSONObject

data class TripDrivingVersusCourse(val packId: String,val version: Int,val state: String,val score: Int?)
data class TripDrivingVersusCar(val carId: String,val name: String,val participating: Boolean,val state: String,
    val averageScore: Double?,val measuredCourseCount: Int,val courses: List<TripDrivingVersusCourse>,val totalScore: Int?=null,val final: Boolean=false)
data class TripDrivingVersus(val kind: String,val automatic: Boolean,val state: String,val reason: String?,
    val cars: List<TripDrivingVersusCar>,val winnerCarIds: List<String>,val tied: Boolean,val scope: String="courses")

internal object TripDrivingVersusCodec {
    private fun keys(value: JSONObject,vararg expected: String)=check(value.keys().asSequence().toSet()==expected.toSet())
    private fun text(value: JSONObject,key: String,max: Int): String {
        val raw=value.get(key);check(raw is String && raw.codePointCount(0,raw.length) in 1..max && raw.none {it.isISOControl()});return raw
    }
    private fun integer(value: JSONObject,key: String,min: Int,max: Int): Int {
        val raw=value.get(key);check(raw is Int || raw is Long)
        return (raw as Number).toLong().also {check(it in min.toLong()..max.toLong())}.toInt()
    }
    private fun flag(value: JSONObject,key: String): Boolean {val raw=value.get(key);check(raw is Boolean);return raw}
    private fun id(value: JSONObject,key: String)=text(value,key,32).also {check(Regex("[a-f0-9]{32}").matches(it))}
    private fun state(value: JSONObject,allowed: Set<String>)=text(value,"state",19).also {check(it in allowed)}
    private fun rows(value: JSONArray,max: Int,parse: (JSONObject)->TripDrivingVersusCourse): List<TripDrivingVersusCourse> {
        check(value.length()<=max);return (0 until value.length()).map {parse(value.getJSONObject(it))}
    }
    private fun readTotal(value: JSONObject): TripDrivingVersus {
        keys(value,"kind","automatic","state","reason","cars","winnerCarIds","tied","scope")
        check(value.get("scope")=="trip")
        val copy=JSONObject(value.toString());copy.remove("scope")
        val raw=copy.getJSONArray("cars")
        val totals=(0 until raw.length()).map {index->
            val car=raw.getJSONObject(index)
            keys(car,"carId","name","participating","state","averageScore","measuredCourseCount","courses","totalScore","final")
            val score=if(car.isNull("totalScore"))null else integer(car,"totalScore",0,100)
            val final=flag(car,"final")
            check(car.isNull("averageScore") && integer(car,"measuredCourseCount",0,0)==0 && car.getJSONArray("courses").length()==0)
            check(car.getString("state") !in setOf("sharing-unavailable","withdrawn") || score==null)
            car.remove("totalScore");car.remove("final")
            score to final
        }
        val parsed=read(copy)
        val result=parsed.copy(scope="trip",cars=parsed.cars.mapIndexed {index,car->car.copy(totalScore=totals[index].first,final=totals[index].second)})
        check(result.state!="final" || result.winnerCarIds.all {id->result.cars.any {it.carId==id && it.final && it.totalScore!=null}})
        return result
    }
    fun read(value: JSONObject): TripDrivingVersus {
        if(value.has("scope"))return readTotal(value)
        keys(value,"kind","automatic","state","reason","cars","winnerCarIds","tied")
        check(value.get("kind")=="safe-driving-versus" && flag(value,"automatic"))
        val topState=state(value,setOf("pending","final","unavailable"))
        val reason=if(value.isNull("reason"))null else text(value,"reason",80)
        val raw=value.getJSONArray("cars");check(raw.length()<=20)
        val cars=(0 until raw.length()).map {index->
            val car=raw.getJSONObject(index)
            keys(car,"carId","name","participating","state","averageScore","measuredCourseCount","courses")
            check(flag(car,"participating"))
            val courses=rows(car.getJSONArray("courses"),100) {course->
                keys(course,"packId","version","state","score")
                val pack=text(course,"packId",80).also {check(Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(it))}
                val courseState=state(course,setOf("pending","final","unavailable","sharing-unavailable"))
                val score=if(course.isNull("score"))null else integer(course,"score",0,100)
                check(score==null || courseState=="final")
                TripDrivingVersusCourse(pack,integer(course,"version",1,Int.MAX_VALUE),courseState,score)
            }
            check(courses.map {it.packId}.distinct().size==courses.size)
            val average=if(car.isNull("averageScore"))null else car.get("averageScore").let {number->
                check(number is Number);number.toDouble().also {check(it.isFinite() && it in 0.0..100.0)}
            }
            val measured=integer(car,"measuredCourseCount",0,courses.size)
            check(measured==courses.count {it.score!=null} && (average==null || measured>0))
            TripDrivingVersusCar(id(car,"carId"),text(car,"name",80),true,
                state(car,setOf("pending","ready","unavailable","withdrawn","sharing-unavailable")),average,measured,courses)
        }
        check(cars.map {it.carId}.distinct().size==cars.size)
        val winners=value.getJSONArray("winnerCarIds");check(winners.length()<=cars.size)
        val ids=(0 until winners.length()).map {index->winners.get(index).also {check(it is String && Regex("[a-f0-9]{32}").matches(it))} as String}
        check(ids.distinct().size==ids.size && ids.all {winner->cars.any {it.carId==winner}})
        val tied=flag(value,"tied")
        check((topState=="final" || ids.isEmpty()) && tied==(ids.size>1))
        return TripDrivingVersus("safe-driving-versus",true,topState,reason,cars,ids,tied)
    }
}
