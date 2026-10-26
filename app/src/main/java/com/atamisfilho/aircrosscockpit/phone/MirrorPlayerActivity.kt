package com.atamisfilho.aircrosscockpit.phone

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.location.LocationManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.SeekBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import com.atamisfilho.aircrosscockpit.R
import com.atamisfilho.aircrosscockpit.car.MotionGate
import com.atamisfilho.aircrosscockpit.media.MediaEntry
import com.atamisfilho.aircrosscockpit.media.MediaRegistry
import com.atamisfilho.aircrosscockpit.util.Prefs
import com.google.android.material.button.MaterialButton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.lifecycle.lifecycleScope

/**
 * Modo Espelho (MirrorLink): player de vídeo em TELA CHEIA no próprio
 * celular, pensado para ser espelhado na tela do carro.
 *
 * Por quê existe: a central do C4 Aircross 2019 só fala MirrorLink (não tem
 * Android Auto), e o S25 Ultra não tem servidor MirrorLink. O caminho
 * prático é um celular antigo certificado (Galaxy S8/S9, Android 9) rodando
 * este app e espelhado no carro. Como o MirrorLink espelha via VNC:
 *  - só toques simples (sem gestos multi-touch);
 *  - alavancas GRANDES (≥ 88 dp), texto grande;
 *  - a trava de segurança usa o GPS do próprio celular ([MotionGate.startGps]),
 *    porque aqui não existe sensor do carro.
 */
class MirrorPlayerActivity : AppCompatActivity() {

    private var player: ExoPlayer? = null

    // Fila em reprodução (mesma lógica do app do carro: retoma da posição salva)
    private var queue: List<MediaEntry> = emptyList()
    private var currentId: String? = null
    private var seeking = false

    // Views
    private lateinit var listRoot: View
    private lateinit var playerRoot: View
    private lateinit var lockOverlay: View
    private lateinit var listContainer: LinearLayout
    private lateinit var tvGpsState: TextView
    private lateinit var tvNowPlaying: TextView
    private lateinit var tvTime: TextView
    private lateinit var tvLockTitle: TextView
    private lateinit var tvLockSub: TextView
    private lateinit var btnLockAction: MaterialButton
    private lateinit var btnPlay: MaterialButton
    private lateinit var btnStar: MaterialButton
    private lateinit var seekBar: SeekBar

    private val main = Handler(Looper.getMainLooper())

    /** Listener único do player (criado junto com o player, sem vazamento). */
    private val playerListener = object : Player.Listener {
        override fun onMediaItemTransition(mediaItem: MediaItem?, reason: Int) {
            // Salva a posição do item anterior antes de trocar de faixa.
            saveCurrentPosition()
            currentId = mediaItem?.mediaId
            tvNowPlaying.text = queue.firstOrNull { it.id == currentId }?.title ?: ""
            refreshStarIcon()
        }

        override fun onPlaybackStateChanged(playbackState: Int) {
            if (playbackState == Player.STATE_ENDED) {
                // Terminou: zera a posição p/ a próxima tocar do início.
                currentId?.let { Prefs.savePosition(this@MirrorPlayerActivity, it, 0L) }
            }
        }
    }

    private val tick = object : Runnable {
        override fun run() {
            val p = player ?: return
            if (!seeking) {
                val dur = p.duration
                if (dur > 0) {
                    seekBar.progress = ((p.currentPosition * 100) / dur).toInt()
                }
            }
            tvTime.text = timeLabel()
            refreshPlayIcon()
            refreshStarIcon()
            main.postDelayed(this, 500)
        }
    }

