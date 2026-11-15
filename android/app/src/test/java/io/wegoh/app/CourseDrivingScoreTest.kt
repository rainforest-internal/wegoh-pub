package io.wegoh.app

import java.io.Closeable
import org.junit.Assert.*
import org.junit.Test

class CourseDrivingScoreTest {
    @Test fun liveScoreUpdatesOnFirstMeasurementAndDeductionsWithoutAServerOrPollingTimer() {
        lateinit var sample: (Long,Double?)->Unit
        val updates=mutableListOf<Int?>()
        val scores=LocalCourseScores({null},{_,_->},{callback->sample=callback;Closeable {}},changed={_,result->updates+=result.score})
        scores.start("a")
        sample(1000,10.0);sample(1200,10.0);sample(1400,10.0);sample(1600,20.0);sample(1800,10.0)
        assertEquals(listOf(null,100,95,90),updates)
    }
    @Test fun countsKeepUpdatingAfterTheScoreReachesZero() {
        lateinit var sample: (Long,Double?)->Unit
        val initial=CourseDrivingResult(accelerations=20,measuredMillis=1000)
        val updates=mutableListOf<CourseDrivingResult>()
        val scores=LocalCourseScores({initial},{_,_->},{callback->sample=callback;Closeable {}},changed={_,result->updates+=result})
        scores.start("a")
        sample(1000,10.0);sample(1200,20.0);sample(1400,10.0)
        assertTrue(updates.all {it.score==0})
        assertEquals(21,updates.last().accelerations)
        assertEquals(1,updates.last().brakings)
        assertTrue(updates.any {it.accelerations==21 && it.brakings==0})
    }
    @Test fun thresholdIncludesTenAndEachDirectionDeductsFive() {
        val score=CourseDrivingScore()
        score.sample(1000,20.0);score.sample(2000,29.9)
        assertEquals(100,score.result.score)
        score.sample(3000,39.9)
        assertEquals(95,score.result.score)
        score.sample(4000,29.9)
        assertEquals(90,score.finish().score)
        assertEquals(1,score.result.accelerations);assertEquals(1,score.result.brakings)
    }
    @Test fun highFrequencyWindowsCountOneContinuousEventThenAllowAnotherAfterSettling() {
        val score=CourseDrivingScore()
        for(index in 0..15)score.sample(1000+index*200L,index*3.0)
        assertEquals(1,score.result.accelerations)
        for(index in 1..6)score.sample(4000+index*200L,45.0)
        score.sample(6200,55.0)
        assertEquals(2,score.result.accelerations)
        assertEquals(90,score.result.score)
    }
    @Test fun duplicatesOutOfOrderMissingAndInvalidReadingsNeverCreateAcceleration() {
        val score=CourseDrivingScore()
        score.sample(1000,0.0);score.sample(1000,100.0);score.sample(900,90.0)
        score.sample(2001,100.0)
        assertEquals(0,score.result.accelerations)
        assertNull(score.result.score)
        score.sample(2100,null);score.sample(2200,Double.NaN)
        score.sample(2300,0.0);score.sample(3300,9.9)
        assertEquals(100,score.result.score);assertTrue(score.result.interrupted)
        score.sample(3400,-10.0);score.sample(3500,50.0)
        assertEquals(0,score.result.brakings)
    }
    @Test fun floorIsZeroAndCompletionFreezesTheResult() {
        val score=CourseDrivingScore()
        for(index in 1..30)score.sample(index*1000L,if(index%2==0)20.0 else 0.0)
        val result=score.finish()
        assertEquals(0,result.score);assertEquals(100,result.deductions)
        score.sample(31000,200.0);assertEquals(result,score.result)
    }
    @Test fun shortWindowCanDetectTenButSlowerChangesDoNotAccumulateOverMoreThanASecond() {
        val score=CourseDrivingScore()
        score.sample(1000,0.0);score.sample(1200,10.0)
        assertEquals(95,score.result.score)
        val slow=CourseDrivingScore()
        for(index in 1..10)slow.sample(index*1000L,index*9.0)
        assertEquals(100,slow.finish().score)
    }
    @Test fun coursesAndAccountsHaveIndependentResultsAndResumeWithoutCrossGapPenalty() {
        val saved=mutableMapOf<String,CourseDrivingResult>()
        val callbacks=mutableListOf<(Long,Double?)->Unit>()
        var closed=0
        fun session()=LocalCourseScores({saved[it]},{key,result->saved[key]=result},{callback->
            callbacks+=callback;Closeable {closed++}
        })
        val scores=session()
        scores.start("account-a-course-a")
        callbacks.last()(1000,0.0);callbacks.last()(2000,10.0)
        scores.start("account-a-course-b")
        callbacks.first()(3000,50.0)
        callbacks.last()(3000,40.0);callbacks.last()(4000,30.0)
        assertEquals(95,scores.finish("account-a-course-b")?.score)
        scores.start("account-b-course-a")
        callbacks.last()(1000,0.0);callbacks.last()(2000,0.0)
        assertEquals(100,scores.finish("account-b-course-a")?.score)
        val restored=session()
        restored.start("account-a-course-a")
        callbacks.last()(10000,90.0);callbacks.last()(11000,90.0)
        val result=restored.finish("account-a-course-a")!!
        assertEquals(95,result.score);assertTrue(result.interrupted)
        assertEquals(1,result.accelerations)
        val count=callbacks.size
        restored.start("account-a-course-a");assertEquals(count,callbacks.size)
        assertTrue(closed>=4)
        restored.reset("account-a-course-a");restored.start("account-a-course-a")
        callbacks.last()(12000,10.0);callbacks.last()(13000,10.0)
        assertEquals(100,restored.finish("account-a-course-a")?.score)
    }
    @Test fun noSpeedOrCorruptStorageDoesNotProduceAPerfectScore() {
        val noSpeed=LocalCourseScores({null},{_,_->},{Closeable {}})
        noSpeed.start("a");assertNull(noSpeed.finish("a")?.score)
        var subscribed=false
        val corrupt=LocalCourseScores({error("corrupt")},{_,_->},{subscribed=true;Closeable {}})
        corrupt.start("a");assertFalse(subscribed);assertNull(corrupt.finish("a"))
    }
    @Test fun forgettingBeforePrivacyDeletionDoesNotRestoreACachedScore() {
        val saved=mutableMapOf<String,CourseDrivingResult>()
        val scores=LocalCourseScores({saved[it]},{key,result->saved[key]=result},{Closeable {}})
        scores.finish("a");assertNotNull(scores.read("a"))
        scores.forget();saved.clear()
        assertNull(scores.read("a"))
    }
}
