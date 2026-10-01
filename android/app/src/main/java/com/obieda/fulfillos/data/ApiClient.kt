package com.obieda.fulfillos.data

import com.obieda.fulfillos.BuildConfig
import com.obieda.fulfillos.domain.InventoryLookup
import com.obieda.fulfillos.domain.StowTaskSummary
import com.obieda.fulfillos.domain.ShipmentSummary
import com.obieda.fulfillos.domain.ShipmentLineSummary
import com.obieda.fulfillos.domain.ReplenishmentSummary
import com.obieda.fulfillos.domain.RecoverySummary
import com.obieda.fulfillos.domain.RecoveryItem
import com.obieda.fulfillos.domain.CycleCountEntrySummary
import com.obieda.fulfillos.domain.InventoryRow
import com.obieda.fulfillos.domain.BarcodeProduct
import com.obieda.fulfillos.domain.ClosedBagSummary
import com.obieda.fulfillos.domain.CompletionItem
import com.obieda.fulfillos.domain.OrderCompletionSummary
import com.obieda.fulfillos.domain.PendingOperationEvent
import com.obieda.fulfillos.domain.PendingPickEvent
import com.obieda.fulfillos.domain.SessionInfo
import com.obieda.fulfillos.domain.TaskItem
import com.obieda.fulfillos.domain.TaskSnapshot
import com.obieda.fulfillos.domain.UnpackItemRecommendation
import com.obieda.fulfillos.domain.UnpackManifestItem
import com.obieda.fulfillos.domain.UnpackSummary
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

class ApiClient {
    @Volatile var accessToken: String? = null

    data class Result(val code: Int, val body: String) {
        val ok: Boolean get() = code in 200..299
    }

    fun login(username: String, password: String, deviceId: String, appVersion: String): Result =
        request(
            "/auth/login",
            JSONObject()
                .put("username", username)
                .put("password", password)
                .put("device_id", deviceId)
                .put("app_version", appVersion)
                .toString(),
            authorized = false,
        )

    fun forgotPassword(identifier: String): Result =
        request(
            "/auth/forgot-password",
            JSONObject()
                .put("identifier", identifier.trim())
                .toString(),
            authorized = false,
        )

    fun refresh(refreshToken: String, deviceId: String): Result =
        request(
            "/auth/refresh",
            JSONObject()
                .put("refresh_token", refreshToken)
                .put("device_id", deviceId)
                .toString(),
            authorized = false,
        )

    fun completeFirstLogin(newPin: String): Result =
        request(
            "/auth/complete-first-login",
            JSONObject()
                .put("new_password", newPin)
                .toString(),
        )

    fun heartbeat(
        currentTaskId: String?,
        appVersion: String,
        connectivity: String,
        batteryPercent: Int?,
        lastLocationId: String?,
        activity: String,
    ): Result =
        request(
            "/devices/heartbeat",
            JSONObject()
                .put("current_task_id", currentTaskId ?: JSONObject.NULL)
                .put("app_version", appVersion)
                .put("connectivity", connectivity)
                .put("battery_percent", batteryPercent ?: JSONObject.NULL)
                .put("last_location_id", lastLocationId ?: JSONObject.NULL)
                .put("activity", activity)
                .toString(),
        )

    fun getActiveTask(): Result = request("/me/active-task", null, "GET")
    fun claimNextTask(): Result = request("/tasks/claim-next", "{}")
    fun getMyOffers(): Result = request("/ops/dispatch/me/offers", null, "GET")
    fun acceptTask(taskId: String): Result = request("/ops/dispatch/tasks/${encode(taskId)}/claim", "{}")
    fun rejectTask(taskId: String, reason: String = "ASSOCIATE_REJECTED"): Result =
        request(
            "/ops/dispatch/tasks/${encode(taskId)}/reject",
            JSONObject().put("reason", reason).toString(),
        )

    fun getTask(taskId: String): Result = request("/tasks/${encode(taskId)}", null, "GET")

