package io.wegoh.app.nativeauth

/**
 * Field diagnostics for functional-permission invalidation and social client endings.
 * Lines carry only fixed reason words, HTTP status, fixed uppercase machine codes and request
 * path templates; identifiers, query values, tokens and server free text never enter them.
 */
internal object NativeFunctionalDiagnostics {
    private val word=Regex("[a-z]+(?:-[a-z]+)*")
    private val hex=Regex("[a-f0-9]{8,}")
    private val reasonWord=Regex("[a-z0-9_.-]{1,48}")

    /** `GET /v1/native/trips/{id}/signals?cursor={v}`: segments that are not plain words become `{id}`. */
    fun pathTemplate(method: String,path: String): String {
        val route=path.substringBefore('?')
        val query=path.substringAfter('?',"")
        val segments=route.split('/').joinToString("/") {segment -> when {
            segment.isEmpty() || segment=="v1"->segment
            segment.length<=40 && word.matches(segment) && !hex.matches(segment)->segment
            else->"{id}"
        }}
        val keys=query.split('&').filter {it.isNotEmpty()}.joinToString("&") {
            val key=it.substringBefore('=')
            (if(key.length<=24 && word.matches(key))key else "{k}")+"={v}"
        }
        val verb=method.takeIf {it in setOf("GET","POST","PUT","PATCH","DELETE")} ?: "OTHER"
        return "$verb $segments"+if(keys.isEmpty())"" else "?$keys"
    }

    /** Request-side scope: the declared diagnostic scope, else the failing path template, else the call phase. */
    fun scope(diagnosticScope: String?,failure: Throwable?,phase: String): String =
        diagnosticScope ?: (failure as? NativeSocialFailure)?.requestTemplate ?: "phase=$phase"

    /** Reason for a failed social call that clears functional authority. */
    fun socialReason(failure: Throwable?): String {
        val value=failure as? NativeSocialFailure ?: return "social_failure"
        if(value.reason==NativeSocialFailure.Reason.REVISION_CHANGED)return "social_revision_changed"
        return "social_"+value.kind.name.lowercase()
    }

    fun invalidated(reason: String,scope: String?,failure: Throwable?,gateCleared: Boolean,clients: Int): String {
        val social=failure as? NativeSocialFailure
        return "native.functional: invalidated reason=${safeReason(reason)} scope=${scope?.let(::safeScope) ?: "none"} "+
            "status=${social?.httpStatus ?: 0} code=${NativeSocialErrorCodec.safeCode(social?.serverErrorCode) ?: "none"} "+
            "gate=${if(gateCleared)"cleared" else "kept"} clients=$clients"
    }

    enum class End(val wire: String) { EXPIRED("expired"), INVALIDATED("invalidated"), TRANSPORT("transport"),
        CLOSE("close"), LOCAL("local") }

    fun ended(client: String,end: End,cause: String?,expiryInSeconds: Long?,suppressed: Int): String =
        "native.social: ended client=${safeReason(client)} reason=${end.wire}"+
            (cause?.let {" cause=${safeReason(it)}"} ?: "")+
            (expiryInSeconds?.let {" expiry_in_s=${it.coerceAtLeast(0)}"} ?: "")+
            (if(suppressed>0)" suppressed=$suppressed" else "")

    private fun safeReason(value: String)=value.takeIf {reasonWord.matches(it)} ?: "other"
    /** Diagnostic scopes are fixed dotted words; templates are built by [pathTemplate]. */
    private fun safeScope(value: String)=value.takeIf {reasonWord.matches(it) ||
        Regex("[A-Z]+ [a-z0-9/{}_?=&.-]{1,160}").matches(it) || Regex("phase=[a-z_]{1,24}").matches(it)} ?: "other"
}

/** At most one line per key per [intervalMillis]; the next admitted line reports how many were skipped. */
internal class DiagnosticRateLimit(private val now: ()->Long,private val intervalMillis: Long=10_000) {
    private val lastAt=HashMap<String,Long>()
    private val skipped=HashMap<String,Int>()
    /** Returns the skipped count to report, or null when this line is suppressed. */
    @Synchronized fun admit(key: String): Int? {
        val time=now()
        if(lastAt[key]?.let {time-it in 0 until intervalMillis}==true) {skipped[key]=(skipped[key] ?: 0)+1;return null}
        lastAt[key]=time
        return skipped.remove(key) ?: 0
    }
}
