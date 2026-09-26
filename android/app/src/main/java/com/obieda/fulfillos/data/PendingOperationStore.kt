package com.obieda.fulfillos.data

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import com.obieda.fulfillos.domain.PendingOperationEvent

class PendingOperationStore(context: Context) : SQLiteOpenHelper(context, "fulfillos_operations.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE pending_operation(
                event_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                resource_id TEXT,
                product_id TEXT NOT NULL,
                qty INTEGER NOT NULL,
                source_location_id TEXT,
                destination_location_id TEXT,
                reason TEXT,
                created_ms INTEGER NOT NULL,
                state TEXT NOT NULL
            )
            """.trimIndent()
        )
        db.execSQL("CREATE INDEX idx_pending_operation_state ON pending_operation(state, created_ms)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    @Synchronized
    fun persistBeforeNetwork(event: PendingOperationEvent) {
        writableDatabase.execSQL(
            """INSERT OR IGNORE INTO pending_operation
            (event_id,kind,resource_id,product_id,qty,source_location_id,destination_location_id,reason,created_ms,state)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            arrayOf<Any?>(
                event.eventId, event.kind.name, event.resourceId, event.productId, event.qty,
                event.sourceLocationId, event.destinationLocationId, event.reason,
                event.createdAtEpochMs, event.state.name,
            )
        )
    }

    @Synchronized
    fun mark(eventId: String, state: PendingOperationEvent.State) {
        writableDatabase.execSQL(
            "UPDATE pending_operation SET state=? WHERE event_id=?",
            arrayOf(state.name, eventId),
        )
    }

    @Synchronized
    fun pending(): List<PendingOperationEvent> {
        val cursor = readableDatabase.query(
            "pending_operation",
            null,
            "state IN ('PENDING','SENDING')",
            null,
            null,
            null,
            "created_ms ASC",
        )
        return buildList {
            cursor.use {
                while (it.moveToNext()) {
                    add(
                        PendingOperationEvent(
                            eventId = it.getString(it.getColumnIndexOrThrow("event_id")),
                            kind = PendingOperationEvent.Kind.valueOf(it.getString(it.getColumnIndexOrThrow("kind"))),
                            resourceId = it.getString(it.getColumnIndexOrThrow("resource_id")),
                            productId = it.getString(it.getColumnIndexOrThrow("product_id")),
                            qty = it.getInt(it.getColumnIndexOrThrow("qty")),
                            sourceLocationId = it.getString(it.getColumnIndexOrThrow("source_location_id")),
                            destinationLocationId = it.getString(it.getColumnIndexOrThrow("destination_location_id")),
                            reason = it.getString(it.getColumnIndexOrThrow("reason")),
                            createdAtEpochMs = it.getLong(it.getColumnIndexOrThrow("created_ms")),
                            state = PendingOperationEvent.State.valueOf(it.getString(it.getColumnIndexOrThrow("state"))),
                        )
                    )
                }
            }
        }
    }

    @Synchronized
    fun pendingCount(): Int {
        val cursor = readableDatabase.rawQuery(
            "SELECT COUNT(*) FROM pending_operation WHERE state IN ('PENDING','SENDING')",
            null,
        )
        cursor.use { return if (it.moveToFirst()) it.getInt(0) else 0 }
    }
}
