package io.wegoh.app.nativeauth

/**
 * 기능 권한 교체(첫 권한 읽기, 리모컨 받기 저장 등)는 연결 상태를 바꾸지 않고 열린 클라이언트만 무효화한다.
 * 그 뒤에는 연결 상태 알림이 오지 않으므로 화면이 스스로 다시 열어야 한다. 성공 전 반복 무효화는 [limit]번까지만
 * 다시 열고, 읽기에 성공하면 [reset]한다.
 */
internal class InvalidationReloads(private val limit: Int=INVALIDATION_RELOAD_LIMIT) {
    var attempts=0
        private set
    /** 다시 열어도 되면 이번 시도 번호, 한도를 넘었으면 null. */
    fun take(): Int? = if(attempts>=limit) null else ++attempts
    fun reset() {attempts=0}
}

internal const val INVALIDATION_RELOAD_LIMIT=3
