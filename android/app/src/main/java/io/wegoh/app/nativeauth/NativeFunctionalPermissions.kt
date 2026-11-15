package io.wegoh.app.nativeauth

import java.util.Collections

/** Functional consent is separate from the four credential scopes. None is implied. */
enum class FunctionalPurpose(val wire: String) {
    FRIENDS_READ("friends:read"), FRIENDS_MANAGE("friends:manage"),
    ROOMS_READ("rooms:read"), ROOMS_INTERACT("rooms:interact"),
    DRIVING_SCORE_REPORT("driving-score:report"),
    HISTORY_READ("history:read"), HISTORY_WRITE("history:write"),
    ROOM_MUSIC_READ("room-music:read"), ROOM_MUSIC_CONTROL("room-music:control"),
    ROOM_VOICE_RECEIVE("room-voice:receive"), ROOM_VOICE_TRANSMIT("room-voice:transmit"),
    VEHICLE_LOCATION_REPORT("vehicle-location:report"), VEHICLE_VISITS_REPORT("vehicle-visits:report"),
    VEHICLE_REPORTS_READ("vehicle-reports:read"), DEVICE_COMMANDS_RECEIVE("device-commands:receive"),
    DEVICE_COMMANDS_REQUEST("device-commands:request"), MISSIONS_READ("missions:read"),
    MISSIONS_PROGRESS("missions:progress"), RECOMMENDATIONS_USE("recommendations:use"), CAUTIONS_READ("cautions:read");

    companion object {
        internal val accountPurposes = setOf(FRIENDS_READ, FRIENDS_MANAGE, ROOMS_READ, ROOMS_INTERACT,
            HISTORY_READ, MISSIONS_READ, RECOMMENDATIONS_USE, CAUTIONS_READ)
        internal fun fromWire(value: String): FunctionalPurpose = entries.singleOrNull {it.wire==value}
            ?: error("NATIVE_FUNCTIONAL_PERMISSION_INVALID")
    }
}

internal data class FunctionalDisclosure(val version: Int,val sha256: String)
internal data class ScoreReportAuthority(val deviceId: String,val grantId: String)

/** A verified, ephemeral permission snapshot. It cannot approve or extend consent. */
class FunctionalPermissions internal constructor(
    internal val deviceId: String, internal val grantId: String,
    val revision: Long, val expiresAtMillis: Long,
    purposes: Set<FunctionalPurpose>,
    internal val disclosureVersion: Int, internal val disclosureSha256: String,
    val approvedDisclosureVersion: Int?=null
) {
    val approvedPurposes: Set<FunctionalPurpose> = Collections.unmodifiableSet(purposes.toSet())
    internal val disclosure get()=FunctionalDisclosure(disclosureVersion,disclosureSha256)
    fun allows(purpose: FunctionalPurpose): Boolean = purpose in approvedPurposes
    internal fun scoreReportAuthority(): ScoreReportAuthority? = if(approvedPurposes.containsAll(setOf(
        FunctionalPurpose.ROOMS_READ,FunctionalPurpose.ROOMS_INTERACT)))
        ScoreReportAuthority(deviceId,grantId) else null
    override fun toString() = "FunctionalPermissions(redacted)"
}

/** A response/queued action is valid only for the exact snapshot that authorized it. */
internal class FunctionalPermissionGate {
    data class Stamp internal constructor(val generation: Long, val permissions: FunctionalPermissions)
    private var generation=0L
    private var snapshot: FunctionalPermissions?=null

    @Synchronized fun clear() {generation++;snapshot=null}
    @Synchronized fun cached(deviceId: String,grantId: String,now: Long): FunctionalPermissions? = snapshot?.takeIf {
        it.deviceId==deviceId && it.grantId==grantId && now<it.expiresAtMillis
    }
    @Synchronized fun replace(next: FunctionalPermissions): Boolean {
        val previous=snapshot
        if(previous!=null && previous.deviceId==next.deviceId && previous.grantId==next.grantId) {
            check(next.revision>=previous.revision) {"NATIVE_FUNCTIONAL_PERMISSION_STALE"}
            if(next.revision==previous.revision) {
                val before = previous.approvedPurposes - FunctionalPurpose.DEVICE_COMMANDS_RECEIVE
                val after = next.approvedPurposes - FunctionalPurpose.DEVICE_COMMANDS_RECEIVE
                check(next.disclosure==previous.disclosure &&
                    (after == before || after == before + FunctionalPurpose.accountPurposes) &&
                    previous.approvedDisclosureVersion==next.approvedDisclosureVersion &&
                    next.expiresAtMillis==previous.expiresAtMillis) {"NATIVE_FUNCTIONAL_PERMISSION_INVALID"}
            }
        }
        if(previous!=null && previous.deviceId==next.deviceId && previous.grantId==next.grantId &&
            previous.revision==next.revision && previous.expiresAtMillis==next.expiresAtMillis &&
            previous.approvedPurposes==next.approvedPurposes && previous.disclosureVersion==next.disclosureVersion &&
            previous.disclosureSha256==next.disclosureSha256 && previous.approvedDisclosureVersion==next.approvedDisclosureVersion)return false
        generation++;snapshot=next
        return previous!=null
    }
    @Synchronized fun scoreReportAuthority(now: Long): ScoreReportAuthority? =
        snapshot?.takeIf {now<it.expiresAtMillis}?.scoreReportAuthority()
    @Synchronized fun stamp(all: Set<FunctionalPurpose>,any: Set<FunctionalPurpose>,now: Long): Stamp {
        val current=snapshot ?: throw NativeSocialFailure(NativeSocialFailure.Kind.CONSENT_REQUIRED)
        if(now>=current.expiresAtMillis || !current.approvedPurposes.containsAll(all) ||
            (any.isNotEmpty() && any.none {current.allows(it)}))throw NativeSocialFailure(NativeSocialFailure.Kind.CONSENT_REQUIRED)
        return Stamp(generation,current)
    }
    @Synchronized fun stamp(purpose: FunctionalPurpose,now: Long): Stamp {
        val current=snapshot ?: throw FunctionalPermissionRequired(purpose)
        if(now>=current.expiresAtMillis || !current.allows(purpose))throw FunctionalPermissionRequired(purpose)
        return Stamp(generation,current)
    }
    @Synchronized fun current(stamp: Stamp,now: Long): Boolean = stamp.generation==generation &&
        snapshot===stamp.permissions && now<stamp.permissions.expiresAtMillis
}

class FunctionalPermissionRequired(val purpose: FunctionalPurpose) : IllegalStateException("NATIVE_FUNCTIONAL_PERMISSION_REQUIRED")
