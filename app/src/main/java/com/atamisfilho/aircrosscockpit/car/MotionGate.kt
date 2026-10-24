package com.atamisfilho.aircrosscockpit.car

import android.os.Handler
import android.os.Looper
import androidx.car.app.CarContext
import androidx.car.app.hardware.CarHardwareManager
import androidx.car.app.hardware.common.CarValue
import androidx.car.app.hardware.common.CarValueListener
import androidx.car.app.hardware.info.CarSensors
import com.atamisfilho.aircrosscockpit.CockpitApp
import com.atamisfilho.aircrosscockpit.util.Prefs
import java.util.concurrent.CopyOnWriteArraySet
import java.util.concurrent.Executor
import kotlin.math.abs

/**
 * Monitor de movimento do veículo via sensor de velocidade do Android Auto.
 *
 * O vídeo na tela do carro só é liberado com o carro PARADO (padrão de
 * segurança da plataforma). Estados:
 *  - STOPPED     → sensor OK, carro parado → vídeo liberado
 *  - MOVING      → sensor OK, carro em movimento → vídeo bloqueado
 *  - UNKNOWN     → aguardando primeira leitura do sensor
 *  - UNAVAILABLE → o carro não reporta velocidade → respeita o ajuste
 *                  "Permitir vídeo sem sensor" feito no celular
 */
object MotionGate {

    enum class State { UNKNOWN, STOPPED, MOVING, UNAVAILABLE }

    @Volatile
    var state: State = State.UNKNOWN
        private set

    private val listeners = CopyOnWriteArraySet<(State) -> Unit>()
    private val main = Handler(Looper.getMainLooper())
    private var sensors: CarSensors? = null

    /** Km/h a partir do qual consideramos o carro em movimento. */
    private const val MOVING_KMH = 3f

    private val timeout = Runnable {
        if (state == State.UNKNOWN) update(State.UNAVAILABLE)
    }

    private val speedListener = object : CarValueListener<CarValue<Float>> {
        override fun onCarValueChanged(value: CarValue<Float>) {
            val v = value.value
            when {
                value.status == CarValue.STATUS_SUCCESS && v != null ->
                    update(if (abs(v) > MOVING_KMH) State.MOVING else State.STOPPED)

                value.status == CarValue.STATUS_UNIMPLEMENTED ||
                    value.status == CarValue.STATUS_UNAVAILABLE ->
                    update(State.UNAVAILABLE)

                // STATUS_UNKNOWN: mantém o estado atual
            }
        }
    }

    fun start(carContext: CarContext) {
        stop()
        update(State.UNKNOWN)
        try {
            val hw = carContext.getCarService(CarHardwareManager::class.java)
            val s = hw.carSensors
            sensors = s
            s.addSpeedListener(Executor { it.run() }, speedListener)
        } catch (t: Throwable) {
            // Head unit sem suporte a sensores — cai para o ajuste do celular.
            update(State.UNAVAILABLE)
            return
        }
        // Se nenhuma leitura chegar, consideramos o sensor indisponível.
        main.postDelayed(timeout, 6000)
    }

    fun stop() {
        runCatching { sensors?.removeSpeedListener(speedListener) }
        sensors = null
        main.removeCallbacks(timeout)
    }

    fun addListener(listener: (State) -> Unit) {
        listeners.add(listener)
    }

    fun removeListener(listener: (State) -> Unit) {
        listeners.remove(listener)
    }

    /** Vídeo pode ser reproduzido agora? */
    fun videoAllowed(): Boolean = when (state) {
        State.STOPPED -> true
        State.UNAVAILABLE -> Prefs.allowVideoWithoutSensor(CockpitApp.get())
        State.MOVING, State.UNKNOWN -> false
    }

    private fun update(newState: State) {
        if (state == newState) return
        state = newState
        val snapshot = ArrayList(listeners)
        main.post {
            snapshot.forEach { runCatching { it(newState) } }
        }
    }
}
