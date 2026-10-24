package com.atamisfilho.aircrosscockpit.media

import android.content.ContentUris
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import com.atamisfilho.aircrosscockpit.CockpitApp
import com.atamisfilho.aircrosscockpit.util.Format
import java.io.File

/** Tipo de mídia. */
enum class MediaKind { VIDEO, AUDIO }

/** Uma pasta virtual da biblioteca (ex.: "WhatsApp • Vídeos"). */
data class Folder(
    val id: String,
    val title: String,
    val kind: MediaKind,
    /** true = ordenar por mais recentes primeiro (WhatsApp) */
    val recentFirst: Boolean,
)

/** Uma mídia reproduzível. */
data class MediaEntry(
    val id: String,
    val uri: Uri,
    val title: String,
    val artist: String?,
    val kind: MediaKind,
    val durationMs: Long,
    val sizeBytes: Long,
    val dateModifiedSec: Long,
    val folderId: String,
)

/**
 * Índice central de toda a biblioteca do aparelho:
 *  - Músicas (MediaStore · áudio)
 *  - Vídeos do aparelho (MediaStore · vídeo)
 *  - Vídeos e áudios recebidos no WhatsApp (varredura direta das pastas)
 *
 * O scan roda uma única vez (sob lock) e é cacheado em memória.
 * mediaId = "v|a:" + URI, o que gera IDs estáveis entre o app do carro,
 * o serviço de mídia e o testador do celular.
 */
object MediaRegistry {

    val FOLDERS = listOf(
        Folder("wa_video", "WhatsApp · Vídeos", MediaKind.VIDEO, recentFirst = true),
        Folder("wa_audio", "WhatsApp · Áudios", MediaKind.AUDIO, recentFirst = true),
        Folder("device_video", "Vídeos do celular", MediaKind.VIDEO, recentFirst = true),
        Folder("music", "Músicas", MediaKind.AUDIO, recentFirst = false),
        Folder("favorites", "Favoritos", MediaKind.AUDIO, recentFirst = false),
    )

    @Volatile
    private var scanned = false

    private val entriesByFolder = HashMap<String, MutableList<MediaEntry>>()
    private val entryById = HashMap<String, MediaEntry>()

    @Synchronized
    private fun doScan(context: Context) {
        entriesByFolder.clear()
        entryById.clear()
        val app = context.applicationContext

        scanMediaStoreVideo(app)
        scanMediaStoreAudio(app)
        scanWhatsappFiles(app)
        scanned = true
    }

    /** Garante que o scan foi feito. Chamar de thread de background (IO). */
    fun ensureScanned(context: Context) {
        if (!scanned) doScan(context)
    }

    /** Reescaneia agora (botão "Escanear novamente"). */
    fun rescan(context: Context) {
        synchronized(this) { scanned = false }
        ensureScanned(context)
    }

    fun folder(id: String): Folder? = FOLDERS.firstOrNull { it.id == id }

    fun entries(folderId: String, context: Context): List<MediaEntry> {
        ensureScanned(context)
        if (folderId == "favorites") {
            val favIds = com.atamisfilho.aircrosscockpit.util.Prefs.favorites(context)
            val favs = favIds.mapNotNull { entryById[it] }
                .sortedByDescending { it.dateModifiedSec }
            return favs
        }
        val list = entriesByFolder[folderId] ?: return emptyList()
        return list
    }

    fun entry(mediaId: String, context: Context): MediaEntry? {
        ensureScanned(context)
        return entryById[mediaId]
    }

    fun counts(context: Context): String {
        ensureScanned(context)
        val music = entriesByFolder["music"]?.size ?: 0
        val dv = entriesByFolder["device_video"]?.size ?: 0
        val wav = entriesByFolder["wa_video"]?.size ?: 0
        val waa = entriesByFolder["wa_audio"]?.size ?: 0
        return "Músicas: $music · Vídeos: $dv · Vídeos do WhatsApp: $wav · Áudios do WhatsApp: $waa"
    }

    // ------------------------------------------------------------------
    // MediaStore
    // ------------------------------------------------------------------

    private fun scanMediaStoreVideo(context: Context) {
        val out = ArrayList<MediaEntry>()
        val cr = context.contentResolver
        val projection = arrayOf(
            MediaStore.Video.Media._ID,
            MediaStore.Video.Media.DISPLAY_NAME,
            MediaStore.Video.Media.DURATION,
            MediaStore.Video.Media.SIZE,
            MediaStore.Video.Media.DATE_MODIFIED,
        )
        cr.query(
            MediaStore.Video.Media.EXTERNAL_CONTENT_URI,
            projection, null, null,
            "${MediaStore.Video.Media.DATE_MODIFIED} DESC"
        )?.use { c ->
            val iId = c.getColumnIndexOrThrow(MediaStore.Video.Media._ID)
            val iName = c.getColumnIndexOrThrow(MediaStore.Video.Media.DISPLAY_NAME)
            val iDur = c.getColumnIndexOrThrow(MediaStore.Video.Media.DURATION)
            val iSize = c.getColumnIndexOrThrow(MediaStore.Video.Media.SIZE)
            val iDate = c.getColumnIndexOrThrow(MediaStore.Video.Media.DATE_MODIFIED)
            while (c.moveToNext()) {
                val uri = ContentUris.withAppendedId(
                    MediaStore.Video.Media.EXTERNAL_CONTENT_URI, c.getLong(iId))
                val entry = MediaEntry(
                    id = "v:${uri}",
                    uri = uri,
                    title = Format.cleanTitle(c.getString(iName)),
                    artist = null,
                    kind = MediaKind.VIDEO,
                    durationMs = c.getLong(iDur),
                    sizeBytes = c.getLong(iSize),
                    dateModifiedSec = c.getLong(iDate),
                    folderId = "device_video",
                )
                out.add(entry)
            }
        }
        entriesByFolder["device_video"] = out
        out.forEach { entryById[it.id] = it }
    }

