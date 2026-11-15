package io.wegoh.app.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.text.Html
import android.util.LruCache
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import java.io.Closeable
import java.net.InetAddress
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Dns
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import kotlin.coroutines.resume

internal class MusicThumbnailLoader: Closeable {
    private val workers=Executors.newFixedThreadPool(2)
    private val cache=LruCache<String,Bitmap>(24)
    private val misses=mutableSetOf<String>()
    private val client=OkHttpClient.Builder().followRedirects(false).followSslRedirects(false)
        .connectTimeout(3,TimeUnit.SECONDS).readTimeout(3,TimeUnit.SECONDS).callTimeout(8,TimeUnit.SECONDS)
        .dns(object: Dns {
            override fun lookup(hostname: String): List<InetAddress> = Dns.SYSTEM.lookup(hostname).also {addresses->
                check(addresses.isNotEmpty() && addresses.all(::publicAddress))
            }
        })
        .build()
    suspend fun load(url: String): Bitmap? = suspendCancellableCoroutine {continuation->
        synchronized(cache) {
            cache.get(url)?.let {continuation.resume(it);return@suspendCancellableCoroutine}
            if(url in misses){continuation.resume(null);return@suspendCancellableCoroutine}
        }
        val future=try {workers.submit {
            val bitmap=runCatching {fetch(url)}.getOrNull()
            synchronized(cache) {if(bitmap!=null)cache.put(url,bitmap) else if(misses.size<100)misses.add(url)}
            if(continuation.isActive)continuation.resume(bitmap)
        }} catch(_: java.util.concurrent.RejectedExecutionException) {continuation.resume(null);return@suspendCancellableCoroutine}
        continuation.invokeOnCancellation {future.cancel(true)}
    }
    private fun fetch(address: String): Bitmap? {
        val deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(8)
        val (pageUrl,pageBytes)=get(address.toHttpUrl(),1536*1024,false,deadline)
        val page=pageBytes.toString(Charsets.UTF_8)
        val image=Regex("(?is)<meta\\b[^>]{0,4096}>").findAll(page).mapNotNull {tag->
            val attrs=Regex("(?is)([\\w:-]+)\\s*=\\s*([\"'])(.*?)\\2").findAll(tag.value)
                .associate {it.groupValues[1].lowercase() to it.groupValues[3]}
            if((attrs["property"] ?: attrs["name"])?.lowercase() in setOf("og:image","twitter:image"))attrs["content"] else null
        }.firstOrNull() ?: return null
        val imageUrl=pageUrl.resolve(Html.fromHtml(image,Html.FROM_HTML_MODE_LEGACY).toString()) ?: return null
        val bytes=get(imageUrl,512*1024,true,deadline).second
        val bounds=BitmapFactory.Options().apply {inJustDecodeBounds=true}
        BitmapFactory.decodeByteArray(bytes,0,bytes.size,bounds)
        check(bounds.outWidth in 1..8192 && bounds.outHeight in 1..8192 && bounds.outWidth.toLong()*bounds.outHeight<=16_777_216)
        val options=BitmapFactory.Options().apply {
            inSampleSize=1
            while(bounds.outWidth/inSampleSize>256 || bounds.outHeight/inSampleSize>256)inSampleSize*=2
        }
        return BitmapFactory.decodeByteArray(bytes,0,bytes.size,options)
    }
    private fun get(initial: HttpUrl,limit: Int,image: Boolean,deadline: Long): Pair<HttpUrl,ByteArray> {
        var url=initial
        repeat(4) {
            check(url.isHttps && url.username.isEmpty() && url.password.isEmpty() && url.port==443)
            check(image || url.host in MUSIC_HOSTS)
            val remaining=deadline-System.nanoTime();check(remaining>0 && !Thread.currentThread().isInterrupted)
            val call=client.newCall(Request.Builder().url(url).header("User-Agent","Mozilla/5.0 WegoHLinkPreview/1.0").build())
            call.timeout().timeout(remaining,TimeUnit.NANOSECONDS)
            call.execute().use {response->
                if(response.code in listOf(301,302,303,307,308)) {
                    url=url.resolve(response.header("Location") ?: error("Missing redirect")) ?: error("Invalid redirect")
                } else {
                    check(response.isSuccessful)
                    val type=response.header("Content-Type").orEmpty().lowercase()
                    check(if(image)type.startsWith("image/") else type.contains("text/html") || type.contains("application/xhtml"))
                    val body=checkNotNull(response.body)
                    body.byteStream().use {stream->
                        val out=java.io.ByteArrayOutputStream();val buffer=ByteArray(8192)
                        while(out.size()<=limit) {val count=stream.read(buffer,0,minOf(buffer.size,limit+1-out.size()));if(count<0)break;out.write(buffer,0,count)}
                        check(out.size()<=limit);return url to out.toByteArray()
                    }
                }
            }
        }
        error("Redirect limit")
    }
    override fun close(){workers.shutdownNow();client.dispatcher.cancelAll();client.dispatcher.executorService.execute {client.connectionPool.evictAll()};client.dispatcher.executorService.shutdown();synchronized(cache){cache.evictAll();misses.clear()}}
    companion object {
        private val MUSIC_HOSTS=setOf("melon.com","www.melon.com","m.melon.com","m2.melon.com","kko.to","kko.kakao.com","open.spotify.com","spotify.link","music.youtube.com","youtube.com","www.youtube.com","m.youtube.com","youtu.be")
        private fun publicAddress(address: InetAddress): Boolean {
            if(address.isAnyLocalAddress || address.isLoopbackAddress || address.isLinkLocalAddress || address.isSiteLocalAddress || address.isMulticastAddress)return false
            val b=address.address.map {it.toInt() and 255}
            return if(b.size==4)b[0] !in setOf(0,127) && b[0]<224 && !(b[0]==100 && b[1] in 64..127) && !(b[0]==198 && b[1] in 18..19)
                else b[0] and 224 == 32
        }
    }
}

@Composable
internal fun MusicThumbnail(url: String,loader: MusicThumbnailLoader) {
    val bitmap by produceState<Bitmap?>(null,url,loader) {value=null;value=loader.load(url)}
    val palette=LocalCarPalette.current
    Box(Modifier.size(CarTokens.MusicThumbnailSize).clip(RoundedCornerShape(CarTokens.Radius)).background(palette.background),contentAlignment=Alignment.Center) {
        if(bitmap!=null)Image(bitmap!!.asImageBitmap(),contentDescription=null,modifier=Modifier.size(CarTokens.MusicThumbnailSize),contentScale=ContentScale.Crop)
        else CarIcon(CarSymbol.Music,Modifier.size(CarTokens.Icon),palette.secondary)
    }
}
