package io.wegoh.app

import android.content.Context
import org.json.JSONObject

internal fun courseScoreKey(vararg parts: String)=java.security.MessageDigest.getInstance("SHA-256")
    .digest(org.json.JSONArray(parts.toList()).toString().toByteArray(Charsets.UTF_8))
    .joinToString("") {"%02x".format(it.toInt() and 255)}

internal fun localCourseScoreKey(owner: CourseOwner,pack: DrivePack)=courseScoreKey(
    if(owner is CourseOwner.Account)owner.storageKey else "local",pack.key)

internal fun vehicleCourseScores(context: Context,
    changed: (String,CourseDrivingResult)->Unit = {_,_->},
    observe: ((Long,Double?)->Unit)->java.io.Closeable = {callback->CourseSpeedObserver(context,callback)}): CourseScores {
    val store=PrivateStore(context)
    return LocalCourseScores(load={key->store.read("course-score-$key")?.let {raw->
        val value=JSONObject(raw)
        check(value.getInt("schema")==1)
        CourseDrivingResult(value.getInt("accelerations"),value.getInt("brakings"),value.getLong("measuredMillis"),
            value.getBoolean("interrupted"),value.getBoolean("completed"))
    }},save={key,result->
        store.write("course-score-$key",JSONObject().put("schema",1).put("accelerations",result.accelerations)
            .put("brakings",result.brakings).put("measuredMillis",result.measuredMillis)
            .put("interrupted",result.interrupted).put("completed",result.completed).toString())
    },observe=observe,nowMillis=android.os.SystemClock::elapsedRealtime,changed=changed)
}
