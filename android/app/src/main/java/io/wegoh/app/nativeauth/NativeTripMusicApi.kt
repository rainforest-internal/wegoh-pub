package io.wegoh.app.nativeauth

import java.io.Closeable
import java.net.URI
import org.json.JSONObject

data class TripSavedPlaylist(val id: String,val title: String,val url: String,val addedById: String,
    val addedByName: String,val reviewState: String) {
    override fun toString()="TripSavedPlaylist(redacted)"
}

/** A trip playlist item that one member's vehicle opened most recently. Not the external player's live state. */
data class TripMusicPlayback(val itemId: String,val startedById: String,val startedByName: String,val startedAt: String) {
    override fun toString()="TripMusicPlayback(redacted)"
}

data class TripMusicCollection(val tripId: String,val items: List<TripSavedPlaylist>,val limit: Int,val canAdd: Boolean,
    val canReorder: Boolean=false,val nowPlaying: List<TripMusicPlayback> = emptyList(),val viewerId: String?=null) {
    override fun toString()="TripMusicCollection(redacted)"
    /** What this vehicle's account opened last, so "next" continues this car's queue. */
    val mine get()=nowPlaying.firstOrNull {it.startedById==viewerId}
    /** This car's playback first, otherwise the latest one any member's car opened. */
    val playing get()=(mine ?: nowPlaying.firstOrNull())?.let {playback->items.firstOrNull {it.id==playback.itemId}?.let {playback to it}}
}

data class TripSavedPlaylistSource(val playlistId: String,val playlistRevision: Long,val trackId: String)

interface TripMusicApi {
    fun read(tripId: String,callback: (Result<TripMusicCollection>)->Unit): Closeable
    fun add(tripId: String,source: TripSavedPlaylistSource,rightsConfirmed: Boolean,reviewConsent: Boolean,
        callback: (Result<TripMusicCollection>)->Unit): Closeable
    fun play(tripId: String,itemId: String,callback: (Result<TripMusicCollection>)->Unit): Closeable
    fun move(tripId: String,itemId: String,afterId: String?,callback: (Result<TripMusicCollection>)->Unit): Closeable
}

internal class NativeTripMusicApi(private val client: NativeSocialClient): TripMusicApi {
    override fun read(tripId: String,callback: (Result<TripMusicCollection>)->Unit): Closeable = client.call(
        NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),setupRequired=true,diagnosticScope="trip.music.read",fetch={api,token,_,account->
            NativeTripMusicCodec.collection(api.tripSavedPlaylists(tripId,token),tripId,account)}),callback)

    override fun add(tripId: String,source: TripSavedPlaylistSource,rightsConfirmed: Boolean,reviewConsent: Boolean,
        callback: (Result<TripMusicCollection>)->Unit): Closeable {
        val body=NativeTripMusicCodec.addBody(source,rightsConfirmed,reviewConsent)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),
            mutation=true,setupRequired=true,fetch={api,token,permission,account->
                NativeTripMusicCodec.collection(api.addTripSavedPlaylist(tripId,body,permission.revision,token),tripId,account)}),callback)
    }

    override fun play(tripId: String,itemId: String,callback: (Result<TripMusicCollection>)->Unit): Closeable {
        val body=NativeTripMusicCodec.playBody(itemId)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),
            mutation=true,setupRequired=true,fetch={api,token,permission,account->
                NativeTripMusicCodec.collection(api.tripMusicNowPlaying(tripId,body,permission.revision,token),tripId,account)}),callback)
    }

    override fun move(tripId: String,itemId: String,afterId: String?,callback: (Result<TripMusicCollection>)->Unit): Closeable {
        val body=NativeTripMusicCodec.moveBody(itemId,afterId)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),
            mutation=true,setupRequired=true,fetch={api,token,permission,account->
                NativeTripMusicCodec.collection(api.tripSavedPlaylistPosition(tripId,itemId,body,permission.revision,token),tripId,account)}),callback)
    }
}

internal object NativeTripMusicCodec {
    private val ID=Regex("[a-f0-9]{32}")
    private val ACCOUNT=Regex("team-[a-f0-9]{40}")
    private val REVIEW_STATES=setOf("private","quarantined","approved","rejected")

