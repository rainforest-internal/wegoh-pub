package io.wegoh.app.nativeauth

internal object NativeConnectionDiagnostics {
    enum class Operation(val wire: String) { INITIALIZE("initialize"), START("start"), CHECK("check") }
    enum class Event(val wire: String) { STARTED("started"), FAILED("failed"), FINISHED("finished") }
    private val stateMessages=setOf("NATIVE_PRIVATE_KEY_MISSING","NATIVE_STATE_KEY_MISSING",
        "NATIVE_STATE_FILE_MISSING","NATIVE_STATE_INVALID","NATIVE_STATE_MIGRATION_INVALID",
        "NATIVE_STATE_MIGRATION_ARCHIVE_CONFLICT","NATIVE_CERTIFICATE_RECOVERY_REQUIRED")

    fun message(event: Event,operation: Operation,stage: VehicleConnection.Stage,error: Throwable?=null): String {
        val prefix="native.connection: ${event.wire} operation=${operation.wire} stage=${stage.name}"
        if(event!=Event.FAILED)return prefix
        val chain=generateSequence(error) {it.cause}.take(8).toList()
        val native=chain.filterIsInstance<NativeApiClient.Failure>().firstOrNull()
        val reason=when {
            chain.any {it is java.net.UnknownHostException}->"dns"
            chain.any {it is javax.net.ssl.SSLException || it is java.security.cert.CertificateException}->"tls"
            chain.any {it is java.net.SocketTimeoutException || it is java.util.concurrent.TimeoutException}->"timeout"
            native!=null->"native_rejected"
            chain.any {it is IllegalStateException && it.message=="NATIVE_JSON_RESPONSE_REQUIRED"}->"invalid_content_type"
            chain.any {it is java.security.KeyStoreException || it is java.security.UnrecoverableKeyException ||
                it is javax.crypto.AEADBadTagException || it is IllegalStateException && it.message in stateMessages}->"state_unavailable"
            else->"unexpected"
        }
        val status=native?.status?.takeIf {it in 100..599}?.let {" status=$it"}.orEmpty()
        return "$prefix reason=$reason$status"
    }
}
