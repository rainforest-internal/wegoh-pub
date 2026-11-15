package io.wegoh.app.nativeauth

import android.content.Context
import android.os.Build
import android.os.Looper
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** One app-private, backup-excluded connection record. Missing keys/state fail closed.
 * No account token or PKCE verifier is returned by this storage class.
 */
internal class NativeConnectionState(context: Context, profile: String,
    private val initialInstallationId: String? = null) {
    init { require(Regex("[a-z0-9_-]{1,40}").matches(profile)) }
    private val alias = "wegoh.native.state.$profile"
    private val file = AtomicFile(File(context.noBackupFilesDir, "$alias.enc"))
    private val aad = "WegoH native connection v1:$profile".toByteArray(Charsets.US_ASCII)
    private val store get() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    fun <T> locked(block: () -> T): T {
        check(Looper.myLooper() != Looper.getMainLooper()) { "NATIVE_WORKER_THREAD_REQUIRED" }
        return synchronized(LOCK, block)
    }

    internal fun hasStateOrKey(): Boolean = file.baseFile.exists() || File(file.baseFile.path+".bak").exists() || store.containsAlias(alias)

    fun initialize() = locked {
        check(Build.VERSION.SDK_INT >= 29) { "NATIVE_TLS13_UNSUPPORTED" }
        val present = file.baseFile.exists() || File(file.baseFile.path + ".bak").exists()
        if (present) { check(store.containsAlias(alias)) { "NATIVE_STATE_KEY_MISSING" }; read(); return@locked }
        check(!store.containsAlias(alias)) { "NATIVE_STATE_FILE_MISSING" }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(alias,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true).build())
        generator.generateKey()
        val id = initialInstallationId ?: ByteArray(16).also { SecureRandom().nextBytes(it) }
            .joinToString("") { "%02x".format(it.toInt() and 255) }
        require(Regex("[a-f0-9]{32}").matches(id))
        write(JSONObject().put("version", 1).put("installationId", id).put("phase", "READY"))
    }

    fun read(): JSONObject = locked {
        check(store.containsAlias(alias)) { "NATIVE_STATE_KEY_MISSING" }
        val raw = file.openRead().use { boundedBytes(it, 65536) }
        check(raw.size >= 32 && raw.copyOfRange(0,4).contentEquals(HEADER)) { "NATIVE_STATE_INVALID" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, store.getKey(alias, null) as SecretKey,
            GCMParameterSpec(128, raw.copyOfRange(4,16)))
        cipher.updateAAD(aad)
        val value = JSONObject(String(cipher.doFinal(raw.copyOfRange(16,raw.size)), Charsets.UTF_8))
        check(value.getInt("version") == 1 && Regex("[a-f0-9]{32}")
            .matches(value.getString("installationId"))) { "NATIVE_STATE_INVALID" }
        value
    }

    /** Preserve exact encrypted pre-cutover bytes once; never export plaintext or keys. */
    internal fun preservePrePublicV1(): String = locked {
        val raw=file.openRead().use { boundedBytes(it,65536) }
        val archive=AtomicFile(File(file.baseFile.parentFile,file.baseFile.name+".pre-public1"))
        val present=archive.baseFile.exists() || File(archive.baseFile.path+".bak").exists()
        if(present) {
            check(archive.openRead().use { boundedBytes(it,65536) }.contentEquals(raw)) { "NATIVE_STATE_MIGRATION_ARCHIVE_CONFLICT" }
        } else {
            val stream=archive.startWrite()
            try {stream.write(raw);archive.finishWrite(stream)}
            catch(failure: Throwable) {archive.failWrite(stream);throw failure}
        }
        NativeDeviceIdentity.sha256(raw)
    }

    fun write(value: JSONObject) = locked {
        val raw = value.toString().toByteArray(Charsets.UTF_8)
        require(raw.size <= 60000)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, store.getKey(alias, null) as SecretKey)
        cipher.updateAAD(aad)
        check(cipher.iv.size == 12)
        val stream = file.startWrite()
        try {
            stream.write(HEADER + cipher.iv + cipher.doFinal(raw))
            file.finishWrite(stream)
        } catch (failure: Throwable) { file.failWrite(stream); throw failure }
    }

    companion object {
        private val LOCK = Any()
        private val HEADER = byteArrayOf(0x57,0x4e,0x30,0x31)
    }
}
