package com.obieda.fulfillos.data

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.obieda.fulfillos.domain.PendingPickEvent

class PendingEventStore(context: Context) : SQLiteOpenHelper(context, "fulfillos_events.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE pending_pick_event(
                event_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                client_seq INTEGER NOT NULL,
                task_item_id TEXT NOT NULL,
                location_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                qty INTEGER NOT NULL,
                barcode TEXT,
                created_ms INTEGER NOT NULL,
                state TEXT NOT NULL
            )
            """.trimIndent()
        )
        db.execSQL("CREATE UNIQUE INDEX idx_task_seq ON pending_pick_event(task_id, client_seq)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    @Synchronized
    fun persistBeforeNetwork(event: PendingPickEvent) {
        writableDatabase.execSQL(
            """INSERT OR IGNORE INTO pending_pick_event
            (event_id,task_id,client_seq,task_item_id,location_id,product_id,qty,barcode,created_ms,state)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            arrayOf<Any?>(event.eventId, event.taskId, event.clientSeq, event.taskItemId, event.locationId,
                event.productId, event.qty, event.barcode, event.createdAtEpochMs, event.state.name)
        )
    }

    @Synchronized
    fun mark(eventId: String, state: PendingPickEvent.State) {
        writableDatabase.execSQL("UPDATE pending_pick_event SET state=? WHERE event_id=?", arrayOf(state.name, eventId))
    }

    @Synchronized
    fun pending(taskId: String? = null): List<PendingPickEvent> {
        val where = if (taskId == null) "state IN ('PENDING','SENDING')" else "task_id=? AND state IN ('PENDING','SENDING')"
        val args = if (taskId == null) emptyArray() else arrayOf(taskId)
        val c = readableDatabase.query("pending_pick_event", null, where, args, null, null, "client_seq ASC")
        return buildList {
            c.use {
                while (it.moveToNext()) {
                    add(PendingPickEvent(
                        eventId = it.getString(it.getColumnIndexOrThrow("event_id")),
                        taskId = it.getString(it.getColumnIndexOrThrow("task_id")),
                        clientSeq = it.getLong(it.getColumnIndexOrThrow("client_seq")),
                        taskItemId = it.getString(it.getColumnIndexOrThrow("task_item_id")),
                        locationId = it.getString(it.getColumnIndexOrThrow("location_id")),
                        productId = it.getString(it.getColumnIndexOrThrow("product_id")),
                        qty = it.getInt(it.getColumnIndexOrThrow("qty")),
                        barcode = it.getString(it.getColumnIndexOrThrow("barcode")),
                        createdAtEpochMs = it.getLong(it.getColumnIndexOrThrow("created_ms")),
                        state = PendingPickEvent.State.valueOf(it.getString(it.getColumnIndexOrThrow("state"))),
                    ))
                }
            }
        }
    }

    @Synchronized
    fun nextClientSeq(taskId: String): Long {
        val c = readableDatabase.rawQuery("SELECT COALESCE(MAX(client_seq),0) FROM pending_pick_event WHERE task_id=?", arrayOf(taskId))
        c.use { return if (it.moveToFirst()) it.getLong(0) + 1L else 1L }
    }
}
