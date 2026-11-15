package io.wegoh.app.nativeauth

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import android.util.Base64
import java.io.ByteArrayInputStream
import java.io.File
import java.io.InputStream
import java.io.ByteArrayOutputStream
import java.math.BigInteger
import java.net.Socket
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.Principal
import java.security.PrivateKey
import java.security.Signature
import java.security.cert.CertificateFactory
import java.security.cert.CertPathValidator
import java.security.cert.PKIXParameters
import java.security.cert.TrustAnchor
import java.security.cert.X509Certificate
import java.security.interfaces.RSAPublicKey
import java.util.Date
import javax.net.ssl.SSLEngine
import javax.net.ssl.X509ExtendedKeyManager
import javax.security.auth.x500.X500Principal

/** App-private non-exportable identity, independent from the user's account/session.
 * No UI, global key selection, private-key export, credentials in URLs or logging.
 * Certificate authority anchors must come from reviewed deployment configuration;
 * never trust an authority solely because the enrollment response includes it.
 */
internal class NativeDeviceIdentity(context: Context, private val installationId: String) {
    init { require(Regex("[a-f0-9]{32}").matches(installationId)) }
    private val alias = "wegoh.native.$installationId"
    private val certificateFile = AtomicFile(File(context.noBackupFilesDir, "$alias.chain.pem"))
    private val store get() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    enum class CertificateState { MISSING, NOT_YET_VALID, EXPIRED, RENEWAL_DUE, CONFIGURED }

    /** Caller persists this non-personal random installation ID; never use VIN/email. */
    fun initialize(): Unit = synchronized(KEY_LOCK) {
        check(Build.VERSION.SDK_INT >= 29) { "NATIVE_TLS13_UNSUPPORTED" }
        if (store.containsAlias(alias)) return@synchronized
        check(!certificateFile.baseFile.exists()) { "NATIVE_PRIVATE_KEY_MISSING" }
        val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore")
        generator.initialize(KeyGenParameterSpec.Builder(alias,
            KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
            .setKeySize(2048)
            .setDigests(KeyProperties.DIGEST_NONE, KeyProperties.DIGEST_SHA256,
                KeyProperties.DIGEST_SHA384, KeyProperties.DIGEST_SHA512)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1,
                KeyProperties.SIGNATURE_PADDING_RSA_PSS)
            .setCertificateSubject(X500Principal("CN=WegoH-$installationId"))
            .setCertificateSerialNumber(BigInteger.ONE)
            .setUserAuthenticationRequired(false)
            .build())
        generator.generateKeyPair()
        Unit
    }

    /** Existing durable state must never silently generate a replacement identity. */
    fun requireExisting() {
        check(store.containsAlias(alias)) { "NATIVE_PRIVATE_KEY_MISSING" }
        privateKey(); publicKey()
    }

    private fun privateKey(): PrivateKey =
        (store.getKey(alias, null) as? PrivateKey) ?: error("NATIVE_PRIVATE_KEY_MISSING")

    private fun publicKey() = store.getCertificate(alias)?.publicKey
        ?: error("NATIVE_PRIVATE_KEY_MISSING")

    /** PKCS#10 v1, RSA2048, SHA256withRSA, CN only, no requested extensions. */
    @Synchronized fun csrPem(): String {
        check(Build.VERSION.SDK_INT >= 29) { "NATIVE_TLS13_UNSUPPORTED" }
        val info = Der.sequence(Der.element(0x02, byteArrayOf(0)),
            X500Principal("CN=WegoH-$installationId").encoded, publicKey().encoded,
            Der.element(0xa0, byteArrayOf()))
        val signature = Signature.getInstance("SHA256withRSA").run {
            initSign(privateKey()); update(info); sign()
        }
        val algorithm = byteArrayOf(0x30,0x0d,0x06,0x09,0x2a,0x86.toByte(),0x48,
            0x86.toByte(),0xf7.toByte(),0x0d,0x01,0x01,0x0b,0x05,0x00)
        return pem("CERTIFICATE REQUEST", Der.sequence(info, algorithm,
            Der.element(0x03, byteArrayOf(0) + signature)))
    }

    internal fun installationKeyId(): String = sha256(publicKey().encoded)
    internal fun certificatePem(): String = loadChain().joinToString("") { pem("CERTIFICATE",it.encoded) }
    internal fun signAccess(transcript: ByteArray): String {
        require(transcript.size in 1..8192)
        return NativeAccessCodec.encode(Signature.getInstance("SHA256withRSA").run {
            initSign(privateKey());update(transcript);sign()
        })
    }

