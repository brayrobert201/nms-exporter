// The exporter's wall-screen mode (GET/POST /api/mode), kept free of Android types so the
// cycling and the parsing can be checked on the JVM.
package toys.bobs.nms

import org.json.JSONObject

object WallMode {
    /** What the tile cycles through when the server does not send its own `activities` list. */
    val DEFAULT = listOf("idle", "gathering", "crafting", "mission")

    /** The server's answer, reduced to what the tile shows. `error` is set when it refused. */
    data class State(val activity: String?, val activities: List<String>, val error: String? = null) {
        val idle: Boolean get() = activity == null || activity == "idle"
    }

    fun parse(body: String): State {
        val o = JSONObject(body)
        val list = o.optJSONArray("activities")?.let { a ->
            (0 until a.length()).mapNotNull { a.optString(it).takeIf(String::isNotBlank) }
        }.orEmpty()
        val activity = o.optString("activity").takeIf { o.has("activity") && it.isNotBlank() }
        val error = o.optString("error").takeIf { o.has("error") && it.isNotBlank() }
        return State(activity, list.ifEmpty { DEFAULT }, error)
    }

    /** The activity after [current] in [order]; an unknown or missing current starts at the first. */
    fun next(current: String?, order: List<String>): String {
        val list = order.ifEmpty { DEFAULT }
        return list[(list.indexOf(current) + 1) % list.size] // indexOf is -1 when unknown: the first
    }

    /** "gathering" -> "Gathering", "deep_space" -> "Deep space". */
    fun label(activity: String): String =
        activity.replace('_', ' ').replaceFirstChar { it.titlecase() }

    fun body(activity: String): String = JSONObject().put("activity", activity).toString()
}
