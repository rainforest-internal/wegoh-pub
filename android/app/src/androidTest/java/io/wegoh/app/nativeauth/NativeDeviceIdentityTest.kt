package io.wegoh.app.nativeauth

import android.os.Bundle
import android.test.InstrumentationTestCase
import android.util.Base64
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.security.KeyStore
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.Date
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.SSLHandshakeException
import java.net.Socket

/** Synthetic keys/CA only. The host harness supplies a fresh installation ID and
 * public fixture certificates; cleanup touches only this run's test alias/files.
 */
class NativeDeviceIdentityTest : InstrumentationTestCase() {
    private fun argument(name: String) = (instrumentation as android.test.InstrumentationTestRunner).arguments.getString(name)
        ?: error("Missing fixture argument")
    private fun identity() = NativeDeviceIdentity(instrumentation.targetContext, argument("installationId"))
    private fun fixture(name: String) = File(instrumentation.targetContext.noBackupFilesDir,
        "nativeauth-test-${argument("installationId")}/$name").readText(Charsets.US_ASCII)
    private fun cert(name: String) = NativeDeviceIdentity.parseCertificates(fixture(name)).single()
    private fun rejected(block: () -> Unit) {
        try { block(); fail("Input should be rejected") } catch (expected: Exception) { }
    }

    fun test01PrepareCsr() {
        val id = identity()
        id.initialize()
        id.initialize() // Reusing the same installation must never replace its key.
        assertEquals(NativeDeviceIdentity.CertificateState.MISSING, id.certificateState())
        val first = id.csrPem()
        val second = id.csrPem()
        assertEquals(first, second) // Deterministic PKCS1 signature over one public key.
        val out = Bundle().apply { putString("csrPemBase64", Base64.encodeToString(
            first.toByteArray(Charsets.US_ASCII), Base64.NO_WRAP))
            putString("proofSignature", id.signAccess(("WegoH identity fixture\n"+argument("installationId")).toByteArray(Charsets.US_ASCII))) }
        instrumentation.sendStatus(2, out)
    }

    fun test03CleanupOwnAlias() {
        val own = argument("installationId")
        require(Regex("[a-f0-9]{32}").matches(own))
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.deleteEntry("wegoh.native.$own")
        File(instrumentation.targetContext.noBackupFilesDir,"wegoh.native.$own.chain.pem").delete()
        val keys = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        keys.deleteEntry("wegoh.native." + NativeDeviceIdentity.sha256("lost:$own".toByteArray()).take(32))
        for (profile in listOf("session-$own", "lost-$own")) {
            keys.deleteEntry("wegoh.native.state.$profile")
            File(instrumentation.targetContext.noBackupFilesDir, "wegoh.native.state.$profile.enc").delete()
        }
    }

