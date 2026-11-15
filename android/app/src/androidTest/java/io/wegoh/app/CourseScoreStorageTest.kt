package io.wegoh.app

import android.os.SystemClock
import android.test.InstrumentationTestCase
import java.io.Closeable

@Suppress("DEPRECATION")
class CourseScoreStorageTest: InstrumentationTestCase() {
    private fun scores(callbacks: MutableList<(Long,Double?)->Unit>)=vehicleCourseScores(instrumentation.targetContext) {callback->
        callbacks.add(callback);Closeable {}
    }
    fun testEncryptedCourseResultsSurviveRecreationAndKeepRawSpeedOutOfStorage() {
        val context=instrumentation.targetContext
        val key=courseScoreKey("score-storage-test",System.nanoTime().toString())
        val callbacks=mutableListOf<(Long,Double?)->Unit>()
        val scores=scores(callbacks)
        scores.start(key)
        val sample=callbacks.last()
        val time=SystemClock.elapsedRealtime()
        sample(time-1000,20.0);sample(time-500,30.0);sample(time,20.0)
        assertEquals(90,scores.finish(key)?.score)
        val restored=scores(callbacks)
        assertEquals(90,restored.read(key)?.score)
        val record=checkNotNull(PrivateStore(context).read("course-score-$key"))
        assertFalse(record.contains("speed"));assertFalse(record.contains("latitude"));assertFalse(record.contains("timestamp"))
        val encrypted=context.noBackupFilesDir.resolve("private/course-score-$key").readBytes()
        assertFalse(encrypted.toString(Charsets.UTF_8).contains("accelerations"))
        restored.reset(key);assertNull(restored.read(key)?.score)
    }
}
