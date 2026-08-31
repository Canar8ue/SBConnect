package com.sbconnect.client

import android.os.Handler
import android.os.Looper
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * HTTP client that talks to the SBConnect Windows receiver.
 *
 * The Windows receiver is the HTTP server; this singleton is the HTTP client.
 * Every request carries the `X-SB-Connect-Code` pairing header when a code is
 * set. All network I/O runs on a background [ExecutorService]; results are
 * delivered back on the main thread so callers can touch the UI directly.
 */
object RelayClient {

    private const val TAG = "RelayClient"
    const val DEFAULT_PORT = 45800
    private const val TIMEOUT_MS = 5000
    private const val COMMAND_READ_TIMEOUT_MS = 40000

    private val executor: ExecutorService = Executors.newFixedThreadPool(2)
    private val mainHandler = Handler(Looper.getMainLooper())

    // Configured once by RelayService, then read by the network workers.
    private var host: String = ""
    private var port: Int = DEFAULT_PORT
    private var code: String = ""

    @Volatile
    private var commandChannelRunning = false

    /** True once a host has been configured. */
    fun isConfigured(): Boolean = host.isNotBlank()

    /** Store the receiver address and pairing code. */
    fun configure(host: String, port: Int, code: String) {
        this.host = normalizeHost(host)
        this.port = if (port in 1..65535) port else DEFAULT_PORT
        this.code = code.trim()
    }

    /** Configure from saved settings so notifications relay even if the foreground service isn't running. */
    fun configureFromPrefs(context: android.content.Context) {
        configure(Prefs.getHost(context), Prefs.getPort(context), Prefs.getCode(context))
    }

    private val baseUrl: String
        get() = "http://$host:$port"

    /**
     * GET /ping — connectivity/pairing test. Reports success only on HTTP 200.
     */
    fun ping(host: String, port: Int, code: String, onResult: (Boolean) -> Unit) {
        executor.execute {
            var ok = false
            try {
                val conn = open("http://${normalizeHost(host)}:$port/ping", code, "GET")
                try {
                    ok = conn.responseCode == HttpURLConnection.HTTP_OK
                } finally {
                    conn.disconnect()
                }
            } catch (e: Exception) {
                Log.w(TAG, "ping failed", e)
            }
            mainHandler.post { onResult(ok) }
        }
    }

    /**
     * POST /notify — relays a notification as JSON, optionally with media
     * action buttons or a reply action. Fire-and-forget: failures are logged.
     */
    fun sendNotification(
        title: String,
        text: String,
        app: String,
        nid: Int = -1,
        type: String = "normal",
        actions: List<Pair<Int, String>> = emptyList(),
        canReply: Boolean = false,
    ) {
        if (!isConfigured()) return
        executor.execute {
            try {
                val body = JSONObject()
                    .put("title", title)
                    .put("text", text)
                    .put("app", app)
                    .put("nid", nid)
                    .put("type", type)
                    .put("can_reply", canReply)
                    .apply {
                        val arr = JSONArray()
                        for ((id, label) in actions) {
                            arr.put(JSONObject().put("id", id).put("label", label))
                        }
                        put("actions", arr)
                    }
                    .toString()
                val conn = open("$baseUrl/notify", code, "POST")
                try {
                    conn.doOutput = true
                    conn.setRequestProperty("Content-Type", "application/json")
                    conn.outputStream.use { out ->
                        out.write(body.toByteArray(Charsets.UTF_8))
                        out.flush()
                    }
                    conn.responseCode
                } finally {
                    conn.disconnect()
                }
            } catch (e: Exception) {
                Log.w(TAG, "sendNotification failed", e)
            }
        }
    }

    /**
     * Long-poll loop for the PC → phone command channel. Holds an open
     * /commands request; when the PC queues a command (toast button click) it
     * is delivered here and forwarded to [onCommand] on the main thread.
     */
    fun startCommandChannel(onCommand: (JSONObject) -> Unit) {
        if (commandChannelRunning) return
        commandChannelRunning = true
        executor.execute {
            while (commandChannelRunning && isConfigured()) {
                try {
                    val conn = openLong("$baseUrl/commands", code)
                    try {
                        if (conn.responseCode == HttpURLConnection.HTTP_OK) {
                            val raw = conn.inputStream.bufferedReader().readText()
                            val cmd = JSONObject(raw).optJSONObject("command")
                            if (cmd != null) {
                                mainHandler.post { onCommand(cmd) }
                            }
                        }
                    } finally {
                        conn.disconnect()
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "command channel error", e)
                    try {
                        Thread.sleep(2000)
                    } catch (_: InterruptedException) {
                        break
                    }
                }
            }
            commandChannelRunning = false
        }
    }

    fun stopCommandChannel() {
        commandChannelRunning = false
    }

    /**
     * POST /file — streams raw file bytes to the receiver.
     *
     * @param contentLength the exact byte length from [android.provider.OpenableColumns.SIZE],
     *   or -1 when unknown (falls back to chunked transfer, which the receiver
     *   may or may not accept).
     */
    fun sendFile(
        inputStream: InputStream,
        fileName: String,
        onResult: (Boolean, String?) -> Unit,
        contentLength: Long = -1L
    ) {
        if (!isConfigured()) {
            inputStream.closeQuietly()
            mainHandler.post { onResult(false, "Not connected. Start the relay first.") }
            return
        }
        executor.execute {
            var ok = false
            var error: String? = null
            try {
                val conn = open("$baseUrl/file", code, "POST")
                try {
                    conn.doOutput = true
                    conn.setRequestProperty("Content-Type", "application/octet-stream")
                    conn.setRequestProperty("X-File-Name", URLEncoder.encode(fileName, "UTF-8"))
                    if (contentLength >= 0) {
                        // Fixed length lets HttpURLConnection set Content-Length itself.
                        conn.setFixedLengthStreamingMode(contentLength)
                    } else {
                        conn.setChunkedStreamingMode(0)
                    }
                    conn.outputStream.use { out -> inputStream.copyTo(out) }
                    val status = conn.responseCode
                    ok = status == HttpURLConnection.HTTP_OK
                    if (!ok) error = "HTTP $status"
                } finally {
                    conn.disconnect()
                }
            } catch (e: Exception) {
                Log.w(TAG, "sendFile failed", e)
                error = e.message ?: e.javaClass.simpleName
            } finally {
                inputStream.closeQuietly()
            }
            mainHandler.post { onResult(ok, error) }
        }
    }

    /** Build and open a connection with common timeouts and the pairing header. */
    private fun open(url: String, code: String, method: String): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            useCaches = false
            if (code.isNotBlank()) {
                setRequestProperty("X-SB-Connect-Code", code.trim())
            }
        }

    /** Like [open] but with a long read timeout for the command long-poll. */
    private fun openLong(url: String, code: String): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = TIMEOUT_MS
            readTimeout = COMMAND_READ_TIMEOUT_MS
            useCaches = false
            if (code.isNotBlank()) {
                setRequestProperty("X-SB-Connect-Code", code.trim())
            }
        }

    /** Strip an optional scheme (e.g. "http://") the user may have pasted in. */
    private fun normalizeHost(raw: String): String {
        val trimmed = raw.trim()
        return trimmed.substringAfter("://", trimmed)
    }

    private fun InputStream.closeQuietly() {
        try {
            close()
        } catch (_: Exception) {
            // Ignore: stream is already unusable.
        }
    }
}
