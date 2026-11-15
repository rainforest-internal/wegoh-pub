package io.wegoh.app

import io.wegoh.app.nativeauth.CourseRoadCoordinate
import org.junit.Assert.*
import org.junit.Test

class CourseRoadMapsTest {
    private val points=listOf(Stop("a","첫 장소",37.5,127.0,100f,"도착"),Stop("b","다음 장소",37.6,127.1,100f,"도착"))
    private fun course(id: String="coast",version: Int=1,checksum: String="a".repeat(64))=PublishedPack(id,version,"코스","작성자","",2,checksum)
    private fun pack(course: PublishedPack)=DrivePack(course.id,course.version,course.title,course.author,"",points)
    private val road=listOf(CourseRoadCoordinate(37.5,127.0),CourseRoadCoordinate(37.51,127.07),CourseRoadCoordinate(37.6,127.1))

    @Test fun sharesFlightAndReusesVerifiedCoordinatesAndRoad() {
        var reads=0;var routes=0;var response: ((Result<List<CourseRoadCoordinate>>)->Unit)?=null
        val cache=CourseRoadMaps({"account:1"},{c,done->reads++;done(Result.success(pack(c)))},{_,p,done->
            routes++;assertEquals(points.map {CourseRoadCoordinate(it.latitude,it.longitude)},p);response=done})
        val results=mutableListOf<CourseRoadPreview>()
        repeat(2) {cache.load(course()) {results.add(it.getOrThrow())}}
        assertEquals(1,reads);assertEquals(1,routes);assertTrue(results.isEmpty())
        response!!(Result.success(road))
        cache.load(course()) {results.add(it.getOrThrow())}
        assertEquals(3,results.size);assertEquals(road,results.last().path);assertEquals(1,routes)
    }

    @Test fun accountEpochAndOrderedCoordinateIdentityCannotReuseOldRoad() {
        var owner: String?="alice:1";var reads=0;var routes=0
        val cache=CourseRoadMaps({owner},{c,done->reads++;done(Result.success(pack(c)))},{_,_,done->routes++;done(Result.success(road))})
        cache.load(course()) {it.getOrThrow()}
        cache.load(course(version=2)) {it.getOrThrow()}
        cache.load(course(checksum="b".repeat(64))) {it.getOrThrow()}
        owner="bob:1";cache.load(course()) {it.getOrThrow()}
        owner="bob:2";cache.load(course()) {it.getOrThrow()}
        assertEquals(5,reads);assertEquals(5,routes)
        owner=null;cache.load(course()) {assertTrue(it.isFailure)}
        assertEquals(5,reads)
        assertNotEquals(CourseRoadKey(course(),road),CourseRoadKey(course(),road.reversed()))
    }

    @Test fun logoutSuppressesLateOldAccountReply() {
        var owner: String?="alice"
        var reply: ((Result<List<CourseRoadCoordinate>>)->Unit)?=null
        val cache=CourseRoadMaps({owner},{c,done->done(Result.success(pack(c)))},{_,_,done->reply=done})
        val results=mutableListOf<Result<CourseRoadPreview>>()
        cache.load(course()) {results.add(it)}
        owner=null;cache.clear();reply!!(Result.success(road))
        assertEquals(1,results.size);assertTrue(results.single().isFailure)
        owner="bob";cache.load(course()) {results.add(it)}
        assertEquals(1,results.size)
        reply!!(Result.success(road));assertTrue(results.last().isSuccess)
    }

    @Test fun onlyTwoInflightAndCancelledQueuedCardsNeverLoad() {
        var starts=0
        val replies=mutableListOf<(Result<DrivePack>)->Unit>()
        val cache=CourseRoadMaps({"alice"},{_,done->starts++;replies.add(done)},{_,_,done->done(Result.success(road))})
        cache.load(course("one")) {}
        cache.load(course("two")) {}
        val cancelled=cache.load(course("three")) {};cancelled.close()
        cache.load(course("four")) {}
        assertEquals(2,starts)
        replies[0](Result.success(pack(course("one"))))
        assertEquals(3,starts)
    }

    @Test fun boundedCacheEvictsAndFailureDoesNotCacheFakeLine() {
        var reads=0;var fail=true
        val cache=CourseRoadMaps({"alice"},{c,done->reads++;done(Result.success(pack(c)))},{_,_,done->
            done(if(fail)Result.failure(IllegalStateException("provider")) else Result.success(road))},capacity=2)
        cache.load(course("one")) {assertTrue(it.isFailure)}
        fail=false;cache.load(course("one")) {assertEquals(road,it.getOrThrow().path)}
        cache.load(course("two")) {it.getOrThrow()};cache.load(course("three")) {it.getOrThrow()}
        cache.load(course("one")) {it.getOrThrow()}
        assertEquals(4,reads)
    }

    @Test fun oneSavedPlaceSkipsRoadProviderWithoutInventingRoute() {
        var routes=0
        val cache=CourseRoadMaps({"alice"},{c,done->done(Result.success(pack(c).copy(stops=points.take(1))))},{_,_,_->routes++})
        cache.load(course().copy(stopCount=1)) {assertEquals(points.take(1),it.getOrThrow().stops);assertTrue(it.getOrThrow().path.isEmpty())}
        assertEquals(0,routes)
    }
}
