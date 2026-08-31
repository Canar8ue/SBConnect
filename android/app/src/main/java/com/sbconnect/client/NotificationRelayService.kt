package com.sbconnect.client

import android.app.Notification
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.drawable.BitmapDrawable
import android.graphics.drawable.Drawable
import android.graphics.drawable.Icon
import android.os.Build
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Base64
import android.util.Log
import androidx.core.app.NotificationCompat
import java.io.ByteArrayOutputStream
import java.util.concurrent.ConcurrentHashMap

/**
 * Notification listener that captures incoming notifications and relays them
 * to the Windows receiver via [RelayClient].
 *
 * Media (ongoing) notifications are relayed with their action buttons and album
 * artwork so the PC can display the cover art and control playback; message
 * notifications expose a "Reply" action when the app provides one.
 */
class NotificationRelayService : NotificationListenerService() {

    companion object {
        private const val TAG = "NotifRelay"
        private const val SELF_PACKAGE = "com.sbconnect.client"
    }

    // Media notifications update constantly (progress ticks); only relay when
    // the actual content (title/text/actions) changes.
    private val mediaState = ConcurrentHashMap<String, String>()

    override fun onListenerConnected() {
        super.onListenerConnected()
        RelayClient.configureFromPrefs(this)
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        val notification = sbn.notification ?: return

        // Drop our own foreground notification and group summaries.
        if (sbn.packageName == SELF_PACKAGE) return
        if (notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        // Media notifications are ongoing but carry useful controls — let them
        // through; skip other ongoing/persistent noise (music apps, VPN, etc.).
        val media = isMediaNotification(notification)
        if (sbn.isOngoing && !media) return

        val title = extractTitle(notification)
        val text = extractText(notification, title)

        if (!RelayClient.isConfigured()) {
            RelayClient.configureFromPrefs(this)
        }
        val app = resolveAppLabel(sbn.packageName)

        if (media) {
            relayMedia(sbn, notification, title, text, app)
            return
        }

        // Normal / message notifications. If the app exposes a RemoteInput
        // reply action (Google Messages, WhatsApp, Telegram, ...) enable reply.
        val replyAction = notification.actions?.firstOrNull { !it.remoteInputs.isNullOrEmpty() }
        if (title.isEmpty() && text.isEmpty() && replyAction == null) return

        val nid = if (replyAction != null) ActionStore.putReply(sbn.key, replyAction) else -1
        val type = if (replyAction != null) "message" else "normal"
        val art = extractArtwork(notification)
        RelayClient.sendNotification(
            title,
            text,
            app,
            nid = nid,
            type = type,
            canReply = replyAction != null,
            art = art,
        )
        Log.d(TAG, "Relayed notification from $app (type=$type)")
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        if (sbn == null) return
        ActionStore.remove(sbn.key)
        mediaState.remove(sbn.key)
    }

    private fun relayMedia(
        sbn: StatusBarNotification,
        notification: Notification,
        title: String,
        text: String,
        app: String,
    ) {
        val actions = notification.actions?.toList().orEmpty()
        val signature = "$title|$text|" + actions.joinToString(",") { it.title?.toString().orEmpty() }
        if (mediaState[sbn.key] == signature) return  // progress tick, nothing new
        mediaState[sbn.key] = signature

        val nid = ActionStore.putMedia(sbn.key, actions)
        val actionPairs = actions.mapIndexed { index, action -> index to action.title?.toString().orEmpty() }
        val art = extractArtwork(notification)
        RelayClient.sendNotification(
            title,
            text,
            app,
            nid = nid,
            type = "media",
            actions = actionPairs,
            art = art,
        )
        Log.d(TAG, "Relayed media from $app (hasArt=${art != null})")
    }

    private fun isMediaNotification(notification: Notification): Boolean {
        if (notification.category == Notification.CATEGORY_TRANSPORT) return true
        val actions = notification.actions ?: return false
        if (actions.isEmpty()) return false
        val titles = actions.mapNotNull { it.title?.toString()?.lowercase() }
        val keys = listOf("play", "pause", "next", "previous", "skip", "seek")
        return keys.any { key -> titles.any { it.contains(key) } }
    }

    private fun extractArtwork(notification: Notification): String? {
        try {
            // 1. Try getLargeIcon() (Icon) on API 23+
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                val icon = notification.getLargeIcon()
                if (icon != null) {
                    val drawable = icon.loadDrawable(this)
                    if (drawable != null) {
                        val bmp = drawableToBitmap(drawable)
                        if (bmp != null) return bitmapToBase64(bmp)
                    }
                }
            }

            // 2. Try the legacy largeIcon Bitmap field
            @Suppress("DEPRECATION")
            val legacyBitmap = notification.largeIcon
            if (legacyBitmap != null) {
                return bitmapToBase64(legacyBitmap)
            }

            // 3. Try EXTRA_LARGE_ICON parcelable
            val extraLarge = notification.extras.get(Notification.EXTRA_LARGE_ICON)
            if (extraLarge is Bitmap) {
                return bitmapToBase64(extraLarge)
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && extraLarge is Icon) {
                val drawable = extraLarge.loadDrawable(this)
                if (drawable != null) {
                    val bmp = drawableToBitmap(drawable)
                    if (bmp != null) return bitmapToBase64(bmp)
                }
            }

            // 4. Try EXTRA_PICTURE
            val picture = notification.extras.get(Notification.EXTRA_PICTURE)
            if (picture is Bitmap) {
                return bitmapToBase64(picture)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to extract artwork", e)
        }
        return null
    }

    private fun drawableToBitmap(drawable: Drawable): Bitmap? {
        if (drawable is BitmapDrawable && drawable.bitmap != null) {
            return drawable.bitmap
        }
        val w = if (drawable.intrinsicWidth > 0) drawable.intrinsicWidth else 256
        val h = if (drawable.intrinsicHeight > 0) drawable.intrinsicHeight else 256
        val bitmap = Bitmap.createBitmap(w.coerceIn(64, 512), h.coerceIn(64, 512), Bitmap.Config.ARGB_8888)
        val canvas = Canvas(bitmap)
        drawable.setBounds(0, 0, canvas.width, canvas.height)
        drawable.draw(canvas)
        return bitmap
    }

    private fun bitmapToBase64(bitmap: Bitmap): String {
        val maxDim = 256
        val scale = minOf(1f, maxDim.toFloat() / maxOf(bitmap.width, bitmap.height))
        val targetW = (bitmap.width * scale).toInt().coerceAtLeast(1)
        val targetH = (bitmap.height * scale).toInt().coerceAtLeast(1)
        val scaled = if (scale < 1f) Bitmap.createScaledBitmap(bitmap, targetW, targetH, true) else bitmap
        val stream = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, 85, stream)
        return Base64.encodeToString(stream.toByteArray(), Base64.NO_WRAP)
    }

