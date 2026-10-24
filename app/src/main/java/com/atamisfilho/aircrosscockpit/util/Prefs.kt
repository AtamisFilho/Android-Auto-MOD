package com.atamisfilho.aircrosscockpit.util

import android.content.Context
import android.content.SharedPreferences

/**
 * Preferências persistentes: favoritos, posições de reprodução e ajustes.
 */
object Prefs {
    private const val FILE = "cockpit_prefs"

    private fun sp(context: Context): SharedPreferences =
        context.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    // ---------- Favoritos ----------

    fun favorites(context: Context): MutableSet<String> =
        sp(context).getStringSet("favorites", emptySet())?.toMutableSet() ?: mutableSetOf()

    fun isFavorite(context: Context, mediaId: String): Boolean =
        favorites(context).contains(mediaId)

    fun toggleFavorite(context: Context, mediaId: String): Boolean {
        val set = favorites(context)
        val added = if (set.contains(mediaId)) {
            set.remove(mediaId)
            false
        } else {
            set.add(mediaId)
            true
        }
        sp(context).edit().putStringSet("favorites", set).apply()
        return added
    }

    // ---------- Posição de reprodução (retomar de onde parou) ----------

    fun savedPosition(context: Context, mediaId: String): Long =
        sp(context).getLong("pos:$mediaId", 0L)

    fun savePosition(context: Context, mediaId: String, positionMs: Long) {
        sp(context).edit().putLong("pos:$mediaId", positionMs).apply()
    }

    // ---------- Ajustes ----------

    /**
     * Se true, permite reproduzir vídeo mesmo quando o sensor de velocidade
     * do carro estiver indisponível (não recomendado).
     */
    fun allowVideoWithoutSensor(context: Context): Boolean =
        sp(context).getBoolean("no_sensor_mode", false)

    fun setAllowVideoWithoutSensor(context: Context, value: Boolean) {
        sp(context).edit().putBoolean("no_sensor_mode", value).apply()
    }
}
