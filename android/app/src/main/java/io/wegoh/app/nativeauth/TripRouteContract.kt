package io.wegoh.app.nativeauth

import org.json.JSONObject

data class TripRouteSegment(val segment: String,val items: List<TripRouteItem>)
data class TripJoinPoint(val courseId: String,val ref: String,val name: String,val lat: Double,val lng: Double)
data class TripJoinBarrier(val arrivedCarIds: List<String>,val totalCarCount: Int,val released: Boolean)
/** 이 차 탑승자에게만 오는 next까지의 실시간 진행. 위치 공유 좌표 기준 직선 거리이며 도착을 뜻하지 않는다. */
data class TripPlanProgress(val remainingMeters: Int,val legFraction: Double?)
/** 다른 차도 보는 공유 경로 기준 대략 진행. target은 합류 지점 또는 다음 공유 코스 장소. */
data class TripStatusProgress(val target: TripRouteItem,val remainingMeters: Int,val legFraction: Double?)
data class TripRouteStatus(val phase: String,val joinEtaSeconds: Int?=null,val progress: TripStatusProgress?=null)
data class TripRoutePlan(val contractVersion: Int,val phase: String,val segments: List<TripRouteSegment>,
    val joinPoint: TripJoinPoint,val joinEtaSeconds: Int?,val progressRevision: Long,
    val next: TripRouteItem?,val joinBarrier: TripJoinBarrier,val progress: TripPlanProgress?=null)

internal val TripRoutePlan.singleJoinCourseItem: TripRouteItem?
    get() = TripRouteItem("course",joinPoint.ref,joinPoint.courseId).takeIf {
        segments.firstOrNull {it.segment=="shared"}?.items?.count {item->item.courseId==joinPoint.courseId}==1
    }

internal val TripRoutePlan.awaitingJoinCourseCompletion: Boolean
    get() = phase=="shared" && joinBarrier.released && singleJoinCourseItem?.let {next==it}==true

