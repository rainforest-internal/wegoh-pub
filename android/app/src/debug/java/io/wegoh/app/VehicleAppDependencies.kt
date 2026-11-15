package io.wegoh.app

import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.os.Process
import android.system.Os
import android.system.OsConstants
import io.wegoh.app.nativeauth.NativeDeviceIdentity
import io.wegoh.app.nativeauth.StrictNativeJson
import io.wegoh.app.nativeauth.VehicleConnection
import java.io.File
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import org.json.JSONObject

internal object VehicleAppDependencies {
    private data class Configuration(val profile: String,val port: Int,val eventsPort: Int,val ca: X509Certificate)
    private var configuration: Configuration? = null
    private var used = false

    @Synchronized fun configure(context: Context,intent: Intent) {
        if(!intent.getBooleanExtra("wegoh.local_api_testing",false)) {
            check(configuration==null) {"LOCAL_QA_FRESH_PROCESS_REQUIRED"}
            return
        }
        val file=File(context.noBackupFilesDir,"local-api-qa/bootstrap.json")
        val stat=Os.lstat(file.path)
        check(OsConstants.S_ISREG(stat.st_mode) && stat.st_uid==Process.myUid() &&
            (stat.st_mode and 0x1ff)==0x180 && file.canonicalFile==file.absoluteFile && stat.st_size in 1L..16384L) {"LOCAL_QA_PRIVATE_BOOTSTRAP_REQUIRED"}
        val raw=file.readBytes();check(raw.size<=16384)
        val value=StrictNativeJson.parseBusiness(raw,16384)
        check(value.keys().asSequence().toSet()==setOf("format","synthetic","profile","port","eventsPort","caPem","caSha256")) {"LOCAL_QA_BOOTSTRAP_INVALID"}
        bootstrapInteger(value,"format",1,1)
        check(value.get("synthetic")==true) {"LOCAL_QA_SYNTHETIC_REQUIRED"}
        val profile=value.getString("profile")
        check(Regex("local_qa_[a-f0-9]{24}").matches(profile)) {"LOCAL_QA_PROFILE_INVALID"}
        val port=bootstrapInteger(value,"port",1024,65535)
        val eventsPort=bootstrapInteger(value,"eventsPort",1024,65535)
        val pem=value.getString("caPem").toByteArray(Charsets.US_ASCII)
        val certificates=CertificateFactory.getInstance("X.509").generateCertificates(pem.inputStream())
        check(certificates.size==1) {"LOCAL_QA_CA_INVALID"}
        val ca=certificates.single() as X509Certificate
        ca.checkValidity();check(ca.basicConstraints>=0 && NativeDeviceIdentity.sha256(ca.encoded)==value.getString("caSha256")) {"LOCAL_QA_CA_INVALID"}
        val next=Configuration(profile,port,eventsPort,ca)
        check(!used || configuration==next) {"LOCAL_QA_FRESH_PROCESS_REQUIRED"}
        configuration=next
    }

    internal fun bootstrapInteger(value: JSONObject,key: String,minimum: Int,maximum: Int): Int {
        val raw=value.get(key)
        check(raw is Int || raw is Long) {"LOCAL_QA_INTEGER_INVALID"}
        return (raw as Number).toLong().also {
            check(it in minimum.toLong()..maximum.toLong()) {"LOCAL_QA_INTEGER_INVALID"}
        }.toInt()
    }

    @Synchronized fun connection(context: Context): VehicleConnection {
        used=true
        return configuration?.let {VehicleConnection.synthetic(context,it.profile,it.port,it.ca,it.eventsPort)} ?: VehicleConnection(context)
    }
    @Synchronized fun controller(app: WegoApplication): WegoController {
        used=true
        return WegoController(configuration?.let {QaContext(app,it.profile)} ?: app,app)
    }
    fun privateStoreAlias(context: Context)=(context as? QaContext)?.let {"wegoh.private.v1.${it.profile}"} ?: "wegoh.private.v1"
    fun checkForUpdates()=configuration==null
    fun preferenceName(name: String)=configuration?.let {"${it.profile}.$name"} ?: name

    internal class QaContext(base: Context,val profile: String): ContextWrapper(base) {
        override fun getApplicationContext(): Context=this
        private fun directory(kind: String)=File(baseContext.noBackupFilesDir,"local-api-qa/$profile/$kind").apply {check(mkdirs() || isDirectory)}
        override fun getFilesDir()=directory("files")
        override fun getNoBackupFilesDir()=directory("no-backup")
        override fun getCacheDir()=directory("cache")
        override fun getSharedPreferences(name: String,mode: Int)=baseContext.getSharedPreferences("$profile.$name",mode)
        override fun deleteSharedPreferences(name: String)=baseContext.deleteSharedPreferences("$profile.$name")
    }
}
