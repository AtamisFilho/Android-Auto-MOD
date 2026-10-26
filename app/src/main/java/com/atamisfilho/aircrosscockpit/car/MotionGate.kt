package com.atamisfilho.aircrosscockpit.car

import android.os.Handler
import android.os.Looper
import androidx.car.app.CarContext
import androidx.car.app.hardware.CarHardwareManager
import androidx.car.app.hardware.common.CarValue
import androidx.car.app.hardware.common.OnCarDataAvailableListener
import androidx.car.app.hardware.info.CarInfo
import androidx.car.app.hardware.info.Speed
import com.atamisfilho.aircrosscockpit.CockpitApp
import com.atamisfilho.aircrosscockpit.util.Prefs
import java.util.concurrent.CopyOnWriteArraySet
import kotlin.math.abs

/**
 * Monitor de movimento do veículo — trava de segurança do vídeo.
 *
 * Duas fontes possíveis (mesma regra: vídeo só com o carro PARADO):
 *  1. Android Auto — sensor de velocidade do carro (CarHardwareManager);
 *  2. GPS do próprio celular ([startGps]) — usado no Modo Espelho
 *     (MirrorLink), onde não existe sessão do Android Auto.
 *
 * Estados:
 *  - STOPPED     → fonte OK, carro parado → vídeo liberado
 *  - MOVING      → fonte OK, carro em movimento → vídeo bloqueado
 *  - UNKNOWN     → aguardando primeira leitura (vídeo bloqueado)
 *  - UNAVAILABLE → sem sensor/GPS disponível → respeita o ajuste
 *                  "Permitir vídeo sem sensor" feito no celular
 */
object MotionGate {

    enum class State { UNKNOWN, STOPPED, MOVING, UNAVAILABLE }

    @Volatile
    var state: State = State.UNKNOWN
        private set

    private val listeners = CopyOnWriteArraySet<(State) -> Unit>()
    private val main = Handler(Looper.getMainLooper())
    private var carInfo: CarInfo? = null
    private var gps: GpsSpeedProvider? = null

    /** Km/h a partir do qual consideramos o carro em movimento. */
    private const val MOVING_KMH = 3f

    private val timeout = Runnable {
        if (state == State.UNKNOWN) update(State.UNAVAILABLE)
    }

    private val speedListener = OnCarDataAvailableListener<Speed> { speed ->
        // rawSpeedMetersPerSecond → valor em m/s (pode ser negativo em marcha à ré)
        val raw = speed.rawSpeedMetersPerSecond
        val v = raw.value
        when {
            raw.status == CarValue.STATUS_SUCCESS && v != null -> {
                val kmh = abs(v) * 3.6f
                update(if (kmh > MOVING_KMH) State.MOVING else State.STOPPED)
            }

            raw.status == CarValue.STATUS_UNIMPLEMENTED ||
                raw.status == CarValue.STATUS_UNAVAILABLE ->
                update(State.UNAVAILABLE)

            // STATUS_UNKNOWN: mantém o estado atual
        }
    }

    fun start(carContext: CarContext) {
        stop()
        update(State.UNKNOWN)
        try {
            val hw = carContext.getCarService(CarHardwareManager::class.java)
            val info = hw.carInfo
            carInfo = info
            // Executa o callback na main thread do app do carro.
            val mainExecutor = java.util.concurrent.Executor { r -> main.post(r) }
            info.addSpeedListener(mainExecutor, speedListener)
        } catch (t: Throwable) {
            // Head unit sem suporte a sensores — cai para o ajuste do celular.
            update(State.UNAVAILABLE)
            return
        }
        // Se nenhuma leitura chegar, consideramos o sensor indisponível.
        main.postDelayed(timeout, 6000)
    }

    /**
     * Modo Espelho (MirrorLink): usa o GPS do próprio celular como fonte
     * de velocidade. Assume que não há sessão do Android Auto simultânea
     * (o carro do usuário só tem MirrorLink).
     */
    fun startGps(context: android.content.Context) {
        stop()
        update(State.UNKNOWN)
        val provider = GpsSpeedProvider(context)
        val ok = provider.start { kmh ->
            // null = ainda sem fix com velocidade → mantém UNKNOWN (bloqueado).
            if (kmh != null) {
                update(if (kmh > MOVING_KMH) State.MOVING else State.STOPPED)
            }
        }
        gps = provider
        if (!ok) {
            // Sem permissão de localização ou GPS desligado.
            update(State.UNAVAILABLE)
            return
        }
        // GPS partindo do zero (cold start) pode demorar; enquanto isso o
        // estado UNKNOWN já mantém o vídeo bloqueado. Depois de 20 s sem
        // nenhum fix, cai para UNAVAILABLE (vale o ajuste do celular).
        main.removeCallbacks(timeout)
        main.postDelayed(timeout, 20_000)
    }

    fun stop() {
        runCatching { carInfo?.removeSpeedListener(speedListener) }
        carInfo = null
        gps?.stop()
        gps = null
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
        if (Looper.myLooper() == Looper.getMainLooper()) {
            snapshot.forEach { runCatching { it(newState) } }
        } else {
            main.post {
                snapshot.forEach { runCatching { it(newState) } }
            }
        }
    }
}
