package io.wegoh.app.nativeauth

internal interface AuthorizedAccountReads {
    fun <T> read(scope: VehicleConnection.Scope?,callback: (Result<T>)->Unit,
        normalizeFailure: (Throwable)->Throwable={it},fetch: (NativeApiClient,org.json.JSONObject)->T)
}

internal fun AuthorizedAccountReads.catalogue(path: String,field: String,limit: Int,callback: (Result<NativeApiClient.Document>)->Unit)=
    read(VehicleConnection.Scope.COURSES,callback) {client,credentials ->client.readDocument(path,credentials.getString("accessToken")).also {
        check(it.asObject().getJSONArray(field).length()<=limit)
    }}

internal fun AuthorizedAccountReads.pack(id: String,version: Int,callback: (Result<NativeApiClient.PackVersion>)->Unit,original: Boolean=false) {
    NativeApiClient.packVersionPath(id,version,original)
    read(VehicleConnection.Scope.COURSES,callback) {client,credentials ->
        if(original)client.readOriginalPackVersion(id,version,credentials.getString("accessToken"))
        else client.readPackVersion(id,version,credentials.getString("accessToken"))
    }
}