    private fun scanMediaStoreAudio(context: Context) {
        val out = ArrayList<MediaEntry>()
        val cr = context.contentResolver
        val projection = arrayOf(
            MediaStore.Audio.Media._ID,
            MediaStore.Audio.Media.DISPLAY_NAME,
            MediaStore.Audio.Media.DURATION,
            MediaStore.Audio.Media.SIZE,
            MediaStore.Audio.Media.DATE_MODIFIED,
            MediaStore.Audio.Media.ARTIST,
        )
        // Ignora sons muito curtos (clipes de sistema/ringtones)
        val selection = "${MediaStore.Audio.Media.DURATION} >= 15000"
        cr.query(
            MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,
            projection, selection, null,
            "${MediaStore.Audio.Media.TITLE} ASC"
        )?.use { c ->
            val iId = c.getColumnIndexOrThrow(MediaStore.Audio.Media._ID)
            val iName = c.getColumnIndexOrThrow(MediaStore.Audio.Media.DISPLAY_NAME)
            val iDur = c.getColumnIndexOrThrow(MediaStore.Audio.Media.DURATION)
            val iSize = c.getColumnIndexOrThrow(MediaStore.Audio.Media.SIZE)
            val iDate = c.getColumnIndexOrThrow(MediaStore.Audio.Media.DATE_MODIFIED)
            val iArtist = c.getColumnIndexOrThrow(MediaStore.Audio.Media.ARTIST)
            while (c.moveToNext()) {
                val uri = ContentUris.withAppendedId(
                    MediaStore.Audio.Media.EXTERNAL_CONTENT_URI, c.getLong(iId))
                val entry = MediaEntry(
                    id = "a:${uri}",
                    uri = uri,
                    title = Format.cleanTitle(c.getString(iName)),
                    artist = c.getString(iArtist),
                    kind = MediaKind.AUDIO,
                    durationMs = c.getLong(iDur),
                    sizeBytes = c.getLong(iSize),
                    dateModifiedSec = c.getLong(iDate),
                    folderId = "music",
                )
                out.add(entry)
            }
        }
        entriesByFolder["music"] = out
        out.forEach { entryById[it.id] = it }
    }

    // ------------------------------------------------------------------
    // Pastas do WhatsApp (varredura direta de arquivos)
    // ------------------------------------------------------------------

    private fun scanWhatsappFiles(context: Context) {
        val root = Environment.getExternalStorageDirectory()
        entriesByFolder["wa_video"] = scanDirs(Format.whatsappVideoDirs(root), MediaKind.VIDEO, "wa_video", context)
        entriesByFolder["wa_audio"] = scanDirs(Format.whatsappAudioDirs(root), MediaKind.AUDIO, "wa_audio", context)
    }

    private fun scanDirs(
        dirs: List<File>,
        kind: MediaKind,
        folderId: String,
        context: Context,
    ): MutableList<MediaEntry> {
        val out = ArrayList<MediaEntry>()
        for (dir in dirs) {
            if (!dir.exists() || !dir.isDirectory) continue
            walk(dir, maxDepth = 3, maxFiles = 2000, collected = out) { file ->
                val ext = file.extension.lowercase()
                val ok = if (kind == MediaKind.VIDEO) ext in Format.videoExt else ext in Format.audioExt
                if (!ok) return@walk
                val uri = Uri.fromFile(file)
                val id = "${if (kind == MediaKind.VIDEO) "v" else "a"}:${uri}"
                val entry = MediaEntry(
                    id = id,
                    uri = uri,
                    title = Format.cleanTitle(file.name),
                    artist = "WhatsApp",
                    kind = kind,
                    durationMs = 0L, // resolvido na hora da reprodução
                    sizeBytes = file.length(),
                    dateModifiedSec = file.lastModified() / 1000L,
                    folderId = folderId,
                )
                out.add(entry)
            }
        }
        // Mais recentes primeiro
        out.sortByDescending { it.dateModifiedSec }
        out.forEach { entryById[it.id] = it }
        return out
    }

    private fun walk(dir: File, maxDepth: Int, maxFiles: Int, collected: ArrayList<MediaEntry>, onFile: (File) -> Unit) {
        if (maxDepth < 0 || collected.size >= maxFiles) return
        val files = dir.listFiles() ?: return
        for (f in files) {
            if (collected.size >= maxFiles) return
            if (f.isDirectory) {
                walk(f, maxDepth - 1, maxFiles, collected, onFile)
            } else {
                onFile(f)
            }
        }
    }

    /** Conveniência: contexto global do app. */
    fun appContext(): Context = CockpitApp.get()
}
