package com.sbconnect.client

import android.app.Notification
import android.content.pm.PackageManager
import android.os.Build
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import androidx.core.app.NotificationCompat

/**
 * Notification listener that captures incoming notifications and relays them
 * to the Windows receiver via [RelayClient].
 *
 * It self-configures from saved settings if the foreground service isn't
 * running, so notifications keep flowing after a reboot or process restart.
 */
class NotificationRelayService : NotificationListenerService() {

    companion object {
        private const val TAG = "NotifRelay"
        private const val SELF_PACKAGE = "com.sbconnect.client"
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        // Self-configure so the listener works even if RelayService was never
        // started (e.g. right after granting notification access).
        RelayClient.configureFromPrefs(this)
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        val notification = sbn.notification ?: return

        // Drop our own foreground notification, ongoing/persistent ones, and
        // group summaries (their child notifications carry the real content).
        if (sbn.packageName == SELF_PACKAGE) return
        if (sbn.isOngoing) return
        if (notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return

        val title = extractTitle(notification)
        val text = extractText(notification, title)

        if (title.isEmpty() && text.isEmpty()) return

        if (!RelayClient.isConfigured()) {
            RelayClient.configureFromPrefs(this)
        }

        val app = resolveAppLabel(sbn.packageName)
        RelayClient.sendNotification(title, text, app)
        Log.d(TAG, "Relayed notification from $app")
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) = Unit

    private fun extractTitle(notification: Notification): String =
        notification.extras.getCharSequence(Notification.EXTRA_TITLE)
            ?.toString()?.trim().orEmpty()

    private fun extractText(notification: Notification, title: String): String {
        // 1. Messaging-style (chat / SMS / RCS) — richest source of message text.
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

        // 2. Standard body text.
        extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?.let { return it }

        // 3. Expanded big text.
        extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?.let { return it }

        // 4. Inbox-style lines (multiple emails / updates).
        extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
            ?.mapNotNull { line -> line?.toString()?.trim()?.takeIf { it.isNotEmpty() } }
            ?.joinToString("\n")
            ?.takeIf { it.isNotEmpty() }
            ?.let { return it }

        // 5. Sub-text (secondary line).
        extras.getCharSequence(Notification.EXTRA_SUB_TEXT)?.toString()?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?.let { return it }

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
