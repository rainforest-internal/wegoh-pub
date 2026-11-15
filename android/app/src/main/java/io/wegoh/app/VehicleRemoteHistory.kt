package io.wegoh.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.wegoh.app.nativeauth.VehicleConnection
import io.wegoh.app.nativeauth.VehicleClimateNativeTransport
import org.json.JSONObject

internal enum class VehicleRemoteResult(val label: String) {
    QUEUED("대기 중"), DELIVERED("전달됨"), RECEIVED("수신됨"), PROCESSING("처리 중"),
    APPLIED("적용됨"), DRIVING_BLOCKED("주행 중 제한"), REJECTED("요청 거절됨"),
    TIMED_OUT("시간 초과"), UNKNOWN("적용 여부 미확인"), UNAVAILABLE("연결 확인 필요")
}

internal fun vehiclePendingEntries(inbox: VehicleClimateNativeTransport.Inbox,now: Long,
    senderName: (String)->String?,allowed: Map<String,String> = TRUSTED_CLIMATE_ACTIONS.values.associate {it.id to it.revision}): List<VehicleRemoteEntry> {
    val serverNow=inbox.serverNowMillis ?: System.currentTimeMillis()
    return inbox.requests.mapNotNull {request->
        if(!request.friendRemote || allowed[request.capabilityId]!=request.revision.toString() ||
            inbox.descriptors[request.capabilityId]!=request.revision)return@mapNotNull null
        val result=when(request.stage) {
            "queued"->VehicleRemoteResult.QUEUED;"delivered"->VehicleRemoteResult.DELIVERED
            "received"->VehicleRemoteResult.RECEIVED;"sdk-accepted"->VehicleRemoteResult.PROCESSING
            else->return@mapNotNull null
        }
        val age=(serverNow-request.createdAtMillis).coerceIn(0,now)
        val remaining=request.expiresAtMillis?.let {(it-serverNow).coerceIn(0,300_000)} ?: 30_000L
        VehicleRemoteEntry(request.requesterId?.let(senderName) ?: "친구",inbox.labels[request.capabilityId] ?: "리모컨 조작",
            result,now-age,result==VehicleRemoteResult.PROCESSING,request.id,now+remaining)
    }
}

internal class VehicleRemoteEntry(val sender: String,val action: String,val result: VehicleRemoteResult,
    val completedAtElapsedMillis: Long,val mayHaveExecuted: Boolean,val requestId: String?=null,
    val expiresAtElapsedMillis: Long=Long.MAX_VALUE) {
    val pending get()=result in setOf(VehicleRemoteResult.QUEUED,VehicleRemoteResult.DELIVERED,VehicleRemoteResult.RECEIVED,VehicleRemoteResult.PROCESSING)
    fun visibleAt(now: Long)=!pending || now<expiresAtElapsedMillis
    val resultLabel: String get()=if(!pending && mayHaveExecuted && result!=VehicleRemoteResult.APPLIED && result!=VehicleRemoteResult.UNKNOWN)
        "${result.label}\n적용 여부 미확인" else result.label
    fun relativeTime(nowElapsedMillis: Long): String {
        val minutes=(nowElapsedMillis-completedAtElapsedMillis).coerceAtLeast(0)/60_000
        return if(minutes==0L)"방금" else "${minutes}분 전"
    }
    override fun toString()="VehicleRemoteEntry(redacted)"
}

internal class VehicleRemoteHistory(private val nowElapsedMillis: ()->Long,
    private val currentBoundary: ()->VehicleConnection.DataBoundary?) {
    class Token internal constructor()
    private data class Snapshot(val boundary: VehicleConnection.DataBoundary?=null,val token: Token?=null,
        val entries: List<VehicleRemoteEntry> = emptyList(),val pending: List<VehicleRemoteEntry> = emptyList())
    private var snapshot by mutableStateOf(Snapshot())
    @Synchronized fun refreshBoundary(): VehicleConnection.DataBoundary? {
        val current=currentBoundary()
        if(current!=snapshot.boundary)snapshot=Snapshot(current,current?.let {Token()})
        return current
    }
    @Synchronized fun captureToken(revision: Long?=null): Token? {
        refreshBoundary()
        return snapshot.token.takeIf {revision==null || snapshot.boundary?.revision==revision}
    }
    @Synchronized fun entriesFor(boundary: VehicleConnection.DataBoundary?): List<VehicleRemoteEntry> {
        val saved=snapshot
        return if(boundary!=null && boundary==saved.boundary && boundary==currentBoundary())
            saved.pending.filter {it.visibleAt(nowElapsedMillis())}+saved.entries else emptyList()
    }
    @Synchronized fun pending(token: Token?,entries: List<VehicleRemoteEntry>) {
        refreshBoundary()
        if(token==null || token!==snapshot.token)return
        val completed=snapshot.entries.mapNotNull {it.requestId}.toSet()
        snapshot=snapshot.copy(pending=entries.filter {it.pending && it.requestId!=null && it.requestId !in completed}
            .distinctBy {it.requestId}.take(100))
    }
    @Synchronized fun advance(token: Token?,id: String,senderName: String?,action: String,result: VehicleRemoteResult,deadline: Long) {
        refreshBoundary()
        if(token==null || token!==snapshot.token || snapshot.entries.any {it.requestId==id})return
        val old=snapshot.pending.firstOrNull {it.requestId==id}
        val entry=VehicleRemoteEntry(senderName?.trim()?.takeIf {it.isNotEmpty()} ?: old?.sender ?: "친구",action,result,
            old?.completedAtElapsedMillis ?: nowElapsedMillis(),result==VehicleRemoteResult.PROCESSING,id,deadline)
        snapshot=snapshot.copy(pending=listOf(entry)+snapshot.pending.filterNot {it.requestId==id})
    }
    @Synchronized fun clearPending(token: Token?)=pending(token,emptyList())
    @Synchronized fun record(token: Token?,senderName: String?,action: String,result: VehicleRemoteResult,mayHaveExecuted: Boolean=false,requestId: String?=null) {
        refreshBoundary()
        if(token==null || token!==snapshot.token)return
        val sender=senderName?.trim()?.takeIf {it.isNotEmpty()} ?: "친구"
        snapshot=snapshot.copy(entries=(listOf(VehicleRemoteEntry(sender,action,result,nowElapsedMillis(),mayHaveExecuted,requestId))+
            snapshot.entries.filterNot {requestId!=null && it.requestId==requestId}).take(5),pending=snapshot.pending.filterNot {requestId!=null && it.requestId==requestId})
    }
}