    private fun fields(value: JSONObject,vararg names: String) {check(value.keys().asSequence().toSet()==names.toSet())}
    private fun text(value: JSONObject,key: String,max: Int): String {
        val raw=value.get(key)
        check(raw is String && raw.codePointCount(0,raw.length) in 1..max &&
            raw.any {!it.isWhitespace() && it!='\u0085'} && raw.none {it.isISOControl()})
        return raw
    }
    private fun identifier(value: JSONObject,key: String,account: Boolean=false): String = text(value,key,64).also {
        check((if(account)ACCOUNT else ID).matches(it))
    }
    private fun url(value: JSONObject): String = text(value,"url",2048).also {raw->
        check(raw.none {it.isWhitespace() || it=='\u0085' || it=='\\'})
        val uri=URI(raw)
        check(uri.isAbsolute && uri.scheme.equals("https",true) && !uri.host.isNullOrBlank() &&
            uri.rawUserInfo==null && uri.port in setOf(-1,443))
    }
    fun collection(bytes: ByteArray,tripId: String,accountId: String): TripMusicCollection =
        collection(StrictNativeJson.parseBusiness(bytes,1048576),tripId,accountId)

    fun collection(value: JSONObject,tripId: String,accountId: String): TripMusicCollection {
        check(ID.matches(tripId) && ACCOUNT.matches(accountId))
        fields(value,"tripId","items","limit","canAdd","canReorder","nowPlaying")
        val returnedTrip=identifier(value,"tripId");check(returnedTrip==tripId)
        val rawLimit=value.get("limit");check(rawLimit is Int || rawLimit is Long)
        check((rawLimit as Number).toLong()==200L)
        val canAdd=value.get("canAdd");check(canAdd is Boolean)
        val canReorder=value.get("canReorder");check(canReorder is Boolean)
        val rows=value.getJSONArray("items");check(rows.length()<=200)
        val items=(0 until rows.length()).map {index->
            val row=rows.getJSONObject(index)
            fields(row,"id","title","url","addedBy","reviewState")
            val author=row.getJSONObject("addedBy");fields(author,"id","name")
            val state=text(row,"reviewState",16);check(state in REVIEW_STATES)
            val authorId=identifier(author,"id",true);check(state=="approved" || authorId==accountId)
            TripSavedPlaylist(identifier(row,"id"),text(row,"title",120),url(row),authorId,
                text(author,"name",80),state)
        }
        check(items.map {it.id}.distinct().size==items.size)
        val visible=items.map {it.id}.toSet()
        val playingRows=value.getJSONArray("nowPlaying");check(playingRows.length()<=20)
        val playing=(0 until playingRows.length()).map {index->
            val row=playingRows.getJSONObject(index)
            fields(row,"itemId","startedBy","startedAt")
            val by=row.getJSONObject("startedBy");fields(by,"id","name")
            val item=identifier(row,"itemId");check(item in visible)
            TripMusicPlayback(item,identifier(by,"id",true),text(by,"name",80),text(row,"startedAt",40))
        }
        check(playing.map {it.startedById}.distinct().size==playing.size)
        return TripMusicCollection(returnedTrip,items,200,canAdd,canReorder,playing,accountId)
    }

    fun playBody(itemId: String): JSONObject {
        require(ID.matches(itemId))
        return JSONObject().put("itemId",itemId)
    }

    fun moveBody(itemId: String,afterId: String?): JSONObject {
        require(ID.matches(itemId) && (afterId==null || ID.matches(afterId) && afterId!=itemId))
        return JSONObject().put("afterId",afterId ?: JSONObject.NULL)
    }

    fun addBody(source: TripSavedPlaylistSource,rightsConfirmed: Boolean,reviewConsent: Boolean): JSONObject {
        require(ID.matches(source.playlistId) && ID.matches(source.trackId) && source.playlistRevision in 1..2147483647L)
        require(rightsConfirmed && reviewConsent)
        return JSONObject().put("playlistId",source.playlistId).put("playlistRevision",source.playlistRevision)
            .put("trackId",source.trackId).put("rightsConfirmed",rightsConfirmed).put("reviewConsent",reviewConsent)
    }
}
