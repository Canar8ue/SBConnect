package com.sbconnect.client

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.util.Log

/**
 * Persistent foreground service that keeps the process (and therefore the
 * notification listener + network link) alive. It configures [RelayClient]
 * and reflects the connection state in its ongoing notification.
 */
class RelayService : Service() {

    companion object {
        private const val TAG = "RelayService"
        const val CHANNEL_ID = "sbconnect_relay"
        const val NOTIFICATION_ID = 1

        private const val ACTION_STOP = "com.sbconnect.client.action.STOP"
        private const val EXTRA_HOST = "extra_host"
        private const val EXTRA_PORT = "extra_port"
        private const val EXTRA_CODE = "extra_code"

        /** Start the relay foreground service with the given receiver details. */
        fun start(context: Context, host: String, port: Int, code: String) {
            val intent = Intent(context, RelayService::class.java).apply {
                putExtra(EXTRA_HOST, host)
                putExtra(EXTRA_PORT, port)
                putExtra(EXTRA_CODE, code)
            }
            context.startForegroundService(intent)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, RelayService::class.java))
        }
    }

    private var host: String = ""
    private var port: Int = RelayClient.DEFAULT_PORT
    private var code: String = ""

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Stop action from the ongoing notification's action button.
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }

        // New explicit values win; otherwise fall back to the saved settings
        // (also covers a START_STICKY restart with a null intent).
        host = intent?.getStringExtra(EXTRA_HOST) ?: Prefs.getHost(this)
        port = intent?.getIntExtra(EXTRA_PORT, Prefs.getPort(this)) ?: Prefs.getPort(this)
        code = intent?.getStringExtra(EXTRA_CODE) ?: Prefs.getCode(this)

        RelayClient.configure(host, port, code)

        startForeground(NOTIFICATION_ID, buildNotification(getString(R.string.notif_connecting)))
        pingAndUpdate()

        Log.d(TAG, "RelayService started for $host:$port")
        return START_STICKY
    }

    override fun onDestroy() {
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }

    private fun pingAndUpdate() {
        RelayClient.ping(host, port, code) { ok ->
            updateNotification(
                if (ok) getString(R.string.notif_connected, host)
                else getString(R.string.notif_not_connected)
            )
        }
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIFICATION_ID, buildNotification(text))
    }

    private fun createChannel() {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.channel_relay_name),
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description = getString(R.string.channel_relay_desc)
        }
        nm.createNotificationChannel(channel)
    }

    private fun buildNotification(text: String): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, RelayService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return Notification.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentIntent(openIntent)
            .setOngoing(true)
            .addAction(
                Notification.Action.Builder(
                    null,
                    getString(R.string.action_stop),
                    stopIntent
                ).build()
            )
            .build()
    }
}
