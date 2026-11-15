package io.wegoh.app.nativeauth

interface DiscoveryApi {
    fun readPublicPacks(callback: (Result<NativeApiClient.Document>)->Unit)
    fun readPackVersion(id: String,version: Int,callback: (Result<NativeApiClient.PackVersion>)->Unit)
    fun readCourseLibrary(callback: (Result<NativeApiClient.Document>)->Unit)
    fun readPublicCourse(id: String,version: Int,callback: (Result<NativeApiClient.Document>)->Unit)
}

internal class NativeDiscoveryApi(private val reads: AuthorizedAccountReads): DiscoveryApi {
    override fun readPublicPacks(callback: (Result<NativeApiClient.Document>)->Unit)=reads.catalogue("/v1/packs","packs",100,callback)
    override fun readPackVersion(id: String,version: Int,callback: (Result<NativeApiClient.PackVersion>)->Unit)=reads.pack(id,version,callback)
    override fun readCourseLibrary(callback: (Result<NativeApiClient.Document>)->Unit)=
        reads.read(VehicleConnection.Scope.COURSES,callback) {client,credentials->
            client.readDocument("/v1/native/courses/library",credentials.getString("accessToken"))
        }
    override fun readPublicCourse(id: String,version: Int,callback: (Result<NativeApiClient.Document>)->Unit)=
        reads.read(VehicleConnection.Scope.COURSES,callback) {client,credentials->
            client.readDocument(NativeApiClient.publicCoursePath(id,version),credentials.getString("accessToken"))
        }
}
