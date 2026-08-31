package com.sbconnect.client

import android.app.Notification
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.util.Log
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * Stores the actionable parts of live notifications (media buttons, reply
 * actions) keyed by a stable numeric id, so the PC→phone command channel can
 * execute them when the user clicks a button on the PC.
 */
object ActionStore {

    private const val TAG = "ActionStore"

    private val mediaActions = ConcurrentHashMap<Int, Map<Int, Notification.Action>>()
    private val replyActions = ConcurrentHashMap<Int, Notification.Action>()
    private val nidByKey = ConcurrentHashMap<String, Int>()
    private val nextNid = AtomicInteger(1)

    /** Returns a stable nid for the notification, storing its media buttons. */
    fun putMedia(sbnKey: String, actions: List<Notification.Action>): Int {
        val nid = nidByKey.getOrPut(sbnKey) { nextNid.getAndIncrement() }
        if (actions.isNotEmpty()) {
            mediaActions[nid] = actions.mapIndexed { index, action -> index to action }.toMap()
        }
        return nid
    }

    /** Returns a stable nid for the notification, storing its reply action. */
    fun putReply(sbnKey: String, action: Notification.Action): Int {
        val nid = nidByKey.getOrPut(sbnKey) { nextNid.getAndIncrement() }
        replyActions[nid] = action
        return nid
    }

    fun remove(sbnKey: String) {
        val nid = nidByKey.remove(sbnKey) ?: return
        mediaActions.remove(nid)
        replyActions.remove(nid)
    }

    /** Execute a media button by its index (pause / play / next / previous). */
    fun executeMediaAction(nid: Int, actionId: Int) {
        val action = mediaActions[nid]?.get(actionId)
        if (action == null) {
            Log.w(TAG, "No media action for nid=$nid actionId=$actionId")
            return
        }
        Log.d(TAG, "Executing media action nid=$nid actionId=$actionId label=${action.title}")
        runCatching { action.actionIntent.send() }
            .onFailure { Log.w(TAG, "Media action send failed (nid=$nid actionId=$actionId)", it) }
    }

    /** Inject a reply into the app's RemoteInput-based reply action. */
    fun executeReply(context: Context, nid: Int, text: String) {
        val action = replyActions[nid]
        if (action == null) {
            Log.w(TAG, "No reply action for nid=$nid")
            return
        }
        Log.d(TAG, "Executing reply nid=$nid text=$text")
        runCatching { sendReply(context, action, text) }
            .onFailure { Log.w(TAG, "Reply send failed (nid=$nid)", it) }
    }

    private fun sendReply(context: Context, action: Notification.Action, text: String) {
        val remoteInputs = action.remoteInputs ?: return
        if (remoteInputs.isEmpty()) return
        val intent = Intent()
        val extras = Bundle()
        for (ri in remoteInputs) {
            if (ri.allowFreeFormInput) {
                extras.putCharSequence(ri.resultKey, text)
            }
        }
        RemoteInput.addResultsToIntent(remoteInputs, intent, extras)
        action.actionIntent.send(context, 0, intent)
    }
}
