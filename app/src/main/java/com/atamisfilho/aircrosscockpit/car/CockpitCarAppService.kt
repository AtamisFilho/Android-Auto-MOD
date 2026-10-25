package com.atamisfilho.aircrosscockpit.car

import androidx.car.app.CarAppService
import androidx.car.app.Session
import androidx.car.app.SessionInfo
import androidx.car.app.validation.HostValidator

/**
 * Ponto de entrada do app na tela do carro (Car App Library).
 */
class CockpitCarAppService : CarAppService() {

    /**
     * App pessoal (sideload): aceita qualquer host do Android Auto.
     * O validador padrão (DefaultHostValidator) só é recomendado para
     * apps publicados na Play Store.
     */
    override fun createHostValidator(): HostValidator =
        HostValidator.ALLOW_ALL_HOSTS_VALIDATOR

    override fun onCreateSession(sessionInfo: SessionInfo): Session = CockpitSession()

    override fun onDestroy() {
        // Garantia extra de limpeza quando o Android Auto desvincula o app.
        MotionGate.stop()
        VideoPlayerController.release()
        super.onDestroy()
    }
}