    fun postPick(event: PendingPickEvent): Result {
        val json = JSONObject()
            .put("event_id", event.eventId)
            .put("client_seq", event.clientSeq)
            .put("task_item_id", event.taskItemId)
            .put("qty", event.qty)

        return when (event.kind) {
            PendingPickEvent.Kind.PICK -> {
                json.put("location_id", event.locationId)
                    .put("product_id", event.productId)
                    .put("barcode", event.barcode ?: JSONObject.NULL)
                request("/tasks/${encode(event.taskId)}/scan", json.toString())
            }
            PendingPickEvent.Kind.SHORT -> {
                json.put("reason", event.reason ?: "MISSING_AT_LOCATION")
                request("/tasks/${encode(event.taskId)}/short", json.toString())
            }
            PendingPickEvent.Kind.SKIP -> {
                json.put("reason", event.reason ?: "DEFERRED")
                request("/ops/tasks/${encode(event.taskId)}/skip", json.toString())
            }
            PendingPickEvent.Kind.DAMAGED -> {
                json.put("reason", event.reason ?: "DAMAGED")
                request("/ops/tasks/${encode(event.taskId)}/damaged", json.toString())
            }
        }
    }

    fun closeBag(taskId: String, spooCode: String): Result =
        request(
            "/ops/tasks/${encode(taskId)}/bags",
            JSONObject().put("spoo_code", spooCode.trim()).toString(),
        )

    fun finishPicking(taskId: String): Result =
        request("/ops/tasks/${encode(taskId)}/finish-picking", "{}")

    fun getWorkerState(): Result = request("/ops/me/state", null, "GET")

    fun updateWorkerState(state: String, reason: String? = null): Result =
        request(
            "/ops/me/state",
            JSONObject()
                .put("state", state)
                .put("reason", reason ?: JSONObject.NULL)
                .toString(),
        )

    fun parseWorkerState(body: String): String =
        JSONObject(body).optString("state", "AVAILABLE")

    fun startBreak(breakType: String = "REST", paid: Boolean = true): Result =
        request(
            "/ops/breaks/start",
            JSONObject()
                .put("break_type", breakType)
                .put("paid", paid)
                .toString(),
        )

    fun endBreak(): Result =
        request("/ops/breaks/end", "{}")

    fun inventoryByProduct(asin: String): Result =
        request("/inventory/product/${encode(asin)}", null, "GET")

    fun inventoryByLocation(locationId: String): Result =
        request("/inventory/location/${encode(locationId)}", null, "GET")

    fun inventoryByBarcode(barcode: String): Result =
        request("/inventory/barcode/${encode(barcode)}", null, "GET")

    fun getActiveUnpack(temperatureClass: String? = null): Result {
        val suffix = temperatureClass?.let { "?temperature_class=${encode(it)}" }.orEmpty()
        return request("/unpack/active$suffix", null, "GET")
    }

    fun startUnpack(temperatureClass: String): Result =
        request(
            "/unpack/sessions",
            JSONObject().put("temperature_class", temperatureClass).toString(),
        )

    fun bindUnpackSource(sessionId: String, sourceRef: String): Result =
        request(
            "/unpack/sessions/${encode(sessionId)}/source",
            JSONObject().put("source_ref", sourceRef.trim()).toString(),
        )

    fun getUnpack(sessionId: String): Result =
        request("/unpack/sessions/${encode(sessionId)}", null, "GET")

    fun completeUnpack(sessionId: String): Result =
        request("/unpack/sessions/${encode(sessionId)}/complete", "{}")

