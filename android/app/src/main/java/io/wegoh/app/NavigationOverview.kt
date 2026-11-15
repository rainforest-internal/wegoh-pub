package io.wegoh.app

/** Transient OEM values only. No mock fallback, coordinates, persistence or network sharing. */
data class NavigationLeg(val stopId: String,val cumulativeSeconds: Int,val cumulativeMeters: Int)
data class NavigationTraffic(val startMeters: Double,val endMeters: Double,val condition: String)
data class NavigationOverview(val packKey: String,val legs: List<NavigationLeg>,val receivedAt: Long,
    val traffic: List<NavigationTraffic> = emptyList(),val trafficReceivedAt: Long? = null) {
    fun timeLabel(index: Int,now: Long): String {
        if(now-receivedAt !in 0..90000 || index !in legs.indices)return "시간 미확인"
        val before=if(index==0)0 else legs[index-1].cumulativeSeconds
        val seconds=legs[index].cumulativeSeconds-before
        if(seconds<0 || legs[index].cumulativeSeconds<=0)return "시간 미확인"
        return "약 ${(seconds+59)/60}분"
    }
    fun trafficLabel(index: Int,now: Long): String {
        if(now-receivedAt !in 0..90000 || trafficReceivedAt==null || now-trafficReceivedAt !in 0..90000 || index !in legs.indices)return "교통 미확인"
        val start=if(index==0)0 else legs[index-1].cumulativeMeters
        val end=legs[index].cumulativeMeters
        if(end<=start)return "교통 미확인"
        val conditions=traffic.filter {it.startMeters<end && it.endMeters>start}.map{it.condition}
        return when {"HEAVY" in conditions->"정체 포함";"SLOW" in conditions->"서행 포함";"MODERATE" in conditions->"혼잡 포함";else->"교통 미확인"}
    }
}

/** Known OEM estimates for one stop. Unknown values are left out so a stop list never repeats "미확인" per row. */
fun NavigationOverview?.stopEstimates(stopId: String,now: Long): List<String> {
    val overview=this ?: return emptyList()
    val leg=overview.legs.indexOfFirst {it.stopId==stopId}
    return listOf(overview.timeLabel(leg,now) to "시간 미확인",overview.trafficLabel(leg,now) to "교통 미확인")
        .filter {(label,unknown)->label!=unknown}.map {it.first}
}
