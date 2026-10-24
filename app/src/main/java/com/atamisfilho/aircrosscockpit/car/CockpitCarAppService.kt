package com.atamisfilho.aircrosscockpit.car

import androidx.car.app.CarAppService
import androidx.car.app.Session
import androidx.car.app.SessionInfo

/**
 * Ponto de entrada do app na tela do carro (Car App Library).
 */
class CockpitCarAppService : CarAppService() {
    override fun onCreateSession(sessionInfo: SessionInfo): Session = CockpitSession()
}
