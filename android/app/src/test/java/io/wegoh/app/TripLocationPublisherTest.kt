package io.wegoh.app

import io.wegoh.app.nativeauth.NativeSocialFailure
import io.wegoh.app.nativeauth.TripLocationFix
import io.wegoh.app.nativeauth.TripLocationShare
import io.wegoh.app.nativeauth.TripLocationTransport
import java.io.Closeable
import org.junit.Assert.*
import org.junit.Test

class TripLocationPublisherTest {
    private val trip = "a".repeat(32)
    private val otherTrip = "b".repeat(32)
    private val share = "c".repeat(32)

    private class Observation(val callback: (TripLocationFix)->Unit, val unavailable: (LocationUnavailableReason)->Unit) {
        var closed = false
        fun emit(fix: TripLocationFix) = callback(fix)
    }

    private class Transport: TripLocationTransport {
        data class Read(val trip: String, val reply: (Result<TripLocationShare>)->Unit) {
            var closed = false
        }
        data class Report(val trip: String, val share: String, val fix: TripLocationFix,
            val reply: (Result<Unit>)->Unit) {
            var closed = false
        }
        val reads = mutableListOf<Read>()
        val reports = mutableListOf<Report>()
        override fun readLocationShare(id: String,callback: (Result<TripLocationShare>)->Unit): Closeable {
            val read = Read(id,callback)
            reads += read
            return Closeable {read.closed=true}
        }
        override fun reportLocation(id: String,shareId: String,fix: TripLocationFix,
            callback: (Result<Unit>)->Unit): Closeable {
            val report = Report(id,shareId,fix,callback)
            reports += report
            return Closeable {report.closed=true}
        }
    }

    private class Fixture: Closeable {
        var now = 1_800_000_000_000L
        val observations = mutableListOf<Observation>()
        val statuses = mutableListOf<String?>()
        val transport = Transport()
        val publisher = TripLocationPublisher(observe={callback,unavailable->
            val observed = Observation(callback,unavailable)
            observations += observed
            Closeable {observed.closed=true}
        },now={now},status=statuses::add)
        fun fix() = TripLocationFix(37.5,127.0,now,8.0)
        override fun close() = publisher.close()
    }

