package com.atamisfilho.aircrosscockpit.car

import android.content.Intent
import androidx.car.app.Session
import com.atamisfilho.aircrosscockpit.media.MediaRegistry

/**
 * Sessão do app do carro: inicia o sensor de movimento e a tela inicial,
 * e libera os recursos quando o carro desconecta.
 */
class CockpitSession : Session() {

    override fun onCreateScreen(intent: Intent): androidx.car.app.Screen {
        // Scan da biblioteca em background — as telas usam o resultado.
        Thread { runCatching { MediaRegistry.ensureScanned(carContext) } }.start()
        MotionGate.start(carContext)
        return HomeScreen(carContext)
    }

    override fun onDestroy() {
        MotionGate.stop()
        VideoPlayerController.release()
        super.onDestroy()
    }
}
