package io.wegoh.app

import io.wegoh.app.nativeauth.CourseRoadCoordinate
import java.io.Closeable

internal data class CourseRoadPreview(val stops: List<Stop>,val path: List<CourseRoadCoordinate>)
internal data class CourseRoadKey(val course: PublishedPack,val coordinates: List<CourseRoadCoordinate>)

internal fun decodeCourseRoadPack(course: PublishedPack,bytes: ByteArray): DrivePack=
    PackCodec.decode(bytes.toString(Charsets.UTF_8)).also {check(it.key==course.key && it.stops.size==course.stopCount)}

internal class CourseRoadMaps(private val account: ()->String?,
    private val read: (PublishedPack,(Result<DrivePack>)->Unit)->Unit,
    private val route: (PublishedPack,List<CourseRoadCoordinate>,(Result<List<CourseRoadCoordinate>>)->Unit)->Unit,
    private val capacity: Int=24,private val concurrency: Int=2) {
    private class Flight(val course: PublishedPack,val generation: Long) {
        val listeners=linkedSetOf<(Result<CourseRoadPreview>)->Unit>()
        var started=false
    }
    private var owner: String?=null
    private var generation=0L
    private var active=0
    private val packs=linkedMapOf<PublishedPack,DrivePack>()
    private val roads=linkedMapOf<CourseRoadKey,List<CourseRoadCoordinate>>()
    private val flights=linkedMapOf<PublishedPack,Flight>()

    fun clear() {
        generation++;owner=null;active=0;packs.clear();roads.clear()
        val previous=flights.values.toList();flights.clear()
        previous.forEach {flight->flight.listeners.toList().forEach {it(Result.failure(IllegalStateException("COURSE_MAP_ACCOUNT_CHANGED")))}}
    }
    private fun current(): Boolean {
        val next=account()
        if(owner!=next) {clear();owner=next}
        return next!=null
    }
    fun load(course: PublishedPack,callback: (Result<CourseRoadPreview>)->Unit): Closeable {
        if(!current()) {callback(Result.failure(IllegalStateException("COURSE_MAP_CONNECTION_REQUIRED")));return Closeable {}}
        val saved=packs[course]
        if(saved!=null)roads[key(course,saved)]?.let {callback(Result.success(CourseRoadPreview(saved.stops,it)));return Closeable {}}
        val existing=flights[course]
        if(existing==null && flights.size>=capacity) {
            callback(Result.failure(IllegalStateException("COURSE_MAP_BUSY")));return Closeable {}
        }
        val flight=existing ?: Flight(course,generation).also {flights[course]=it}
        flight.listeners.add(callback);drain()
        return Closeable {
            flight.listeners.remove(callback)
            if(!flight.started && flight.listeners.isEmpty())flights.remove(course,flight)
        }
    }
    private fun key(course: PublishedPack,pack: DrivePack)=CourseRoadKey(course,pack.stops.map {CourseRoadCoordinate(it.latitude,it.longitude)})
    private fun valid(flight: Flight)=current() && flight.generation==generation && flights[flight.course]===flight
    private fun drain() {
        if(!current())return
        while(active<concurrency) {
            val next=flights.values.firstOrNull {!it.started} ?: return
            next.started=true;active++
            val cached=packs[next.course]
            if(cached!=null)loadRoute(next,cached)
            else read(next.course) {result->
                if(valid(next))result.fold({pack->
                    packs[next.course]=pack;trim(packs);loadRoute(next,pack)
                },{finish(next,Result.failure(it))})
            }
        }
    }
    private fun loadRoute(flight: Flight,pack: DrivePack) {
        val key=key(flight.course,pack)
        if(key.coordinates.size<2) {roads[key]=emptyList();trim(roads);finish(flight,Result.success(CourseRoadPreview(pack.stops,emptyList())));return}
        route(flight.course,key.coordinates) {result->
            if(valid(flight))result.fold({path->
                roads[key]=path;trim(roads);finish(flight,Result.success(CourseRoadPreview(pack.stops,path)))
            },{finish(flight,Result.failure(it))})
        }
    }
    private fun finish(flight: Flight,result: Result<CourseRoadPreview>) {
        if(!valid(flight))return
        flights.remove(flight.course);active--
        flight.listeners.toList().forEach {it(result)};drain()
    }
    private fun <K,V> trim(values: MutableMap<K,V>) {while(values.size>capacity)values.remove(values.keys.first())}
}
