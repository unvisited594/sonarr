package app.sonar.player

import android.media.audiofx.Equalizer
import android.util.Log
import app.sonar.data.LookData
import app.sonar.data.LookSettings
import kotlin.math.abs
import kotlin.math.ln

/**
 * Эквалайзер Android, привязанный к звуку плеера. Пресеты и 10 полос — как на ПК; на телефоне
 * полос обычно 5, поэтому каждая полоса берёт значение ближайшей по частоте полосы Sonar.
 */
object Eq {
    private var eq: Equalizer? = null
    private var session = 0
    private var last: LookSettings? = null

    fun attach(audioSessionId: Int) {
        if (audioSessionId == session && eq != null) return
        release()
        session = audioSessionId
        eq = runCatching { Equalizer(0, audioSessionId) }.onFailure { Log.w("SonarEq", "эквалайзер недоступен", it) }.getOrNull()
        last?.let { apply(it) }
    }

    val available: Boolean get() = eq != null

    fun apply(look: LookSettings) {
        last = look
        val e = eq ?: return
        runCatching {
            e.enabled = look.eqOn
            if (!look.eqOn) return
            val range = e.bandLevelRange   // миллибелы, обычно −1500..1500
            for (b in 0 until e.numberOfBands.toInt()) {
                val hz = e.getCenterFreq(b.toShort()) / 1000.0
                val nearest = LookData.eqBands.indices.minByOrNull { abs(ln(LookData.eqBands[it].toDouble()) - ln(hz.coerceAtLeast(1.0))) } ?: 0
                val mb = (look.eqGains.getOrElse(nearest) { 0f } * 100).toInt().coerceIn(range[0].toInt(), range[1].toInt())
                e.setBandLevel(b.toShort(), mb.toShort())
            }
        }.onFailure { Log.w("SonarEq", "не применился", it) }
    }

    fun release() {
        runCatching { eq?.release() }
        eq = null
    }
}