    /** Validate before atomic replacement; a failed import leaves prior credentials intact.
     * Anchors are the CLIENT issuer CAs, not the HTTPS server trust store.
     * Revocation remains authoritative at Cloudflare for new TLS handshakes.
     */
    fun installCertificateChain(chainPem: String, issuerAnchors: Set<X509Certificate>,
        now: Date = Date()) = synchronized(KEY_LOCK) {
        require(issuerAnchors.isNotEmpty()) { "NATIVE_CLIENT_ISSUER_REQUIRED" }
        val certificates = parseCertificates(chainPem)
        val leaf = certificates.first()
        require(leaf.publicKey.encoded.contentEquals(publicKey().encoded)) { "NATIVE_CERTIFICATE_KEY_MISMATCH" }
        validateLeaf(leaf, now)
        certificates.forEach { it.checkValidity(now) }
        issuerAnchors.forEach { it.checkValidity(now); require(it.basicConstraints >= 0) }
        val path = certificates.filterNot { c -> issuerAnchors.any { it.encoded.contentEquals(c.encoded) } }
        require(path.isNotEmpty() && path.first() == leaf)
        val parameters = PKIXParameters(issuerAnchors.map { TrustAnchor(it, null) }.toSet()).apply {
            date = now
            isRevocationEnabled = false // No offline claim of Cloudflare revocation knowledge.
        }
        CertPathValidator.getInstance("PKIX").validate(
            CertificateFactory.getInstance("X.509").generateCertPath(path), parameters)
        saveChain(certificates)
    }

    /** Managed CA may issue a leaf without publishing its root. The fingerprint
     * must be from the authenticated issuance response or verified administrator,
     * never calculated from the untrusted import and then passed as its own proof.
     * CONFIGURED does not mean Cloudflare has accepted this certificate.
     */
    fun installManagedCertificate(leafPem: String, expectedSha256: String, now: Date = Date()) = synchronized(KEY_LOCK) {
        require(Regex("[a-f0-9]{64}").matches(expectedSha256))
        val chain = parseCertificates(leafPem)
        require(chain.size == 1)
        val leaf = chain.single()
        require(MessageDigest.isEqual(sha256(leaf.encoded).toByteArray(Charsets.US_ASCII),
            expectedSha256.toByteArray(Charsets.US_ASCII))) { "NATIVE_CERTIFICATE_RECEIPT_MISMATCH" }
        require(leaf.publicKey.encoded.contentEquals(publicKey().encoded)) { "NATIVE_CERTIFICATE_KEY_MISMATCH" }
        validateLeaf(leaf, now)
        saveChain(chain)
    }

    private fun validateLeaf(leaf: X509Certificate, now: Date) {
        require(leaf.subjectX500Principal == X500Principal("CN=WegoH-$installationId")) { "NATIVE_CERTIFICATE_SUBJECT_MISMATCH" }
        val rsa = leaf.publicKey as? RSAPublicKey ?: error("NATIVE_RSA2048_REQUIRED")
        require(rsa.modulus.bitLength() == 2048 && rsa.publicExponent == BigInteger.valueOf(65537))
        require(leaf.basicConstraints == -1) { "NATIVE_LEAF_CERTIFICATE_REQUIRED" }
        requireClientKeyUsage(leaf)
        require(leaf.extendedKeyUsage?.contains("1.3.6.1.5.5.7.3.2") == true) { "NATIVE_CLIENT_AUTH_REQUIRED" }
        leaf.checkValidity(now)
        require(leaf.subjectX500Principal != leaf.issuerX500Principal) { "NATIVE_ISSUED_CERTIFICATE_REQUIRED" }
    }

    private fun saveChain(certificates: List<X509Certificate>) {
        val stream = certificateFile.startWrite()
        try {
            stream.write(certificates.joinToString("") { pem("CERTIFICATE", it.encoded) }.toByteArray(Charsets.US_ASCII))
            certificateFile.finishWrite(stream)
        } catch (failure: Throwable) {
            certificateFile.failWrite(stream); throw failure
        }
    }

    fun certificateState(now: Date = Date(), renewalBeforeMillis: Long = 30L*24*60*60*1000): CertificateState {
        require(renewalBeforeMillis >= 0)
        if (!certificateFile.baseFile.exists()) return CertificateState.MISSING
        val leaf = loadChain().first()
        if (now.before(leaf.notBefore)) return CertificateState.NOT_YET_VALID
        if (!now.before(leaf.notAfter)) return CertificateState.EXPIRED
        return if (leaf.notAfter.time - now.time <= renewalBeforeMillis) CertificateState.RENEWAL_DUE
            else CertificateState.CONFIGURED
    }

    fun certificateSha256(): String = sha256(loadChain().first().encoded)

    @Synchronized fun keyManager(): X509ExtendedKeyManager = keyManagerFor(loadChain())