    fun postOperation(event: PendingOperationEvent): Result {
        val json = JSONObject()
            .put("event_id", event.eventId)
            .put("product_id", event.productId)
            .put("qty", event.qty)

        return when (event.kind) {
            PendingOperationEvent.Kind.UNPACK_SCAN -> {
                val sessionId = requireNotNull(event.resourceId) { "UNPACK_SCAN requires session id" }
                request("/unpack/sessions/${encode(sessionId)}/scan", json.toString())
            }
            PendingOperationEvent.Kind.BOH_MOVE -> {
                json.put("source_location_id", event.sourceLocationId)
                    .put("destination_location_id", event.destinationLocationId)
                request("/boh/move", json.toString())
            }
            PendingOperationEvent.Kind.DAMAGE -> {
                json.put("source_location_id", event.sourceLocationId)
                    .put("reason", event.reason ?: "DAMAGED")
                request("/damage", json.toString())
            }
            PendingOperationEvent.Kind.RECOVERY_STOW -> {
                val taskId = requireNotNull(event.resourceId) { "RECOVERY_STOW requires task id" }
                json.put("destination_location_id", event.destinationLocationId)
                request("/tasks/${encode(taskId)}/recovery/stow", json.toString())
            }
        }
    }

    fun getRecovery(taskId: String): Result =
        request("/tasks/${encode(taskId)}/recovery", null, "GET")

    fun startCycleCount(locationId: String): Result =
        request(
            "/cycle-count/sessions",
            JSONObject().put("location_id", locationId.trim().uppercase()).toString(),
        )

    fun recordCycleCount(sessionId: String, productId: String, countedQty: Int): Result =
        request(
            "/cycle-count/sessions/${encode(sessionId)}/count",
            JSONObject()
                .put("product_id", productId)
                .put("counted_qty", countedQty)
                .toString(),
        )

    fun applyCycleCount(sessionId: String): Result =
        request(
            "/cycle-count/sessions/${encode(sessionId)}/apply",
            JSONObject().put("reason", "CYCLE_COUNT_ADJUSTMENT").toString(),
        )

    fun getShipments(): Result = request("/ops/shipments", null, "GET")

    fun getShipmentPlacement(shipmentId: String, productId: String, destination: String): Result =
        request("/ops/shipments/${encode(shipmentId)}/placement?product_id=${encode(productId)}" +
            "&destination_location_id=${encode(destination)}", null, "GET")

    fun openShipment(shipmentId: String, zone: String, temperatureC: Double): Result =
        request("/ops/shipments/${encode(shipmentId)}/open", JSONObject()
            .put("storage_domain", zone).put("opening_temperature_c", temperatureC).toString())

    fun receiveShipmentLine(
        shipmentId: String,
        eventId: String,
        productId: String,
        goodQty: Int,
        damagedQty: Int = 0,
        lotCode: String? = null,
        expiresOn: String? = null,
        discrepancyReason: String? = null,
    ): Result =
        request(
            "/ops/shipments/${encode(shipmentId)}/receive",
            JSONObject()
                .put("event_id", eventId)
                .put("product_id", productId)
                .put("good_qty", goodQty)
                .put("damaged_qty", damagedQty)
                .put("lot_code", lotCode ?: JSONObject.NULL)
                .put("expires_on", expiresOn ?: JSONObject.NULL)
                .put("discrepancy_reason", discrepancyReason ?: JSONObject.NULL)
                .toString(),
        )

    fun completeReceiving(shipmentId: String): Result =
        request("/ops/shipments/${encode(shipmentId)}/complete-receive", "{}")

    fun adhocStowShipmentItem(
        shipmentId: String, eventId: String, productId: String,
        destinationLocationId: String, qty: Int, expiresOn: String?,
        lotCode: String?, reason: String,
    ): Result = request(
        "/ops/shipments/${encode(shipmentId)}/adhoc-stow",
        JSONObject().put("event_id", eventId).put("product_id", productId)
            .put("destination_location_id", destinationLocationId).put("qty", qty)
            .put("expires_on", expiresOn ?: JSONObject.NULL)
            .put("lot_code", lotCode ?: JSONObject.NULL).put("reason", reason).toString(),
    )

    fun getStowRecommendations(taskId: String): Result =
        request("/ops/stow/${encode(taskId)}/recommendations", null, "GET")

