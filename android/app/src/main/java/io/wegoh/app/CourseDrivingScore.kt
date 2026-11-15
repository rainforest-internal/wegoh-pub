package io.wegoh.app

import java.io.Closeable

data class CourseDrivingResult(val accelerations: Int=0,val brakings: Int=0,
    val measuredMillis: Long=0,val interrupted: Boolean=false,val completed: Boolean=false) {
    init {require(accelerations>=0 && brakings>=0 && measuredMillis>=0)}
    val deductions get()=minOf(100L,(accelerations.toLong()+brakings)*5).toInt()
    val score: Int? get()=if(measuredMillis>0)100-deductions else null
}

internal class CourseDrivingScore(initial: CourseDrivingResult=CourseDrivingResult()) {
    var result=initial;private set
    private data class Sample(val at: Long,val speed: Double)
    private val window=ArrayDeque<Sample>()
    private var direction=0
    fun unavailable() {window.clear();direction=0;result=result.copy(interrupted=true)}
    fun sample(atMillis: Long,speedKmh: Double?) {
        if(result.completed)return
        if(atMillis<=0 || speedKmh==null || !speedKmh.isFinite() || speedKmh<0) {unavailable();return}
        val last=window.lastOrNull()
        if(last!=null && atMillis<=last.at)return
        if(last!=null && atMillis-last.at>1000)unavailable()
        else if(last!=null)result=result.copy(measuredMillis=result.measuredMillis+(atMillis-last.at))
        while(window.firstOrNull()?.let {atMillis-it.at>1000}==true)window.removeFirst()
        val up=window.any {speedKmh-it.speed>=10.0-0.000001}
        val down=window.any {it.speed-speedKmh>=10.0-0.000001}
        val next=when {
            up && down->when {speedKmh>(last?.speed ?: speedKmh)->1;speedKmh<(last?.speed ?: speedKmh)->-1;else->direction}
            up->1;down->-1;else->0
        }
        if(next!=0 && next!=direction)result=if(next>0)result.copy(accelerations=result.accelerations+1)
            else result.copy(brakings=result.brakings+1)
        direction=next
        window.addLast(Sample(atMillis,speedKmh))
    }
    fun finish(): CourseDrivingResult {result=result.copy(completed=true);window.clear();return result}
}

internal interface CourseScores {
    fun start(key: String)
    fun pause()
    fun finish(key: String): CourseDrivingResult?
    fun read(key: String): CourseDrivingResult?
    fun reset(key: String)
    fun forget()
}

internal class LocalCourseScores(private val load: (String)->CourseDrivingResult?,
    private val save: (String,CourseDrivingResult)->Unit,
    private val observe: ((Long,Double?)->Unit)->Closeable,
    private val nowMillis: ()->Long = {0},
    private val changed: (String,CourseDrivingResult)->Unit = {_,_->}): CourseScores {
    private var key: String?=null
    private var engine: CourseDrivingScore?=null
    private var observation: Closeable?=null
    private var generation=0
    private var lastSampleAt=0L
    private val failed=mutableSetOf<String>()
    private val cached=mutableMapOf<String,CourseDrivingResult?>()
    private fun stored(key: String): CourseDrivingResult? {
        if(!cached.containsKey(key))cached[key]=load(key)
        return cached[key]
    }
    private fun persist(key: String,result: CourseDrivingResult) {
        try {save(key,result);cached[key]=result} catch(error: Exception) {failed.add(key);throw error}
    }
    override fun read(key: String)=if(key in failed)null else runCatching {if(this.key==key)engine?.result else stored(key)}.getOrNull()
    override fun start(key: String) {
        if(this.key==key)return
        pause()
        if(key in failed)return
        val stored=runCatching {stored(key)}.getOrElse {return}
        if(stored?.completed==true)return
        val scorer=CourseDrivingScore(stored ?: CourseDrivingResult())
        if(stored?.measuredMillis?.let {it>0}==true)scorer.unavailable()
        this.key=key;engine=scorer;lastSampleAt=0
        changed(key,scorer.result)
        val token=++generation
        observation=runCatching {observe {time,speed->
            if(token==generation && this.key==key) {
                val before=scorer.result
                scorer.sample(time,speed)
                if(before.score!=scorer.result.score || before.interrupted!=scorer.result.interrupted ||
                    before.accelerations!=scorer.result.accelerations || before.brakings!=scorer.result.brakings)changed(key,scorer.result)
                if(speed!=null && speed.isFinite() && speed>=0 && time>lastSampleAt)lastSampleAt=time
                if(before.accelerations!=scorer.result.accelerations || before.brakings!=scorer.result.brakings)
                    if(runCatching {persist(key,scorer.result)}.isFailure)pause()
            }
        }}.getOrElse {scorer.unavailable();null}
    }
    override fun pause() {
        if(engine?.result?.completed==false)engine?.unavailable()
        generation++;observation?.close();observation=null
        val previous=key;key=null
        val scorer=engine;engine=null
        if(previous!=null && scorer!=null)changed(previous,scorer.result)
        if(previous!=null && scorer!=null)runCatching {persist(previous,scorer.result)}
    }
    override fun finish(key: String): CourseDrivingResult? {
        if(key in failed)return null
        if(this.key==key && lastSampleAt>0 && nowMillis()-lastSampleAt>1000)engine?.unavailable()
        val result=(if(this.key==key)engine?.finish() else runCatching {stored(key)}.getOrElse {return null})
            ?.copy(completed=true) ?: CourseDrivingResult(completed=true)
        if(this.key==key)pause()
        return runCatching {persist(key,result);result}.getOrNull()
    }
    override fun reset(key: String) {
        if(this.key==key)pause()
        persist(key,CourseDrivingResult())
        failed.remove(key)
    }
    override fun forget() {pause();cached.clear();failed.clear()}
}
