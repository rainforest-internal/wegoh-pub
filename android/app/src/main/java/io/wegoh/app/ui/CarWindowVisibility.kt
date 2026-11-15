package io.wegoh.app.ui

import android.view.View
import android.view.ViewTreeObserver
import androidx.activity.ComponentActivity
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.platform.LocalView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import java.io.Closeable

internal data class CarWindowState(val visible: Boolean=false,val focused: Boolean=false)

internal class CarWindowVisibility(private val host: ComponentActivity,private val changed: (CarWindowState)->Unit): Closeable {
    private val views=linkedSetOf<WindowView>()
    private val observers=linkedSetOf<(CarWindowState)->Unit>()
    private var resumed=host.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)
    private var closed=false
    var state by mutableStateOf(CarWindowState());private set
    private val root=host.window.decorView
    private val lifecycle=LifecycleEventObserver {_,event ->
        when(event) {
            Lifecycle.Event.ON_RESUME -> {resumed=true;update()}
            Lifecycle.Event.ON_PAUSE,Lifecycle.Event.ON_STOP -> {resumed=false;update()}
            Lifecycle.Event.ON_DESTROY -> close()
            else -> Unit
        }
    }
    init {watch(root);host.lifecycle.addObserver(lifecycle)}
    private fun update() {
        if(closed)return
        val shown=if(resumed && !host.isFinishing && !host.isDestroyed)views.filter {
            it.view.isAttachedToWindow && it.view.isShown && it.view.windowVisibility==View.VISIBLE
        } else emptyList()
        publish(CarWindowState(shown.isNotEmpty(),shown.any {it.view.hasWindowFocus()}))
    }
    private fun publish(value: CarWindowState) {
        if(state!=value){state=value;changed(value);observers.toList().forEach {it(value)}}
    }
    fun observe(observer: (CarWindowState)->Unit): Closeable {
        if(closed){observer(CarWindowState());return Closeable {}}
        observers.add(observer);observer(state)
        return Closeable {observers.remove(observer)}
    }
    fun watch(view: View): Closeable {
        if(closed)return Closeable {}
        val entry=WindowView(view);views.add(entry);entry.bind();update()
        return Closeable {entry.close();update()}
    }
    private inner class WindowView(val view: View): Closeable {
        private var tree: ViewTreeObserver?=null
        private val focus=ViewTreeObserver.OnWindowFocusChangeListener {update()}
        private val layout=ViewTreeObserver.OnGlobalLayoutListener {update()}
        private val attach=object: View.OnAttachStateChangeListener {
            override fun onViewAttachedToWindow(v: View) {bindTree();update()}
            override fun onViewDetachedFromWindow(v: View) {unbindTree();update()}
        }
        fun bind() {view.addOnAttachStateChangeListener(attach);if(view.isAttachedToWindow)bindTree()}
        private fun bindTree() {unbindTree();view.viewTreeObserver.also {tree=it;it.addOnWindowFocusChangeListener(focus);it.addOnGlobalLayoutListener(layout)}}
        private fun unbindTree() {tree?.takeIf {it.isAlive}?.let {it.removeOnWindowFocusChangeListener(focus);it.removeOnGlobalLayoutListener(layout)};tree=null}
        override fun close() {unbindTree();view.removeOnAttachStateChangeListener(attach);views.remove(this)}
    }
    override fun close() {
        if(closed)return
        closed=true;resumed=false;host.lifecycle.removeObserver(lifecycle)
        views.toList().forEach {it.close()};publish(CarWindowState());observers.clear()
    }
}

internal val LocalCarWindowVisibility=staticCompositionLocalOf<CarWindowVisibility?> {null}

@Composable
internal fun ProvideCarWindowVisibility(owner: CarWindowVisibility,content: @Composable ()->Unit) {
    CompositionLocalProvider(LocalCarWindowVisibility provides owner,content=content)
}

@Composable
internal fun ObserveOwnedCarWindow() {
    val owner=LocalCarWindowVisibility.current
    val view=LocalView.current
    DisposableEffect(owner,view) {val watch=owner?.watch(view);onDispose {watch?.close()}}
}
