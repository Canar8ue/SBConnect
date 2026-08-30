package com.sbconnect.client

import android.os.Handler
import android.os.Looper
import android.util.Log
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

    private val executor: ExecutorService = Executors.newFixedThreadPool(2)
    private val mainHandler = Handler(Looper.getMainLooper())

    // Configured once by RelayService, then read by the network workers.
    // Writes happen on the main thread before any request is submitted, so
    // the values are safely visible to the executor threads.
    private var host: String = ""
    private var port: Int = DEFAULT_PORT
    private var code: String = ""

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
     * POST /notify — relays a notification as JSON. Fire-and-forget: any
     * failure is only logged.
     */
    fun sendNotification(title: String, text: String, app: String) {
        if (!isConfigured()) return
        executor.execute {
            try {
                val body =
                    """{"title":${json(title)},"text":${json(text)},"app":${json(app)}}"""
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

    /** Strip an optional scheme (e.g. "http://") the user may have pasted in. */
    private fun normalizeHost(raw: String): String {
        val trimmed = raw.trim()
        return trimmed.substringAfter("://", trimmed)
    }

    /** Minimal JSON string escaping (no external JSON library). */
    private fun json(value: String): String {
        val sb = StringBuilder("\"")
        for (c in value) {
            when (c) {
                '\\' -> sb.append("\\\\")
                '"' -> sb.append("\\\"")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                else -> if (c < ' ') sb.append("\\u%04x".format(c.code)) else sb.append(c)
            }
        }
        return sb.append('"').toString()
    }

    private fun InputStream.closeQuietly() {
        try {
            close()
        } catch (_: Exception) {
            // Ignore: stream is already unusable.
        }
    }
}