    private val permLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) {
            MotionGate.startGps(this)
            refreshGateUi()
        }

    private val gateListener: (MotionGate.State) -> Unit = { refreshGateUi() }

    // ------------------------------------------------------------------
    // Ciclo de vida
    // ------------------------------------------------------------------

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_mirror)

        // Tela sempre acesa enquanto o Modo Espelho estiver aberto
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        bindViews()
        wireControls()
        buildList()

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun onHandleBackPressed() {
                if (playerRoot.visibility == View.VISIBLE) {
                    showList()
                } else {
                    finish()
                }
            }
        })

        if (!hasLocationPermission()) {
            permLauncher.launch(Manifest.permission.ACCESS_FINE_LOCATION)
        }
    }

    override fun onStart() {
        super.onStart()
        MotionGate.addListener(gateListener)
        MotionGate.startGps(this)
        refreshGateUi()
    }

    override fun onStop() {
        MotionGate.removeListener(gateListener)
        MotionGate.stop()
        saveCurrentPosition()
        player?.pause()
        super.onStop()
    }

    override fun onDestroy() {
        main.removeCallbacks(tick)
        saveCurrentPosition()
        player?.release()
        player = null
        super.onDestroy()
    }

    // ------------------------------------------------------------------
    // Ligações de UI
    // ------------------------------------------------------------------

    private fun bindViews() {
        listRoot = findViewById(R.id.listRoot)
        playerRoot = findViewById(R.id.playerRoot)
        lockOverlay = findViewById(R.id.lockOverlay)
        listContainer = findViewById(R.id.listContainer)
        tvGpsState = findViewById(R.id.tvGpsState)
        tvNowPlaying = findViewById(R.id.tvNowPlaying)
        tvTime = findViewById(R.id.tvTime)
        tvLockTitle = findViewById(R.id.tvLockTitle)
        tvLockSub = findViewById(R.id.tvLockSub)
        btnLockAction = findViewById(R.id.btnLockAction)
        btnPlay = findViewById(R.id.btnPlay)
        btnStar = findViewById(R.id.btnStar)
        seekBar = findViewById(R.id.seekBar)
    }

    private fun wireControls() {
        btnPlay.setOnClickListener { togglePlayPause() }
        findViewById<MaterialButton>(R.id.btnPrev).setOnClickListener {
            player?.let { if (it.hasPreviousMediaItem()) it.seekToPreviousMediaItem() }
        }
        findViewById<MaterialButton>(R.id.btnNext).setOnClickListener {
            player?.let { if (it.hasNextMediaItem()) it.seekToNextMediaItem() }
        }
        findViewById<MaterialButton>(R.id.btnBack10).setOnClickListener {
            player?.let { p -> p.seekTo((p.currentPosition - 10_000).coerceAtLeast(0)) }
        }
        findViewById<MaterialButton>(R.id.btnFwd10).setOnClickListener {
            player?.let { p ->
                val dur = p.duration
                val target = if (dur > 0) (p.currentPosition + 10_000).coerceAtMost(dur)
                else p.currentPosition + 10_000
                p.seekTo(target)
            }
        }
        findViewById<MaterialButton>(R.id.btnBackList).setOnClickListener { showList() }

        btnStar.setOnClickListener {
            val id = currentId ?: return@setOnClickListener
            Prefs.toggleFavorite(this, id)
            refreshStarIcon()
        }

        btnLockAction.setOnClickListener {
            when {
                !hasLocationPermission() ->
                    permLauncher.launch(Manifest.permission.ACCESS_FINE_LOCATION)
                !isGpsEnabled() ->
                    startActivity(Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS))
                else -> {
                    MotionGate.startGps(this)
                    refreshGateUi()
                }
            }
        }

        seekBar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                if (fromUser) seeking = true
            }
            override fun onStartTracking(sb: SeekBar?) { seeking = true }
            override fun onStopTracking(sb: SeekBar?) {
                val p = player
                val dur = p?.duration ?: 0L
                if (p != null && dur > 0) {
                    p.seekTo((sb?.progress ?: 0) * dur / 100)
                }
                seeking = false
            }
        })
    }

    // ------------------------------------------------------------------
    // Lista (tela 1)
    // ------------------------------------------------------------------

    private fun buildList() {
        listContainer.removeAllViews()
        tvGpsState.text = gateStateLabel()

        lifecycleScope.launch {
            val sections = withContext(Dispatchers.IO) {
                val wa = MediaRegistry.entries("wa_video", this@MirrorPlayerActivity)
                val dv = MediaRegistry.entries("device_video", this@MirrorPlayerActivity)
                listOf(
                    "WhatsApp · Vídeos (${wa.size})" to wa,
                    "Vídeos do celular" to dv,
                )
            }
            for ((label, entries) in sections) {
                if (entries.isEmpty()) continue
                addSectionTitle(label)
                for (entry in entries.take(60)) {
                    listContainer.addView(bigRow(entry, entries))
                }
            }
        }
    }

    /** Alavanca grande (88 dp) — digitação de toque simples no espelhamento. */
    private fun bigRow(entry: MediaEntry, section: List<MediaEntry>): View {
        val btn = MaterialButton(this)
        btn.layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(88)
        ).apply { setMargins(0, 0, 0, dp(8)) }
        btn.text = "  ${entry.title}"
        btn.textSize = 18f
        btn.maxLines = 2
        btn.isAllCaps = false
        btn.textAlignment = View.TEXT_ALIGNMENT_TEXT_START
        btn.icon = ContextCompat.getDrawable(this, R.drawable.ic_folder_video)
        btn.iconSize = dp(32)
        btn.iconPadding = dp(16)
        btn.setOnClickListener {
            val index = section.indexOfFirst { it.id == entry.id }.coerceAtLeast(0)
            openPlayer(section, index)
        }
        return btn
    }

    private fun addSectionTitle(label: String) {
        val tv = TextView(this)
        tv.text = label
        tv.textSize = 16f
        tv.setTypeface(null, android.graphics.Typeface.BOLD)
        tv.setTextColor(getColor(R.color.amber))
        tv.setPadding(dp(12), dp(12), dp(12), dp(6))
        listContainer.addView(tv)
    }

    // ------------------------------------------------------------------
    // Player (tela 2)
    // ------------------------------------------------------------------

    private fun openPlayer(section: List<MediaEntry>, index: Int) {
        queue = section
        val p = ensurePlayer()

        val items = section.map {
            MediaItem.Builder().setMediaId(it.id).setUri(it.uri).build()
        }
        val startMs = Prefs.savedPosition(this, section[index].id)
        p.setMediaItems(items, index, startMs)
        p.prepare()

        currentId = section[index].id
        tvNowPlaying.text = section[index].title

        listRoot.visibility = View.GONE
        playerRoot.visibility = View.VISIBLE

        if (MotionGate.videoAllowed()) p.play() else p.pause()

        main.removeCallbacks(tick)
        main.post(tick)
        refreshGateUi()
    }

    private fun ensurePlayer(): ExoPlayer {
        player?.let { return it }
        val attrs = AudioAttributes.Builder()
            .setUsage(C.USAGE_MEDIA)
            .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE)
            .build()
        val p = ExoPlayer.Builder(this)
            .setAudioAttributes(attrs, /* handleAudioFocus = */ true)
            .setHandleAudioBecomingNoisy(true)
            .build()
        p.setVideoScalingMode(C.VIDEO_SCALING_MODE_SCALE_TO_FIT_WITH_CROPPING)
        p.addListener(playerListener)
        findViewById<PlayerView>(R.id.playerView).player = p
        player = p
        return p
    }

    private fun showList() {
        saveCurrentPosition()
        player?.pause()
        listRoot.visibility = View.VISIBLE
        playerRoot.visibility = View.GONE
        buildList()
    }

    private fun togglePlayPause() {
        val p = player ?: return
        if (p.isPlaying) {
            p.pause()
        } else {
            if (!MotionGate.videoAllowed()) {
                Toast.makeText(this, R.string.blocked_by_speed, Toast.LENGTH_SHORT).show()
                return
            }
            p.play()
        }
        refreshPlayIcon()
    }

    private fun saveCurrentPosition() {
        val id = currentId ?: return
        val p = player ?: return
        val pos = p.currentPosition
        Prefs.savePosition(this, id, if (pos > 5_000) pos else 0L)
    }

    // ------------------------------------------------------------------
    // Trava de segurança (GPS) — mesma regra do app do carro: só parado
    // ------------------------------------------------------------------

    private fun refreshGateUi() {
        val state = MotionGate.state
        tvGpsState.text = gateStateLabel()

        val blocked = !MotionGate.videoAllowed()
        lockOverlay.visibility = if (blocked) View.VISIBLE else View.GONE
        if (!blocked) return

        when (state) {
            MotionGate.State.MOVING -> {
                player?.pause()
                tvLockTitle.setText(R.string.lock_moving_title)
                tvLockSub.setText(R.string.lock_moving_sub)
                btnLockAction.visibility = View.GONE
            }
            MotionGate.State.UNKNOWN -> {
                player?.pause()
                tvLockTitle.setText(R.string.lock_waiting_title)
                tvLockSub.setText(R.string.lock_waiting_sub)
                btnLockAction.visibility = View.GONE
            }
            MotionGate.State.UNAVAILABLE -> {
                tvLockTitle.setText(R.string.lock_unavailable_title)
                tvLockSub.setText(R.string.lock_unavailable_sub)
                btnLockAction.visibility = View.VISIBLE
                btnLockAction.setText(
                    if (!hasLocationPermission()) R.string.lock_grant
                    else if (!isGpsEnabled()) R.string.lock_enable_gps
                    else R.string.lock_retry
                )
            }
            MotionGate.State.STOPPED -> { /* desbloqueado — overlay invisível */ }
        }
    }

    private fun gateStateLabel(): String = when (MotionGate.state) {
        MotionGate.State.STOPPED -> getString(R.string.gps_state_stopped)
        MotionGate.State.MOVING -> getString(R.string.gps_state_moving)
        MotionGate.State.UNKNOWN -> getString(R.string.gps_state_waiting)
        MotionGate.State.UNAVAILABLE -> getString(R.string.gps_state_unavailable)
    }

    // ------------------------------------------------------------------
    // Utilidades
    // ------------------------------------------------------------------

    private fun hasLocationPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED

    private fun isGpsEnabled(): Boolean = try {
        val lm = getSystemService(LocationManager::class.java)
        lm?.isProviderEnabled(LocationManager.GPS_PROVIDER) == true ||
            lm?.isProviderEnabled(LocationManager.NETWORK_PROVIDER) == true
    } catch (t: Throwable) {
        false
    }

    private fun timeLabel(): String {
        val p = player ?: return "--:--"
        val known = queue.firstOrNull { it.id == currentId }?.durationMs ?: 0L
        val dur = if (p.duration > 0) p.duration else known
        return "${fmt(p.currentPosition)} / ${if (dur > 0) fmt(dur) else "--:--"}"
    }

    private fun fmt(ms: Long): String {
        val totalSec = ms / 1000
        val h = totalSec / 3600
        val m = (totalSec % 3600) / 60
        val s = totalSec % 60
        return if (h > 0) String.format(java.util.Locale.US, "%d:%02d:%02d", h, m, s)
        else String.format(java.util.Locale.US, "%d:%02d", m, s)
    }

    private fun refreshPlayIcon() {
        btnPlay.setIconResource(
            if (player?.isPlaying == true) R.drawable.ic_pause else R.drawable.ic_play
        )
    }

    private fun refreshStarIcon() {
        val fav = currentId?.let { Prefs.isFavorite(this, it) } == true
        btnStar.setIconResource(if (fav) R.drawable.ic_star else R.drawable.ic_star_outline)
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