    fun completeStow(taskId: String, eventId: String, destinationLocationId: String): Result =
        request(
            "/ops/stow/${encode(taskId)}/complete",
            JSONObject()
                .put("event_id", eventId)
                .put("destination_location_id", destinationLocationId.trim().uppercase())
                .toString(),
        )

    fun getReplenishmentQueue(mine: Boolean = true): Result =
        request("/ops/replenishment/queue?mine=${if (mine) "true" else "false"}", null, "GET")

    fun claimReplenishment(taskId: String): Result =
        request("/ops/replenishment/${encode(taskId)}/claim", "{}")

    fun scanReplenishmentSource(taskId: String, eventId: String, locationId: String): Result =
        request(
            "/ops/replenishment/${encode(taskId)}/source",
            JSONObject()
                .put("event_id", eventId)
                .put("source_location_id", locationId.trim().uppercase())
                .toString(),
        )

    fun scanReplenishmentItem(taskId: String, eventId: String, barcode: String): Result =
        request(
            "/ops/replenishment/${encode(taskId)}/item",
            JSONObject()
                .put("event_id", eventId)
                .put("barcode", barcode.trim())
                .toString(),
        )

    fun scanReplenishmentDestination(taskId: String, eventId: String, locationId: String): Result =
        request(
            "/ops/replenishment/${encode(taskId)}/destination",
            JSONObject()
                .put("event_id", eventId)
                .put("destination_location_id", locationId.trim().uppercase())
                .toString(),
        )

    fun completeReplenishment(taskId: String, eventId: String, actualQty: Int): Result =
        request(
            "/ops/replenishment/${encode(taskId)}/complete",
            JSONObject()
                .put("event_id", eventId)
                .put("actual_qty", actualQty)
                .toString(),
        )

    fun parseRecovery(body: String): RecoverySummary {
        val root = JSONObject(body)
        return RecoverySummary(
            taskId = root.getString("task_id"),
            orderId = root.getString("order_id"),
            recoveryType = root.getString("recovery_type"),
            sourceLocationId = root.nullableString("source_location_id"),
            items = root.optJSONArray("items")?.mapObjects { item ->
                RecoveryItem(
                    productId = item.getString("product_id"),
                    asin = item.nullableString("asin"),
                    title = item.optString("title", "Unknown product"),
                    qty = item.getInt("qty"),
                    sourceLocationId = item.getString("source_location_id"),
                    compatibleDestinations = item.optJSONArray("compatible_destinations")?.strings().orEmpty(),
                )
            }.orEmpty(),
        )
    }

    fun parseCycleCountEntry(body: String): CycleCountEntrySummary {
        val root = JSONObject(body)
        return CycleCountEntrySummary(
            entryId = root.getString("entry_id"),
            productId = root.getString("product_id"),
            systemQty = root.getInt("system_qty"),
            countedQty = root.getInt("counted_qty"),
            variance = root.getInt("variance"),
        )
    }

    fun parseShipments(body: String): List<ShipmentSummary> {
        val root = JSONObject(body)
        return root.optJSONArray("shipments")?.mapObjects(::parseShipment).orEmpty()
    }

    fun parseShipment(body: String): ShipmentSummary = parseShipment(JSONObject(body))

