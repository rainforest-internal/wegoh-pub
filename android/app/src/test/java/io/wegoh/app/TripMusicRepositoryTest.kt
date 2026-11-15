package io.wegoh.app

import io.wegoh.app.nativeauth.*
import java.io.Closeable
import org.junit.Assert.*
import org.junit.Test

class TripMusicRepositoryTest {
    private val trip="a".repeat(32)
    private val me="team-"+"b".repeat(40)
    private val saved=TripSavedPlaylist("c".repeat(32),"여행에 추가된 음악","https://music.youtube.com/playlist?list=trip",me,"일행","approved")
    private val source=TripMusicSourceItem(TripSavedPlaylistSource("d".repeat(32),7,"e".repeat(32)),"내 계정에 저장한 음악","멜론")
    private fun collection(vararg items: TripSavedPlaylist)=TripMusicCollection(trip,items.toList(),200,true)

    private class Pending<T>(private val callback: (Result<T>)->Unit): Closeable {
        var cancelled=false
            private set
        override fun close(){cancelled=true}
        fun success(value: T)=callback(Result.success(value))
        fun failure(error: Throwable)=callback(Result.failure(error))
    }
    private data class Addition(val source: TripSavedPlaylistSource,val rights: Boolean,val review: Boolean,
        val response: Pending<TripMusicCollection>)
    private class FakeGateway: TripMusicGateway {
        var connected=true
        private var ready=false
        var closed=false
            private set
        override val current get()=connected && ready && !closed
        lateinit var observer: NativeSocialObserver
        private lateinit var opening: (Result<Unit>)->Unit
        val reads=mutableListOf<Pending<TripMusicCollection>>()
        val sourceReads=mutableListOf<Pending<List<TripMusicSourceItem>>>()
        val additions=mutableListOf<Addition>()
        val plays=mutableListOf<Pair<String,Pending<TripMusicCollection>>>()
        val moves=mutableListOf<Triple<String,String?,Pending<TripMusicCollection>>>()
        override fun play(itemId: String,callback: (Result<TripMusicCollection>)->Unit): Closeable =
            Pending(callback).also {plays+=itemId to it}
        override fun move(itemId: String,afterId: String?,callback: (Result<TripMusicCollection>)->Unit): Closeable =
            Pending(callback).also {moves+=Triple(itemId,afterId,it)}
        override fun open(observer: NativeSocialObserver,callback: (Result<Unit>)->Unit) {this.observer=observer;opening=callback}
        fun opened(){ready=true;opening(Result.success(Unit))}
        override fun read(callback: (Result<TripMusicCollection>)->Unit): Closeable = Pending(callback).also {reads+=it}
        override fun sources(callback: (Result<List<TripMusicSourceItem>>)->Unit): Closeable = Pending(callback).also {sourceReads+=it}
        override fun add(source: TripSavedPlaylistSource,rights: Boolean,review: Boolean,
            callback: (Result<TripMusicCollection>)->Unit): Closeable = Pending(callback).also {
                additions+=Addition(source,rights,review,it)
            }
        override fun close(){closed=true}
        fun resources(vararg resources: String)=observer.onResourcesChanged(resources.toSet())
        fun invalidate(){connected=false;observer.onInvalidated()}
    }
    private inner class Fixture {
        val gateways=mutableListOf<FakeGateway>()
        val repository=TripMusicRepository(trip) {FakeGateway().also {gateways+=it}}
        val gateway get()=gateways.last()
        fun ready(value: TripMusicCollection=collection(saved)) {
            repository.setAvailable(true);gateway.opened();gateway.reads.last().success(value)
        }
        fun own(vararg items: TripMusicSourceItem) {repository.loadSources();gateway.sourceReads.last().success(items.toList())}
    }
    private fun fixture(block: (Fixture)->Unit) {
        val fixture=Fixture()
        try {block(fixture)} finally {fixture.repository.close()}
    }

