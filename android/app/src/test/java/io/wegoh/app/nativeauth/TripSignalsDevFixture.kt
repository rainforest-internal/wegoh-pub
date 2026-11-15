package io.wegoh.app.nativeauth

internal object TripSignalsDevFixture {
    fun response(count: Int=3,createdAt: String="2026-11-09 13:13:15.323474+09:00"): String {
        val kinds=listOf("rest","hungry","restroom")
        return """{"signals":[${kinds.take(count).mapIndexed {index,kind->"""
            {"id":"${(index+1).toString(16).padStart(32,'0')}","accountId":"team-${"0".repeat(40)}","kind":"$kind",
             "destination":{"latitude":37.689,"longitude":128.755,"name":"선택한 장소"},
             "createdAt":"$createdAt","revision":1,"contextState":"valid","votes":{"agree":0,"pass":0},"myVote":null,"agreed":false}
        """}.joinToString(",")}],"nextCursor":null}"""
    }
    fun signals(count: Int=3,createdAt: String="2026-11-09 13:13:15.323474+09:00")=
        TripSignalsCodec.signals(StrictNativeJson.parseBusiness(response(count,createdAt).toByteArray(Charsets.UTF_8)))
}
