package com.atamisfilho.aircrosscockpit.car

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.view.Surface
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import com.atamisfilho.aircrosscockpit.CockpitApp
import com.atamisfilho.aircrosscockpit.media.MediaEntry
import com.atamisfilho.aircrosscockpit.media.MediaKind
import com.atamisfilho.aircrosscockpit.util.Prefs

/**
 * Player global do app de tela do carro (ExoPlayer + Surface em tela cheia).
 *
 * Otimizado para: retomar de onde parou (posição salva por mídia),
 * pausar automaticamente quando o carro entra em movimento (vídeo) e
 * notificar as telas para atualizar (invalidate) a cada segundo.
 */
object VideoPlayerController {

    private val main = Handler(Looper.getMainLooper())

    private var player: ExoPlayer? = null
    private var surface: Surface? = null

    /** Fila atual da pasta aberta. */
    var queue: List<MediaEntry> = emptyList()
        private set

    /** ID da mídia em reprodução. */
    var currentId: String? = null
        private set

    /** Hook para as telas se invalidarem (atualizar progresso/ícones). */
    var onChange: (() -> Unit)? = null

    private val tick = object : Runnable {
        override fun run() {
            val e = currentEntry()
            val p = player
            if (p == null || e == null) {
                return
            }
            // Só avança o relógio quando há algo tocando (ou pausado com vídeo permitido).
            if (p.isPlaying || p.playWhenReady) {
                saveCurrentPosition()
            }
            onChange?.invoke()
            main.postDelayed(this, 1000)
        }
    }

    private val gateListener: (MotionGate.State) -> Unit = { _ ->
        // Vídeo sempre pausa quando o carro anda.
        val e = currentEntry()
        if (e != null && e.kind == MediaKind.VIDEO && player?.isPlaying == true && !MotionGate.videoAllowed()) {
            pause()
        }
        onChange?.invoke()
    }

    private val playerListener = object : Player.Listener {
        override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
            // Salva a posição do item anterior quando troca de faixa.
            saveCurrentPosition()
            currentId = mediaItem?.mediaId
            onChange?.invoke()
        }

        override fun onIsPlayingChanged(isPlaying: Boolean) {
            if (isPlaying) {
                main.removeCallbacks(tick)
                main.post(tick)
            }
            onChange?.invoke()
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            if (playbackState == Player.STATE_ENDED) {
                // Terminou: zera a posição salva para a próxima tocar do início.
                currentId?.let { Prefs.savePosition(CockpitApp.get(), it, 0L) }
            }
            onChange?.invoke()
        }
    }

    @Synchronized
    private fun ensure(): ExoPlayer {
        player?.let { return it }
        val ctx: Context = CockpitApp.get()
        val attrs = AudioAttributes.Builder()
            .setUsage(C.USAGE_MEDIA)
            .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE)
            .build()
        val p = ExoPlayer.Builder(ctx)
            .setAudioAttributes(attrs, /* handleAudioFocus = */ true)
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_LOCAL)
            .build()
        // Vídeo em TELA CHEIA com recorte central (fullscreen com crop).
        p.setVideoScalingMode(C.VIDEO_SCALING_MODE_SCALE_TO_FIT_WITH_CROPPING)
        p.addListener(playerListener)
        player = p
        MotionGate.addListener(gateListener)
        return p
    }

    // ------------------------------------------------------------------
    // API usada pelas telas
    // ------------------------------------------------------------------

    /** Toca a pasta a partir do índice dado (retoma da última posição). */
    fun playQueue(entries: List<MediaEntry>, startIndex: Int, autoPlay: Boolean = true) {
        if (entries.isEmpty()) return
        val p = ensure()
        queue = entries
        val items = entries.map { MediaItem.Builder().setMediaId(it.id).setUri(it.uri).build() }
        val id = entries[startIndex.coerceIn(entries.indices)].id
        currentId = id
        val startMs = Prefs.savedPosition(CockpitApp.get(), id)
        p.setMediaItems(items, startIndex.coerceIn(entries.indices), startMs)
        p.prepare()
        surface?.let { p.setVideoSurface(it) }
        if (autoPlay) {
            play()
        } else {
            p.playWhenReady = false
            main.removeCallbacks(tick)
            main.post(tick)
        }
    }

    /** Liga/desliga o player à Surface da tela do carro. */
    fun setSurface(s: Surface?) {
        surface = s
        player?.setVideoSurface(s)
    }

    fun play() {
        val e = currentEntry()
        val p = player ?: return
        if (e != null && e.kind == MediaKind.VIDEO && !MotionGate.videoAllowed()) return
        p.play()
    }

    fun pause() {
        saveCurrentPosition()
        player?.pause()
    }

    fun togglePlayPause() {
        val p = player ?: return
        if (p.isPlaying) pause() else play()
    }

    fun next() {
        val p = player ?: return
        if (p.hasNextMediaItem()) p.seekToNextMediaItem()
    }

    fun previous() {
        val p = player ?: return
        if (p.hasPreviousMediaItem()) p.seekToPreviousMediaItem()
    }

    fun isPlaying(): Boolean = player?.isPlaying == true

    fun isFavorite(): Boolean = currentId?.let { Prefs.isFavorite(CockpitApp.get(), it) } == true

    fun toggleFavorite(): Boolean {
        val id = currentId ?: return false
        return Prefs.toggleFavorite(CockpitApp.get(), id).also { onChange?.invoke() }
    }

    fun currentEntry(): MediaEntry? {
        val id = currentId ?: return null
        return queue.firstOrNull { it.id == id }
    }

    fun positionMs(): Long = player?.currentPosition ?: 0L

    fun durationMs(): Long {
        val known = currentEntry()?.durationMs ?: 0L
        val p = player?.duration ?: 0L
        return if (p > 0) p else known
    }

    fun saveCurrentPosition() {
        val id = currentId ?: return
        val p = player ?: return
        val pos = p.currentPosition
        // Posições irrelevantes não são salvas (início/fim).
        Prefs.savePosition(CockpitApp.get(), id, if (pos > 5_000) pos else 0L)
    }

    fun release() {
        saveCurrentPosition()
        MotionGate.removeListener(gateListener)
        main.removeCallbacks(tick)
        player?.removeListener(playerListener)
        player?.release()
        player = null
        surface = null
        onChange = null
        queue = emptyList()
        currentId = null
    }
}
