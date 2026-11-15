package io.wegoh.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Only confirmed pack stops, stored on-device. Sharing requires a separate user action. */
class VisitedPlaces(context: Context,private val namespace: String?=null) {
    init {require(namespace==null || namespace.matches(Regex("[a-f0-9]{64}")))}
    private val record=namespace?.let {"account-$it-visits"} ?: "visits"
    private val context=context.applicationContext
    private val store=PrivateStore(context)
    private val prefs get() = context.getSharedPreferences("visited_places", Context.MODE_PRIVATE)
    fun list(): JSONArray {
        if(namespace!=null)return JSONArray(store.read(record) ?: "[]")
        if(!store.exists("visits") && prefs.contains("places"))store.write("visits",prefs.getString("places","[]")!!)
        val records=JSONArray(store.read("visits") ?: "[]")
        if(prefs.contains("places")) {
            LegacyArchive.preserve(store,"visits",JSONArray(prefs.getString("places","[]")).toString())
            check(context.deleteSharedPreferences("visited_places")) {"이전 방문 정리 실패"}
        }
        return records
    }
    fun record(pack: DrivePack, stop: Stop): Boolean = runCatching {
        val place = JSONObject().put("id", stop.placeId ?: "pack:${pack.id}/${stop.id}")
            .put("provider",stop.placeProvider ?: "drive-pack").put("name",stop.originalPlaceName ?: stop.name)
            .put("address",stop.address).put("latitude",stop.latitude).put("longitude",stop.longitude)
        val next=JSONArray().put(JSONObject().put("id", UUID.randomUUID().toString())
            .put("place",place).put("visitedAt",System.currentTimeMillis()))
        val previous=list()
        check(previous.length()<1000) {"방문 기록 저장 한도"}
        for(index in 0 until previous.length()) next.put(previous.getJSONObject(index))
        store.write(record,next.toString());true
    }.getOrDefault(false)
}