internal object TripRouteContractCodec {
    private val phases=setOf("pickup","waiting","shared","drop","done")
    private fun keys(value: JSONObject,vararg names: String)=check(value.keys().asSequence().toSet()==names.toSet())
    private fun text(value: JSONObject,key: String,max: Int): String {
        val raw=value.get(key);check(raw is String && raw.codePointCount(0,raw.length) in 1..max && raw.none {it.isISOControl()});return raw
    }
    private fun count(value: JSONObject,key: String,max: Int=Int.MAX_VALUE): Int {
        val raw=value.get(key);check(raw is Int || raw is Long)
        return (raw as Number).toLong().also {check(it in 0..max.toLong())}.toInt()
    }
    private fun flag(value: JSONObject,key: String): Boolean {val raw=value.get(key);check(raw is Boolean);return raw}
    private fun phase(value: JSONObject)=text(value,"phase",8).also {check(it in phases)}
    private fun eta(value: JSONObject): Int? {check(value.has("joinEtaSeconds") && value.isNull("joinEtaSeconds"));return null}
    private fun coordinate(value: JSONObject,key: String,max: Double): Double {
        val raw=value.get(key);check(raw is Number);return raw.toDouble().also {check(it.isFinite() && it in -max..max)}
    }
    fun version(value: JSONObject): Int = if(!value.has("routeContractVersion"))1 else
        count(value,"routeContractVersion",2).also {check(it in 1..2)}
    private fun fraction(value: JSONObject): Double? {
        check(value.has("legFraction"));if(value.isNull("legFraction"))return null
        val raw=value.get("legFraction");check(raw is Number && raw !is Boolean)
        return raw.toDouble().also {check(it.isFinite() && it in 0.0..1.0)}
    }
    fun status(value: JSONObject): TripRouteStatus {
        keys(value,"phase","joinEtaSeconds","progress")
        val phase=phase(value)
        check(value.has("progress"))
        val progress=if(value.isNull("progress"))null else value.getJSONObject("progress").let {raw->
            keys(raw,"target","remainingMeters","legFraction")
            val target=item(raw.getJSONObject("target"));check(target.type=="course" && phase in setOf("pickup","shared"))
            TripStatusProgress(target,count(raw,"remainingMeters"),fraction(raw))
        }
        return TripRouteStatus(phase,eta(value),progress)
    }
    private fun item(value: JSONObject): TripRouteItem {
        val item=NativeTripsCodec.routeItem(value)
        if(item.type=="course") {keys(value,"type","courseId","ref");check(item.courseId!=null)}
        else keys(value,"type","ref")
        return item
    }
    fun plan(value: JSONObject): TripRoutePlan {
        keys(value,"contractVersion","phase","segments","joinPoint","joinEtaSeconds","progressRevision","next","joinBarrier","progress")
        check(count(value,"contractVersion",2)==2)
        val raw=value.getJSONArray("segments");check(raw.length()==3)
        val segments=listOf("pickup","shared","drop").mapIndexed {index,expected->
            val segment=raw.getJSONObject(index);keys(segment,"segment","items")
            check(text(segment,"segment",6)==expected)
            val values=segment.getJSONArray("items")
            val items=(0 until values.length()).map {item(values.getJSONObject(it))}
            check(items.size<=1000 && items.all {it.dropRef==null && when(expected) {
                "pickup"->it.type in setOf("pickup","signal");"drop"->it.type in setOf("drop","signal");else->it.type=="signal" || it.type=="course" && it.courseId!=null
            }})
            TripRouteSegment(expected,items)
        }
        val items=segments.flatMap {it.items};check(items.map {it.key}.distinct().size==items.size)
        val join=value.getJSONObject("joinPoint");keys(join,"courseId","ref","name","lat","lng")
        val course=text(join,"courseId",80);val ref=text(join,"ref",80)
        NativeTripsCodec.routeItem(JSONObject().put("type","course").put("courseId",course).put("ref",ref))
        val point=TripJoinPoint(course,ref,text(join,"name",80),coordinate(join,"lat",90.0),coordinate(join,"lng",180.0))
        check(segments[1].items.any {it.type=="course" && it.courseId==course && it.ref==ref})
        val next=if(value.isNull("next"))null else item(value.getJSONObject("next"))
        check(value.has("next") && (next==null || next in items))
        val barrier=value.getJSONObject("joinBarrier");keys(barrier,"arrivedCarIds","totalCarCount","released")
        val ids=barrier.getJSONArray("arrivedCarIds");check(ids.length()<=20)
        val arrived=(0 until ids.length()).map {ids.get(it).also {id->check(id is String && Regex("[a-f0-9]{32}").matches(id))} as String}
        check(arrived.distinct().size==arrived.size)
        val total=count(barrier,"totalCarCount",20);check(arrived.size<=total)
        val progress=if(value.isNull("progress"))null else value.getJSONObject("progress").let {raw->
            keys(raw,"remainingMeters","legFraction");check(next!=null)
            TripPlanProgress(count(raw,"remainingMeters"),fraction(raw))
        }
        return TripRoutePlan(2,phase(value),segments,point,eta(value),count(value,"progressRevision").toLong(),next,
            TripJoinBarrier(arrived,total,flag(barrier,"released")),progress)
    }
    fun arrivalBody(routeRevision: Long,progressRevision: Long,item: TripRouteItem,singleJoinCompletion: Boolean=false): JSONObject {
        require(routeRevision in 0..Int.MAX_VALUE.toLong() && progressRevision in 0..Int.MAX_VALUE.toLong() && item.dropRef==null &&
            (item.type!="course" || item.courseId!=null))
        return JSONObject().put("routeRevision",routeRevision).put("progressRevision",progressRevision)
            .put("item",NativeTripsCodec.routeBody(listOf(item)).getJSONArray("items").getJSONObject(0))
            .also {if(singleJoinCompletion)it.put("singleJoinCompletion","explicit-v1")}
    }
    fun completionBody(routeRevision: Long,progressRevision: Long): JSONObject {
        require(routeRevision in 0..Int.MAX_VALUE.toLong() && progressRevision in 0..Int.MAX_VALUE.toLong())
        return JSONObject().put("routeRevision",routeRevision).put("progressRevision",progressRevision)
    }
    fun arrival(value: JSONObject): TripRoutePlan {
        keys(value,"status","routePlan");check(value.get("status") in setOf("updated","unchanged"))
        return plan(value.getJSONObject("routePlan"))
    }
}

/**
 * 표시용 상세 재조회에서 실시간 진행만 옮긴다. 진행 번호·단계가 그대로인 차에만 적용해
 * 경로 영역이 정한 next·phase를 오래된 응답으로 되돌리지 않는다.
 */
internal fun withLiveProgress(current: List<TripCar>,fresh: List<TripCar>): List<TripCar> = current.map {car->
    val update=fresh.firstOrNull {it.id==car.id} ?: return@map car
    val plan=car.routePlan?.let {plan->update.routePlan?.takeIf {it.progressRevision==plan.progressRevision && it.next==plan.next}
        ?.let {plan.copy(progress=it.progress)} ?: plan}
    val status=car.routeStatus?.let {status->update.routeStatus?.takeIf {it.phase==status.phase}
        ?.let {status.copy(progress=it.progress)} ?: status}
    car.copy(routePlan=plan,routeStatus=status)
}
