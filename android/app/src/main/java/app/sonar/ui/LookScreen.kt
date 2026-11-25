package app.sonar.ui

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.sonar.data.LookData
import app.sonar.data.LookSettings
import app.sonar.data.Pack
import app.sonar.data.Packs
import app.sonar.data.Store
import app.sonar.player.Eq
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private fun changeLook(change: (LookSettings) -> LookSettings) = Store.updateLook(change)

@Composable
private fun Title(text: String) =
    Text(text, fontSize = 19.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 22.dp, bottom = 8.dp))

@Composable
private fun Hint(text: String) = Text(text, color = SonarColors.muted, fontSize = 13.sp)

@Composable
private fun SwitchRow(title: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Chips(options: List<Pair<String, String>>, selected: String, onPick: (String) -> Unit) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for ((id, title) in options) FilterChip(selected = id == selected, onClick = { onPick(id) }, label = { Text(title) })
    }
}

@Composable
private fun LabeledSlider(title: String, value: Float, range: ClosedFloatingPointRange<Float>, steps: Int = 0,
                          shown: String, onChange: (Float) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(title, Modifier.weight(1f))
        Text(shown, color = SonarColors.muted, fontSize = 13.sp)
    }
    Slider(value = value, onValueChange = onChange, valueRange = range, steps = steps)
}

