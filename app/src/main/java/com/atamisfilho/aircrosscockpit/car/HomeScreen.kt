package com.atamisfilho.aircrosscockpit.car

import android.os.Handler
import android.os.Looper
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.model.Action
import androidx.car.app.model.GridItem
import androidx.car.app.model.GridTemplate
import androidx.car.app.model.ItemList
import androidx.car.app.model.Template
import com.atamisfilho.aircrosscockpit.media.MediaRegistry

/**
 * Tela inicial do app no carro: grade com as pastas da biblioteca.
 */
class HomeScreen(carContext: CarContext) : Screen(carContext) {

    private val main = Handler(Looper.getMainLooper())

    override fun onGetTemplate(): Template {
        // Primeiro acesso antes do scan terminar → mostra "carregando"
        // e dispara o scan em background (nunca na main thread).
        if (!MediaRegistry.isScanned()) {
            Thread {
                runCatching { MediaRegistry.ensureScanned(carContext) }
                main.post { runCatching { invalidate() } }
            }.start()
            return GridTemplate.Builder()
                .setHeaderAction(Action.APP_ICON)
                .setTitle("Aircross Cockpit")
                .setLoading(true)
                .build()
        }

        val list = ItemList.Builder()
        MediaRegistry.FOLDERS.forEach { folder ->
            val count = runCatching {
                MediaRegistry.entries(folder.id, carContext).size
            }.getOrDefault(0)

            list.addItem(
                GridItem.Builder()
                    .setTitle("${folder.title} ($count)")
                    .setImage(CarIcons.forFolder(carContext, folder.id))
                    .setOnClickListener {
                        screenManager.push(FolderScreen(carContext, folder.id))
                    }
                    .build()
            )
        }
        return GridTemplate.Builder()
            .setHeaderAction(Action.APP_ICON)
            .setTitle("Aircross Cockpit")
            .setSingleList(list.build())
            .build()
    }
}
