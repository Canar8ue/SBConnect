package com.sbconnect.client

import android.app.Notification
import android.content.pm.PackageManager
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log

/**
 * Notification listener that captures incoming notifications and relays them
 * to the Windows receiver via [RelayClient].
 *
 * The user must grant notification access (Settings → Notification access)
 * before this service receives anything.
 */
class NotificationRelayService : NotificationListenerService() {

    companion object {
        private const val TAG = "NotifRelay"
        private const val SELF_PACKAGE = "com.sbconnect.client"
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        if (sbn == null) return
        val notification = sbn.notification ?: return

        // Ignore persistent/ongoing notifications, group summaries, and our own.
        if (sbn.isOngoing) return
        if (notification.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        if (sbn.packageName == SELF_PACKAGE) return

        val extras = notification.extras
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        var text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()
        if (text.isEmpty()) {
            text = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString().orEmpty()
        }

        // Nothing useful to relay.
        if (title.isEmpty() && text.isEmpty()) return

        val app = resolveAppLabel(sbn.packageName)
        RelayClient.sendNotification(title, text, app)
        Log.d(TAG, "Relayed notification from $app")
    }

    override fun onNotificationRemoved(sbn: StatusBarNotification?) {
        // Not needed for this app.
    }

    /** Resolve a human-friendly app label, falling back to the package name. */
    private fun resolveAppLabel(packageName: String): String {
        return try {
            val appInfo = packageManager.getApplicationInfo(packageName, 0)
            packageManager.getApplicationLabel(appInfo).toString()
        } catch (e: PackageManager.NameNotFoundException) {
            packageName
        }
    }
}
