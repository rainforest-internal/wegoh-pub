package io.wegoh.app.nativeauth

import org.json.JSONObject

internal object NativeSocialErrorCodec {
    fun safeCode(value: String?): String?=value?.takeIf {Regex("[A-Z][A-Z0-9_]{1,63}").matches(it)}
    fun code(value: JSONObject?): String?=listOf("error","code").firstNotNullOfOrNull {safeCode(value?.opt(it) as? String)}
    /** Client-side cause before HTTP mapping: class name and only a fixed uppercase code, never free text. */
    fun localCause(error: Throwable): String="cause=${error.javaClass.simpleName.ifEmpty {"anonymous"}} code=${safeCode(error.message) ?: "none"}"
    fun fields(error: Throwable): String {
        val failure=error as? NativeSocialFailure
        return "status=${failure?.httpStatus ?: 0} kind=${failure?.kind?.name?.lowercase() ?: "invalid_response"} error_code=${safeCode(failure?.serverErrorCode) ?: "none"}"
    }
    /** 403 codes that reject one feature by business rule; refreshing functional permissions cannot cure them. */
    private val featureLocalForbidden=setOf("VEHICLE_OWNER_REQUIRED")
    /** These trip conflicts use the bare FastAPI detail envelope, not arbitrary display text. */
    private val activeTripConflicts=setOf("TRIP_ALREADY_ACTIVE","TRIP_MEMBER_ALREADY_ACTIVE")
    fun invalidatesAuthority(error: Throwable?): Boolean {
        val failure=error as? NativeSocialFailure ?: return false
        if(failure.reason==NativeSocialFailure.Reason.REVISION_CHANGED)return true
        return when(failure.kind) {
            NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED,NativeSocialFailure.Kind.STALE->true
            NativeSocialFailure.Kind.FORBIDDEN->safeCode(failure.serverErrorCode) !in featureLocalForbidden
            else->false
        }
    }
    fun failure(status: Int,value: JSONObject?,mutation: Boolean,retry: Int?,
        tripVoiceParticipationRead: Boolean=false,requestTemplate: String?=null): NativeSocialFailure {
        // The optional voice endpoint reports disabled service as a bare FastAPI detail.
        if(tripVoiceParticipationRead && !mutation && status==403 && value?.length()==1 &&
            value.opt("detail")=="TRIP_VOICE_UNAVAILABLE")
            return NativeSocialFailure(NativeSocialFailure.Kind.UNAVAILABLE,httpStatus=status,
                retryAfterSeconds=retry,serverErrorCode="TRIP_VOICE_UNAVAILABLE",requestTemplate=requestTemplate)
        val code=code(value) ?: if(status==409 && value?.length()==1)
            (value.opt("detail") as? String)?.takeIf {it in activeTripConflicts} else null
        val changed=code=="FUNCTIONAL_REVISION_CHANGED" || value?.opt("detail")=="FUNCTIONAL_REVISION_CHANGED"
        val kind=when(status) {
            400,422->NativeSocialFailure.Kind.INVALID_RESPONSE
            401->NativeSocialFailure.Kind.AUTHORIZATION_REQUIRED
            403->NativeSocialFailure.Kind.FORBIDDEN
            404->NativeSocialFailure.Kind.NOT_FOUND
            409->NativeSocialFailure.Kind.CONFLICT
            413->NativeSocialFailure.Kind.TOO_LARGE
            429->NativeSocialFailure.Kind.RATE_LIMITED
            else->NativeSocialFailure.Kind.UNAVAILABLE
        }
        return NativeSocialFailure(kind,status,if(changed && status==409)NativeSocialFailure.Reason.REVISION_CHANGED else null,
            mutation,retry,code,requestTemplate)
    }
}