    private fun parseShipment(root: JSONObject): ShipmentSummary {
        return ShipmentSummary(
            id = root.getString("id"),
            label = root.getString("label"),
            shipmentType = root.getString("shipment_type"),
            storageDomain = root.getString("storage_domain"),
            status = root.getString("status"),
            expectedUnits = root.optInt("expected_units", 0),
            receivedUnits = root.optInt("received_units", 0),
            damagedUnits = root.optInt("damaged_units", 0),
            missingUnits = root.optInt("missing_units", 0),
            targetStowMinutes = root.optInt("target_stow_minutes", 0),
            elapsedMinutes = if (root.has("elapsed_minutes") && !root.isNull("elapsed_minutes")) root.getInt("elapsed_minutes") else null,
            stowOverdue = root.optBoolean("stow_overdue", false),
            lines = root.optJSONArray("lines")?.mapObjects { line ->
                ShipmentLineSummary(
                    id = line.getString("id"),
                    productId = line.getString("product_id"),
                    expectedQty = line.optInt("expected_qty", 0),
                    receivedQty = line.optInt("received_qty", 0),
                    damagedQty = line.optInt("damaged_qty", 0),
                    missingQty = line.optInt("missing_qty", 0),
                    recommendedStow = line.optJSONArray("recommended_stow")?.mapObjects { rec ->
                        rec.getString("location_id")
                    }.orEmpty(),
                )
            }.orEmpty(),
            stowTasks = root.optJSONArray("stow_tasks")?.mapObjects { task ->
                StowTaskSummary(
                    id = task.getString("id"),
                    productId = task.getString("product_id"),
                    qty = task.optInt("qty", 0),
                    status = task.getString("status"),
                    destinationLocationId = task.nullableString("destination_location_id"),
                )
            }.orEmpty(),
        )
    }

    fun parseReplenishmentQueue(body: String): List<ReplenishmentSummary> {
        val root = JSONObject(body)
        return root.optJSONArray("tasks")?.mapObjects(::parseReplenishment).orEmpty()
    }

    fun parseReplenishmentEnvelope(body: String): ReplenishmentSummary {
        val root = JSONObject(body)
        return if (root.has("task") && !root.isNull("task")) {
            parseReplenishment(root.getJSONObject("task"))
        } else {
            parseReplenishment(root)
        }
    }

    private fun parseReplenishment(root: JSONObject): ReplenishmentSummary =
        ReplenishmentSummary(
            id = root.getString("id"),
            productId = root.getString("product_id"),
            asin = root.nullableString("asin"),
            title = root.optString("title", "Unknown product"),
            sourceLocationId = root.getString("source_location_id"),
            destinationLocationId = root.getString("destination_location_id"),
            qty = root.optInt("qty", 0),
            actualQty = root.optInt("actual_qty", 0),
            status = root.getString("status"),
            priority = root.optInt("priority", 0),
            sourceAvailableQty = root.optInt("source_available_qty", 0),
            destinationOnHand = root.optInt("destination_on_hand", 0),
        )

    fun parseBarcodeProduct(body: String): BarcodeProduct {
        val root = JSONObject(body)
        val product = root.getJSONObject("product")
        return BarcodeProduct(
            barcode = root.getString("barcode"),
            productId = product.getString("id"),
            asin = product.getString("asin"),
            title = product.getString("title"),
            temperatureClass = product.getString("temperature_class"),
            handlingClass = product.getString("handling_class"),
        )
    }

    fun parseActiveUnpack(body: String): UnpackSummary? {
        val root = JSONObject(body)
        if (!root.has("session") || root.isNull("session")) return null
        return parseUnpack(root.getJSONObject("session"))
    }

    fun parseUnpack(body: String): UnpackSummary = parseUnpack(JSONObject(body))

    private fun parseUnpack(o: JSONObject): UnpackSummary {
        val items = o.optJSONArray("items")?.mapObjects { item ->
            UnpackItemRecommendation(
                productId = item.getString("product_id"),
                qty = item.getInt("qty"),
                compatibleDestinations = item.optJSONArray("compatible_destinations")?.strings().orEmpty(),
            )
        }.orEmpty()
        val manifest = o.optJSONArray("manifest")?.mapObjects { item ->
            UnpackManifestItem(
                productId = item.getString("product_id"),
                asin = item.nullableString("asin"),
                title = item.optString("title", "Unknown product"),
                expectedQty = item.optInt("expected_qty", 0),
                verifiedQty = item.optInt("verified_qty", 0),
                missingQty = item.optInt("missing_qty", 0),
            )
        }.orEmpty()
        return UnpackSummary(
            sessionId = o.getString("session_id"),
            status = o.getString("status"),
            temperatureClass = o.getString("temperature_class"),
            toteLocationId = o.getString("tote_location_id"),
            sourceRef = o.nullableString("source_ref"),
            manifestLocked = o.optBoolean("manifest_locked", false),
            expectedUnits = o.optInt("expected_units", 0),
            verifiedUnits = o.optInt("verified_units", 0),
            remainingUnits = o.optInt("remaining_units", 0),
            completeReady = o.optBoolean("complete_ready", false),
            manifest = manifest,
            items = items,
        )
    }