    /** Memory-only staged leaf, used solely by the exact renewal rebind request.
     * It never replaces the committed certificate file or creates another key. */
    internal fun stagedKeyManager(leafPem: String, expectedSha256: String): X509ExtendedKeyManager {
        val chain=parseCertificates(leafPem)
        require(chain.size==1 && sha256(chain.single().encoded)==expectedSha256)
        validateLeaf(chain.single(),Date())
        return keyManagerFor(chain.toTypedArray())
    }
    private fun keyManagerFor(chain: Array<X509Certificate>): X509ExtendedKeyManager {
        chain.forEach { it.checkValidity() }
        check(chain.first().publicKey.encoded.contentEquals(publicKey().encoded)) { "NATIVE_CERTIFICATE_KEY_MISMATCH" }
        val key = privateKey()
        return object : X509ExtendedKeyManager() {
            private fun matches(type: String?, issuers: Array<out Principal>?): Boolean = type == "RSA" &&
                (issuers.isNullOrEmpty() || chain.any { c -> issuers.any { it == c.issuerX500Principal || it == c.subjectX500Principal } })
            override fun getClientAliases(type: String?, issuers: Array<out Principal>?) =
                if (matches(type, issuers)) arrayOf(alias) else null
            override fun chooseClientAlias(types: Array<out String>?, issuers: Array<out Principal>?, socket: Socket?) =
                if (types?.any { matches(it, issuers) } == true) alias else null
            override fun chooseEngineClientAlias(types: Array<out String>?, issuers: Array<out Principal>?, engine: SSLEngine?) =
                if (types?.any { matches(it, issuers) } == true) alias else null
            override fun getCertificateChain(selected: String?) = if (selected == alias) chain.copyOf() else null
            override fun getPrivateKey(selected: String?) = if (selected == alias) key else null
            override fun getServerAliases(type: String?, issuers: Array<out Principal>?) = null
            override fun chooseServerAlias(type: String?, issuers: Array<out Principal>?, socket: Socket?) = null
        }
    }

    private fun loadChain(): Array<X509Certificate> = synchronized(KEY_LOCK) {
        check(store.containsAlias(alias)) { "NATIVE_PRIVATE_KEY_MISSING" }
        val encoded = certificateFile.openRead().use { input ->
            boundedBytes(input, 32768)
        }
        parseCertificates(String(encoded, Charsets.US_ASCII)).toTypedArray()
    }

    companion object {
        private val KEY_LOCK = Any()
        /** RFC5280/9846: absence is allowed; an explicit usage must permit TLS signing.
         * CA/CRL signing remains forbidden for a client leaf. EKU is checked separately. */
        internal fun requireClientKeyUsage(leaf: X509Certificate) {
            val usage = leaf.keyUsage
            require(usage != null || leaf.getExtensionValue("2.5.29.15") == null) { "NATIVE_DIGITAL_SIGNATURE_REQUIRED" }
            usage?.let { bits ->
                require(bits.getOrNull(0) == true) { "NATIVE_DIGITAL_SIGNATURE_REQUIRED" }
                require(bits.getOrNull(5) != true && bits.getOrNull(6) != true) { "NATIVE_LEAF_CERTIFICATE_REQUIRED" }
            }
        }
        internal fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256")
            .digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
        internal fun parseCertificates(text: String): List<X509Certificate> {
            require(text.length <= 32768)
            val pattern = Regex("-----BEGIN CERTIFICATE-----\\s+([A-Za-z0-9+/=\\r\\n]+)-----END CERTIFICATE-----")
            val matches = pattern.findAll(text).toList()
            require(matches.size in 1..5 && pattern.replace(text, "").isBlank()) { "NATIVE_CERTIFICATE_FORMAT" }
            val factory = CertificateFactory.getInstance("X.509")
            return matches.map { factory.generateCertificate(ByteArrayInputStream(Base64.decode(it.groupValues[1], Base64.DEFAULT))) as X509Certificate }
        }
        private fun pem(kind: String, bytes: ByteArray): String = "-----BEGIN $kind-----\n" +
            Base64.encodeToString(bytes, Base64.NO_WRAP).chunked(64).joinToString("\n") + "\n-----END $kind-----\n"
    }
}

/** Minimal DER writer for bounded CSR construction, never a general ASN.1 parser. */
internal object Der {
    fun sequence(vararg values: ByteArray) = element(0x30, values.fold(byteArrayOf()) { all, v -> all + v })
    fun element(tag: Int, value: ByteArray): ByteArray {
        require(value.size <= 65535)
        val length = when {
            value.size < 128 -> byteArrayOf(value.size.toByte())
            value.size < 256 -> byteArrayOf(0x81.toByte(), value.size.toByte())
            else -> byteArrayOf(0x82.toByte(), (value.size shr 8).toByte(), value.size.toByte())
        }
        return byteArrayOf(tag.toByte()) + length + value
    }
}

internal fun boundedBytes(input: InputStream, maximum: Int): ByteArray {
    val out = ByteArrayOutputStream()
    val buffer = ByteArray(4096)
    while (true) {
        val count = input.read(buffer, 0, minOf(buffer.size, maximum + 1 - out.size()))
        if (count < 0) return out.toByteArray()
        out.write(buffer, 0, count)
        check(out.size() <= maximum) { "NATIVE_RESPONSE_TOO_LARGE" }
    }
}
