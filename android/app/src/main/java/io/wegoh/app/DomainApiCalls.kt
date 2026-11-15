package io.wegoh.app

import io.wegoh.app.nativeauth.*
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.suspendCancellableCoroutine

private suspend fun <T> awaitApi(start: ((Result<T>)->Unit)->Unit): T=suspendCancellableCoroutine {continuation->
    start {if(continuation.isActive)continuation.resumeWith(it)}
}
internal suspend fun <T> apiResult(call: suspend ()->T): Result<T> = try {Result.success(call())}
    catch(error: CancellationException) {throw error}
    catch(error: Exception) {Result.failure(error)}
internal suspend fun ProfileApi.displayName(): String=awaitApi(::readDisplayName)
internal suspend fun ProfileApi.saveDisplayName(name: String,expected: String): String=awaitApi {updateDisplayName(name,expected,it)}
internal suspend fun CoursesApi.courses(): NativeApiClient.Document=awaitApi(::readCourses)
internal suspend fun CoursesApi.packVersion(id: String,version: Int): NativeApiClient.PackVersion=awaitApi {readPackVersion(id,version,it)}
internal suspend fun CoursesApi.originalPackVersion(id: String,version: Int): NativeApiClient.PackVersion=awaitApi {readOriginalPackVersion(id,version,it)}
internal suspend fun DiscoveryApi.publicPacks(): NativeApiClient.Document=awaitApi(::readPublicPacks)
internal suspend fun DiscoveryApi.courseLibrary(): NativeApiClient.Document=awaitApi(::readCourseLibrary)
internal suspend fun DiscoveryApi.publicCourse(id: String,version: Int): NativeApiClient.Document=awaitApi {readPublicCourse(id,version,it)}
internal suspend fun DiscoveryApi.packVersion(id: String,version: Int): NativeApiClient.PackVersion=awaitApi {readPackVersion(id,version,it)}
internal suspend fun PlaylistsApi.playlists(): NativeApiClient.Document=awaitApi(::readPlaylists)
internal suspend fun PlaylistsApi.playlist(id: String): NativeApiClient.Document=awaitApi {readPlaylist(id,it)}

internal suspend fun ProfileApi.vehicleProfile(): VehicleProfile=awaitApi(::readVehicleProfile)
internal suspend fun ProfileApi.saveVehicleProfile(plate: String,name: String,revision: Int): VehicleProfile=awaitApi {updateVehicleProfile(plate,name,revision,it)}