    fun parseSessionEnvelope(body: String): SessionInfo {
        val root = JSONObject(body)
        return parseSession(root.getJSONObject("session").toString())
    }

    fun parseSession(body: String): SessionInfo {
        val o = JSONObject(body)
        return SessionInfo(
            accessToken = o.getString("access_token"),
            refreshToken = o.getString("refresh_token"),
            userId = o.getString("user_id"),
            username = o.getString("username"),
            role = o.getString("role"),
            deviceId = o.getString("device_id"),
            mustChangePassword = o.optBoolean("must_change_password", false),
        )
    }

    fun parseFirstOffer(body: String): TaskSnapshot? {
        val root = JSONObject(body)
        val offers = root.optJSONArray("offers") ?: return null
        if (offers.length() == 0) return null
        val offer = offers.getJSONObject(0)
        return parseTask(offer.getJSONObject("task")).copy(
            offerExpiresAt = offer.nullableString("expires_at"),
        )
    }

    fun parseClosedBag(body: String): ClosedBagSummary {
        val root = JSONObject(body)
        return ClosedBagSummary(
            bagNo = root.getInt("bag_no"),
            spooLast4 = root.getString("spoo_last4"),
        )
    }

    fun parseCompletionSummary(body: String): OrderCompletionSummary {
        val root = JSONObject(body)
        val items = root.optJSONArray("items")?.mapObjects { item ->
            CompletionItem(
                title = item.optString("title", "Unknown product"),
                requestedQty = item.optInt("requested_qty", 0),
                pickedQty = item.optInt("picked_qty", 0),
                shortedQty = item.optInt("shorted_qty", 0),
            )
        }.orEmpty()
        val bags = root.optJSONArray("bags")?.mapObjects { bag ->
            ClosedBagSummary(
                bagNo = bag.getInt("bag_no"),
                spooLast4 = bag.getString("spoo_last4"),
            )
        }.orEmpty()
        return OrderCompletionSummary(
            orderId = root.getString("order_id"),
            externalRef = root.nullableString("external_ref"),
            pickerUsername = root.optJSONObject("picker")?.nullableString("username"),
            items = items,
            bagCount = root.optInt("bag_count", bags.size),
            bags = bags,
            pickedUnits = root.optInt("picked_units", 0),
            shortedUnits = root.optInt("shorted_units", 0),
        )
    }

    fun parseTaskEnvelope(body: String): TaskSnapshot? {
        val root = JSONObject(body)
        if (!root.has("task") || root.isNull("task")) return null
        return parseTask(root.getJSONObject("task"))
    }

    fun parseTask(body: String): TaskSnapshot = parseTask(JSONObject(body))

    fun parsePickSnapshot(body: String): TaskSnapshot {
        val root = JSONObject(body)
        return parseTask(root.getJSONObject("snapshot"))
    }

    fun parseConflictSnapshot(body: String): TaskSnapshot? {
        return runCatching {
            val root = JSONObject(body)
            val detail = root.optJSONObject("detail") ?: return null
            val snapshot = detail.optJSONObject("authoritative_snapshot") ?: return null
            parseTask(snapshot)
        }.getOrNull()
    }

    fun parseConflictMessage(body: String): String {
        return runCatching {
            val root = JSONObject(body)
            val detail = root.optJSONObject("detail")
            detail?.optString("message")?.takeIf { it.isNotBlank() }
                ?: root.optString("detail")
        }.getOrNull().orEmpty().ifBlank { "Server state changed; reconciliation required" }
    }