    private fun extractTitle(notification: Notification): String =
        notification.extras.getCharSequence(Notification.EXTRA_TITLE)
            ?.toString()?.trim().orEmpty()

    private fun extractText(notification: Notification, title: String): String {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            val style = NotificationCompat.MessagingStyle
                .extractMessagingStyleFromNotification(notification)
            val last = style?.messages?.lastOrNull()
            if (last != null) {
                val sender = last.person?.name?.toString()?.trim().orEmpty()
                val text = last.text?.toString()?.trim().orEmpty()
                if (text.isNotEmpty()) {
                    return if (sender.isNotEmpty() && sender != title) "$sender: $text" else text
                }
            }
        }

        val extras = notification.extras
        extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.trim()
            ?.takeIf { it.isNotEmpty() }?.let { return it }
        extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.trim()
            ?.takeIf { it.isNotEmpty() }?.let { return it }
        extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
            ?.mapNotNull { line -> line?.toString()?.trim()?.takeIf { it.isNotEmpty() } }
            ?.joinToString("\n")
            ?.takeIf { it.isNotEmpty() }?.let { return it }
        extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString()?.trim()
            ?.takeIf { it.isNotEmpty() }?.let { return it }
        return ""
    }

    private fun resolveAppLabel(packageName: String): String = try {
        packageManager.getApplicationLabel(
            packageManager.getApplicationInfo(packageName, 0)
        ).toString()
    } catch (e: PackageManager.NameNotFoundException) {
        packageName
    }
}
