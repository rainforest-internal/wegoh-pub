package io.wegoh.app.nativeauth

interface CoursesApi {
    fun readCourses(callback: (Result<NativeApiClient.Document>)->Unit)
    fun readPackVersion(id: String,version: Int,callback: (Result<NativeApiClient.PackVersion>)->Unit)
    fun readOriginalPackVersion(id: String,version: Int,callback: (Result<NativeApiClient.PackVersion>)->Unit)
}

internal class NativeCoursesApi(private val reads: AuthorizedAccountReads): CoursesApi {
    override fun readCourses(callback: (Result<NativeApiClient.Document>)->Unit)=reads.catalogue("/v1/studio/packs","packs",1000,callback)
    override fun readPackVersion(id: String,version: Int,callback: (Result<NativeApiClient.PackVersion>)->Unit)=reads.pack(id,version,callback)
    override fun readOriginalPackVersion(id: String,version: Int,callback: (Result<NativeApiClient.PackVersion>)->Unit)=reads.pack(id,version,callback,original=true)
}
