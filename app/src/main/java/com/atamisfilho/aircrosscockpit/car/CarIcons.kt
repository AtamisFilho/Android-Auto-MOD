package com.atamisfilho.aircrosscockpit.car

import androidx.car.app.CarContext
import androidx.car.app.model.CarIcon
import androidx.core.graphics.drawable.IconCompat
import com.atamisfilho.aircrosscockpit.R
import com.atamisfilho.aircrosscockpit.media.MediaEntry
import com.atamisfilho.aircrosscockpit.media.MediaKind

/** Ícones usados nas telas do carro. */
object CarIcons {

    fun fromRes(carContext: CarContext, resId: Int): CarIcon =
        CarIcon.Builder(IconCompat.createWithResource(carContext, resId)).build()

    fun forFolder(carContext: CarContext, folderId: String): CarIcon = when (folderId) {
        "wa_video", "wa_audio" -> fromRes(carContext, R.drawable.ic_folder_wa)
        "device_video" -> fromRes(carContext, R.drawable.ic_folder_video)
        "music" -> fromRes(carContext, R.drawable.ic_folder_music)
        "favorites" -> fromRes(carContext, R.drawable.ic_star)
        else -> fromRes(carContext, R.drawable.ic_folder_video)
    }

    fun forEntry(carContext: CarContext, entry: MediaEntry): CarIcon =
        if (entry.kind == MediaKind.VIDEO) fromRes(carContext, R.drawable.ic_folder_video)
        else fromRes(carContext, R.drawable.ic_folder_music)

    fun play(carContext: CarContext) = fromRes(carContext, R.drawable.ic_play)
    fun pause(carContext: CarContext) = fromRes(carContext, R.drawable.ic_pause)
    fun next(carContext: CarContext) = fromRes(carContext, R.drawable.ic_next)
    fun prev(carContext: CarContext) = fromRes(carContext, R.drawable.ic_prev)
    fun star(carContext: CarContext, filled: Boolean) =
        fromRes(carContext, if (filled) R.drawable.ic_star else R.drawable.ic_star_outline)
}
