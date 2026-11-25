package app.sonar.data

import app.sonar.BuildConfig
import app.sonar.net.Http
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.InputStream
import java.util.zip.ZipInputStream

/** Оформление: то же, что на ПК (тема, акцент, живой фон, пластинка, текст песни, эквалайзер). */
@Serializable
data class LookSettings(
    val theme: String = "dark",              // dark | amoled | light
    val accent: String = "#7C4DFF",
    val flowOn: Boolean = true,
    val flowSource: String = "cover",        // cover | fire | sunset | ocean | aurora | neon | custom
    val flowCustom: List<String> = listOf("#FF7A00", "#FFD000", "#8A2BE2"),
    val flowSpeed: Int = 50,
    val vinyl: Boolean = false,
    val lyricsStyle: String = "dotify",      // dotify | karaoke
    val lyricsColor: String = "#FFFFFF",
    val lyricsSung: String = "#000000",
    val lyricsHalo: Boolean = true,
    val lyricsSize: Int = 26,
    val lyricsAlign: String = "left",        // left | center
    val lyricsOffset: Int = 0,               // мс: плюс — текст раньше
    val eqOn: Boolean = false,
    val eqPreset: String = "flat",
    val eqGains: List<Float> = List(10) { 0f },
)

data class FlowPreset(val id: String, val title: String, val colors: List<String>, val base: String)

object LookData {
    val flowPresets = listOf(
        FlowPreset("fire", "Огонь", listOf("#FF7A00", "#FFD000", "#FF3D00", "#8A2BE2"), "#000000"),
        FlowPreset("sunset", "Закат", listOf("#FF5F6D", "#FFC371", "#C33764", "#FF9A8B"), "#0D0207"),
        FlowPreset("ocean", "Океан", listOf("#00C6FF", "#0052FF", "#00E5A8", "#3A0CA3"), "#020611"),
        FlowPreset("aurora", "Аврора", listOf("#00FF9C", "#00B3FF", "#A24BFF", "#1DE9B6"), "#02040A"),
        FlowPreset("neon", "Неон", listOf("#FF00E5", "#00F0FF", "#7C4DFF", "#FF2E63"), "#05010D"),
    )
    val accents = listOf("#7C4DFF", "#00E5FF", "#FF4D6D", "#FF7A00", "#FFD23F", "#3DDC84", "#F2F2F2", "#FF2BD6")
    val lyricPairs = listOf(
        Triple("Белый и чёрный", "#FFFFFF", "#000000"), Triple("Белый и золото", "#FFFFFF", "#FFC93C"),
        Triple("Неон", "#9EF6FF", "#FF2BD6"), Triple("Мягкий", "#BFC4D6", "#FFFFFF"), Triple("Тёмный", "#1C1C22", "#FFFFFF"),
    )
    val eqBands = listOf(31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
    val eqPresets = linkedMapOf(
        "flat" to ("Ровно" to listOf(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)),
        "bass" to ("Бас" to listOf(7, 6, 5, 3, 1, 0, 0, 0, 0, 0)),
        "bass_max" to ("Больше баса" to listOf(10, 9, 7, 4, 1, 0, -1, -1, 0, 0)),
        "vocal" to ("Вокал" to listOf(-2, -2, -1, 1, 3, 4, 4, 3, 1, 0)),
        "night" to ("Ночь" to listOf(-4, -3, -1, 0, 1, 1, 0, -2, -4, -6)),
        "electro" to ("Электроника" to listOf(6, 5, 2, 0, -2, 0, 1, 3, 5, 6)),
        "rock" to ("Рок" to listOf(5, 4, 2, -1, -2, -1, 2, 4, 5, 5)),
        "hiphop" to ("Хип-хоп" to listOf(6, 5, 3, 2, -1, -1, 1, 0, 2, 3)),
        "acoustic" to ("Акустика" to listOf(3, 3, 2, 1, 1, 1, 2, 3, 2, 1)),
        "clarity" to ("Чёткость" to listOf(0, 0, -1, -1, 0, 1, 3, 5, 6, 5)),
    )
}

/** Набор оформления из Мастерской (общий формат с ПК). */
data class Pack(val name: String, val author: String, val description: String, val settings: JsonObject?, val file: String?)

object Packs {
    private val json = Json { ignoreUnknownKeys = true }

