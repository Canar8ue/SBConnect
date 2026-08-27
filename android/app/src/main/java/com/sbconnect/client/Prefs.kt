package com.sbconnect.client

import android.content.Context
import android.content.SharedPreferences

/**
 * Tiny wrapper over [SharedPreferences] that stores the receiver host, port
 * and pairing code entered by the user.
 */
object Prefs {

    private const val NAME = "sbconnect_prefs"
    private const val KEY_HOST = "host"
    private const val KEY_PORT = "port"
    private const val KEY_CODE = "code"

    private fun prefs(context: Context): SharedPreferences =
        context.applicationContext.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    fun getHost(context: Context): String = prefs(context).getString(KEY_HOST, "").orEmpty()

    fun getPort(context: Context): Int =
        prefs(context).getInt(KEY_PORT, RelayClient.DEFAULT_PORT)

    fun getCode(context: Context): String = prefs(context).getString(KEY_CODE, "").orEmpty()

    fun setHost(context: Context, value: String) =
        prefs(context).edit().putString(KEY_HOST, value.trim()).apply()

    fun setPort(context: Context, value: Int) =
        prefs(context).edit().putInt(KEY_PORT, value).apply()

    fun setCode(context: Context, value: String) =
        prefs(context).edit().putString(KEY_CODE, value.trim()).apply()
}
