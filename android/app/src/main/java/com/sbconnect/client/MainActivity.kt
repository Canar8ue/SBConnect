package com.sbconnect.client

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.OpenableColumns
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.sbconnect.client.databinding.ActivityMainBinding

/**
 * Android Settings style entry point: configure the receiver, start/stop the relay,
 * grant the required permissions, and send files.
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "MainActivity"
        private const val REQUEST_POST_NOTIFICATIONS = 1001
    }

    private lateinit var binding: ActivityMainBinding

    private val openFilePicker =
        registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            uri?.let { sendFile(it) }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupStatusIndicator()
        prefillFromPrefs()

        binding.buttonStart.setOnClickListener { onStartClicked() }
        binding.buttonStop.setOnClickListener { onStopClicked() }
        binding.buttonNotificationAccess.setOnClickListener { openNotificationAccessSettings() }
        binding.buttonBattery.setOnClickListener { requestBatteryExemption() }
        binding.buttonSendFile.setOnClickListener { openFilePicker.launch(arrayOf("*/*")) }

        requestPostNotificationsIfNeeded()
        showSavedStatus()
    }

    private fun setupStatusIndicator() {
        val dot = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(ContextCompat.getColor(this@MainActivity, R.color.status_inactive))
        }
        binding.indicatorStatus.background = dot
    }

    private fun prefillFromPrefs() {
        binding.inputHost.setText(Prefs.getHost(this))
        binding.inputPort.setText(Prefs.getPort(this).toString())
        binding.inputCode.setText(Prefs.getCode(this))
    }

    private fun onStartClicked() {
        val host = binding.inputHost.text?.toString()?.trim().orEmpty()
        val port = binding.inputPort.text?.toString()?.trim()?.toIntOrNull()
        val code = binding.inputCode.text?.toString()?.trim().orEmpty()

        if (host.isEmpty()) {
            setStatus(getString(R.string.error_host_required), R.color.status_error)
            return
        }
        if (port == null || port !in 1..65535) {
            setStatus(getString(R.string.error_invalid_port), R.color.status_error)
            return
        }

        Prefs.setHost(this, host)
        Prefs.setPort(this, port)
        Prefs.setCode(this, code)

        RelayService.start(this, host, port, code)
        setStatus(getString(R.string.status_connecting, host), R.color.primary)

        // Immediate ping for fast visual feedback
        RelayClient.ping(host, port, code) { ok ->
            if (ok) {
                setStatus(getString(R.string.status_connected, host), R.color.status_active)
            } else {
                setStatus(getString(R.string.status_not_connected, host), R.color.status_error)
            }
        }
    }

    private fun onStopClicked() {
        RelayService.stop(this)
        setStatus(getString(R.string.status_stopped), R.color.status_inactive)
    }

    private fun openNotificationAccessSettings() {
        try {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        } catch (e: Exception) {
            Log.w(TAG, "Unable to open notification listener settings", e)
            Toast.makeText(this, R.string.error_open_settings, Toast.LENGTH_SHORT).show()
        }
    }

    private fun requestBatteryExemption() {
        val pm = getSystemService(PowerManager::class.java) ?: return
        if (pm.isIgnoringBatteryOptimizations(packageName)) {
            Toast.makeText(this, R.string.battery_already_exempt, Toast.LENGTH_SHORT).show()
            return
        }
        try {
            startActivity(
                Intent(
                    Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:$packageName")
                )
            )
        } catch (e: Exception) {
            Log.w(TAG, "Unable to request battery optimization exemption", e)
            Toast.makeText(this, R.string.battery_intent_failed, Toast.LENGTH_SHORT).show()
        }
    }

    private fun sendFile(uri: Uri) {
        var name = getString(R.string.default_file_name)
        var size = -1L

        try {
            contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val nameIdx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (nameIdx >= 0) {
                        cursor.getString(nameIdx)?.takeIf { it.isNotBlank() }?.let { name = it }
                    }
                    val sizeIdx = cursor.getColumnIndex(OpenableColumns.SIZE)
                    if (sizeIdx >= 0 && !cursor.isNull(sizeIdx)) {
                        size = cursor.getLong(sizeIdx)
                    }
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "Failed to query file metadata", e)
        }

        val inputStream = try {
            contentResolver.openInputStream(uri)
        } catch (e: Exception) {
            Log.w(TAG, "Failed to open file stream", e)
            null
        }

        if (inputStream == null) {
            setStatus(getString(R.string.error_open_file), R.color.status_error)
            return
        }

        setStatus(getString(R.string.status_sending_file, name), R.color.primary)
        RelayClient.sendFile(inputStream, name, { ok, error ->
            val message = if (ok) {
                getString(R.string.status_file_sent, name)
            } else {
                getString(R.string.status_file_failed, error ?: getString(R.string.unknown_error))
            }
            setStatus(message, if (ok) R.color.status_active else R.color.status_error)
            Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
        }, contentLength = size)
    }

    private fun requestPostNotificationsIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                REQUEST_POST_NOTIFICATIONS
            )
        }
    }

    private fun showSavedStatus() {
        val host = Prefs.getHost(this)
        if (host.isEmpty()) {
            setStatus(getString(R.string.status_not_configured), R.color.status_inactive)
        } else {
            setStatus(getString(R.string.status_saved, host, Prefs.getPort(this)), R.color.status_inactive)
        }
    }

    private fun setStatus(text: String, colorRes: Int = R.color.status_inactive) {
        binding.textStatus.text = text
        val dot = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(ContextCompat.getColor(this@MainActivity, colorRes))
        }
        binding.indicatorStatus.background = dot
    }
}