    /** Встроенные наборы — те же, что на ПК. */
    val builtin: List<Pack> by lazy {
        fun p(name: String, about: String, s: String) = Pack(name, "", about, json.parseToJsonElement(s).jsonObject, null)
        listOf(
            p("Неоновая ночь", "Неоновый фон, караоке розовым по голубому",
                """{"accent":"#ff2bd6","flow_source":"neon","lyrics_style":"karaoke","lyrics_color":"#9ef6ff","lyrics_sung":"#ff2bd6","lyrics_align":"center"}"""),
            p("Тёплый винил", "Закатный фон, пластинка, золотой текст",
                """{"accent":"#ffc371","flow_source":"sunset","vinyl":true,"lyrics_style":"dotify","lyrics_color":"#ffffff","lyrics_sung":"#ffc93c"}"""),
            p("Океан", "Синие и бирюзовые волны",
                """{"accent":"#00c6ff","flow_source":"ocean","lyrics_style":"dotify","lyrics_color":"#bfe9ff","lyrics_sung":"#ffffff","lyrics_align":"center"}"""),
            p("Северное сияние", "Зелёно-фиолетовое сияние",
                """{"accent":"#00ff9c","flow_source":"aurora","lyrics_style":"karaoke","lyrics_color":"#ffffff","lyrics_sung":"#00ff9c","lyrics_align":"center"}"""),
            p("Светлый день", "Светлая тема и огненный фон",
                """{"theme":"light","accent":"#ff7a00","flow_source":"fire","vinyl":true,"lyrics_style":"karaoke"}"""),
        )
    }

    private fun str(o: JsonObject, k: String): String? =
        (o[k] as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** Применить настройки набора ПК-формата к оформлению телефона (что понятно телефону). */
    fun apply(base: LookSettings, s: JsonObject): LookSettings {
        var l = base
        str(s, "theme")?.let { l = l.copy(theme = if (it == "light") "light" else "dark") }
        str(s, "accent")?.takeIf { it.startsWith("#") }?.let { l = l.copy(accent = it) }
        str(s, "flow_source")?.let { l = l.copy(flowSource = it) }
        (s["flow_custom"] as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.content }?.takeIf { it.isNotEmpty() }
            ?.let { l = l.copy(flowCustom = it) }
        (s["flow_speed"] as? JsonPrimitive)?.doubleOrNull?.let { l = l.copy(flowSpeed = it.toInt()) }
        (s["vinyl"] as? JsonPrimitive)?.booleanOrNull?.let { l = l.copy(vinyl = it) }
        str(s, "lyrics_style")?.let { l = l.copy(lyricsStyle = it) }
        str(s, "lyrics_color")?.let { l = l.copy(lyricsColor = it) }
        str(s, "lyrics_sung")?.let { l = l.copy(lyricsSung = it) }
        (s["lyrics_halo"] as? JsonPrimitive)?.booleanOrNull?.let { l = l.copy(lyricsHalo = it) }
        str(s, "lyrics_align")?.let { l = l.copy(lyricsAlign = it) }
        (s["lyrics_size"] as? JsonPrimitive)?.doubleOrNull?.let { l = l.copy(lyricsSize = (it * 0.85).toInt().coerceIn(16, 44)) }
        (s["lyrics_offset"] as? JsonPrimitive)?.doubleOrNull?.let { l = l.copy(lyricsOffset = it.toInt()) }
        return l
    }

    private fun fromJson(el: JsonElement): Pack {
        val o = el.jsonObject
        return Pack(str(o, "name") ?: "Набор", str(o, "author") ?: "", str(o, "description") ?: "",
            o["settings"] as? JsonObject, str(o, "file"))
    }

    /** Файл набора с ПК: .sonarpack / .zip (внутри pack.json) или просто .json. */
    fun read(input: InputStream): Pack {
        val bytes = input.readBytes()
        if (bytes.size >= 2 && bytes[0] == 'P'.code.toByte() && bytes[1] == 'K'.code.toByte()) {
            ZipInputStream(bytes.inputStream()).use { zip ->
                while (true) {
                    val e = zip.nextEntry ?: break
                    if (e.name == "pack.json") return fromJson(json.parseToJsonElement(zip.readBytes().decodeToString()))
                }
            }
            throw IllegalArgumentException("В файле нет pack.json — это не набор Sonar")
        }
        return fromJson(json.parseToJsonElement(bytes.decodeToString()))
    }

    private fun raw(path: String) = "https://raw.githubusercontent.com/${BuildConfig.GITHUB_REPO}/main/workshop/$path"

    /** Блокирующий вызов: каталог Мастерской из репозитория. */
    fun online(): List<Pack> {
        val root = json.parseToJsonElement(Http.get(raw("index.json")))
        val items = (root as? JsonObject)?.get("packs")?.jsonArray ?: (root as? JsonArray) ?: return emptyList()
        return items.mapNotNull { runCatching { fromJson(it) }.getOrNull() }
    }

    /** Блокирующий вызов: настройки набора из каталога (если они в отдельном файле). */
    fun settingsOf(p: Pack): JsonObject? {
        p.settings?.let { return it }
        val f = p.file?.takeIf { Regex("""[\w.\-/]+""").matches(it) && ".." !in it } ?: return null
        val req = okhttp3.Request.Builder().url(raw(f)).header("User-Agent", "Sonar Android").build()
        Http.client.newCall(req).execute().use { r ->
            val body = r.body?.byteStream() ?: return null
            return read(body).settings
        }
    }
}
