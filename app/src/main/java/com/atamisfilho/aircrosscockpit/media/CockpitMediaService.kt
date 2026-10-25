package com.atamisfilho.aircrosscockpit.media

import android.app.PendingIntent
import android.content.Intent
import androidx.media3.common.AudioAttributes
import androidx.media3.common.C
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.LibraryResult
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaSession
import com.atamisfilho.aircrosscockpit.phone.MainActivity
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture

/**
 * Serviço de mídia (media3 MediaLibraryService).
 *
 * É este serviço que faz o app aparecer na lista de APPS DE MÍDIA do
 * Android Auto (junto ao Spotify), com controles no volante e
 * reprodução em segundo plano via notificação.
 *
 * Biblioteca exposta: Músicas · Áudios do WhatsApp · Favoritos.
 */
class CockpitMediaService : MediaLibraryService() {

    companion object {
        private const val ROOT_ID = "root"
    }

    private var mediaSession: MediaLibrarySession? = null
    private var player: ExoPlayer? = null

    // ------------------------------------------------------------------
    // Ciclo de vida
    // ------------------------------------------------------------------

    override fun onCreate() {
        super.onCreate()

        // Scan inicial fora da main thread — a primeira navegação já acha tudo pronto.
        Thread { runCatching { MediaRegistry.ensureScanned(this) } }.start()

        val attrs = AudioAttributes.Builder()
            .setUsage(C.USAGE_MEDIA)
            .setContentType(C.AUDIO_CONTENT_TYPE_MUSIC)
            .build()

        val exo = ExoPlayer.Builder(this)
            .setAudioAttributes(attrs, /* handleAudioFocus = */ true)
            .setHandleAudioBecomingNoisy(true)
            .setWakeMode(C.WAKE_MODE_LOCAL)
            .build()

        val sessionActivity = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        mediaSession = MediaLibrarySession.Builder(this, exo, LibraryCallback())
            .setSessionActivity(sessionActivity)
            .build()

        player = exo
    }

    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaLibrarySession? =
        mediaSession

    override fun onTaskRemoved(rootIntent: Intent?) {
        val p = player
        if (p == null || !p.playWhenReady || p.mediaItemCount == 0) {
            stopSelf()
        }
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        mediaSession?.release()
        mediaSession = null
        player?.release()
        player = null
        super.onDestroy()
    }

    // ------------------------------------------------------------------
    // Itens
    // ------------------------------------------------------------------

    private fun rootItem(): MediaItem = MediaItem.Builder()
        .setMediaId(ROOT_ID)
        .setMediaMetadata(
            MediaMetadata.Builder()
                .setTitle("Aircross Cockpit")
                .setMediaType(MediaMetadata.MEDIA_TYPE_FOLDER_MIXED)
                .setIsBrowsable(true)
                .setIsPlayable(false)
                .build()
        )
        .build()

    private fun folderItem(folder: Folder): MediaItem = MediaItem.Builder()
        .setMediaId(folder.id)
        .setMediaMetadata(
            MediaMetadata.Builder()
                .setTitle(folder.title)
                .setMediaType(MediaMetadata.MEDIA_TYPE_FOLDER_MIXED)
                .setIsBrowsable(true)
                .setIsPlayable(false)
                .build()
        )
        .build()

    private fun playableItem(entry: MediaEntry): MediaItem {
        val metadata = MediaMetadata.Builder()
            .setTitle(entry.title)
            .setArtist(entry.artist ?: "")
            .setMediaType(
                if (entry.kind == MediaKind.VIDEO) MediaMetadata.MEDIA_TYPE_VIDEO
                else MediaMetadata.MEDIA_TYPE_MUSIC
            )
            .setIsBrowsable(false)
            .setIsPlayable(true)
        if (entry.durationMs > 0) metadata.setDurationMs(entry.durationMs)
        return MediaItem.Builder()
            .setMediaId(entry.id)
            .setUri(entry.uri)
            .setMediaMetadata(metadata.build())
            .build()
    }

    private fun resolvePlayable(mediaId: String): MediaItem? =
        MediaRegistry.entry(mediaId, this)?.let { playableItem(it) }

    // ------------------------------------------------------------------
    // Callbacks da biblioteca (navegação feita pelo Android Auto)
    // ------------------------------------------------------------------

    private inner class LibraryCallback : MediaLibrarySession.Callback {

        override fun onGetLibraryRoot(
            session: MediaLibrarySession,
            controller: MediaSession.ControllerInfo,
            params: MediaLibraryService.LibraryParams?,
        ): ListenableFuture<LibraryResult<MediaItem>> =
            Futures.immediateFuture(LibraryResult.ofItem(rootItem(), params))

        override fun onGetChildren(
            session: MediaLibrarySession,
            controller: MediaSession.ControllerInfo,
            parentId: String,
            page: Int,
            pageSize: Int,
            params: MediaLibraryService.LibraryParams?,
        ): ListenableFuture<LibraryResult<ImmutableList<MediaItem>>> {
            if (parentId == ROOT_ID) {
                // Pastas de áudio do app de mídia (vídeos ficam no app de tela do carro)
                val audioFolders = MediaRegistry.FOLDERS.filter { it.kind == MediaKind.AUDIO }
                val items = audioFolders.map { folderItem(it) }
                return Futures.immediateFuture(LibraryResult.ofItemList(items, params))
            }

            val folder = MediaRegistry.folder(parentId)
                ?: return Futures.immediateFuture(LibraryResult.ofError(LibraryResult.RESULT_ERROR_BAD_VALUE))

            val all = MediaRegistry.entries(parentId, this@CockpitMediaService)
                .filter { it.kind == MediaKind.AUDIO } // app de mídia = só áudio
                .map { playableItem(it) }

            val items = if (pageSize > 0) {
                val from = page * pageSize
                if (from >= all.size) emptyList() else all.subList(from, minOf(from + pageSize, all.size))
            } else {
                all.take(500)
            }
            return Futures.immediateFuture(LibraryResult.ofItemList(items, params))
        }

        override fun onGetItem(
            session: MediaLibrarySession,
            controller: MediaSession.ControllerInfo,
            mediaId: String,
        ): ListenableFuture<LibraryResult<MediaItem>> {
            val item = resolvePlayable(mediaId)
            return if (item != null) {
                Futures.immediateFuture(LibraryResult.ofItem(item, null))
            } else {
                Futures.immediateFuture(LibraryResult.ofError(LibraryResult.RESULT_ERROR_BAD_VALUE))
            }
        }

        /**
         * O Android Auto envia itens só com mediaId — resolvemos para itens
         * com URI real para o ExoPlayer poder tocar.
         */
        override fun onAddMediaItems(
            mediaSession: MediaSession,
            controller: MediaSession.ControllerInfo,
            mediaItems: MutableList<MediaItem>,
        ): ListenableFuture<MutableList<MediaItem>> {
            val resolved = mediaItems.map { requested ->
                val existing = resolvePlayable(requested.mediaId)
                existing ?: requested.takeIf { it.localConfiguration?.uri != null } ?: requested
            }
            return Futures.immediateFuture(resolved.toMutableList())
        }
    }
}
