package com.atamisfilho.aircrosscockpit.phone

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.atamisfilho.aircrosscockpit.R
import com.atamisfilho.aircrosscockpit.media.MediaRegistry
import com.atamisfilho.aircrosscockpit.util.Prefs
import com.google.android.material.button.MaterialButton
import com.google.android.material.materialswitch.MaterialSwitch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * UI no celular: onboarding de permissões, resumo da biblioteca,
 * ajuste de segurança e atalho para o testador de mídia.
 */
class MainActivity : AppCompatActivity() {

    private val permLauncher =
        registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            refresh()
        }

    private lateinit var tvPermVideo: android.widget.TextView
    private lateinit var tvPermAudio: android.widget.TextView
    private lateinit var tvPermNotif: android.widget.TextView
    private lateinit var tvPermLocation: android.widget.TextView
    private lateinit var tvCounts: android.widget.TextView
    private lateinit var switchNoSensor: MaterialSwitch

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvPermVideo = findViewById(R.id.tvPermVideo)
        tvPermAudio = findViewById(R.id.tvPermAudio)
        tvPermNotif = findViewById(R.id.tvPermNotif)
        tvPermLocation = findViewById(R.id.tvPermLocation)
        tvCounts = findViewById(R.id.tvCounts)
        switchNoSensor = findViewById(R.id.switchNoSensor)

        findViewById<MaterialButton>(R.id.btnGrant).setOnClickListener { requestPermissions() }
        findViewById<MaterialButton>(R.id.btnScan).setOnClickListener { rescan() }
        findViewById<MaterialButton>(R.id.btnTest).setOnClickListener {
            startActivity(Intent(this, TestPlayerActivity::class.java))
        }
        findViewById<MaterialButton>(R.id.btnMirror).setOnClickListener {
            startActivity(Intent(this, MirrorPlayerActivity::class.java))
        }
        findViewById<MaterialButton>(R.id.btnExport).setOnClickListener {
            startActivity(Intent(this, ExportActivity::class.java))
        }

        switchNoSensor.isChecked = Prefs.allowVideoWithoutSensor(this)
        switchNoSensor.setOnCheckedChangeListener { _, checked ->
            Prefs.setAllowVideoWithoutSensor(this, checked)
        }

        refresh()
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    // ------------------------------------------------------------------

    private fun requestPermissions() {
        val wanted = if (Build.VERSION.SDK_INT >= 33) {
            arrayOf(
                Manifest.permission.READ_MEDIA_VIDEO,
                Manifest.permission.READ_MEDIA_AUDIO,
                Manifest.permission.POST_NOTIFICATIONS,
                // Localização: trava de velocidade por GPS do Modo Espelho
                Manifest.permission.ACCESS_FINE_LOCATION,
            )
        } else {
            arrayOf(
                Manifest.permission.READ_EXTERNAL_STORAGE,
                Manifest.permission.ACCESS_FINE_LOCATION,
            )
        }
        val missing = wanted.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) return
        permLauncher.launch(missing.toTypedArray())
    }

    private fun rescan() {
        lifecycleScope.launch {
            withContext(Dispatchers.IO) {
                runCatching { MediaRegistry.rescan(this@MainActivity) }
            }
            refresh()
        }
    }

    private fun refresh() {
        fun mark(granted: Boolean): String =
            if (granted) getString(R.string.status_ok) else getString(R.string.status_missing)

        tvPermVideo.text = "${getString(R.string.perm_video)} — " +
            mark(has(Manifest.permission.READ_MEDIA_VIDEO) || has(Manifest.permission.READ_EXTERNAL_STORAGE))
        tvPermAudio.text = "${getString(R.string.perm_audio)} — " +
            mark(has(Manifest.permission.READ_MEDIA_AUDIO) || has(Manifest.permission.READ_EXTERNAL_STORAGE))
        tvPermNotif.text = "${getString(R.string.perm_notif)} — " +
            mark(has(Manifest.permission.POST_NOTIFICATIONS) || Build.VERSION.SDK_INT < 33)
        tvPermLocation.text = "${getString(R.string.perm_location)} — " +
            mark(has(Manifest.permission.ACCESS_FINE_LOCATION) ||
                has(Manifest.permission.ACCESS_COARSE_LOCATION))

        // Contagens (scan em background; primeira vez pode demorar ~1s)
        tvCounts.text = getString(R.string.scan_hint)
        lifecycleScope.launch {
            val text = withContext(Dispatchers.IO) {
                runCatching { MediaRegistry.counts(this@MainActivity) }.getOrDefault("?")
            }
            tvCounts.text = text
        }
    }

    private fun has(permission: String): Boolean =
        ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED
}