internal fun vehicleRemoteResult(outcome: VehicleCommandOutcome,drivingBlocked: Boolean=false): VehicleRemoteResult=when {
    outcome.state==VehicleCommandState.TARGET_CONFIRMED->VehicleRemoteResult.APPLIED
    outcome.reason==VehicleFailure.TIMEOUT->VehicleRemoteResult.TIMED_OUT
    outcome.mayHaveExecuted || outcome.state==VehicleCommandState.UNKNOWN->VehicleRemoteResult.UNKNOWN
    outcome.reason==VehicleFailure.DRIVING_RESTRICTED || drivingBlocked->VehicleRemoteResult.DRIVING_BLOCKED
    outcome.reason==VehicleFailure.DISCONNECTED->VehicleRemoteResult.UNAVAILABLE
    else->VehicleRemoteResult.REJECTED
}

/** Server reason for a `rejected` ACK; the phone and every vehicle screen read the same value. */
internal const val DRIVING_RESTRICTED_REASON="driving-restricted"
internal fun vehicleRejectionEvidence(result: VehicleRemoteResult): JSONObject=
    if(result==VehicleRemoteResult.DRIVING_BLOCKED)JSONObject().put("reason",DRIVING_RESTRICTED_REASON) else JSONObject()

internal fun vehicleRemoteAction(target: ClimateTarget): String {
    fun seat(value: VehicleSeat)=when(value) {
        VehicleSeat.ROW_1_LEFT->"운전석"
        VehicleSeat.ROW_1_CENTER->"앞좌석 가운데"
        VehicleSeat.ROW_1_RIGHT->"조수석"
        VehicleSeat.ROW_2_LEFT->"2열 왼쪽"
        VehicleSeat.ROW_2_CENTER->"2열 가운데"
        VehicleSeat.ROW_2_RIGHT->"2열 오른쪽"
        VehicleSeat.ROW_3_LEFT->"3열 왼쪽"
        VehicleSeat.ROW_3_CENTER->"3열 가운데"
        VehicleSeat.ROW_3_RIGHT->"3열 오른쪽"
    }
    fun window(value: VehicleWindow)=when(value) {
        VehicleWindow.ROW_1_LEFT->"운전석"
        VehicleWindow.ROW_1_RIGHT->"조수석"
        VehicleWindow.ROW_2_LEFT->"2열 왼쪽"
        VehicleWindow.ROW_2_RIGHT->"2열 오른쪽"
    }
    fun switch(value: Boolean)=if(value)"켜기" else "끄기"
    fun level(value: Int)=if(value==0)"끄기" else "${value}단계"
    return when(target) {
        is ClimateTarget.Celsius->"${seat(target.seat)} 설정 온도 ${target.value.toString().removeSuffix(".0")}°C"
        is ClimateTarget.Fan->"${seat(target.seat)} 바람 세기 ${level(target.value)}"
        is ClimateTarget.GlobalPower->"공조 ${switch(target.enabled)}"
        is ClimateTarget.Ac->"${seat(target.seat)} 에어컨 ${switch(target.value)}"
        is ClimateTarget.AirCleaner->"${seat(target.seat)} 공기 청정 ${switch(target.value)}"
        is ClimateTarget.SeatHeat->"${seat(target.seat)} 시트 열선 ${level(target.value)}"
        is ClimateTarget.SeatVentilation->"${seat(target.seat)} 시트 통풍 ${level(target.value)}"
        is ClimateTarget.WindowPosition->"${window(target.window)} 창문 ${target.value}%"
        is ClimateTarget.CabinLight->"실내등 ${switch(target.value)}"
        is ClimateTarget.ReadingLight->"${seat(target.seat)} 독서등 ${switch(target.value)}"
        is ClimateTarget.AmbientLight->"${seat(target.seat)} 무드등 ${switch(target.value)}"
    }
}
