package io.wegoh.app.nativeauth

import java.io.Closeable

interface SocialOverviewApi {
    fun readOverview(callback: (Result<SocialOverview>)->Unit): Closeable
}
interface RoomsApi {
    fun readRoom(roomId: String,callback: (Result<SocialRoom>)->Unit): Closeable
    fun readMusic(roomId: String,callback: (Result<SocialRoomMusic>)->Unit): Closeable
    fun sendStatusSignal(roomId: String,kind: SocialSignalKind,callback: (Result<SocialSignalReceipt>)->Unit): Closeable
}
interface HistoryApi {
    fun readHistoryPage(cursor: SocialHistoryCursor?=null,callback: (Result<SocialHistoryPage>)->Unit): Closeable
    fun readHistoryItem(itemId: String,callback: (Result<SocialHistoryDetail>)->Unit): Closeable
}

internal class NativeSocialOverviewApi(private val client: NativeSocialClient): SocialOverviewApi {
    override fun readOverview(callback: (Result<SocialOverview>)->Unit): Closeable = client.call(NativeSocialRequest(emptySet(),
        setOf(FunctionalPurpose.FRIENDS_READ,FunctionalPurpose.ROOMS_READ,FunctionalPurpose.HISTORY_READ),diagnosticScope="social.overview",fetch={api,token,permission,_->
            WegoLog.i("WegoH","social.overview: permissions loaded friends_read=${permission.allows(FunctionalPurpose.FRIENDS_READ)} rooms_read=${permission.allows(FunctionalPurpose.ROOMS_READ)} history_read=${permission.allows(FunctionalPurpose.HISTORY_READ)}")
            NativeSocialCodec.overview(api.socialOverview(token),permission).also {
                WegoLog.i("WegoH","social.overview: loaded friends_available=${it.friendsAvailable} friend_count=${it.friends.size}")
            }},expires={it.rooms.minOfOrNull {room->room.expiresAt.toEpochMilli()}}),callback)
}
internal class NativeRoomsApi(private val client: NativeSocialClient): RoomsApi {
    override fun readMusic(roomId: String,callback: (Result<SocialRoomMusic>)->Unit): Closeable {
        NativeSocialCodec.roomId(roomId)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOM_MUSIC_READ),
            fetch={api,token,_,_->NativeSocialCodec.roomMusic(api.businessRead("/v1/social/rooms/$roomId/music",token),roomId)}),callback)
    }
    override fun readRoom(roomId: String,callback: (Result<SocialRoom>)->Unit): Closeable {
        NativeSocialCodec.roomId(roomId)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ),fetch={api,token,permission,_->
            NativeSocialCodec.room(api.socialRoom(roomId,token),roomId,permission)},expires={it.expiresAt.toEpochMilli()}),callback)
    }
    override fun sendStatusSignal(roomId: String,kind: SocialSignalKind,callback: (Result<SocialSignalReceipt>)->Unit): Closeable {
        NativeSocialCodec.roomId(roomId)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT),mutation=true,
            fetch={api,token,permission,_->NativeSocialCodec.signalReceipt(api.socialSignal(roomId,kind,permission.revision,token))}),callback)
    }
}
internal class NativeHistoryApi(private val client: NativeSocialClient): HistoryApi {
    override fun readHistoryItem(itemId: String,callback: (Result<SocialHistoryDetail>)->Unit): Closeable {
        NativeSocialCodec.roomId(itemId)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.HISTORY_READ),fetch={api,token,permission,account->
            NativeSocialCodec.historyDetail(api.businessRead("/v1/social/history/$itemId",token),itemId,permission,account)}),callback)
    }
    override fun readHistoryPage(cursor: SocialHistoryCursor?,callback: (Result<SocialHistoryPage>)->Unit): Closeable =
        client.call(NativeSocialRequest(setOf(FunctionalPurpose.HISTORY_READ),fetch={api,token,permission,account->
            NativeSocialCodec.historyPage(api.socialHistory(cursor?.encoded,token),permission,account)}),callback)
}

interface FriendsApi {
    fun respond(target: String,accept: Boolean,callback: (Result<Unit>)->Unit): Closeable
    fun remove(target: String,callback: (Result<Unit>)->Unit): Closeable
    fun block(target: String,callback: (Result<Unit>)->Unit): Closeable
}
internal class NativeFriendsApi(private val client: NativeSocialClient): FriendsApi {
    private fun change(target: String,action: String,accept: Boolean?,callback: (Result<Unit>)->Unit): Closeable {
        require(Regex("team-[a-f0-9]{40}").matches(target))
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.FRIENDS_READ,FunctionalPurpose.FRIENDS_MANAGE),mutation=true,
            fetch={api,token,permission,_->
                val response=api.friendChange(target,action,accept,permission.revision,token)
                val expected=when(action){"respond"->if(accept==true)"accepted" else "declined";"remove"->"removed";else->"blocked"}
                check(response.keys().asSequence().toSet()==setOf("status") && response.getString("status")==expected)
                Unit
            }),callback)
    }
    override fun respond(target: String,accept: Boolean,callback: (Result<Unit>)->Unit)=change(target,"respond",accept,callback)
    override fun remove(target: String,callback: (Result<Unit>)->Unit)=change(target,"remove",null,callback)
    override fun block(target: String,callback: (Result<Unit>)->Unit)=change(target,"block",null,callback)
}
