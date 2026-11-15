package io.wegoh.app.nativeauth


internal object TripLoadDiagnostics {
    fun message(scope: String,error: Throwable,trip: String?): String {
        val id=trip?.takeIf {Regex("[a-f0-9]{32}").matches(it)}?.take(8) ?: "none"
        val native=error as? NativeSocialFailure
        val status=native?.let {" kind=${it.kind.name.lowercase()} status=${it.httpStatus ?: 0} error_code=${NativeSocialErrorCodec.safeCode(it.serverErrorCode) ?: "none"}"}.orEmpty()
        val field=(error as? NativeTripFieldFailure)?.field
        val reason=if(field==null)error.javaClass.simpleName else "invalid_field"
        return "$scope: load failed reason=$reason trip=$id$status"+field?.let {" field=$it"}.orEmpty()
    }
    fun write(message: String) {WegoLog.w("WegoH",message)}
    /** Decode failures arrive at the repository as a template-less INVALID_RESPONSE, so the precise one is kept here. */
    fun <T> decode(scope: String,trip: String?,request: String?=null,parse: ()->T): T = try {parse()} catch(error: Exception) {
        write(message(scope,error,trip));NativeNetLog.decodeFailed(error)
        ClientDiagnostics.failed(scope,ClientFailure(
            if(error is NativeTripFieldFailure)"invalid_field" else error.javaClass.simpleName,request))
        throw error
    }
    /** Failure an error screen reports; local decode failures were already recorded by [decode]. */
    fun recordFailure(scope: String,error: Throwable) {
        val social=error as? NativeSocialFailure
        if(social?.kind==NativeSocialFailure.Kind.INVALID_RESPONSE && social.requestTemplate==null)return
        ClientDiagnostics.failed(scope,ClientFailure(
            social?.kind?.name?.lowercase() ?: error.javaClass.simpleName,social?.requestTemplate))
    }
}