/** «Оформление»: тема, акцент, фон плеера, пластинка, текст песни, эквалайзер, наборы из Мастерской. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun LookScreen(onClose: () -> Unit) {
    val look by Store.look.collectAsState()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var packStatus by remember { mutableStateOf<String?>(null) }
    var online by remember { mutableStateOf<List<Pack>?>(null) }
    BackHandler(onBack = onClose)

    fun applyPack(p: Pack) {
        scope.launch {
            val s = runCatching { withContext(Dispatchers.IO) { Packs.settingsOf(p) } }.getOrNull()
            if (s == null) packStatus = "Набор «${p.name}» не скачался"
            else { changeLook { Packs.apply(it, s) }; packStatus = "Оформление «${p.name}» применено" }
        }
    }

    val openFile = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) scope.launch {
            val p = runCatching {
                withContext(Dispatchers.IO) { context.contentResolver.openInputStream(uri)!!.use { Packs.read(it) } }
            }
            p.getOrNull()?.let { applyPack(it) } ?: run { packStatus = "Не получилось: ${p.exceptionOrNull()?.message}" }
        }
    }

    Box(Modifier.fillMaxSize().background(SonarColors.bg).statusBarsPadding().navigationBarsPadding()) {
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(start = 20.dp, end = 20.dp, bottom = 40.dp)) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 8.dp)) {
                    IconButton(onClick = onClose) { Icon(Icons.Filled.ArrowBack, contentDescription = "Назад") }
                    Text("Оформление", fontSize = 28.sp, fontWeight = FontWeight.Black)
                }
            }
            item {
                Column {
                    Title("Тема")
                    Chips(listOf("dark" to "Тёмная", "amoled" to "Чёрная (AMOLED)", "light" to "Светлая"), look.theme) { v -> changeLook { it.copy(theme = v) } }
                    Spacer(Modifier.height(10.dp))
                    Hint("Акцентный цвет")
                    Spacer(Modifier.height(8.dp))
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        for (c in LookData.accents) {
                            val on = c.equals(look.accent, ignoreCase = true)
                            Box(Modifier.size(36.dp).clip(CircleShape).background(hex(c))
                                .border(if (on) 3.dp else 0.dp, SonarColors.text, CircleShape)
                                .clickable { changeLook { it.copy(accent = c) } })
                        }
                    }
                }
            }
            item {
                Column {
                    Title("Фон большого плеера")
                    SwitchRow("Живой фон", look.flowOn) { v -> changeLook { it.copy(flowOn = v) } }
                    Chips(listOf("cover" to "Из обложки") + LookData.flowPresets.map { it.id to it.title }, look.flowSource) { v ->
                        changeLook { it.copy(flowSource = v) }
                    }
                    Spacer(Modifier.height(10.dp))
                    Box(Modifier.fillMaxWidth().height(120.dp).clip(RoundedCornerShape(18.dp))) { FlowBackground(null) }
                    LabeledSlider("Скорость", look.flowSpeed.toFloat(), 0f..100f, shown = "${look.flowSpeed}%") { v ->
                        changeLook { it.copy(flowSpeed = v.toInt()) }
                    }
                    SwitchRow("Обложка-пластинка", look.vinyl) { v -> changeLook { it.copy(vinyl = v) } }
                }
            }
            item {
                Column {
                    Title("Текст песни")
                    Chips(listOf("dotify" to "Как в Dotify", "karaoke" to "Караоке"), look.lyricsStyle) { v -> changeLook { it.copy(lyricsStyle = v) } }
                    Spacer(Modifier.height(10.dp))
                    Hint("Цвета: текст и спетое")
                    Spacer(Modifier.height(6.dp))
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        for ((title, a, b) in LookData.lyricPairs) {
                            val on = a.equals(look.lyricsColor, true) && b.equals(look.lyricsSung, true)
                            FilterChip(selected = on, onClick = { changeLook { it.copy(lyricsColor = a, lyricsSung = b) } },
                                label = { Text(title) }, leadingIcon = {
                                    Box(Modifier.size(16.dp).clip(CircleShape).background(Brush.horizontalGradient(listOf(hex(a), hex(b)))))
                                })
                        }
                    }
                    SwitchRow("Обводка букв", look.lyricsHalo) { v -> changeLook { it.copy(lyricsHalo = v) } }
                    Chips(listOf("left" to "Слева", "center" to "По центру"), look.lyricsAlign) { v -> changeLook { it.copy(lyricsAlign = v) } }
                    LabeledSlider("Размер", look.lyricsSize.toFloat(), 16f..44f, shown = "${look.lyricsSize}") { v ->
                        changeLook { it.copy(lyricsSize = v.toInt()) }
                    }
                    LabeledSlider("Сдвиг по времени", look.lyricsOffset.toFloat(), -3000f..3000f, steps = 59,
                        shown = if (look.lyricsOffset == 0) "без сдвига" else "${if (look.lyricsOffset > 0) "раньше" else "позже"} на ${"%.1f".format(kotlin.math.abs(look.lyricsOffset) / 1000f)} с") { v ->
                        changeLook { it.copy(lyricsOffset = (v / 100).toInt() * 100) }
                    }
                }
            }
            item {
                Column {
                    Title("Эквалайзер")
                    SwitchRow("Включить", look.eqOn) { v -> changeLook { it.copy(eqOn = v) } }
                    if (!Eq.available) Hint("На этом телефоне эквалайзер появится после запуска первого трека.")
                    Chips(LookData.eqPresets.map { (id, v) -> id to v.first }, look.eqPreset) { id ->
                        val gains = LookData.eqPresets[id]?.second?.map { it.toFloat() } ?: List(10) { 0f }
                        changeLook { it.copy(eqPreset = id, eqGains = gains, eqOn = id != "flat" || it.eqOn) }
                    }
                    Spacer(Modifier.height(6.dp))
                    LookData.eqBands.forEachIndexed { i, hz ->
                        val g = look.eqGains.getOrElse(i) { 0f }
                        LabeledSlider(if (hz >= 1000) "${hz / 1000} кГц" else "$hz Гц", g, -12f..12f,
                            shown = "%+.0f дБ".format(g)) { v ->
                            changeLook { it.copy(eqGains = it.eqGains.toMutableList().also { l -> while (l.size < 10) l += 0f; l[i] = v }, eqPreset = "custom", eqOn = true) }
                        }
                    }
                }
            }
            item {
                Column {
                    Title("Наборы оформления")
                    Hint("Те же наборы, что в Мастерской на ПК: тема, акцент, фон, пластинка и вид текста.")
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { openFile.launch(arrayOf("*/*")) }) { Text("Открыть файл набора") }
                        OutlinedButton(onClick = {
                            packStatus = "Загружаю каталог…"
                            scope.launch {
                                val r = runCatching { withContext(Dispatchers.IO) { Packs.online() } }
                                online = r.getOrNull()
                                packStatus = if (r.isFailure) "Каталог недоступен" else null
                            }
                        }) { Text("Каталог") }
                    }
                    packStatus?.let { Text(it, color = SonarColors.muted, modifier = Modifier.padding(top = 8.dp)) }
                    Spacer(Modifier.height(8.dp))
                    for (p in Packs.builtin + (online ?: emptyList())) {
                        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp).clip(RoundedCornerShape(14.dp))
                            .background(SonarColors.surface).clickable { applyPack(p) }.padding(14.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(p.name, fontWeight = FontWeight.SemiBold)
                                if (p.description.isNotBlank()) Text(p.description, color = SonarColors.muted, fontSize = 13.sp)
                            }
                            Spacer(Modifier.width(8.dp))
                            Text("Применить", color = SonarColors.accent, fontWeight = FontWeight.SemiBold)
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    OutlinedButton(onClick = { changeLook { LookSettings() }; packStatus = "Вернул как было" }) { Text("Вернуть как было") }
                }
            }
        }
    }
}
