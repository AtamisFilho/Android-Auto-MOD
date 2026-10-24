package com.atamisfilho.aircrosscockpit.util

import android.net.Uri
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Utilitários de formatação e caminhos. */
object Format {

    fun duration(ms: Long): String {
        if (ms <= 0) return "--:--"
        val totalSec = ms / 1000
        val h = totalSec / 3600
        val m = (totalSec % 3600) / 60
        val s = totalSec % 60
        return if (h > 0) String.format(Locale.US, "%d:%02d:%02d", h, m, s)
        else String.format(Locale.US, "%d:%02d", m, s)
    }

    fun bytes(size: Long): String = when {
        size >= 1 shl 30 -> String.format(Locale.US, "%.1f GB", size / 1073741824.0)
        size >= 1 shl 20 -> String.format(Locale.US, "%.1f MB", size / 1048576.0)
        size >= 1 shl 10 -> String.format(Locale.US, "%.0f KB", size / 1024.0)
        else -> "$size B"
    }

    private val dateFmt = SimpleDateFormat("dd/MM/yy HH:mm", Locale("pt", "BR"))

    fun date(epochSec: Long): String = if (epochSec <= 0) "" else dateFmt.format(Date(epochSec * 1000L))

    /** Limpa o nome do arquivo (remove extensão). */
    fun cleanTitle(raw: String?): String {
        val n = raw?.trim().orEmpty()
        if (n.isEmpty()) return "Sem título"
        val dot = n.lastIndexOf('.')
        return if (dot > 0) n.substring(0, dot) else n
    }

    fun uriLabel(uri: Uri): String = cleanTitle(uri.lastPathSegment)

    /** Caminhos possíveis das mídias do WhatsApp (herdados e armazenamento novo). */
    fun whatsappVideoDirs(root: File): List<File> = listOf(
        File(root, "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Video"),
        File(root, "WhatsApp/Media/WhatsApp Video"),
        File(root, "Android/media/com.whatsapp.w4b/WhatsApp Business/Media/WhatsApp Business Video"),
        File(root, "WhatsApp Business/Media/WhatsApp Business Video"),
    )

    fun whatsappAudioDirs(root: File): List<File> = listOf(
        File(root, "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Audio"),
        File(root, "WhatsApp/Media/WhatsApp Audio"),
        File(root, "Android/media/com.whatsapp.w4b/WhatsApp Business/Media/WhatsApp Business Audio"),
        File(root, "WhatsApp Business/Media/WhatsApp Business Audio"),
    )

    val videoExt = setOf("mp4", "3gp", "mkv", "mov", "avi", "webm")
    val audioExt = setOf("mp3", "m4a", "aac", "opus", "ogg", "wav", "amr", "flac")
}