    @Test fun observationWaitsForCurrentTripSharingAndDoesNotStartWhenOff() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            assertTrue(f.observations.isEmpty())
            assertEquals(trip,f.transport.reads.single().trip)
            f.transport.reads.single().reply(Result.success(TripLocationShare(trip,null)))
            assertTrue(f.observations.isEmpty())
            assertTrue(f.transport.reports.isEmpty())
        }
    }

    @Test fun detachStopsObservationAndReopeningUsesFreshSharingEpoch() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val before = f.observations.single()
            before.emit(f.fix())
            assertEquals(share,f.transport.reports.single().share)
            f.publisher.update(null,null)
            assertTrue(before.closed)
            assertTrue(f.transport.reports.single().closed)
            f.now += 10_000
            before.emit(f.fix())
            assertEquals(1,f.transport.reports.size)
            f.publisher.update(trip,f.transport)
            val renewedShare = "d".repeat(32)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,renewedShare)))
            before.emit(f.fix())
            f.observations.last().emit(f.fix())
            assertEquals(listOf(share,renewedShare),f.transport.reports.map {it.share})
        }
    }

    @Test fun replacedTripIgnoresLateSharingReadAndOldObservation() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            val old = f.transport.reads.single()
            f.publisher.update(otherTrip,f.transport)
            assertTrue(old.closed)
            old.reply(Result.success(TripLocationShare(trip,share)))
            assertTrue(f.observations.isEmpty())
            f.transport.reads.last().reply(Result.success(TripLocationShare(otherTrip,share)))
            f.observations.single().emit(f.fix())
            assertEquals(otherTrip,f.transport.reports.single().trip)
            val before = f.observations.single()
            val nextTransport = Transport()
            f.publisher.update(otherTrip,nextTransport)
            assertTrue(before.closed)
            f.now += 10_000
            before.emit(f.fix())
            assertTrue(nextTransport.reports.isEmpty())
        }
    }

    @Test fun keepsOneRequestInFlightAndThrottlesFreshFixes() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val observed = f.observations.single()
            observed.emit(f.fix())
            f.now += 10_000
            observed.emit(f.fix())
            assertEquals(1,f.transport.reports.size)
            f.transport.reports.single().reply(Result.success(Unit))
            observed.emit(f.fix())
            assertEquals(2,f.transport.reports.size)
            f.transport.reports.last().reply(Result.success(Unit))
            f.now += 1
            observed.emit(f.fix())
            assertEquals(2,f.transport.reports.size)
        }
    }

    @Test fun rejectsStaleFutureAndInvalidSdkFixes() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val observed = f.observations.single()
            listOf(
                TripLocationFix(37.5,127.0,f.now-60_001,8.0),
                TripLocationFix(37.5,127.0,f.now+1,8.0),
                TripLocationFix(Double.NaN,127.0,f.now,8.0),
                TripLocationFix(91.0,127.0,f.now,8.0),
                TripLocationFix(37.5,181.0,f.now,8.0),
                TripLocationFix(37.5,127.0,f.now,-1.0),
                TripLocationFix(37.5,127.0,f.now,Double.NaN)
            ).forEach(observed::emit)
            assertTrue(f.transport.reports.isEmpty())
            observed.emit(f.fix())
            assertEquals(f.fix(),f.transport.reports.single().fix)
        }
    }

    @Test fun transportFailurePausesUntilExplicitCloseAndReopen() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val before = f.observations.single()
            before.emit(f.fix())
            f.transport.reports.single().reply(Result.failure(IllegalStateException("unavailable")))
            assertTrue(before.closed)
            f.now += 10_000
            before.emit(f.fix())
            f.publisher.update(trip,f.transport)
            assertEquals(1,f.transport.reads.size)
            assertEquals(1,f.transport.reports.size)
            f.publisher.update(null,null)
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,"d".repeat(32))))
            f.observations.last().emit(f.fix())
            assertEquals(2,f.transport.reports.size)
        }
    }

    @Test fun unavailableSdkLocationShowsFailureAndRequiresExplicitReopen() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val before = f.observations.single()
            before.unavailable(LocationUnavailableReason.ERROR)
            assertTrue(before.closed)
            assertTrue(f.statuses.last()?.contains("확인할 수 없어요")==true)
            before.emit(f.fix())
            f.publisher.update(trip,f.transport)
            assertEquals(1,f.transport.reads.size)
            assertTrue(f.transport.reports.isEmpty())
            f.publisher.update(null,null)
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            f.observations.last().emit(f.fix())
            f.transport.reports.single().reply(Result.success(Unit))
            assertTrue(f.statuses.last()?.contains("공유해요")==true)
        }
    }

    @Test fun emptyFixDoesNotClaimSharingOrTerminateTheRecoverableSubscription() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val observed=f.observations.single()
            observed.unavailable(LocationUnavailableReason.NO_DATA)
            assertFalse(observed.closed)
            assertTrue(f.transport.reports.isEmpty())
            assertTrue(f.statuses.last()?.contains("기다리고 있어요")==true)
            observed.emit(f.fix())
            observed.unavailable(LocationUnavailableReason.NO_DATA)
            f.transport.reports.last().reply(Result.success(Unit))
            assertTrue("An earlier upload acknowledgement must not hide a later empty fix",f.statuses.last()?.contains("기다리고 있어요")==true)
            f.now+=10_000
            observed.emit(f.fix())
            f.transport.reports.last().reply(Result.success(Unit))
            assertTrue(f.statuses.last()?.contains("공유해요")==true)
            assertEquals(1,f.observations.size)
        }
    }

    @Test fun transientFailureRechecksSameShareAndUsesOnlyNewFreshObservation() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val observed=f.observations.single()
            val first=f.fix()
            observed.emit(first)
            f.transport.reports.last().reply(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,httpStatus=503)))
            assertFalse(observed.closed)
            f.publisher.update(trip,f.transport)
            assertEquals(1,f.transport.reads.size)
            f.now+=10_000
            observed.emit(first)
            observed.emit(first.copy(capturedAtMillis=f.now-60_001))
            observed.emit(first.copy(capturedAtMillis=f.now+1))
            assertEquals(1,f.transport.reads.size)
            observed.emit(f.fix())
            assertEquals(2,f.transport.reads.size)
            assertEquals(1,f.transport.reports.size)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            assertEquals(2,f.transport.reports.size)
            assertEquals(f.fix(),f.transport.reports.last().fix)
            f.transport.reports.last().reply(Result.success(Unit))
            assertTrue(f.statuses.last()?.contains("공유해요")==true)
        }
    }

    @Test fun authorizationConflictAndInvalidFailuresNeverAutomaticallyResume() {
        for(kind in listOf(NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,NativeSocialFailure.Kind.FORBIDDEN,
            NativeSocialFailure.Kind.CONFLICT,NativeSocialFailure.Kind.INVALID_RESPONSE,NativeSocialFailure.Kind.CONSENT_REQUIRED)) {
            Fixture().use {f->
                f.publisher.update(trip,f.transport)
                f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
                val observed=f.observations.single()
                observed.emit(f.fix())
                f.transport.reports.last().reply(Result.failure(NativeSocialFailure(kind)))
                assertTrue(observed.closed)
                f.now+=10_000;observed.emit(f.fix())
                assertEquals(1,f.transport.reads.size)
                assertEquals(1,f.transport.reports.size)
            }
        }
    }

    @Test fun transientRecoveryIsBoundedAndChangedShareCannotPublish() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val observed=f.observations.single()
            repeat(4) {attempt->
                observed.emit(f.fix())
                if(attempt>0)f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
                assertEquals(attempt+1,f.transport.reports.size)
                f.transport.reports.last().reply(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,httpStatus=408)))
                f.now+=10_000
            }
            assertTrue(observed.closed)
            observed.emit(f.fix())
            assertEquals(4,f.transport.reports.size)
        }
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val observed=f.observations.single();observed.emit(f.fix())
            f.transport.reports.last().reply(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))
            f.now+=10_000;observed.emit(f.fix())
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,"d".repeat(32))))
            assertTrue(observed.closed)
            assertEquals(1,f.transport.reports.size)
        }
    }

    @Test fun closedRecoveryAndRevokedShareIgnoreLateCallbacks() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val observed=f.observations.single();observed.emit(f.fix())
            f.transport.reports.last().reply(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))
            f.now+=10_000;observed.emit(f.fix())
            assertEquals(2,f.transport.reads.size)
            val pending=f.transport.reads.last()
            f.publisher.update(null,null)
            assertTrue(pending.closed)
            pending.reply(Result.success(TripLocationShare(trip,share)))
            observed.emit(f.fix())
            assertEquals(1,f.transport.reports.size)
        }
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val observed=f.observations.single();observed.emit(f.fix())
            f.transport.reports.last().reply(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE)))
            f.now+=10_000;observed.emit(f.fix())
            assertEquals(2,f.transport.reads.size)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,null)))
            assertTrue(observed.closed)
            assertEquals(1,f.transport.reports.size)
        }
    }

    @Test fun unavailableWithProhibitionStatusDoesNotRetry() {
        for(status in listOf(400,401,403,404,409,429)) {
            Fixture().use {f->
                f.publisher.update(trip,f.transport)
                f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
                val observed=f.observations.single();observed.emit(f.fix())
                f.transport.reports.last().reply(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,httpStatus=status)))
                assertTrue(observed.closed)
                f.now+=10_000;observed.emit(f.fix())
                assertEquals(1,f.transport.reports.size)
                assertEquals(1,f.transport.reads.size)
            }
        }
    }

    @Test fun recoveryHonorsRetryAfterAndRechecksFreshnessAfterAsyncShareRead() {
        Fixture().use {f->
            f.publisher.update(trip,f.transport)
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            val observed=f.observations.single();observed.emit(f.fix())
            f.transport.reports.last().reply(Result.failure(NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,httpStatus=503,retryAfterSeconds=30)))
            f.now+=10_000;observed.emit(f.fix())
            assertEquals(1,f.transport.reads.size)
            f.now+=20_000;observed.emit(f.fix())
            assertEquals(2,f.transport.reads.size)
            f.now+=60_001
            f.transport.reads.last().reply(Result.success(TripLocationShare(trip,share)))
            assertEquals(1,f.transport.reports.size)
            assertTrue(f.statuses.last()?.contains("GPS 위치 시각")==true)
            observed.emit(f.fix())
            assertEquals(2,f.transport.reports.size)
            assertEquals(f.fix(),f.transport.reports.last().fix)
        }
    }
}
