package io.wegoh.app

import java.time.Instant
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject

data class CourseLibraryItem(val published: PublishedPack,val tags: List<String>,val starred: Boolean,
    val starCount: Int,val creatorId: String?,val followId: String?,val canFollow: Boolean,val hasCover: Boolean,
    val creatorRank: Int?,val stopNames: List<String>)
data class CourseLibraryNews(val course: CourseLibraryItem,val eventId: String,val approvedAt: Instant,val read: Boolean)
data class CourseLibraryFollowing(val id: String,val name: String?,val creatorId: String?)
data class CourseLibrary(val public: List<CourseLibraryItem>,val saved: List<CourseLibraryItem>,
    val news: List<CourseLibraryNews>,val following: List<CourseLibraryFollowing>,
    val popularTags: List<String>,val followedTags: List<String>,val unreadCount: Int) {
    val readablePacks get()=(public+saved+news.map {it.course}).map {it.published}.distinctBy {it.key}
}

internal object CourseLibraryCodec {
    private val summaryKeys=setOf("id","version","title","author","description","stopCount","stopNames","starred","starCount","tags",
        "canFollow","followId","creatorRank","creatorId","hasCover","checksum")
    private fun exact(value: JSONObject,keys: Set<String>)=check(value.keys().asSequence().toSet()==keys)
    private fun text(value: JSONObject,key: String,max: Int,empty: Boolean=false,multiline: Boolean=false): String {
        val raw=value.get(key)
        check(raw is String && (empty || raw.isNotBlank()) && raw.codePointCount(0,raw.length)<=max &&
            raw.none {it.isISOControl() && !(multiline && it in "\n\r\t")})
        return raw
    }
    private fun count(value: JSONObject,key: String,max: Int=Int.MAX_VALUE): Int {
        val raw=value.get(key);check(raw is Int || raw is Long)
        return (raw as Number).toLong().also {check(it in 0..max.toLong())}.toInt()
    }
    private fun flag(value: JSONObject,key: String): Boolean {val raw=value.get(key);check(raw is Boolean);return raw}
    private fun nullable(value: JSONObject,key: String,max: Int,valid: (String)->Boolean): String? {
        check(value.has(key))
        if(value.isNull(key))return null
        return text(value,key,max).also {check(valid(it))}
    }
    private fun account(value: JSONObject,key: String)=nullable(value,key,45) {Regex("team-[a-f0-9]{40}").matches(it)}
    private fun uuid(value: JSONObject,key: String)=nullable(value,key,36) {runCatching {UUID.fromString(it).toString()==it}.getOrDefault(false)}
    private fun tags(array: JSONArray,limit: Int=8): List<String> {
        check(array.length()<=limit)
        return (0 until array.length()).map {index->
            val raw=array.get(index)
            check(raw is String && raw.codePointCount(0,raw.length) in 1..24 &&
                Regex("[\\p{L}\\p{N}][\\p{L}\\p{M}\\p{N}_-]*").matches(raw))
            raw
        }.also {check(it.distinct().size==it.size)}
    }
    private fun stopNames(array: JSONArray,count: Int): List<String> {
        check(array.length()==count)
        return (0 until array.length()).map {index->
            val raw=array.get(index)
            check(raw is String && raw.isNotBlank() && raw.codePointCount(0,raw.length)<=80 && raw.none {it.isISOControl()})
            raw
        }
    }
    private fun item(value: JSONObject,news: Boolean=false): CourseLibraryItem {
        exact(value,summaryKeys+if(news)setOf("eventId","approvedAt","read") else emptySet())
        val id=text(value,"id",80).also {check(Regex("[a-z0-9][a-z0-9_-]{0,79}").matches(it))}
        val version=count(value,"version").also {check(it>0)}
        val checksum=text(value,"checksum",64).also {check(Regex("[a-f0-9]{64}").matches(it))}
        val pack=PublishedPack(id,version,text(value,"title",100),text(value,"author",80),
            text(value,"description",500,empty=true,multiline=true),count(value,"stopCount",1000).also {check(it>0)},checksum)
        val rank=if(value.isNull("creatorRank"))null else count(value,"creatorRank",3).also {check(it>0)}
        return CourseLibraryItem(pack,tags(value.getJSONArray("tags")),flag(value,"starred"),count(value,"starCount"),
            account(value,"creatorId"),uuid(value,"followId"),flag(value,"canFollow"),flag(value,"hasCover"),rank,
            stopNames(value.getJSONArray("stopNames"),pack.stopCount))
    }
    fun library(value: JSONObject): CourseLibrary {
        exact(value,setOf("public","saved","news","following","popularTags","followedTags","unreadCount"))
        fun items(key: String): List<CourseLibraryItem> {
            val rows=value.getJSONArray(key);check(rows.length()<=1000)
            return (0 until rows.length()).map {item(rows.getJSONObject(it))}.also {list->
                check(list.map {it.published.key}.distinct().size==list.size)
            }
        }
        val public=items("public");val saved=items("saved")
        check(saved.all {it.starred})
        val rawNews=value.getJSONArray("news");check(rawNews.length()<=1000)
        val news=(0 until rawNews.length()).map {index->
            val row=rawNews.getJSONObject(index)
            CourseLibraryNews(item(row,true),text(row,"eventId",20).also {check(Regex("[1-9][0-9]{0,18}").matches(it))},
                Instant.parse(text(row,"approvedAt",40)),flag(row,"read"))
        }.also {check(it.map {row->row.eventId}.distinct().size==it.size)}
        val rawFollowing=value.getJSONArray("following");check(rawFollowing.length()<=1000)
        val following=(0 until rawFollowing.length()).map {index->
            val row=rawFollowing.getJSONObject(index);exact(row,setOf("id","name","creatorId"))
            val id=checkNotNull(uuid(row,"id"))
            val name=nullable(row,"name",80) {true}
            CourseLibraryFollowing(id,name,account(row,"creatorId"))
        }.also {check(it.map {row->row.id}.distinct().size==it.size)}
        val all=public+saved+news.map {it.course}
        check(all.groupBy {it.published.key}.all {(_,rows)->rows.map {it.published.checksum}.distinct().size==1})
        return CourseLibrary(public,saved,news,following,tags(value.getJSONArray("popularTags"),1000),
            tags(value.getJSONArray("followedTags"),1000),count(value,"unreadCount"))
    }
    fun verifyPublicDetail(value: JSONObject,pack: PublishedPack) {
        exact(value,setOf("pack","checksum","tags","hasCover","creatorId","starred","starCount","canFollow","followId"))
        check(text(value,"checksum",64)==pack.checksum)
        val body=value.getJSONObject("pack")
        check(body.get("id")==pack.id && body.get("version")==pack.version)
        tags(value.getJSONArray("tags"));flag(value,"hasCover");account(value,"creatorId")
        flag(value,"starred");count(value,"starCount");flag(value,"canFollow");uuid(value,"followId")
    }
}
