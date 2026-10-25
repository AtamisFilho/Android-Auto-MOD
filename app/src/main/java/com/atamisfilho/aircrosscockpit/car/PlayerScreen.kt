package com.atamisfilho.aircrosscockpit.car

import androidx.car.app.AppManager
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.SurfaceCallback
import androidx.car.app.SurfaceContainer
import androidx.car.app.model.Action
import androidx.car.app.model.ActionStrip
import androidx.car.app.model.MessageTemplate
import androidx.car.app.model.Template
import androidx.car.app.navigation.model.MessageInfo
import androidx.car.app.navigation.model.NavigationTemplate
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.atamisfilho.aircrosscockpit.media.MediaKind
import com.atamisfilho.aircrosscockpit.util.Format

/**
 * Tela do player: vídeo na Surface em TELA CHEIA do carro (NavigationTemplate)
 * + faixa de ações (anterior, play/pause, próximo, favorito) e cartão de
 * informações com o progresso, atualizado a cada segundo.
 *
 * Como obter a Surface: apps da categoria NAVIGATION recebem uma área de
 * desenho em tela cheia; ela é entregue pelo host via
 * AppManager.setSurfaceCallback(SurfaceCallback) — é o mesmo mecanismo usado
 * pelos apps de vídeo do Android Auto (ex.: Fermata).
 *
 * Regras de segurança:
 *  - vídeo só com o carro PARADO (sensor de velocidade);
 *  - ao entrar em movimento, o vídeo pausa automaticamente.
 */
class PlayerScreen(
    carContext: CarContext,
    private val folderId: String,
) : Screen(carContext) {

    private var registered = false

    private val changeListener: () -> Unit = {
        runCatching { invalidate() }
    }

    /** Recebe a Surface em tela cheia do host do Android Auto. */
    private val surfaceCallback = object : SurfaceCallback {
        override fun onSurfaceAvailable(surfaceContainer: SurfaceContainer) {
            VideoPlayerController.setSurface(surfaceContainer.surface)
        }

        override fun onSurfaceDestroyed(surfaceContainer: SurfaceContainer) {
            VideoPlayerController.setSurface(null)
        }
    }

    init {
        // Limpa o callback da Surface ao sair da tela do player.
        lifecycle.addObserver(LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_DESTROY) {
                unregister()
            }
        })
    }

    private fun registerIfNeeded() {
        if (!registered) {
            VideoPlayerController.onChange = changeListener
            carContext.getCarService(AppManager::class.java)
                .setSurfaceCallback(surfaceCallback)
            registered = true
        }
    }

    private fun unregister() {
        if (registered) {
            VideoPlayerController.onChange = null
            VideoPlayerController.setSurface(null)
            runCatching {
                carContext.getCarService(AppManager::class.java)
                    .setSurfaceCallback(null)
            }
            registered = false
        }
    }

    override fun onGetTemplate(): Template {
        registerIfNeeded()

        val entry = VideoPlayerController.currentEntry()

        // Nada tocando → volta ao estado inicial.
        if (entry == null) {
            return MessageTemplate.Builder("Nada está tocando.")
                .setHeaderAction(Action.BACK)
                .setTitle("Player")
                .addAction(
                    Action.Builder()
                        .setTitle("Abrir arquivos")
                        .setOnClickListener { finish() }
                        .build()
                )
                .build()
        }

        // Vídeo bloqueado (carro em movimento ou sensor aguardando).
        val isVideo = entry.kind == MediaKind.VIDEO
        if (isVideo && !MotionGate.videoAllowed()) {
            val motivo = when (MotionGate.state) {
                MotionGate.State.MOVING ->
                    "O carro está em movimento. O vídeo pausou por segurança e volta quando você parar."
                MotionGate.State.UNKNOWN ->
                    "Aguardando o sensor de velocidade do carro…"
                MotionGate.State.UNAVAILABLE ->
                    "Este carro não reporta velocidade. Libere nas configurações do app no celular ou use somente parado."
                MotionGate.State.STOPPED -> ""
            }
            return MessageTemplate.Builder(motivo)
                .setHeaderAction(Action.BACK)
                .setTitle("Vídeo pausado")
                .addAction(
                    Action.Builder()
                        .setTitle("Tentar de novo")
                        .setOnClickListener { VideoPlayerController.play(); invalidate() }
                        .build()
                )
                .addAction(
                    Action.Builder()
                        .setTitle("Ver arquivos")
                        .setOnClickListener { finish() }
                        .build()
                )
                .build()
        }

        // Player normal: vídeo/áudio na Surface em tela cheia + informações.
        val pos = VideoPlayerController.positionMs()
        val dur = VideoPlayerController.durationMs()
        val playing = VideoPlayerController.isPlaying()
        val symbol = if (playing) "▶" else "❚❚"
        val subtitle = buildString {
            append("${symbol} ${Format.duration(pos)} / ${Format.duration(dur)}")
            entry.artist?.let { append(" · $it") }
        }

        return NavigationTemplate.Builder()
            .setNavigationInfo(
                MessageInfo.Builder(entry.title)
                    .setText(subtitle)
                    .build()
            )
            .setActionStrip(actionStrip())
            .build()
    }

    private fun actionStrip(): ActionStrip {
        val builder = ActionStrip.Builder()
            .addAction(
                Action.Builder()
                    .setIcon(CarIcons.prev(carContext))
                    .setOnClickListener { VideoPlayerController.previous() }
                    .build()
            )
            .addAction(
                Action.Builder()
                    .setIcon(
                        if (VideoPlayerController.isPlaying()) CarIcons.pause(carContext)
                        else CarIcons.play(carContext)
                    )
                    .setOnClickListener { VideoPlayerController.togglePlayPause() }
                    .build()
            )
            .addAction(
                Action.Builder()
                    .setIcon(CarIcons.next(carContext))
                    .setOnClickListener { VideoPlayerController.next() }
                    .build()
            )
            .addAction(
                Action.Builder()
                    .setIcon(CarIcons.star(carContext, VideoPlayerController.isFavorite()))
                    .setOnClickListener { VideoPlayerController.toggleFavorite() }
                    .build()
            )
        return builder.build()
    }
}
