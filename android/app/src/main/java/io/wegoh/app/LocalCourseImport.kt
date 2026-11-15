package io.wegoh.app

import android.content.ContentResolver
import android.net.Uri

internal enum class LocalCourseImportResult { IMPORTED, REJECTED, CANCELLED, BLOCKED }

/** The same document-result boundary is used by MainActivity and isolated SAF tests. */
internal class LocalCourseImport(
    private val controller: WegoController,
    private val resolver: ContentResolver,
) {
    val allowed get() = !controller.state.active && controller.state.setupAllowed && controller.state.storageReady

    fun accept(uri: Uri?): LocalCourseImportResult {
        // Cancel and restrictions changing while the picker is open leave existing state untouched.
        if(uri==null)return LocalCourseImportResult.CANCELLED
        if(!allowed)return LocalCourseImportResult.BLOCKED
        return runCatching {
            require(uri.scheme=="content") {"문서 선택기로 고른 파일이 필요합니다"}
            val pack=resolver.openInputStream(uri)?.use {controller.repository.importPack(it)}
                ?: error("선택한 파일을 읽을 수 없습니다")
            controller.refreshLocal(pack.key)
            controller.note("경로를 가져왔어요")
            LocalCourseImportResult.IMPORTED
        }.getOrElse {
            controller.fail("경로를 불러오지 못했어요")
            LocalCourseImportResult.REJECTED
        }
    }
}
