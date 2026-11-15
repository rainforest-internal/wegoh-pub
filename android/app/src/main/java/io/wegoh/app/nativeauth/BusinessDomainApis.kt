package io.wegoh.app.nativeauth

import java.io.Closeable

interface DeviceCommandsApi {
    fun readCommandInbox(callback: (Result<BusinessCommandInbox>)->Unit): Closeable
}
internal class NativeDeviceCommandsApi(private val client: NativeSocialClient): DeviceCommandsApi {
    override fun readCommandInbox(callback: (Result<BusinessCommandInbox>)->Unit): Closeable =
    client.call(NativeSocialRequest(setOf(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE),fetch={api,token,permission,account->
        NativeBusinessCodec.commands(api.businessRead("/v1/device/command-inbox",token),permission.deviceId,account)},
        expires={it.commands.minOfOrNull {item->item.expiresAt.toEpochMilli()}}),callback)
}

internal fun NativeSocialClient.readCommandStatuses(callback: (Result<BusinessCommandInbox>)->Unit): Closeable =
    call(NativeSocialRequest(setOf(FunctionalPurpose.DEVICE_COMMANDS_RECEIVE),fetch={api,token,permission,account->
        NativeBusinessCodec.commands(api.businessRead("/v1/device/command-inbox?view=status",token),permission.deviceId,account)
    }),callback)

interface MissionsApi {
    fun readMissions(roomId: String,callback: (Result<BusinessMissionList>)->Unit): Closeable
    fun readTripMissions(tripId: String,callback: (Result<BusinessMissionList>)->Unit): Closeable {
        callback(Result.failure(IllegalStateException("Trip missions unavailable")));return Closeable {}
    }
    fun reportProgress(roomId: String,missionId: String,eventId: String,checkpoint: Int,participationRevision: Int,
        callback: (Result<BusinessMission>)->Unit): Closeable
}
internal class NativeMissionsApi(private val client: NativeSocialClient): MissionsApi {
    override fun readMissions(roomId: String,callback: (Result<BusinessMissionList>)->Unit): Closeable {
    NativeSocialCodec.roomId(roomId)
    return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.MISSIONS_READ),fetch={api,token,_,_->
        NativeBusinessCodec.missions(api.businessRead("/v1/native/rooms/$roomId/missions",token),roomId)},
        expires={it.missions.mapNotNull {item->item.expiresAt?.toEpochMilli()}.minOrNull()}),callback)
}
    override fun readTripMissions(tripId: String,callback: (Result<BusinessMissionList>)->Unit): Closeable {
        NativeApiClient.tripPath(tripId)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.MISSIONS_READ),fetch={api,token,_,_->
            NativeBusinessCodec.tripMissions(api.businessRead("/v1/native/trips/$tripId/missions",token),tripId)}),callback)
    }
    override fun reportProgress(roomId: String,missionId: String,eventId: String,checkpoint: Int,participationRevision: Int,
        callback: (Result<BusinessMission>)->Unit): Closeable {
        val path=NativeApiClient.missionProgressPath(roomId,missionId)
        NativeBusinessCodec.missionProgressRequest(eventId,checkpoint,participationRevision,1)
        return client.call(NativeSocialRequest(setOf(FunctionalPurpose.ROOMS_READ,FunctionalPurpose.MISSIONS_READ,
            FunctionalPurpose.MISSIONS_PROGRESS),mutation=true,fetch={api,token,permission,_->
            NativeBusinessCodec.mission(api.missionProgress(path,
                NativeBusinessCodec.missionProgressRequest(eventId,checkpoint,participationRevision,permission.revision),token),roomId)
                .also {check(it.id==missionId)}
        },expires={it.expiresAt?.toEpochMilli()}),callback)
    }
}

interface RecommendationsApi {
    fun readSettings(callback: (Result<BusinessRecommendationSettings>)->Unit): Closeable
}
internal class NativeRecommendationsApi(private val client: NativeSocialClient): RecommendationsApi {
    override fun readSettings(callback: (Result<BusinessRecommendationSettings>)->Unit): Closeable =
    client.call(NativeSocialRequest(setOf(FunctionalPurpose.RECOMMENDATIONS_USE),fetch={api,token,_,_->
        NativeBusinessCodec.recommendations(api.businessRead("/v1/recommendations/settings",token))}),callback)
}

interface CautionsApi {
    fun readCautions(callback: (Result<BusinessCautionPage>)->Unit): Closeable
}
internal class NativeCautionsApi(private val client: NativeSocialClient): CautionsApi {
    override fun readCautions(callback: (Result<BusinessCautionPage>)->Unit): Closeable =
    client.call(NativeSocialRequest(setOf(FunctionalPurpose.CAUTIONS_READ),fetch={api,token,_,account->
        NativeBusinessCodec.cautions(api.businessRead("/v1/social/cautions",token),account)},
        expires={it.items.mapNotNull {item->item.shareExpiresAt?.toEpochMilli()}.minOrNull()}),callback)
}
