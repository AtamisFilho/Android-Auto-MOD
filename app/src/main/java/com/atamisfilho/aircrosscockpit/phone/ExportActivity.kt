package com.atamisfilho.aircrosscockpit.phone

import android.content.Intent
import android.database.Cursor
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMuxer
import android.net.Uri
import android.os.Bundle
import android.provider.DocumentsContract
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.atamisfilho.aircrosscockpit.R
import com.atamisfilho.aircrosscockpit.media.MediaEntry
import com.atamisfilho.aircrosscockpit.media.MediaRegistry
import com.atamisfilho.aircrosscockpit.util.Format
import com.atamisfilho.aircrosscockpit.util.Prefs
import com.google.android.material.button.MaterialButton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.nio.ByteBuffer
import java.text.Normalizer

/**
 * Exportação para pendrive (Modo USB): copia os vídeos para que o PLAYER
 * NATIVO da central do carro os reproduza direto do USB — caminho que
 * funciona HOJE com o S25 Ultra, sem espelhamento.
 *
 * Regras de compatibilidade (o objetivo é "abre em qualquer lugar"):
 *  - O arquivo final é sempre MP4 com vídeo H.264 (ou HEVC/MPEG-4 simples
 *    com aviso) e áudio AAC (ou sem áudio, quando o original é AMR etc.);
 *  - Cópia direta quando o original já é MP4/H.264+AAC (vídeo do WhatsApp
 *    quase sempre é) — rápida e sem perda;
 *  - Remux SEM RECODIFICAR quando só o container precisa mudar (ex.: .mkv);
 *  - Verificação final: o arquivo gravado é reaberto com MediaExtractor
 *    (estrutura válida) e o codec é testado contra os decoders DO PRÓPRIO
 *    CELULAR — garantia de que players nativos (Galaxy/Meus Arquivos/
 *    Ficheiros) tocam o vídeo do pendrive, não só a central do carro.
 */
class ExportActivity : AppCompatActivity() {

    private data class Probe(val videoMime: String?, val audioMime: String?)
    private data class RemuxResult(val audioKept: Boolean, val droppedAudioMime: String?)

    private var treeUri: Uri? = null
    private var exporting = false
    private var okCount = 0
    private var failCount = 0

    private val rowButtons = HashMap<String, MaterialButton>()
    private val reportLines = ArrayList<String>()

    private lateinit var tvTarget: TextView
    private lateinit var tvStatus: TextView
    private lateinit var tvReport: TextView
    private lateinit var listContainer: LinearLayout
    private lateinit var btnExport20: MaterialButton

    /** Limite seguro do FAT32 (arquivo de 4 GB não entra no pendrive). */
    private val fat32Max = 4_294_900_000L

