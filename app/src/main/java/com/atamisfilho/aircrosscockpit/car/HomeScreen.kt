package com.atamisfilho.aircrosscockpit.car

import androidx.car.app.CarContext
import androidx.car.app.model.Action
import androidx.car.app.model.GridItem
import androidx.car.app.model.GridTemplate
import androidx.car.app.model.ItemList
import androidx.car.app.model.Template
import androidx.car.app.screen.Screen
import com.atamisfilho.aircrosscockpit.media.MediaRegistry

/**
 * Tela inicial do app no carro: grade com as pastas da biblioteca.
 */
class HomeScreen(carContext: CarContext) : Screen(carContext) {

    override fun onGetTemplate(): Template {
        val list = ItemList.Builder()
        MediaRegistry.FOLDERS.forEach { folder ->
            val count = runCatching {
                MediaRegistry.entries(folder.id, carContext).size
            }.getOrDefault(0)

            list.addItem(
                GridItem.Builder()
                    .setTitle("${folder.title} ($count)")
                    .setImage(CarIcons.forFolder(carContext, folder.id))
                    .setOnClickListener { push(FolderScreen(carContext, folder.id)) }
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
