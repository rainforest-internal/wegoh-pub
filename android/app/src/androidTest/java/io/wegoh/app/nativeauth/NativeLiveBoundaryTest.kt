package io.wegoh.app.nativeauth

import android.os.Bundle
import android.test.InstrumentationTestCase
import java.io.File
import javax.net.ssl.SSLHandshakeException

/** External negative boundary only; independent of the positive synthetic fixture. */
class NativeLiveBoundaryTest : InstrumentationTestCase() {
    private fun argument(name: String) = (instrumentation as android.test.InstrumentationTestRunner).arguments.getString(name)
        ?: error("Missing fixture argument")
    private fun identity() = NativeDeviceIdentity(instrumentation.targetContext, argument("installationId"))
    private fun fixture(name: String) = File(instrumentation.targetContext.noBackupFilesDir,
        "nativeauth-test-${argument("installationId")}/$name").readText(Charsets.US_ASCII)
    private fun cert(name: String) = NativeDeviceIdentity.parseCertificates(fixture(name)).single()

    /** One real, unauthenticated GET with a deliberately untrusted synthetic client issuer.
     * No CF issuance, real user token, browser approval or product state is used.
     */
    fun test04LiveNativeBoundary() {
        val id = identity()
        id.installCertificateChain(fixture("client.pem"), setOf(cert("ca.pem")))
        val report = Bundle()
        try {
            NativeApiClient.native(id).account("A".repeat(43))
            fail("Synthetic client issuer must not receive a real account response")
        } catch (denied: NativeApiClient.Failure) {
            assertEquals(403, denied.status)
            report.putString("liveBoundaryOutcome", "http403")
            report.putString("defaultServerTrust", "connection-accepted-before-edge-denial")
            report.putString("tlsPolicy", "TLSv1.3-only-production-factory")
        } catch (rejected: SSLHandshakeException) {
            val causes = generateSequence<Throwable>(rejected) { it.cause }.toList()
            val localTrustError = causes.any { it is java.security.cert.CertificateException ||
                it is java.security.cert.CertPathValidatorException }
            report.putString("liveBoundaryOutcome", if (localTrustError) "local-server-trust-unverified" else "tls-handshake-rejected")
            report.putString("defaultServerTrust", "not-independently-confirmed")
            report.putString("exceptionClasses", causes.joinToString(",") { it.javaClass.name })
            instrumentation.sendStatus(2, report)
            if (localTrustError) throw rejected
            return
        }
        instrumentation.sendStatus(2, report)
    }

}
