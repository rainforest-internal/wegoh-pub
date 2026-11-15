package io.wegoh.app.nativeauth

internal fun vehicleClimateLeaseDeadline(postStartedElapsedMillis: Long,serverNowMillis: Long,
    leaseExpiresAtMillis: Long,permissionExpiresAtMillis: Long): Long {
    val remaining=minOf(leaseExpiresAtMillis,permissionExpiresAtMillis)-serverNowMillis
    check(postStartedElapsedMillis>=0 && remaining in 1..30_000)
    return Math.addExact(postStartedElapsedMillis,remaining)
}
