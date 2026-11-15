package io.wegoh.app

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import io.wegoh.app.nativeauth.NativeNetLog

sealed interface AppUpdateResult {
    data object Unknown: AppUpdateResult
    data object Current: AppUpdateResult
    data class Available(val versionCode: Long): AppUpdateResult
}

/** Public release metadata only. This never downloads or installs an APK. */
class AppUpdate(private val base: String=BuildConfig.PACK_API_BASE_URL) {
    fun check(installedVersion: Long, installedCertificates: Set<String>): AppUpdateResult = try {
        if(base.isBlank()) AppUpdateResult.Unknown else {
            val endpoint=DistributionPolicy.updateEndpoint(base)
            val connection=URL(endpoint+"/v1/app-release").openConnection() as HttpURLConnection
            connection.connectTimeout=3000;connection.readTimeout=3000
            connection.instanceFollowRedirects=false
            connection.setRequestProperty("Accept","application/json")
            try {NativeNetLog.traced("GET","/v1/app-release",connection) {net->
                net.status=connection.responseCode
                if(connection.responseCode!=200) AppUpdateResult.Unknown
                else connection.inputStream.use { input ->
                    val bytes=java.io.ByteArrayOutputStream()
                    val buffer=ByteArray(1024)
                    while(true) {
                        val count=input.read(buffer)
                        if(count<0)break
                        require(bytes.size()+count<=8192)
                        bytes.write(buffer,0,count)
                    }
                    evaluate(bytes.toString(Charsets.UTF_8.name()),installedVersion,installedCertificates)
                }
            }} finally {connection.disconnect()}
        }
    } catch(_: Exception) {AppUpdateResult.Unknown}

    companion object {
        const val PACKAGE="io.wegoh.app"
        const val MARKET_URI="market://detail?package=io.wegoh.app"
        fun marketIntent()=Intent(Intent.ACTION_VIEW,Uri.parse(MARKET_URI))
        fun installedCertificates(context: Context): Set<String> {
            val info=context.packageManager.getPackageInfo(context.packageName,PackageManager.GET_SIGNING_CERTIFICATES)
            val signing=info.signingInfo ?: return emptySet()
            val certificates=if(signing.hasMultipleSigners())signing.apkContentsSigners else signing.signingCertificateHistory
            return certificates.orEmpty().map { cert ->
                MessageDigest.getInstance("SHA-256").digest(cert.toByteArray()).joinToString(""){"%02x".format(it.toInt() and 255)}
            }.toSet()
        }
        fun evaluate(body: String,installedVersion: Long,installedCertificates: Set<String>): AppUpdateResult = try {
            require(body.toByteArray(Charsets.UTF_8).size<=8192)
            val json=JSONObject(body)
            require(json.keys().asSequence().toSet()==setOf("schemaVersion","packageName","versionCode","versionName","apkSha256","signingCertificatesSha256"))
            require(json.get("schemaVersion") is Int && json.getInt("schemaVersion")==1 && json.get("packageName")==PACKAGE)
            require(json.get("versionCode") is Int || json.get("versionCode") is Long)
            val version=json.getLong("versionCode")
            require(version in 1..Int.MAX_VALUE.toLong())
            require(json.get("versionName") is String && json.getString("versionName").matches(Regex("[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}")))
            require(json.get("apkSha256") is String && json.getString("apkSha256").matches(Regex("[0-9a-f]{64}")))
            val certs=json.getJSONArray("signingCertificatesSha256")
            require(certs.length() in 1..8)
            val values=(0 until certs.length()).map{require(certs.get(it) is String);certs.getString(it)}
            require(values.distinct().size==values.size && values.all{it.matches(Regex("[0-9a-f]{64}"))})
            // App Market remains responsible for package signature/rotation validation at install.
            require(installedCertificates.isNotEmpty() && values.any{it in installedCertificates})
            if(version>installedVersion)AppUpdateResult.Available(version) else AppUpdateResult.Current
        } catch(_: Exception){AppUpdateResult.Unknown}
    }
}
