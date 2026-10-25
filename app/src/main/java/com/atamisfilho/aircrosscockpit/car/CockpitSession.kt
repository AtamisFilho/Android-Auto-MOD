package com.atamisfilho.aircrosscockpit.car

import android.content.Intent
import androidx.car.app.Screen
import androidx.car.app.Session
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.atamisfilho.aircrosscockpit.media.MediaRegistry

/**
 * Sessão do app do carro: inicia o sensor de movimento e a tela inicial,
 * e libera os recursos quando o carro desconecta.
 */
class CockpitSession : Session() {

    override fun onCreateScreen(intent: Intent): Screen {
        // Limpeza quando a sessão do carro encerra (desconectou o cabo).
        lifecycle.addObserver(LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_DESTROY) {
                MotionGate.stop()
                VideoPlayerController.release()
            }
        })

        // Scan da biblioteca em background — as telas usam o resultado.
        Thread { runCatching { MediaRegistry.ensureScanned(carContext) } }.start()
        MotionGate.start(carContext)
        return HomeScreen(carContext)
    }
}
