package com.atamisfilho.aircrosscockpit.car

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import androidx.core.content.ContextCompat

/**
 * Fonte de velocidade por GPS para o Modo Espelho (MirrorLink).
 *
 * No Android Auto a velocidade vem do sensor do carro via [MotionGate]/
 * CarHardwareManager. No espelhamento MirrorLink não existe Android Auto:
 * o carro só mostra a tela do celular. Então a trava de segurança precisa
 * vir do próprio celular — velocidade calculada a cada fix do GPS.
 *
 * Importante (compatibilidade com Android 9/10): o [LocationListener] é
 * implementado como objeto explícito com TODOS os métodos, porque em
 * APIs anteriores à 31 os demais métodos são abstratos e um lambda
 * SAM causaria AbstractMethodError em celulares antigos.
 */
class GpsSpeedProvider(private val context: Context) {

    private var lm: LocationManager? = null
    private var callback: ((Float?) -> Unit)? = null

    /** Última velocidade conhecida em km/h (ou null enquanto sem fix). */
    @Volatile
    var lastKnownKmh: Float? = null
        private set

    private val locationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            val cb = callback ?: return
            // Só confia em fixes com velocidade declarada (hasSpeed);
            // sem isso o valor pode ser 0 mesmo com o carro em movimento.
            val kmh = if (location.hasSpeed()) {
                (location.speed * 3.6f).coerceAtLeast(0f)
            } else {
                null
            }
            if (kmh != null) lastKnownKmh = kmh
            cb(kmh)
        }

        @Deprecated("Deprecated in Java")
        override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}

        override fun onProviderEnabled(provider: String) {}

        override fun onProviderDisabled(provider: String) {}
    }

    /**
     * Inicia as atualizações de localização.
     * @param onSpeed km/h do fix (ou null = ainda sem leitura utilizável)
     * @return false quando não há permissão de localização ou o GPS está
     *         desligado (nesse caso o [MotionGate] assume UNAVAILABLE e
     *         respeita o ajuste "permitir vídeo sem sensor").
     */
    fun start(onSpeed: (Float?) -> Unit): Boolean {
        callback = onSpeed
        val fine = ContextCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
        val coarse = ContextCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_COARSE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED
        if (!fine && !coarse) return false

        val manager = context.getSystemService(LocationManager::class.java) ?: return false
        if (!manager.isProviderEnabled(LocationManager.GPS_PROVIDER) &&
            !manager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        ) return false

        return try {
            manager.requestLocationUpdates(
                LocationManager.GPS_PROVIDER,
                1000L, // 1 s — resolvido rápido o suficiente p/ um vídeo não "escapar"
                0f,
                locationListener,
            )
            lm = manager
            true
        } catch (t: Throwable) {
            false
        }
    }

    fun stop() {
        runCatching { lm?.removeUpdates(locationListener) }
        lm = null
        callback = null
    }
}
