package io.wegoh.app

import java.net.URI

/** A server address never grants a release permission to send plaintext data. */
object DistributionPolicy {
    fun updateEndpoint(base: String, debug: Boolean=BuildConfig.DEBUG): String {
        val safe=endpoint(base,debug)
        val uri=URI(safe)
        require(uri.rawPath.isNullOrEmpty() && uri.port in -1..65535 && uri.port!=0) {"잘못된 서버 주소"}
        return safe
    }
    fun endpoint(base: String, debug: Boolean=BuildConfig.DEBUG): String {
        val uri=URI(base)
        require(uri.userInfo==null && uri.rawQuery==null && uri.rawFragment==null && !uri.host.isNullOrBlank()) {"잘못된 서버 주소"}
        require(uri.scheme=="https" || (debug && uri.scheme=="http" && uri.host=="127.0.0.1")) {"보호된 연결이 필요합니다"}
        return base.trimEnd('/')
    }
}
