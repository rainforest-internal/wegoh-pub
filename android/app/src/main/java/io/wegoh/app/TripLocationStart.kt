package io.wegoh.app

internal fun <T> startTripLocation(candidate: T,start: (T)->Unit,release: (T)->Unit): T? =
    try {start(candidate);candidate} catch(_: Exception) {runCatching {release(candidate)};null}
