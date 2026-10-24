package com.atamisfilho.aircrosscockpit.car

import android.Manifest
import android.content.pm.PackageManager
import androidx.car.app.CarContext
import androidx.car.app.model.Action
import androidx.car.app.model.ItemList
import androidx.car.app.model.ListTemplate
import androidx.car.app.model.Row
import androidx.car.app.model.Template
import androidx.car.app.screen.Screen
import androidx.core.content.ContextCompat
import com.atamisfilho.aircrosscockpit.media.MediaEntry
import com.atamisfilho.aircrosscockpit.media.MediaKind
import com.atamisfilho.aircrosscockpit.media.MediaRegistry
import com.atamisfilho.aircrosscockpit.util.Format

/**
 * Lista de arquivos de uma pasta (WhatsApp · Vídeos, Músicas etc.).
 * Tocar em um item abre o player com a fila inteira da pasta.
 */
class FolderScreen(
    carContext: CarContext,
    private val folderId: String,
) : Screen(carContext) {

    override fun onGetTemplate(): Template {
        val folder = MediaRegistry.folder(folderId)
        val entries = runCatching {
            MediaRegistry.entries(folderId, carContext).take(100)
        }.getOrDefault(emptyList())

        val list = ItemList.Builder()
        if (entries.isEmpty()) {
            list.addItem(
                Row.Builder()
                    .setTitle(if (hasMediaPermission(carContext)) {
                        "Nenhum arquivo nesta pasta"
                    } else {
                        "Abra o app no celular e conceda as permissões"
                    })
                    .build()
            )
        } else {
            entries.forEach { entry ->
                list.addItem(
                    Row.Builder()
                        .setTitle(entry.title)
                        .setSubtitle(subtitleFor(entry))
                        .setImage(CarIcons.forEntry(carContext, entry))
                        .setOnClickListener { onEntryClicked(entries, entry) }
                        .build()
                )
            }
        }

        return ListTemplate.Builder()
            .setHeaderAction(Action.BACK)
            .setTitle(folder?.title ?: "Arquivos")
            .setSingleList(list.build())
            .build()
    }

    private fun onEntryClicked(entries: List<MediaEntry>, entry: MediaEntry) {
        val index = entries.indexOfFirst { it.id == entry.id }.coerceAtLeast(0)
        val isVideo = entry.kind == MediaKind.VIDEO
        // Vídeo começa tocando apenas se o carro estiver parado.
        val autoPlay = !isVideo || MotionGate.videoAllowed()
        VideoPlayerController.playQueue(entries, index, autoPlay = autoPlay)
        push(PlayerScreen(carContext, folderId))
    }

    private fun subtitleFor(entry: MediaEntry): String {
        val parts = ArrayList<String>()
        if (entry.durationMs > 0) parts.add(Format.duration(entry.durationMs))
        parts.add(Format.bytes(entry.sizeBytes))
        entry.dateModifiedSec.takeIf { it > 0 }?.let { parts.add(Format.date(it)) }
        return parts.joinToString(" · ")
    }

    companion object {
        fun hasMediaPermission(carContext: CarContext): Boolean {
            val video = ContextCompat.checkSelfPermission(
                carContext, Manifest.permission.READ_MEDIA_VIDEO) ==
                PackageManager.PERMISSION_GRANTED
            val audio = ContextCompat.checkSelfPermission(
                carContext, Manifest.permission.READ_MEDIA_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
            val legacy = ContextCompat.checkSelfPermission(
                carContext, Manifest.permission.READ_EXTERNAL_STORAGE) ==
                PackageManager.PERMISSION_GRANTED
            return (video && audio) || legacy
        }
    }
}