    fun test02CertificateAndTls13() {
        val id = identity()
        val leaf = cert("client.pem")
        val anchor = cert("ca.pem")
        val expected = NativeDeviceIdentity.sha256(leaf.encoded)
        try {
            // Independent host parser verified the emitted PKCS#10 signature and fields.
            id.installCertificateChain(fixture("client.pem"), setOf(anchor))
            assertEquals(expected, id.certificateSha256())
            val manager = id.keyManager()
            val alias = "wegoh.native.${argument("installationId")}"
            assertNull(manager.getPrivateKey(alias)!!.encoded)
            assertEquals("RSA", manager.getPrivateKey(alias)!!.algorithm)
            assertNull(manager.chooseClientAlias(arrayOf("EC"), null, null))
            assertNull(manager.getPrivateKey("another-alias"))
            assertEquals(expected, identity().certificateSha256())
            assertEquals(NativeDeviceIdentity.CertificateState.RENEWAL_DUE, id.certificateState())
            assertEquals(NativeDeviceIdentity.CertificateState.CONFIGURED,
                id.certificateState(renewalBeforeMillis = 0))
            assertEquals(NativeDeviceIdentity.CertificateState.EXPIRED, id.certificateState(leaf.notAfter))
            assertEquals(NativeDeviceIdentity.CertificateState.NOT_YET_VALID,
                id.certificateState(Date(leaf.notBefore.time - 1)))
            rejected { id.installManagedCertificate(fixture("client.pem"), "0".repeat(64)) }
            for (name in listOf("other-key.pem", "expired.pem", "client-ca.pem", "no-eku.pem", "no-usage.pem")) {
                val bad = cert(name)
                rejected { id.installManagedCertificate(fixture(name), NativeDeviceIdentity.sha256(bad.encoded)) }
                assertEquals(expected, id.certificateSha256())
            }
            rejected { id.installCertificateChain(fixture("client.pem"), setOf(cert("other-ca.pem"))) }
            assertEquals(expected, id.certificateSha256())
            id.installManagedCertificate(fixture("client.pem"), expected)
            assertEquals(1, id.keyManager().getCertificateChain(alias)!!.size)
            rejected { NativeDeviceIdentity.parseCertificates("garbage\n" + fixture("client.pem")) }
            rejected { Der.element(0x30, ByteArray(65536)) }
            assertEquals(0x7f, Der.element(0x04, ByteArray(127))[1].toInt() and 255)
            assertEquals(0x81, Der.element(0x04, ByteArray(128))[1].toInt() and 255)
            assertEquals(0x82, Der.element(0x04, ByteArray(256))[1].toInt() and 255)
            rejected { boundedBytes(ByteArrayInputStream(ByteArray(9)), 8) }
            assertEquals(8, boundedBytes(ByteArrayInputStream(ByteArray(8)), 8).size)
            val trusted = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
                load(null); setCertificateEntry("fixture-ca", anchor)
            }
            val managers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply {
                init(trusted)
            }
            val context = SSLContext.getInstance("TLSv1.3").apply {
                init(arrayOf(id.keyManager()), managers.trustManagers, SecureRandom())
            }
            val socket = Tls13SocketFactory(context.socketFactory)
                .createSocket("127.0.0.1", argument("port").toInt()) as SSLSocket
            socket.use {
                it.soTimeout = 10000
                it.sslParameters = it.sslParameters.apply { endpointIdentificationAlgorithm = "HTTPS" }
                it.startHandshake()
                assertEquals("TLSv1.3", it.session.protocol)
                it.outputStream.write("GET /probe HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".toByteArray(Charsets.US_ASCII))
                it.outputStream.flush()
                val response = String(boundedBytes(it.inputStream, 4096), Charsets.UTF_8)
                assertTrue(response.startsWith("HTTP/1.1 200"))
                assertEquals(expected, JSONObject(response.substringAfter("\r\n\r\n")).getString("clientSha256"))
            }
            val wrongHostSocket = Socket("127.0.0.1", argument("port").toInt())
            (Tls13SocketFactory(context.socketFactory).createSocket(wrongHostSocket,
                "not-the-fixture.invalid", argument("port").toInt(), true) as SSLSocket).use {
                it.soTimeout = 5000
                it.sslParameters = it.sslParameters.apply { endpointIdentificationAlgorithm = "HTTPS" }
                try { it.startHandshake(); fail("Wrong server hostname must fail") }
                catch (expectedFailure: SSLHandshakeException) { }
            }
            val pkce = NativeApiClient.Pkce.generate()
            val client = NativeApiClient.syntheticLoopback(argument("port").toInt(), anchor, id)
            try { client.account("synthetic-wrong"); fail("Wrong Bearer must fail") }
            catch (wrongBearer: NativeApiClient.Failure) { assertEquals(401, wrongBearer.status) }
            try {
                NativeApiClient.syntheticLoopback(argument("port").toInt(), cert("other-ca.pem"), id)
                    .account("A".repeat(43))
                fail("Untrusted HTTPS issuer must fail")
            } catch (expectedFailure: SSLHandshakeException) { }
            assertEquals(43, pkce.verifier.length)
            assertEquals(43, pkce.challenge.length)
            assertEquals("Pkce(redacted)", pkce.toString())
            val note = Bundle().apply { putString("result", "keystore-csr-import-tls13-passed") }
            instrumentation.sendStatus(2, note)
        } finally {
            // This exact random alias was created by test01 for this run.
            KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
                .deleteEntry("wegoh.native.${argument("installationId")}")
            File(instrumentation.targetContext.noBackupFilesDir,
                "wegoh.native.${argument("installationId")}.chain.pem").delete()
        }
    }
}

