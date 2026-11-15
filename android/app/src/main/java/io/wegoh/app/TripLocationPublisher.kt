package io.wegoh.app

import io.wegoh.app.nativeauth.NativeSocialFailure
import io.wegoh.app.nativeauth.TripLocationFix
import io.wegoh.app.nativeauth.TripLocationShare
import io.wegoh.app.nativeauth.TripLocationTransport
import java.io.Closeable

internal class TripLocationPublisher(
    private val observe: ((TripLocationFix)->Unit, (LocationUnavailableReason)->Unit)->Closeable,
    private val now: ()->Long = System::currentTimeMillis,
    private val status: (String?)->Unit = {},
): Closeable {
    private var tripId: String?=null
    private var transport: TripLocationTransport?=null
    private var generation=0L
    private var permissionRead: Closeable?=null
    private var location: Closeable?=null
    private var sending: Closeable?=null
    private var busy=false
    private var lastSentAt: Long?=null
    private var lastCapturedAt: Long?=null
    private var recoveryAttempts=0
    private var refreshShare=false
    private var retryNotBefore=0L
    private var locationAvailable=false

    fun update(id: String?,api: TripLocationTransport?) {
        if(id==tripId && api===transport)return
        close()
        tripId=id;transport=api
        if(id==null || api==null)return
        status("차량 위치를 확인하고 있어요")
        val token=generation
        val request=api.readLocationShare(id) {result->
            if(token!=generation || transport!==api || tripId!=id)return@readLocationShare
            result.fold(onSuccess={share->
                if(share.tripId!=id || share.shareId==null) {
                    stop();status("위치 공유 상태를 다시 불러와 주세요");return@fold
                }
                val watching=observe({fix->send(token,api,share,fix)},{reason->
                    if(token==generation) {
                        locationAvailable=false
                        if(reason==LocationUnavailableReason.ERROR) {
                            stop();status("차량 위치를 확인할 수 없어요. 위치 권한을 확인한 뒤 다시 불러와 주세요")
                        } else status("차량 위치를 받지 못했어요. 새 위치를 기다리고 있어요")
                    }
                })
                if(token==generation)location=watching else watching.close()
            },onFailure={stop();status("위치 공유 상태를 다시 불러와 주세요")})
        }
        if(token==generation)permissionRead=request else request.close()
    }

    private fun send(token: Long,api: TripLocationTransport,share: TripLocationShare,fix: TripLocationFix) {
        if(token!=generation || transport!==api || tripId!=share.tripId)return
        val time=now()
        if(!fix.latitude.isFinite() || fix.latitude !in -90.0..90.0 ||
            !fix.longitude.isFinite() || fix.longitude !in -180.0..180.0 ||
            fix.accuracyMeters?.let { !it.isFinite() || it !in 0.0..10000.0 }==true) {
            locationAvailable=false
            status("차량 위치가 올바르지 않아요. 새 GPS 위치를 기다리고 있어요");return
        }
        if(time-fix.capturedAtMillis !in 0L..60000L) {
            locationAvailable=false
            status("GPS 위치 시각이 맞지 않거나 오래됐어요. 최신 위치를 기다리고 있어요");return
        }
        locationAvailable=true
        if(busy)return
        if(lastCapturedAt?.let {fix.capturedAtMillis<=it}==true || time<retryNotBefore ||
            lastSentAt?.let {time-it<10000L}==true)return
        if(refreshShare) {
            busy=true
            val request=api.readLocationShare(share.tripId) {result->
                if(token!=generation || transport!==api || tripId!=share.tripId)return@readLocationShare
                busy=false;permissionRead=null
                result.fold(onSuccess={current->
                    if(current.tripId!=share.tripId || current.shareId!=share.shareId) {
                        stop();status("위치 공유 상태가 바뀌었어요. 다시 불러와 주세요")
                    } else {
                        refreshShare=false;send(token,api,current,fix)
                    }
                },onFailure={stop();status("위치 공유 상태를 다시 불러와 주세요")})
            }
            if(token==generation && busy)permissionRead=request else request.close()
            return
        }
        busy=true;lastSentAt=time;lastCapturedAt=fix.capturedAtMillis
        val request=api.reportLocation(share.tripId,checkNotNull(share.shareId),fix) {result->
            if(token!=generation || transport!==api || tripId!=share.tripId)return@reportLocation
            busy=false;sending=null
            result.fold(onSuccess={
                recoveryAttempts=0;retryNotBefore=0L
                if(locationAvailable)status("이 화면이 열려 있는 동안 차량 위치를 공유해요")
            },onFailure={error->
                val transient=error is NativeSocialFailure && error.kind==NativeSocialFailure.Kind.UNAVAILABLE &&
                    (error.httpStatus==null || error.httpStatus==408 || error.httpStatus in 500..599)
                if(transient && recoveryAttempts<3) {
                    recoveryAttempts++;refreshShare=true
                    retryNotBefore=now()+maxOf(10000L,((error as NativeSocialFailure).retryAfterSeconds?.toLong() ?: 0L)*1000L)
                    status("차량 위치 전송이 잠시 끊겼어요. 새 GPS 위치에서 공유 상태를 다시 확인해요")
                } else {stop();status("차량 위치를 보내지 못했어요. 다시 불러와 주세요")}
            })
        }
        if(token==generation && busy)sending=request else request.close()
    }

    private fun stop() {
        generation++
        permissionRead?.close();permissionRead=null
        location?.close();location=null
        sending?.close();sending=null
        busy=false;lastSentAt=null;lastCapturedAt=null
        locationAvailable=false
        recoveryAttempts=0;refreshShare=false;retryNotBefore=0L
    }

    override fun close() {stop();tripId=null;transport=null;status(null)}
}
