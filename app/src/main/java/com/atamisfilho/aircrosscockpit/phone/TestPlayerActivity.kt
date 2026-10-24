package com.atamisfilho.aircrosscockpit.phone

import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import androidx.appcompat.app.AppCompatActivity
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import com.atamisfilho.aircrosscockpit.R
import com.atamisfilho.aircrosscockpit.media.MediaRegistry
import com.google.android.material.button.MaterialButton

/**
 * Testador: reproduz vídeos e áudios da biblioteca direto no celular,
 * para validar tudo antes de ir ao carro.
 */
class TestPlayerActivity : AppCompatActivity() {

    private var player: ExoPlayer? = null
    private var playerView: PlayerView? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_test)

        findViewById<MaterialButton>(R.id.btnBack).setOnClickListener { finish() }
        playerView = findViewById(R.id.playerView)

        val attrs = AudioAttributes.Builder()
            .setUsage(C.USAGE_MEDIA)
            .setContentType(C.AUDIO_CONTENT_TYPE_MOVIE)
            .build()
        val p = ExoPlayer.Builder(this)
            .setAudioAttributes(attrs, /* handleAudioFocus = */ true)
            .setHandleAudioBecomingNoisy(true)
            .build()
        playerView?.player = p
        player = p

        buildList()

        // Toca o item mais recente do WhatsApp logo na abertura, se existir.
        val first = MediaRegistry.entries("wa_video", this).firstOrNull()
            ?: MediaRegistry.entries("device_video", this).firstOrNull()
        first?.let { playEntry(it) }
    }

    private fun buildList() {
        val container = findViewById<LinearLayout>(R.id.listContainer)
        container.removeAllViews()

        val sections = listOf(
            "WhatsApp · Vídeos" to MediaRegistry.entries("wa_video", this).take(15),
            "Vídeos do celular" to MediaRegistry.entries("device_video", this).take(10),
            "Músicas" to MediaRegistry.entries("music", this).take(10),
            "WhatsApp · Áudios" to MediaRegistry.entries("wa_audio", this).take(10),
        )

        for ((label, entries) in sections) {
            if (entries.isEmpty()) continue
            addSectionTitle(container, label)
            for (entry in entries) {
                val btn = MaterialButton(this)
                btn.text = "  ${entry.title}"
                btn.textSize = 13f
                btn.maxLines = 2
                btn.textAlignment = View.TEXT_ALIGNMENT_TEXT_START
                btn.isAllCaps = false
                btn.setOnClickListener { playEntry(entry) }
                container.addView(btn)
            }
        }
    }

    private fun addSectionTitle(container: LinearLayout, label: String) {
        val tv = android.widget.TextView(this)
        tv.text = label
        tv.textSize = 14f
        tv.setTypeface(null, android.graphics.Typeface.BOLD)
        tv.setTextColor(getColor(R.color.amber))
        val pad = (12 * resources.displayMetrics.density).toInt()
        tv.setPadding(pad, pad, pad, pad / 3)
        container.addView(tv)
    }

    private fun playEntry(entry: com.atamisfilho.aircrosscockpit.media.MediaEntry) {
        val p = player ?: return
        val item = MediaItem.Builder().setMediaId(entry.id).setUri(entry.uri).build()
        p.setMediaItem(item)
        p.prepare()
        p.play()
        playerView?.useController = true
        playerView?.visibility = View.VISIBLE
        title = entry.title
    }

    override fun onStop() {
        super.onStop()
        player?.run {
            if (isPlaying) pause()
        }
    }

    override fun onDestroy() {
        playerView?.player = null
        player?.release()
        player = null
        super.onDestroy()
    }
}