    @Test fun invalidationWhileShownReopensAndStopsAtTheLimit()=fixture {f->
        f.ready()
        f.gateway.invalidate()
        assertEquals(2,f.gateways.size)
        f.gateway.opened();f.gateway.reads.last().success(collection(saved))
        assertEquals(TripMusicStatus.READY,f.repository.state.status)
        repeat(INVALIDATION_RELOAD_LIMIT+2) {f.gateway.invalidate()}
        assertEquals(2+INVALIDATION_RELOAD_LIMIT,f.gateways.size)
        assertEquals(TripMusicStatus.UNAVAILABLE,f.repository.state.status)
    }

    @Test fun tripCollectionAndMySavedSourcesHaveIndependentLoadingAndEmptyStates()=fixture {f->
        f.ready();val tripCollection=f.repository.state.collection
        assertEquals(TripMusicStatus.READY,f.repository.state.status)
        assertEquals(listOf(saved),tripCollection?.items)
        assertEquals(TripMusicStatus.IDLE,f.repository.state.sourceStatus)
        assertTrue(f.gateway.sourceReads.isEmpty())
        f.repository.loadSources()
        assertSame(tripCollection,f.repository.state.collection)
        assertEquals(TripMusicStatus.LOADING,f.repository.state.sourceStatus)
        f.gateway.sourceReads.single().success(emptyList())
        assertEquals(TripMusicStatus.READY,f.repository.state.sourceStatus)
        assertTrue(f.repository.state.sources.isEmpty())
        assertEquals(listOf(saved),f.repository.state.collection?.items)
        f.own(source)
        assertEquals(source.title,f.repository.state.sources.single().title)
        assertEquals(saved.title,f.repository.state.collection?.items?.single()?.title)
    }

    @Test fun onlyTheCurrentPickerItemWithinTheCollectionCapCanBeAdded()=fixture {f->
        f.ready();f.own(source)
        f.repository.add(source.copy(title="다른 이름"))
        f.repository.add(source.copy(source=source.source.copy(playlistRevision=8)))
        assertTrue(f.gateway.additions.isEmpty())
        f.repository.refresh();f.gateway.reads.last().success(collection(saved).copy(canAdd=false))
        f.repository.add(source)
        assertTrue("The canonical collection cap must disable additions",f.gateway.additions.isEmpty())
    }

