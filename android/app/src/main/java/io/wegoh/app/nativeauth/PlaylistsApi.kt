package io.wegoh.app.nativeauth

interface PlaylistsApi {
    fun readPlaylists(callback: (Result<NativeApiClient.Document>)->Unit)
    fun readPlaylist(id: String,callback: (Result<NativeApiClient.Document>)->Unit)
}

internal class NativePlaylistsApi(private val reads: AuthorizedAccountReads): PlaylistsApi {
    override fun readPlaylists(callback: (Result<NativeApiClient.Document>)->Unit)=reads.read(VehicleConnection.Scope.PLAYLISTS,callback) {client,credentials ->
        client.readDocument("/v1/playlists",credentials.getString("accessToken")).also {check(it.asObject().getJSONArray("playlists").length()<=100)}
    }
    override fun readPlaylist(id: String,callback: (Result<NativeApiClient.Document>)->Unit) {
        val path="/v1/playlists/$id";NativeApiClient.requireReadPath(path)
        reads.read(VehicleConnection.Scope.PLAYLISTS,callback) {client,credentials ->client.readDocument(path,credentials.getString("accessToken")).also {
            val value=it.asObject();check(value.get("id") is String && value.getString("id")==id && value.getJSONArray("tracks").length()<=100)
        }}
    }
}
