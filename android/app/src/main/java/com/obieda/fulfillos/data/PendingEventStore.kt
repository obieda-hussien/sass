package com.obieda.fulfillos.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.obieda.fulfillos.domain.PendingScan
import org.json.JSONObject

/**
 * Durable local journal.
 *
 * The UI may disappear or the PDA may reboot after this row is committed.
 * Unknown events are replayed with the same eventId after reconciliation.
 */
class PendingEventStore(context: Context) :
    SQLiteOpenHelper(context, "fulfillos_events.db", null, 1) {

    override fun onConfigure(db: SQLiteDatabase) {
        db.enableWriteAheadLogging()
        db.execSQL("PRAGMA synchronous=FULL")
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE pending_events (
              event_id TEXT PRIMARY KEY NOT NULL,
              task_id TEXT NOT NULL,
              client_sequence INTEGER NOT NULL,
              payload TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 0,
              last_error TEXT
            )
            """.trimIndent()
        )
        db.execSQL(
            "CREATE UNIQUE INDEX pending_task_sequence ON pending_events(task_id, client_sequence)"
        )
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    fun enqueue(scan: PendingScan) {
        val payload = JSONObject()
            .put("event_id", scan.eventId)
            .put("task_line_id", scan.taskLineId)
            .put("associate_id", scan.associateId)
            .put("device_id", scan.deviceId)
            .put("client_sequence", scan.clientSequence)
            .put("client_task_version", scan.clientTaskVersion)
            .put("location_code", scan.locationCode)
            .put("barcode", scan.barcode)
            .put("quantity", scan.quantity)
            .toString()

        val values = ContentValues().apply {
            put("event_id", scan.eventId)
            put("task_id", scan.taskId)
            put("client_sequence", scan.clientSequence)
            put("payload", payload)
            put("created_at", scan.createdAtEpochMs)
        }
        writableDatabase.insertOrThrow("pending_events", null, values)
    }

    fun removeCommitted(eventIds: Collection<String>) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            eventIds.forEach { eventId ->
                db.delete("pending_events", "event_id = ?", arrayOf(eventId))
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    fun list(taskId: String? = null): List<StoredEvent> {
        val where = if (taskId == null) null else "task_id = ?"
        val args = taskId?.let { arrayOf(it) }
        val cursor = readableDatabase.query(
            "pending_events",
            arrayOf(
                "event_id",
                "task_id",
                "client_sequence",
                "payload",
                "created_at",
                "attempt_count",
                "last_error",
            ),
            where,
            args,
            null,
            null,
            "created_at ASC",
        )
        return buildList {
            cursor.use {
                while (it.moveToNext()) {
                    add(
                        StoredEvent(
                            eventId = it.getString(0),
                            taskId = it.getString(1),
                            clientSequence = it.getInt(2),
                            payload = it.getString(3),
                            createdAt = it.getLong(4),
                            attemptCount = it.getInt(5),
                            lastError = it.getString(6),
                        )
                    )
                }
            }
        }
    }

    fun recordFailure(eventId: String, error: String) {
        writableDatabase.execSQL(
            """
            UPDATE pending_events
            SET attempt_count = attempt_count + 1, last_error = ?
            WHERE event_id = ?
            """.trimIndent(),
            arrayOf(error.take(500), eventId),
        )
    }
}

data class StoredEvent(
    val eventId: String,
    val taskId: String,
    val clientSequence: Int,
    val payload: String,
    val createdAt: Long,
    val attemptCount: Int,
    val lastError: String?,
)
