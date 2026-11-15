package io.wegoh.app

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Encrypt before disk IO. Corruption/key loss fails closed, never becomes empty progress. */
class PrivateStore(context: Context, private val alias: String = VehicleAppDependencies.privateStoreAlias(context)) {
    private val directory=context.noBackupFilesDir.resolve("private").apply {mkdirs()}
    private fun file(name: String): AtomicFile {
        require(name.matches(Regex("[a-zA-Z0-9_@.-]{1,160}")) && !name.startsWith("."))
        return AtomicFile(directory.resolve(name))
    }
    private fun key(create: Boolean): SecretKey {
        keys[alias]?.let{return it}
        val store=KeyStore.getInstance("AndroidKeyStore").apply {load(null)}
        (store.getKey(alias,null) as? SecretKey)?.let {keys[alias]=it;return it}
        check(create && names().isEmpty()) {"보호된 기록의 키를 확인할 수 없습니다"}
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build())
        }.generateKey().also {keys[alias]=it}
    }
    @Synchronized fun exists(name: String): Boolean {
        val source=file(name).baseFile
        return source.exists() || java.io.File(source.path+".bak").exists()
    }
    @Synchronized fun read(name: String): String? {
        if(!exists(name))return null
        val source=file(name)
        check(source.baseFile.length()<=1048608)
        val raw=source.openRead().use {input ->
            val out=java.io.ByteArrayOutputStream();val buffer=ByteArray(8192)
            while(true){val count=input.read(buffer);if(count<0)break;check(out.size()+count<=1048608);out.write(buffer,0,count)}
            out.toByteArray()
        }
        check(raw.size in 32..1048608 && raw.copyOfRange(0,4).contentEquals("WG01".toByteArray())) {"보호된 기록이 손상되었습니다"}
        val cipher=Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE,key(false),GCMParameterSpec(128,raw.copyOfRange(4,16)))
        cipher.updateAAD(name.toByteArray(Charsets.UTF_8))
        return cipher.doFinal(raw.copyOfRange(16,raw.size)).toString(Charsets.UTF_8)
    }
    @Synchronized fun write(name: String, value: String) {
        val plain=value.toByteArray(Charsets.UTF_8);require(plain.size<=1048576)
        val cipher=Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE,key(true));cipher.updateAAD(name.toByteArray(Charsets.UTF_8))
        check(cipher.iv.size==12)
        val encrypted="WG01".toByteArray()+cipher.iv+cipher.doFinal(plain)
        val target=file(name);val stream=target.startWrite()
        try {stream.write(encrypted);target.finishWrite(stream)}catch(error: Exception){target.failWrite(stream);throw error}
    }
    @Synchronized fun names(): List<String> = directory.listFiles().orEmpty()
        .filter {it.isFile && !it.name.endsWith(".bak") && !it.name.endsWith(".new")}.map {it.name}
    /** Called only after a separate explicit user confirmation; never on expiry or test teardown. */
    @Synchronized internal fun deleteStoredFiles() {
        val parent=directory.canonicalFile
        directory.listFiles().orEmpty().forEach { item ->
            check(item.isFile && item.canonicalFile.parentFile==parent)
            check(item.delete())
        }
    }
    companion object {private val keys=java.util.concurrent.ConcurrentHashMap<String,SecretKey>()}
}

/** Preserve a verified encrypted recovery copy before approved legacy plaintext cleanup. */
object LegacyArchive {
    fun preserve(store: PrivateStore, kind: String, value: String) {
        val hash=java.security.MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
            .joinToString(""){"%02x".format(it.toInt() and 255)}
        val name="legacy-$kind-$hash"
        if(!store.exists(name))store.write(name,value)
        check(store.read(name)==value) {"이전 기록 복원 검증 실패"}
    }
}

class PrivateSettings(private val context: Context) {
    private val store=PrivateStore(context)
    private fun data(): JSONObject {
        if(!store.exists("settings")) {
            val old=context.getSharedPreferences("pack_selection",Context.MODE_PRIVATE).getString("selected",null)
            if(old!=null)store.write("settings",JSONObject().put("selected",old).toString())
        }
        val result=store.read("settings")?.let(::JSONObject) ?: JSONObject()
        val legacy=context.getSharedPreferences("pack_selection",Context.MODE_PRIVATE)
        if(legacy.contains("selected")) {
            LegacyArchive.preserve(store,"selection",JSONObject().put("selected",legacy.getString("selected",null)).toString())
            check(context.deleteSharedPreferences("pack_selection")) {"이전 선택 정리 실패"}
        }
        return result
    }
    fun selected(): String?=data().optString("selected").takeIf {it.isNotBlank()}
    fun select(key: String?) {
        val next=data() // Preserve decryption/key/legacy checks even for an unchanged selection.
        if(next.opt("selected")==key)return
        next.put("selected",key);store.write("settings",next.toString())
    }
    fun consented()=data().optInt("locationConsentVersion")==2
    fun consent() {val next=data();next.put("locationConsentVersion",2);store.write("settings",next.toString())}
    fun revoke() {val next=data();next.put("locationConsentVersion",0);store.write("settings",next.toString())}
}

/** Explicit local erasure only. Does not claim to erase previously shared server copies. */
object LocalPrivacy {
    fun withdrawAndDelete(context: Context) {
        // Persist refusal first. Partial IO failure must never leave collection enabled.
        PrivateSettings(context).revoke()
        for(name in listOf("pack_selection","pack_progress","visited_places")) {
            context.getSharedPreferences(name,Context.MODE_PRIVATE).edit().clear().commit().also {check(it)}
            context.deleteSharedPreferences(name)
        }
        val legacy=context.filesDir.resolve("packs")
        val parent=legacy.canonicalFile
        legacy.listFiles().orEmpty().forEach {item ->
            check(item.isFile && item.canonicalFile.parentFile==parent)
            check(item.delete())
        }
        PrivateStore(context).deleteStoredFiles()
        PrivateSettings(context).revoke()
    }
}