    fun parseInventoryProduct(body: String): InventoryLookup {
        val root = JSONObject(body)
        val product = root.getJSONObject("product")
        val rows = root.getJSONArray("locations").mapObjects { o ->
            InventoryRow(
                primary = o.getString("location_id"),
                secondary = "Reserved ${o.optInt("qty_reserved", 0)} • v${o.optInt("version", 0)}",
                quantity = o.getInt("qty_on_hand"),
            )
        }
        return InventoryLookup(
            heading = product.getString("title"),
            subheading = product.getString("asin"),
            total = root.getInt("total_on_hand"),
            rows = rows,
        )
    }

    fun parseInventoryLocation(body: String): InventoryLookup {
        val root = JSONObject(body)
        val rows = root.getJSONArray("items").mapObjects { o ->
            InventoryRow(
                primary = o.optString("title").ifBlank { o.optString("asin", "Unknown product") },
                secondary = o.optString("asin"),
                quantity = o.getInt("qty"),
            )
        }
        return InventoryLookup(
            heading = root.getString("location_id"),
            subheading = "${rows.size} SKU${if (rows.size == 1) "" else "s"}",
            total = rows.sumOf { it.quantity },
            rows = rows,
        )
    }

    private fun parseTask(o: JSONObject): TaskSnapshot {
        val items = o.optJSONArray("items")?.mapObjects { item ->
            TaskItem(
                id = item.getString("id"),
                productId = item.getString("product_id"),
                asin = item.nullableString("asin"),
                title = item.nullableString("title") ?: "Unknown product",
                barcodes = item.optJSONArray("barcodes")?.strings().orEmpty(),
                temperatureClass = item.nullableString("temperature_class"),
                handlingClass = item.nullableString("handling_class"),
                locationId = item.getString("source_location_id"),
                plannedQty = item.getInt("planned_qty"),
                pickedQty = item.getInt("picked_qty"),
                remainingQty = item.optInt("remaining_qty", item.getInt("planned_qty") - item.getInt("picked_qty")),
                sequence = item.getInt("sequence"),
            )
        }.orEmpty()

        return TaskSnapshot(
            taskId = o.getString("task_id"),
            orderId = o.getString("order_id"),
            taskStatus = o.getString("task_status"),
            orderStatus = o.nullableString("order_status"),
            serverVersion = o.optLong("server_version", 0),
            clientHighWaterSeq = o.optLong("client_high_water_seq", 0),
            expectedUnits = o.optInt("expected_units", 0),
            pickedUnits = o.optInt("picked_units", 0),
            shortedUnits = o.optInt("shorted_units", 0),
            processedUnits = o.optInt("processed_units", o.optInt("picked_units", 0)),
            remainingUnits = o.optInt("remaining_units", 0),
            recoveryRequired = o.optBoolean("recovery_required", false),
            offerExpiresAt = o.nullableString("offer_expires_at"),
            items = items,
        )
    }

    private fun request(
        path: String,
        json: String?,
        method: String = "POST",
        authorized: Boolean = true,
    ): Result {
        val conn = URL(BuildConfig.API_BASE_URL + path).openConnection() as HttpURLConnection
        return try {
            conn.requestMethod = method
            conn.connectTimeout = 5_000
            conn.readTimeout = 10_000
            conn.setRequestProperty("Accept", "application/json")
            if (authorized) {
                accessToken?.let { conn.setRequestProperty("Authorization", "Bearer $it") }
            }
            if (json != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(json.toByteArray(Charsets.UTF_8)) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            Result(code, stream?.bufferedReader()?.use { it.readText() }.orEmpty())
        } finally {
            conn.disconnect()
        }
    }

    private fun encode(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")

    private fun JSONObject.nullableString(name: String): String? =
        if (!has(name) || isNull(name)) null else getString(name)

    private fun JSONArray.strings(): List<String> =
        buildList { for (i in 0 until length()) add(getString(i)) }

    private fun <T> JSONArray.mapObjects(block: (JSONObject) -> T): List<T> =
        buildList { for (i in 0 until length()) add(block(getJSONObject(i))) }
}