    @Test fun oneAddActionMapsToTheServerFieldsLocksDuplicatesAndSupportsExplicitRetry()=fixture {f->
        f.ready();f.own(source)
        f.repository.add(source)
        val request=f.gateway.additions.single()
        assertSame(source.source,request.source)
        assertTrue(request.rights);assertTrue(request.review)
        assertEquals(source.key,f.repository.state.adding)
        f.repository.add(source)
        assertEquals("A repeated click must share the pending operation",1,f.gateway.additions.size)
        request.response.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE))
        assertNull(f.repository.state.adding)
        assertNotNull(f.repository.state.notice)
        assertEquals("A failed operation must not replay itself",1,f.gateway.additions.size)
        f.repository.add(source)
        val retry=f.gateway.additions.last()
        assertSame(source.source,retry.source)
        assertTrue(retry.rights);assertTrue(retry.review)
        val added=saved.copy(id="f".repeat(32),title=source.title,reviewState="quarantined")
        val canonical=collection(saved,added)
        retry.response.success(canonical)
        assertSame(canonical,f.repository.state.collection)
        assertNull(f.repository.state.adding)
        assertEquals(1,f.repository.state.addedSequence)
        assertEquals(2,f.gateway.additions.size)
    }

    @Test fun ownNotifyBeforePostSuccessQueuesAReadWithoutWritingAgain()=fixture {f->
        f.ready();f.own(source);f.repository.add(source)
        val request=f.gateway.additions.single()
        f.gateway.resources("rooms","friends")
        f.repository.add(source);f.repository.refresh()
        assertEquals(1,f.gateway.additions.size)
        assertEquals("Notify must wait for the pending write",1,f.gateway.reads.size)
        val added=saved.copy(id="f".repeat(32),title=source.title)
        request.response.success(collection(saved,added))
        assertEquals(2,f.gateway.reads.size)
        assertEquals(TripMusicStatus.READY,f.repository.state.status)
        assertTrue(f.repository.state.refreshing)
        f.repository.add(source)
        f.gateway.reads.last().success(collection(saved,added))
        assertEquals(listOf(saved,added),f.repository.state.collection?.items)
        assertEquals(1,f.repository.state.addedSequence)
        assertEquals(1,f.gateway.additions.size)
    }

    @Test fun playlistAndDeviceInvalidationsImmediatelyInvalidateOldPickerChoices() {
        for(resource in listOf("playlists","devices"))fixture {f->
            f.ready();f.own(source)
            f.repository.loadSources();val staleRead=f.gateway.sourceReads.last()
            f.gateway.resources(resource)
            assertTrue(staleRead.cancelled)
            assertTrue(f.repository.state.sources.isEmpty())
            assertEquals(TripMusicStatus.IDLE,f.repository.state.sourceStatus)
            staleRead.success(listOf(source))
            assertTrue("A cancelled source reply must not restore a selection",f.repository.state.sources.isEmpty())
            f.gateway.reads.last().success(collection(saved))
            f.repository.add(source)
            assertTrue(f.gateway.additions.isEmpty())
            f.own(source.copy(source=source.source.copy(playlistRevision=8)))
            f.repository.add(source)
            assertTrue(f.gateway.additions.isEmpty())
        }
    }

    @Test fun aStaleSourceConflictReloadsThePickerButNeverReplaysThePost() {
        for(error in listOf(NativeSocialFailure(NativeSocialFailure.Kind.CONFLICT),NativeApiClient.Failure(409,"PLAYLIST_CHANGED")))fixture {f->
            f.ready();f.own(source);f.repository.add(source)
            f.gateway.additions.single().response.failure(error)
            assertEquals(TripMusicStatus.LOADING,f.repository.state.sourceStatus)
            assertTrue(f.repository.state.sources.isEmpty())
            assertNotNull(f.repository.state.notice)
            assertEquals(2,f.gateway.sourceReads.size)
            assertEquals(1,f.gateway.additions.size)
            val updated=source.copy(source=source.source.copy(playlistRevision=8))
            f.gateway.sourceReads.last().success(listOf(updated))
            assertEquals(1,f.gateway.additions.size)
            f.repository.add(source);assertEquals(1,f.gateway.additions.size)
            f.repository.add(updated)
            assertEquals(2,f.gateway.additions.size)
            assertEquals(8L,f.gateway.additions.last().source.playlistRevision)
        }
    }

    @Test fun closingHidingOrInvalidatingIgnoresLatePrivateReadsAndOpenCallbacks() {
        for(stop in listOf<(Fixture)->Unit>({it.repository.close()},{it.repository.setAvailable(false)},{it.gateway.invalidate()})) {
            fixture {f->
                f.ready();val old=f.gateway
                f.repository.loadSources();val sourceRead=old.sourceReads.single()
                f.repository.refresh();val tripRead=old.reads.last()
                stop(f)
                assertTrue(old.closed);assertTrue(tripRead.cancelled);assertTrue(sourceRead.cancelled)
                tripRead.success(collection(saved));sourceRead.success(listOf(source));old.opened()
                assertNull(f.repository.state.collection)
                assertTrue(f.repository.state.sources.isEmpty())
                assertNull(f.repository.state.adding)
                assertTrue(old.additions.isEmpty())
            }
        }
    }

    @Test fun aLatePostAfterClosingHidingOrAccountInvalidationCannotRestorePrivateState() {
        for(stop in listOf<(Fixture)->Unit>({it.repository.close()},{it.repository.setAvailable(false)},{it.gateway.invalidate()})) {
            fixture {f->
                f.ready();f.own(source);f.repository.add(source)
                val old=f.gateway;val write=old.additions.single().response
                stop(f);assertTrue(write.cancelled)
                write.success(collection(saved.copy(title="이전 계정 음악")))
                old.resources("rooms","devices");old.opened()
                assertNull(f.repository.state.collection)
                assertTrue(f.repository.state.sources.isEmpty())
                assertNull(f.repository.state.adding)
                assertEquals(0,f.repository.state.addedSequence)
                assertEquals(1,old.additions.size)
            }
        }
    }

    @Test fun backgroundRefreshKeepsTheListVisibleButBlocksActionsUntilRevalidated()=fixture {f->
        f.ready();f.own(source)
        f.gateway.resources("rooms")
        assertEquals(TripMusicStatus.READY,f.repository.state.status)
        assertEquals(listOf(saved),f.repository.state.collection?.items)
        assertTrue(f.repository.state.refreshing)
        val opened=mutableListOf<String>()
        f.repository.play(saved){opened+=it;TripMusicOpen.OPENED};f.repository.add(source)
        assertTrue(opened.isEmpty());assertTrue(f.gateway.additions.isEmpty())
        f.gateway.reads.last().success(collection(saved))
        assertFalse(f.repository.state.refreshing)
        f.repository.play(saved){opened+=it;TripMusicOpen.OPENED}
        assertEquals(listOf(saved.url),opened)
        assertEquals(saved.id,f.gateway.plays.single().first)
        f.gateway.plays.single().second.success(collection(saved))
        f.gateway.resources("rooms")
        f.gateway.reads.last().failure(NativeSocialFailure(NativeSocialFailure.Kind.FORBIDDEN))
        assertNull(f.repository.state.collection)
        assertFalse(f.repository.state.refreshing)
    }

    @Test fun onlyTheCurrentExactTripItemCanBeOpenedAndAnOpenerFailureIsVisible()=fixture {f->
        f.ready();val opened=mutableListOf<String>()
        val launch: (String)->TripMusicOpen={opened+=it;TripMusicOpen.OPENED}
        f.repository.play(saved.copy(url="https://example.invalid/forged"),launch)
        assertTrue(opened.isEmpty())
        f.repository.refresh();f.repository.play(saved,launch)
        assertTrue("A loading snapshot must not open a retained link",opened.isEmpty())
        val fresh=saved.copy(title="수정된 음악",url="https://music.youtube.com/playlist?list=new")
        f.gateway.reads.last().success(collection(fresh))
        f.repository.play(saved,launch);assertTrue(opened.isEmpty())
        f.gateway.connected=false;f.repository.play(fresh,launch);assertTrue(opened.isEmpty())
        f.gateway.connected=true
        f.repository.play(fresh) {opened+=it;TripMusicOpen.FAILED}
        assertEquals(listOf(fresh.url),opened)
        assertNotNull(f.repository.state.notice)
        assertEquals(listOf(fresh),f.repository.state.collection?.items)
        f.repository.play(fresh,launch)
        assertEquals(listOf(fresh.url,fresh.url),opened)
    }

    private val peer="team-"+"f".repeat(40)
    private fun track(id: Char,owner: String=me)=saved.copy(id=id.toString().repeat(32),title="곡 $id",addedById=owner)
    private fun playing(item: TripSavedPlaylist,by: String=me)=TripMusicPlayback(item.id,by,"일행","2026-11-14T00:00:00+00:00")
    private fun queue(vararg items: TripSavedPlaylist,canReorder: Boolean=false,nowPlaying: List<TripMusicPlayback> = emptyList())=
        TripMusicCollection(trip,items.toList(),200,true,canReorder,nowPlaying,me)

    @Test fun playRecordsTheOpenedItemAndNextFollowsThisCarsPositionInTheTripOrder()=fixture {f->
        val first=track('1');val second=track('2');val third=track('3')
        f.ready(queue(first,second,third,nowPlaying=listOf(playing(third,peer))))
        assertEquals("Another car's playback does not move this car's queue",first,f.repository.nextItem())
        val opened=mutableListOf<String>()
        f.repository.playNext {opened+=it;TripMusicOpen.OPENED}
        assertEquals(listOf(first.url),opened);assertEquals(first.id,f.repository.state.playing)
        f.repository.playNext {opened+=it;TripMusicOpen.OPENED}
        assertEquals("A write in flight blocks a second open",1,opened.size)
        f.gateway.plays.single().second.success(queue(first,second,third,nowPlaying=listOf(playing(first),playing(third,peer))))
        assertNull(f.repository.state.playing)
        assertEquals(first.id to first.id,f.repository.state.collection?.playing?.let {it.first.itemId to it.second.id})
        assertEquals(second,f.repository.nextItem())
        f.repository.play(third) {TripMusicOpen.FAILED}
        assertEquals(1,f.gateway.plays.size);assertNotNull(f.repository.state.notice)
        f.repository.play(third) {opened+=it;TripMusicOpen.OPENED}
        f.gateway.plays.last().second.success(queue(first,second,third,nowPlaying=listOf(playing(third))))
        f.repository.playNext {opened+=it;TripMusicOpen.OPENED}
        assertEquals(2,f.gateway.plays.size)
        assertEquals("다음 음악 링크가 없어요",f.repository.state.notice)
    }

    @Test fun eachOpenFailureShowsItsOwnNoticeAndRecordsNothing()=fixture {f->
        val first=track('1');f.ready(queue(first))
        for(result in listOf(TripMusicOpen.RESTRICTED,TripMusicOpen.NO_HANDLER,TripMusicOpen.FAILED)) {
            f.repository.play(first) {result}
            assertEquals(result.notice,f.repository.state.notice)
            assertNull(f.repository.state.playing)
        }
        assertEquals("정차 중에만 열 수 있어요",TripMusicOpen.RESTRICTED.notice)
        assertEquals("이 차에서 링크를 열 수 있는 앱이 없어요",TripMusicOpen.NO_HANDLER.notice)
        assertTrue(f.gateway.plays.isEmpty())
    }

    @Test fun openerStartsOnlyWhenSetupIsAllowedAndLogsOnlyTheReasonCode()  {
        val logs=mutableListOf<String>();var started=0
        assertEquals(TripMusicOpen.RESTRICTED,openTripMusicLink(false,logs::add) {started++})
        assertEquals("A restricted car never hands the link over",0,started)
        assertEquals(TripMusicOpen.OPENED,openTripMusicLink(true,logs::add) {started++})
        assertEquals(1,started)
        assertEquals(TripMusicOpen.FAILED,openTripMusicLink(true,logs::add) {throw SecurityException("dat=${saved.url}")})
        assertEquals(listOf("trip.music.open: failed reason=restricted","trip.music.open: failed reason=failed"),logs)
        assertTrue(logs.none {it.contains("https") || it.contains("youtube")})
    }

    @Test fun failedPlaybackRecordStillOpensTheTrackAndRereadsTheList()=fixture {f->
        val first=track('1');f.ready(queue(first))
        val opened=mutableListOf<String>()
        f.repository.play(first) {opened+=it;TripMusicOpen.OPENED}
        val reads=f.gateway.reads.size
        f.gateway.plays.single().second.failure(NativeSocialFailure(NativeSocialFailure.Kind.CONFLICT))
        assertEquals(listOf(first.url),opened)
        assertEquals("연 음악을 일행에게 알리지 못했어요",f.repository.state.notice)
        assertEquals(reads+1,f.gateway.reads.size)
    }

    @Test fun queueNextMovesAfterThisCarsTrackOnlyForDjOrOwner()=fixture {f->
        val first=track('1');val second=track('2');val third=track('3')
        f.ready(queue(first,second,third,nowPlaying=listOf(playing(first))))
        f.repository.queueNext(third)
        assertTrue("Members without reorder rights never send a move",f.gateway.moves.isEmpty())
        f.gateway.resources("music");f.gateway.reads.last().success(queue(first,second,third,canReorder=true,nowPlaying=listOf(playing(first))))
        f.repository.queueNext(second)
        assertTrue("Already next is a no-op",f.gateway.moves.isEmpty())
        f.repository.queueNext(third)
        assertEquals(third.id to first.id,f.gateway.moves.single().let {it.first to it.second})
        assertEquals(third.id,f.repository.state.moving)
        f.gateway.moves.single().third.failure(NativeSocialFailure(NativeSocialFailure.Kind.FORBIDDEN))
        assertNull(f.repository.state.moving)
        assertEquals("DJ나 여행 만든 사람만 순서를 바꿀 수 있어요",f.repository.state.notice)
        f.gateway.reads.last().success(queue(first,second,third,canReorder=true))
        f.repository.queueNext(third)
        assertEquals("With nothing playing the item goes first",null,f.gateway.moves.last().second)
    }

    @Test fun onlyOtherMembersNewItemsAreAnnouncedAndTheBannerClearsOnce()=fixture {f->
        val first=track('1',peer);f.ready(queue(first))
        assertNull("The first load never announces",f.repository.state.announcement)
        f.gateway.resources("music");f.gateway.reads.last().success(queue(first,track('2')))
        assertNull("This account's own addition is not announced",f.repository.state.announcement)
        f.gateway.resources("music");f.gateway.reads.last().success(queue(first,track('2'),track('3',peer)))
        val one=checkNotNull(f.repository.state.announcement)
        assertEquals("일행님이 음악을 추천했어요",one.text)
        f.gateway.resources("music");f.gateway.reads.last().success(queue(first,track('2'),track('3',peer),track('4',peer),track('5',peer)))
        val two=checkNotNull(f.repository.state.announcement)
        assertEquals("일행이 음악을 추천했어요",two.text)
        f.repository.dismissAnnouncement(one.sequence)
        assertSame("A stale timer never hides a newer notice",two,f.repository.state.announcement)
        f.repository.dismissAnnouncement(two.sequence)
        assertNull(f.repository.state.announcement)
    }

    @Test fun failedTripReadClearsTheOldRecommendationWithoutWaitingForAuthorityInvalidation() {
        for(kind in listOf(NativeSocialFailure.Kind.NOT_FOUND,NativeSocialFailure.Kind.UNAVAILABLE))fixture {f->
            val first=track('1',peer);val added=track('2',peer)
            f.ready(queue(first))
            f.gateway.resources("music")
            f.gateway.reads.last().success(queue(first,added))
            assertNotNull(f.repository.state.announcement)

            f.gateway.resources("music")
            f.gateway.reads.last().failure(NativeSocialFailure(kind))

            assertTrue("A trip-local failure does not need a global account revocation",f.gateway.current)
            assertEquals(TripMusicStatus.UNAVAILABLE,f.repository.state.status)
            assertNull(f.repository.state.collection)
            assertNull("A discarded trip snapshot must not leave its old recommendation visible",f.repository.state.announcement)
            assertFalse(f.repository.state.refreshing)
            assertTrue(f.gateway.additions.isEmpty())
            assertTrue(f.gateway.plays.isEmpty())
        }
    }

    @Test fun theConnectionStaysOpenWhileAnyScreenLeaseIsVisible()=fixture {f->
        val page=f.repository.lease();val bar=f.repository.lease()
        page.available=true;f.gateway.opened();f.gateway.reads.last().success(collection(saved))
        bar.available=true;page.close()
        assertEquals(TripMusicStatus.READY,f.repository.state.status)
        assertEquals(1,f.gateways.size)
        bar.available=false
        assertEquals(TripMusicStatus.IDLE,f.repository.state.status)
        assertTrue(f.gateway.closed)
    }

    @Test fun deniedOwnPlaylistScopeKeepsTheTripCollectionAndLetsThePickerRetry()=fixture {f->
        f.ready();val tripCollection=f.repository.state.collection
        f.repository.loadSources()
        f.gateway.sourceReads.last().failure(VehicleConnection.ScopeRequired(VehicleConnection.Scope.PLAYLISTS))
        assertEquals(TripMusicStatus.READY,f.repository.state.status)
        assertSame(tripCollection,f.repository.state.collection)
        assertEquals(TripMusicStatus.PERMISSION_REQUIRED,f.repository.state.sourceStatus)
        assertTrue(f.repository.state.sources.isEmpty());assertFalse(f.gateway.closed)
        f.repository.add(source);assertTrue(f.gateway.additions.isEmpty())
        f.own(source)
        assertEquals(TripMusicStatus.READY,f.repository.state.sourceStatus)
        assertSame(tripCollection,f.repository.state.collection)
        assertEquals(listOf(source),f.repository.state.sources)
        assertTrue(f.gateway.additions.isEmpty())
    }
}