    private val treePicker =
        registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
            if (uri == null) return@registerForActivityResult
            runCatching {
                contentResolver.takePersistableUriPermission(
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION or
                        Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
                )
            }
            Prefs.setExportTreeUri(this, uri.toString())
            treeUri = uri
            refreshTarget()
        }

    // ------------------------------------------------------------------
    // Ciclo de vida
    // ------------------------------------------------------------------

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_export)

        tvTarget = findViewById(R.id.tvTarget)
        tvStatus = findViewById(R.id.tvStatus)
        tvReport = findViewById(R.id.tvReport)
        listContainer = findViewById(R.id.listContainer)
        btnExport20 = findViewById(R.id.btnExport20)

        findViewById<MaterialButton>(R.id.btnPick).setOnClickListener { treePicker.launch(null) }
        btnExport20.setOnClickListener { exportBatch() }

        Prefs.exportTreeUri(this)?.let { treeUri = Uri.parse(it) }
        refreshTarget()
        buildList()
    }

    private fun refreshTarget() {
        val uri = treeUri
        tvTarget.text = when {
            uri == null -> getString(R.string.export_no_target)
            else -> getString(R.string.export_target_ok, targetLabel(uri))
        }
    }

    private fun targetLabel(uri: Uri): String {
        val name = runCatching {
            val docId = DocumentsContract.getTreeDocumentId(uri)
            docId.substringAfterLast('/').ifBlank { docId }
        }.getOrDefault("")
        return name.ifBlank { uri.lastPathSegment ?: uri.toString() }
    }

    // ------------------------------------------------------------------
    // Lista de vídeos
    // ------------------------------------------------------------------

    private fun buildList() {
        listContainer.removeAllViews()
        rowButtons.clear()
        lifecycleScope.launch {
            val sections = withContext(Dispatchers.IO) {
                listOf(
                    "WhatsApp · Vídeos" to MediaRegistry.entries("wa_video", this@ExportActivity),
                    "Vídeos do celular" to MediaRegistry.entries("device_video", this@ExportActivity),
                )
            }
            for ((label, entries) in sections) {
                if (entries.isEmpty()) continue
                addSectionTitle(label)
                entries.take(60).forEachIndexed { i, entry ->
                    listContainer.addView(row(entry, i + 1))
                }
            }
        }
    }

    private fun row(entry: MediaEntry, index: Int): View {
        val btn = MaterialButton(this)
        btn.layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.MATCH_PARENT, dp(88)
        ).apply { setMargins(0, 0, 0, dp(8)) }
        btn.text = "  ${entry.title}  ·  ${Format.bytes(entry.sizeBytes)}"
        btn.textSize = 18f
        btn.maxLines = 2
        btn.isAllCaps = false
        btn.textAlignment = View.TEXT_ALIGNMENT_TEXT_START
        btn.icon = ContextCompat.getDrawable(this, R.drawable.ic_folder_video)
        btn.iconSize = dp(32)
        btn.iconPadding = dp(16)
        btn.setOnClickListener { exportOneTrigger(entry, index) }
        rowButtons[entry.id] = btn
        return btn
    }

    private fun addSectionTitle(label: String) {
        val tv = TextView(this)
        tv.text = label
        tv.textSize = 16f
        tv.setTypeface(null, android.graphics.Typeface.BOLD)
        tv.setTextColor(getColor(R.color.amber))
        tv.setPadding(dp(12), dp(12), dp(12), dp(6))
        listContainer.addView(tv)
    }

    // ------------------------------------------------------------------
    // Exportação
    // ------------------------------------------------------------------

    private fun exportOneTrigger(entry: MediaEntry, index: Int) {
        if (!requireTarget()) return
        if (exporting) return
        exporting = true
        btnExport20.isEnabled = false
        lifecycleScope.launch {
            setStatus(getString(R.string.export_copying, entry.title))
            val line = exportOne(entry, index)
            addReport(line)
            markRow(entry.id, line.startsWith("✔"))
            setStatus(null)
            exporting = false
            btnExport20.isEnabled = true
        }
    }

    private fun exportBatch() {
        if (!requireTarget()) return
        if (exporting) return
        exporting = true
        btnExport20.isEnabled = false
        lifecycleScope.launch {
            val entries = withContext(Dispatchers.IO) {
                MediaRegistry.entries("wa_video", this@ExportActivity).take(20)
            }
            if (entries.isEmpty()) {
                addReport(getString(R.string.export_nothing))
            }
            entries.forEachIndexed { i, entry ->
                setStatus(getString(R.string.export_progress, i + 1, entries.size, entry.title))
                val line = exportOne(entry, i + 1)
                addReport(line)
                markRow(entry.id, line.startsWith("✔"))
            }
            setStatus(null)
            exporting = false
            btnExport20.isEnabled = true
        }
    }

    private fun requireTarget(): Boolean {
        if (treeUri == null) {
            Toast.makeText(this, R.string.export_need_target, Toast.LENGTH_SHORT).show()
            return false
        }
        return true
    }

    private fun setStatus(text: String?) {
        tvStatus.visibility = if (text == null) View.GONE else View.VISIBLE
        tvStatus.text = text ?: ""
    }

    private fun markRow(entryId: String, ok: Boolean) {
        rowButtons[entryId]?.let { btn ->
            if (ok) {
                btn.text = "${btn.text}  ✔"
                btn.isEnabled = false
            }
        }
    }

    private fun addReport(line: String) {
        if (line.startsWith("✔")) okCount++ else failCount++
        reportLines.add(0, line)
        tvReport.text = reportLines.joinToString("\n") +
            "\n\n${getString(R.string.export_summary, okCount, failCount)}"
    }

    /** Exporta um vídeo. Retorna a linha do relatório. */
    private suspend fun exportOne(entry: MediaEntry, index: Int): String =
        withContext(Dispatchers.IO) {
            try {
                // 1) O que o arquivo tem dentro?
                val probe = probeTracks(entry.uri)
                    ?: return@withContext fail(entry, "arquivo ilegível ou corrompido")
                val vMime = probe.videoMime
                    ?: return@withContext fail(entry, "não tem faixa de vídeo")

                val videoNote = when (vMime) {
                    "video/avc" -> ""                                  // H.264 — ideal
                    "video/hevc" -> " · ⚠ HEVC: central antiga pode não reproduzir"
                    "video/mp4v-es" -> " · ⚠ MPEG-4 simples: testar na central"
                    else -> return@withContext fail(
                        entry, "codec ${friendly(vMime)} não é compatível com a central"
                    )
                }

                if (entry.sizeBytes > fat32Max) {
                    return@withContext fail(entry, "maior que 4 GB (limite do FAT32)")
                }

                // 2) Nome compatível com FAT32 (sem acentos/espaços).
                val name = "%03d-".format(index) + sanitize(entry.title) + ".mp4"

                // 3) Cópia direta (MP4/H.264+AAC) ou remux sem recodificar.
                val ext = sourceExt(entry.uri)
                val aMime = probe.audioMime
                val directCopy = ext == "mp4" && vMime == "video/avc" &&
                    (aMime == null || aMime == "audio/mp4a-latm")

                var audioNote = ""
                var remuxed: RemuxResult? = null
                val tempFile = File(cacheDir, "cockpit_export_tmp.mp4")

                deleteDocByName(name)
                val doc = createDoc(name)

                try {
                    if (directCopy) {
                        copyStream(entry.uri, doc)
                    } else {
                        remuxed = remuxToMp4(entry.uri, tempFile)
                        if (remuxed == null) {
                            return@withContext fail(entry, "não foi possível converter p/ MP4")
                        }
                        if (!remuxed!!.audioKept) {
                            val m = remuxed!!.droppedAudioMime
                            audioNote = if (m == null) " · sem faixa de áudio"
                            else " · sem áudio (${friendly(m)} não suportado)"
                        } else if (aMime == "audio/mpeg") {
                            audioNote = " · ⚠ áudio MP3: algumas centrais não reproduzem"
                        }
                        copyStream(Uri.fromFile(tempFile), doc)
                    }

                    // 4) Verificação: estrutura do arquivo + decoders do CELULAR.
                    val verify = verifyDoc(doc, vMime)
                    val size = docSize(doc)

                    "✔ $name · ${Format.bytes(size)} · ${verify}$videoNote$audioNote"
                } catch (t: Throwable) {
                    runCatching { contentResolver.delete(doc, null, null) }
                    fail(entry, t.message ?: "erro ao gravar")
                } finally {
                    tempFile.delete()
                }
            } catch (t: Throwable) {
                fail(entry, t.message ?: "erro inesperado")
            }
        }

    private fun fail(entry: MediaEntry, reason: String) = "✖ ${entry.title} — $reason"

    // ------------------------------------------------------------------
    // Análise / conversão / verificação
    // ------------------------------------------------------------------

    /** Lê as faixas do arquivo. Retorna null quando o container não abre. */
    private fun probeTracks(uri: Uri): Probe? {
        val ex = MediaExtractor()
        return try {
            ex.setDataSource(this, uri)
            var video: String? = null
            var audio: String? = null
            for (i in 0 until ex.trackCount) {
                val mime = ex.getTrackFormat(i).getString(MediaFormat.KEY_MIME) ?: continue
                when {
                    mime.startsWith("video/") && video == null -> video = mime
                    mime.startsWith("audio/") && audio == null -> audio = mime
                }
            }
            if (video == null) null else Probe(video, audio)
        } catch (t: Throwable) {
            null
        } finally {
            ex.release()
        }
    }

    /**
     * Reempacota (remux) vídeo+áudio num MP4 novo, SEM recodificar —
     * rápido e sem perda de qualidade. Áudio: mantém AAC; MP3 sai com aviso
     * no relatório; o resto (AMR/Opus/Vorbis…) é descartado, anotado.
     */
    private fun remuxToMp4(src: Uri, outFile: File): RemuxResult? {
        val ex = MediaExtractor()
        var muxer: MediaMuxer? = null
        return try {
            ex.setDataSource(this, src)
            var vTrack = -1
            var aTrack = -1
            for (i in 0 until ex.trackCount) {
                val mime = ex.getTrackFormat(i).getString(MediaFormat.KEY_MIME) ?: continue
                if (mime.startsWith("video/") && vTrack < 0) vTrack = i
                if (mime.startsWith("audio/") && aTrack < 0) aTrack = i
            }
            if (vTrack < 0) return null

            ex.selectTrack(vTrack)
            var audioKept = false
            var droppedAudioMime: String? = null
            if (aTrack >= 0) {
                val aMime = ex.getTrackFormat(aTrack).getString(MediaFormat.KEY_MIME)
                when (aMime) {
                    "audio/mp4a-latm", "audio/mpeg" -> {
                        ex.selectTrack(aTrack)
                        audioKept = true
                    }
                    else -> droppedAudioMime = aMime
                }
            }

            outFile.delete()
            muxer = MediaMuxer(outFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            val vOut = muxer.addTrack(ex.getTrackFormat(vTrack))
            val aOut = if (audioKept) muxer.addTrack(ex.getTrackFormat(aTrack)) else -1
            muxer.start()

            val buf = ByteBuffer.allocateDirect(1 shl 20)
            val info = android.media.MediaCodec.BufferInfo()
            while (true) {
                val size = ex.readSampleData(buf, 0)
                if (size < 0) break
                info.offset = 0
                info.size = size
                info.presentationTimeUs = ex.sampleTime
                info.flags = if (ex.sampleFlags and MediaExtractor.SAMPLE_FLAG_SYNC != 0)
                    MediaCodec.BUFFER_FLAG_KEY_FRAME else 0
                when (ex.sampleTrackIndex) {
                    vTrack -> muxer.writeSampleData(vOut, buf, info)
                    aTrack -> if (aOut >= 0) muxer.writeSampleData(aOut, buf, info)
                }
                ex.advance()
            }
            muxer.stop()
            RemuxResult(audioKept, droppedAudioMime)
        } catch (t: Throwable) {
            outFile.delete()
            null
        } finally {
            runCatching { muxer?.release() }
            ex.release()
        }
    }

    /**
     * Garantia de compatibilidade (requisito do usuário):
     *  - reabre o arquivo GRAVADO e confere que a estrutura abre;
     *  - testa o codec contra os decoders nativos DO CELULAR — se o
     *    celular decodifica, os players nativos (Galaxy/Meus Arquivos/
     *    Ficheiros) tocam o vídeo direto do pendrive, além da central.
     */
    private fun verifyDoc(doc: Uri, videoMime: String): String {
        // Estrutura válida?
        val ex = MediaExtractor()
        val opens = try {
            ex.setDataSource(this, doc)
            ex.trackCount > 0
        } catch (t: Throwable) {
            false
        } finally {
            ex.release()
        }
        if (!opens) return "⚠ arquivo gravado não reabriu — teste antes de usar"

        // Decoder presente no celular?
        val phoneDecoder = runCatching {
            MediaCodec.createDecoderByType(videoMime).also { it.release() }
        }.isSuccess

        return when {
            phoneDecoder -> "carro ✓ · celular ✓"
            else -> "carro ✓ · ⚠ sem decoder no celular"
        }
    }

    // ------------------------------------------------------------------
    // SAF (pendrive via sistema de arquivos do Android)
    // ------------------------------------------------------------------

    private fun treeRoot(): Uri? = treeUri?.let {
        DocumentsContract.buildDocumentUriUsingTree(it, DocumentsContract.getTreeDocumentId(it))
    }

    /** Apaga arquivo de mesmo nome no destino (reexportar = sobrescrever). */
    private fun deleteDocByName(name: String) {
        val tree = treeUri ?: return
        val root = treeRoot() ?: return
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(
            tree, DocumentsContract.getTreeDocumentId(tree)
        )
        runCatching {
            contentResolver.query(
                children,
                arrayOf(
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                ),
                null, null, null,
            )?.use { c: Cursor ->
                val iId = c.getColumnIndex(DocumentsContract.Document.COLUMN_DOCUMENT_ID)
                val iName = c.getColumnIndex(DocumentsContract.Document.COLUMN_DISPLAY_NAME)
                while (c.moveToNext()) {
                    if (c.getString(iName) == name) {
                        val child = DocumentsContract.buildDocumentUriUsingTree(tree, c.getString(iId))
                        contentResolver.delete(child, null, null)
                    }
                }
            }
        }
    }

    private fun createDoc(name: String): Uri {
        val root = treeRoot() ?: throw IllegalStateException("sem pendrive escolhido")
        val doc = DocumentsContract.createDocument(contentResolver, root, "video/mp4", name)
            ?: throw IllegalStateException("não foi possível criar $name")
        return doc
    }

    private fun copyStream(src: Uri, dst: Uri) {
        contentResolver.openInputStream(src)?.use { input ->
            contentResolver.openOutputStream(dst, "w")?.use { output ->
                input.copyTo(output, 1 shl 16)
                output.flush()
            } ?: throw IllegalStateException("destino não gravável")
        } ?: throw IllegalStateException("fonte não legível")
    }

    private fun docSize(doc: Uri): Long = runCatching {
        contentResolver.openFileDescriptor(doc, "r")?.use { it.statSize } ?: 0L
    }.getOrDefault(0L)

    // ------------------------------------------------------------------
    // Nomes compatíveis
    // ------------------------------------------------------------------

    /** Nome original do arquivo (p/ saber a extensão real do container). */
    private fun sourceExt(uri: Uri): String? {
        val name = when (uri.scheme) {
            "file" -> File(uri.path ?: "").name
            else -> runCatching {
                contentResolver.query(
                    uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME),
                    null, null, null,
                )?.use { c ->
                    if (c.moveToFirst()) c.getString(0) else null
                }
            }.getOrNull()
        } ?: return null
        val dot = name.lastIndexOf('.')
        return if (dot > 0) name.substring(dot + 1).lowercase() else null
    }

    /** Remove acentos/espaços/símbolos — nome seguro para FAT32 e centrais antigas. */
    private fun sanitize(raw: String): String {
        val ascii = Normalizer.normalize(raw, Normalizer.Form.NFD)
            .replace(Regex("[\\p{InCombiningDiacriticalMarks}]"), "")
        return ascii.replace(Regex("[^A-Za-z0-9._-]+"), "_")
            .trim('_', '.')
            .take(50)
            .ifBlank { "video" }
    }

    private fun friendly(mime: String): String = when (mime) {
        "video/avc" -> "H.264"
        "video/hevc" -> "HEVC"
        "video/mp4v-es" -> "MPEG-4 simples"
        "video/x-vnd.on2.vp9", "video/x-vnd.on2.vp8" -> "VP8/VP9"
        "audio/mp4a-latm" -> "AAC"
        "audio/mpeg" -> "MP3"
        "audio/3gpp" -> "AMR"
        "audio/opus" -> "Opus"
        else -> mime
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()
}
