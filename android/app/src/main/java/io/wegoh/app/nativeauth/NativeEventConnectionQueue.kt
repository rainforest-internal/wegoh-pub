package io.wegoh.app.nativeauth

import java.io.Closeable
import java.util.concurrent.Executor
import java.util.concurrent.RejectedExecutionException

internal fun openNativeEventConnection(owner: Executor,network: Executor,prepare: ()->()->Closeable,
    complete: (Result<Closeable>)->Unit) {
    owner.execute {
        val connect=try {prepare()} catch(error: Exception) {complete(Result.failure(error));return@execute}
        try {network.execute {
            val result=runCatching {connect()}
            try {owner.execute {complete(result)}} catch(_: RejectedExecutionException) {result.getOrNull()?.close()}
        }} catch(error: RejectedExecutionException) {complete(Result.failure(error))}
    }
}
