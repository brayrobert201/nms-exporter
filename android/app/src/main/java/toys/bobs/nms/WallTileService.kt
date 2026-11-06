// "NMS wall" Quick Settings tile: shows the exporter's wall-screen mode and cycles it on a tap,
// without opening the app. Long-press opens MainActivity (QS_TILE_PREFERENCES in the manifest).
package toys.bobs.nms

import android.content.Context
import android.graphics.drawable.Icon
import android.os.Handler
import android.os.Looper
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.util.Log
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class WallTileService : TileService() {
    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    @Volatile private var last: WallMode.State? = null
    @Volatile private var busy = false

    private val serverUrl: String
        get() = getSharedPreferences("nms", Context.MODE_PRIVATE).getString("url", "")?.trim()?.trimEnd('/') ?: ""

    override fun onStartListening() {
        super.onStartListening()
        last?.let { show(it) }
        refresh()
    }

    override fun onClick() {
        super.onClick()
        val base = serverUrl
        if (base.isEmpty()) return showUnavailable(getString(R.string.tile_no_server))
        if (busy) return
        busy = true
        io.execute {
            val result = runCatching {
                // read the mode fresh: the PC or the web page may have changed it since the shade opened
                val now = WallMode.parse(request("GET", "$base/api/mode"))
                val target = WallMode.next(now.activity, now.activities)
                val answer = WallMode.parse(request("POST", "$base/api/mode", WallMode.body(target)))
                // the POST answer carries no list; keep the one we cycled through
                answer.copy(activities = now.activities)
            }
            busy = false
            post(result)
        }
    }

    override fun onDestroy() {
        io.shutdownNow()
        super.onDestroy()
    }

    private fun refresh() {
        val base = serverUrl
        if (base.isEmpty()) return showUnavailable(getString(R.string.tile_no_server))
        io.execute { post(runCatching { WallMode.parse(request("GET", "$base/api/mode")) }) }
    }

    private fun post(result: Result<WallMode.State>) {
        main.post {
            result.fold(
                onSuccess = { s ->
                    if (s.error != null && s.activity == null) {
                        Log.w(TAG, "exporter refused: ${s.error}")
                        last?.let { show(it) } ?: showUnavailable(getString(R.string.tile_unreachable))
                    } else {
                        last = s
                        show(s)
                    }
                },
                onFailure = { e ->
                    Log.w(TAG, "exporter unreachable: $e")
                    last = null
                    showUnavailable(getString(R.string.tile_unreachable))
                },
            )
        }
    }

    private fun show(s: WallMode.State) = update(
        if (s.idle) Tile.STATE_INACTIVE else Tile.STATE_ACTIVE,
        WallMode.label(s.activity ?: "idle"),
    )

    private fun showUnavailable(why: String) = update(Tile.STATE_UNAVAILABLE, why)

    private fun update(state: Int, subtitle: String) {
        val tile = qsTile ?: return // not listening any more
        tile.label = getString(R.string.tile_label)
        tile.subtitle = subtitle
        tile.state = state
        tile.icon = Icon.createWithResource(this, R.drawable.ic_tile_wall)
        tile.updateTile()
    }

    /** One short request; a 4xx body (the exporter's {"error": ...}) is returned, not thrown. */
    private fun request(method: String, url: String, body: String? = null): String {
        val c = URL(url).openConnection() as HttpURLConnection
        try {
            c.requestMethod = method
            c.connectTimeout = TIMEOUT_MS
            c.readTimeout = TIMEOUT_MS
            c.useCaches = false
            c.setRequestProperty("Accept", "application/json")
            if (body != null) {
                c.doOutput = true
                c.setRequestProperty("Content-Type", "application/json")
                c.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = c.responseCode
            val stream = if (code in 200..299) c.inputStream else c.errorStream ?: error("HTTP $code")
            val text = stream.bufferedReader().use { it.readText() }
            if (code !in 200..499) error("HTTP $code")
            return text
        } finally {
            c.disconnect()
        }
    }

    private companion object {
        const val TAG = "NMSTile"
        const val TIMEOUT_MS = 3000
    }
}
