package app.sonar.lyrics

import app.sonar.model.Track
import app.sonar.net.Http
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.URLEncoder

data class LyricLine(val timeMs: Long, val text: String)

/** Текст песни из открытой базы LRCLIB: с разметкой по времени, если есть. */
object Lyrics {
    private val json = Json { ignoreUnknownKeys = true }
    private val stamp = Regex("""\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?]""")
    private val junk = Regex("""\s*[(\[][^)\]]*(official|video|audio|lyric|clip|клип|remaster)[^)\]]*[)\]]""", RegexOption.IGNORE_CASE)

    fun cleanTitle(s: String) = s.replace(junk, "").replace(Regex("""\s*(feat\.?|ft\.?)\s.*$""", RegexOption.IGNORE_CASE), "").trim()

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    /** Исполнитель без хвостов YouTube/SoundCloud: «- Topic», «VEVO», «feat.», второй исполнитель. */
    fun cleanArtist(s: String) = s.split(",", "&", " x ", " feat", " ft.", "•", "·").first()
        .replace(Regex("""\s*-\s*Topic$""", RegexOption.IGNORE_CASE), "")
        .replace(Regex("""VEVO$""", RegexOption.IGNORE_CASE), "").trim()

    private fun search(query: String): List<JsonObject> = runCatching {
        json.parseToJsonElement(Http.get("https://lrclib.net/api/search?$query")).jsonArray.map { it.jsonObject }
    }.getOrDefault(emptyList())

    /**
     * Блокирующий вызов. Пустой список — текста нет. synced=false — без времени.
     * Ищем в несколько заходов: «название + исполнитель», свободный поиск, только название
     * (у SoundCloud исполнитель часто — ник загрузившего, а название вида «Исполнитель - Песня»).
     */
    fun load(track: Track): Pair<List<LyricLine>, Boolean> {
        var title = cleanTitle(track.title)
        var artist = cleanArtist(track.artist)
        if (" - " in title) {   // «Исполнитель - Песня» в названии
            val (a, t) = title.split(" - ", limit = 2)
            if (t.isNotBlank()) { artist = a.trim(); title = cleanTitle(t) }
        }
        val dur = track.durationMs / 1000.0
        val found = LinkedHashMap<String, JsonObject>()
        val attempts = listOf(
            "track_name=${enc(title)}&artist_name=${enc(artist)}",
            "q=${enc("$artist $title")}",
            "track_name=${enc(title)}",
        )
        for (q in attempts) {
            for (o in search(q)) found[o["id"]?.toString() ?: o.toString().take(80)] = o
            val good = found.values.any { o -> !o.str("syncedLyrics").isNullOrBlank() && closeEnough(o, dur) }
            if (good) break
        }
        val best = found.values.filter { closeEnough(it, dur) }.minByOrNull { o ->
            val d = o["duration"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: 0.0
            val synced = !o.str("syncedLyrics").isNullOrBlank()
            (if (synced) 0.0 else 1000.0) + (if (dur > 0) kotlin.math.abs(d - dur) else 0.0)
        } ?: return emptyList<LyricLine>() to false
        best.str("syncedLyrics")?.takeIf { it.isNotBlank() }?.let { return parse(it) to true }
        best.str("plainLyrics")?.takeIf { it.isNotBlank() }?.let { plain ->
            return plain.lines().filter { it.isNotBlank() }.map { LyricLine(-1, it.trim()) } to false
        }
        return emptyList<LyricLine>() to false
    }

    /** Длительность совпадает (±15 с) — значит, это та же песня, а не тёзка. Если длительности нет — берём. */
    private fun closeEnough(o: JsonObject, dur: Double): Boolean {
        if (dur <= 0) return true
        val d = o["duration"]?.jsonPrimitive?.content?.toDoubleOrNull() ?: return true
        return kotlin.math.abs(d - dur) <= 15
    }

    private fun JsonObject.str(k: String): String? =
        this[k]?.let { if (it.toString() == "null") null else it.jsonPrimitive.content }

    fun parse(lrc: String): List<LyricLine> {
        val out = mutableListOf<LyricLine>()
        for (raw in lrc.lines()) {
            val stamps = stamp.findAll(raw).toList()
            if (stamps.isEmpty()) continue
            val text = raw.substring(stamps.last().range.last + 1).replace(Regex("""<\d+:\d+(?:[.:]\d+)?>"""), "").trim()
            if (text.isEmpty()) continue
            for (m in stamps) {
                val (mm, ss, frac) = m.destructured
                val ms = (mm.toLong() * 60 + ss.toLong()) * 1000 + (frac.padEnd(3, '0').take(3).ifEmpty { "0" }).toLong()
                out += LyricLine(ms, text)
            }
        }
        return out.sortedBy { it.timeMs }
    }
}
