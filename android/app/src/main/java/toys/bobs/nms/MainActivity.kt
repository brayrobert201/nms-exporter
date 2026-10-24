// NMS Mobile: a thin shell around the exporter's /mobile page.
//
// The page (nmsexporter/web/mobile.html) is the app; this activity gives it what a browser
// cannot: the screen stays on, the fold posture of a foldable reaches the page, the exporter's
// address is remembered, and the whole thing lives on the launcher. Everything the page can do
// in Chrome it can do here, so the web and the app never drift apart.
package toys.bobs.nms

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.os.Bundle
import android.text.InputType
import android.util.Log
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.SystemBarStyle
import androidx.activity.addCallback
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.window.layout.FoldingFeature
import androidx.window.layout.WindowInfoTracker
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.materialswitch.MaterialSwitch
import kotlinx.coroutines.launch
import org.json.JSONObject

class MainActivity : AppCompatActivity() {
    private lateinit var web: WebView
    private lateinit var root: FrameLayout
    private val prefs by lazy { getSharedPreferences("nms", Context.MODE_PRIVATE) }
    private var lastFold: JSONObject? = null

    private val serverUrl: String
        get() = prefs.getString("url", "") ?: ""
    private val keepAwake: Boolean
        get() = prefs.getBoolean("awake", true)

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge(SystemBarStyle.dark(Color.TRANSPARENT), SystemBarStyle.dark(Color.TRANSPARENT))
        super.onCreate(savedInstanceState)
        root = FrameLayout(this).apply { setBackgroundColor(0xFF0A0A10.toInt()) }
        web = WebView(this)
        root.addView(web, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        setContentView(root)
        // the page draws edge to edge; the system bars and the cutout become padding so nothing hides under them
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val b = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout() or WindowInsetsCompat.Type.ime())
            v.setPadding(b.left, b.top, b.right, b.bottom)
            lastFold?.let { sendFold(it) }
            insets
        }

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            setSupportZoom(false)
            builtInZoomControls = false
            displayZoomControls = false
            mediaPlaybackRequiresUserGesture = false
            cacheMode = WebSettings.LOAD_DEFAULT
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
        }
        web.setBackgroundColor(0xFF0A0A10.toInt())
        web.addJavascriptInterface(Shell(), "NMSShell")
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        web.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(m: ConsoleMessage): Boolean {
                Log.d("NMSMobile", "${m.sourceId()}:${m.lineNumber()} ${m.message()}")
                return true
            }
        }
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // the exporter's own pages stay in the app; anything else is the browser's job
                val mine = runCatching { android.net.Uri.parse(serverUrl).host }.getOrNull()
                return if (request.url.host == mine) false else {
                    runCatching { startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, request.url)) }
                    true
                }
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame) showError("${error.description} (${request.url})")
            }

            override fun onPageFinished(view: WebView, url: String?) {
                lastFold?.let { sendFold(it) }
            }
        }

        onBackPressedDispatcher.addCallback(this) {
            if (web.canGoBack()) web.goBack() else finish()
        }

        applyAwake()
        watchFold()
        if (savedInstanceState != null) web.restoreState(savedInstanceState)
        if (web.url == null) {
            if (serverUrl.isBlank()) showSettings(firstRun = true) else load()
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    override fun onResume() {
        super.onResume()
        web.onResume()
        web.resumeTimers()
    }

    override fun onPause() {
        web.pauseTimers()
        web.onPause()
        super.onPause()
    }

    override fun onDestroy() {
        root.removeView(web)
        web.destroy()
        super.onDestroy()
    }

    private fun applyAwake() {
        if (keepAwake) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    private fun load() {
        val base = serverUrl.trimEnd('/')
        web.loadUrl("$base/mobile")
    }

    private fun showError(why: String) {
        val esc = why.replace("&", "&amp;").replace("<", "&lt;")
        val html = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
            <body style="margin:0;background:#0A0A10;color:#F2F2F5;font:15px/1.5 system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center">
            <div style="padding:32px;max-width:420px"><div style="font-size:22px;font-weight:600;margin-bottom:8px">Exporter unreachable</div>
            <div style="color:#8B8B9E;margin-bottom:24px;word-break:break-all">$esc</div>
            <button onclick="NMSShell.reload()" style="font:600 14px system-ui;padding:12px 22px;border-radius:999px;border:0;background:#7B6CFF;color:#fff;margin:4px">Retry</button>
            <button onclick="NMSShell.openSettings()" style="font:600 14px system-ui;padding:12px 22px;border-radius:999px;border:1px solid rgba(255,255,255,.14);background:transparent;color:#C9C9D2;margin:4px">Settings</button>
            </div></body>"""
        web.loadDataWithBaseURL(null, html, "text/html", "utf-8", null)
    }

    // The fold, as androidx.window reports it, handed to the page: posture (flat, book, tabletop, none),
    // the hinge orientation and its rectangle in CSS pixels relative to the page. The page prefers the
    // viewport-segments media queries when the engine has them and falls back to this.
    private fun watchFold() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                WindowInfoTracker.getOrCreate(this@MainActivity).windowLayoutInfo(this@MainActivity).collect { info ->
                    val f = info.displayFeatures.filterIsInstance<FoldingFeature>().firstOrNull()
                    val o = JSONObject()
                    if (f == null) {
                        o.put("posture", "none")
                    } else {
                        val vertical = f.orientation == FoldingFeature.Orientation.VERTICAL
                        o.put("posture", when {
                            f.state == FoldingFeature.State.HALF_OPENED && vertical -> "book"
                            f.state == FoldingFeature.State.HALF_OPENED -> "tabletop"
                            else -> "flat"
                        })
                        o.put("orientation", if (vertical) "vertical" else "horizontal")
                        o.put("separating", f.isSeparating)
                        o.put("occlusion", if (f.occlusionType == FoldingFeature.OcclusionType.FULL) "full" else "none")
                        o.put("left", f.bounds.left); o.put("top", f.bounds.top)
                        o.put("right", f.bounds.right); o.put("bottom", f.bounds.bottom)
                    }
                    lastFold = o
                    sendFold(o)
                }
            }
        }
    }

    private fun sendFold(o: JSONObject) {
        val d = resources.displayMetrics.density
        val pos = IntArray(2).also { web.getLocationInWindow(it) }
        val css = JSONObject(o.toString())
        if (o.has("left")) {
            css.put("left", (o.getInt("left") - pos[0]) / d); css.put("top", (o.getInt("top") - pos[1]) / d)
            css.put("right", (o.getInt("right") - pos[0]) / d); css.put("bottom", (o.getInt("bottom") - pos[1]) / d)
        }
        web.evaluateJavascript("window.nmsFold && window.nmsFold($css)", null)
    }

    private fun showSettings(firstRun: Boolean = false) {
        val dp = resources.displayMetrics.density
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding((24 * dp).toInt(), (8 * dp).toInt(), (24 * dp).toInt(), 0)
        }
        box.addView(TextView(this).apply { text = getString(R.string.server_label) })
        val url = EditText(this).apply {
            hint = getString(R.string.server_hint)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setText(serverUrl)
        }
        box.addView(url)
        val awake = MaterialSwitch(this).apply {
            text = getString(R.string.keep_awake)
            isChecked = keepAwake
            setPadding(0, (16 * dp).toInt(), 0, 0)
        }
        box.addView(awake)
        val dlg = MaterialAlertDialogBuilder(this)
            .setTitle(R.string.settings_title)
            .setView(box)
            .setCancelable(!firstRun)
            .setPositiveButton(R.string.save) { _, _ ->
                var u = url.text.toString().trim()
                if (u.isNotEmpty() && !u.contains("://")) u = "http://$u"
                prefs.edit().putString("url", u).putBoolean("awake", awake.isChecked).apply()
                applyAwake()
                if (u.isNotEmpty()) load() else showSettings(firstRun = true)
            }
        if (!firstRun) dlg.setNegativeButton(R.string.cancel, null)
        dlg.show()
    }

    // What the page may ask of the shell (window.NMSShell in the page; absent in a browser).
    inner class Shell {
        @JavascriptInterface fun version(): String = BuildConfig.VERSION_NAME
        @JavascriptInterface fun keepAwake(): Boolean = keepAwake
        @JavascriptInterface fun setKeepAwake(on: Boolean) {
            prefs.edit().putBoolean("awake", on).apply()
            runOnUiThread { applyAwake() }
        }
        @JavascriptInterface fun openSettings() { runOnUiThread { showSettings() } }
        @JavascriptInterface fun reload() { runOnUiThread { load() } }
        @JavascriptInterface fun fold(): String = lastFold?.toString() ?: "{\"posture\":\"none\"}"
    }
}
