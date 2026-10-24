package com.atamisfilho.aircrosscockpit.car

import android.view.Surface
import androidx.car.app.CarContext
import androidx.car.app.model.Action
import androidx.car.app.model.ActionStrip
import androidx.car.app.model.MessageTemplate
import androidx.car.app.model.SurfaceCallback
import androidx.car.app.model.SurfaceTemplate
import androidx.car.app.model.Template
import androidx.car.app.screen.Screen
import com.atamisfilho.aircrosscockpit.media.MediaKind
import com.atamisfilho.aircrosscockpit.util.Format

/**
 * Tela do player: vídeo em TELA CHEIA na Surface do carro (com recorte)
 * + faixa de ações (anterior, play/pause, próximo, favorito) e título
 * com o progresso, atualizado a cada segundo.
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

    private val changeListener = {
        runCatching { invalidate() }
    }

    override fun onGetTemplate(): Template {
        if (!registered) {
            VideoPlayerController.onChange = changeListener
            registered = true
        }

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

        // Player normal com vídeo em tela cheia.
        val pos = VideoPlayerController.positionMs()
        val dur = VideoPlayerController.durationMs()
        val playing = VideoPlayerController.isPlaying()
        val title = "${if (playing) "▶" else "❚❚"} ${Format.duration(pos)} / ${Format.duration(dur)} · ${entry.title}"

        return SurfaceTemplate.Builder()
            .setHeaderAction(Action.BACK)
            .setTitle(title)
            .setActionStrip(actionStrip())
            .setSurfaceCallback(object : SurfaceCallback {
                override fun onSurfaceAvailable(surface: Surface) {
                    VideoPlayerController.setSurface(surface)
                }

                override fun onSurfaceDestroyed(surface: Surface) {
                    VideoPlayerController.setSurface(null)
                }
            })
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

    override fun onDestroy() {
        if (registered) {
            VideoPlayerController.onChange = null
            registered = false
        }
        super.onDestroy()
    }
}
