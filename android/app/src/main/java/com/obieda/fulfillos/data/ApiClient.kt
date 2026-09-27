package com.obieda.fulfillos.data

import com.obieda.fulfillos.BuildConfig
import com.obieda.fulfillos.domain.InventoryLookup
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
        return UnpackSummary(
            sessionId = o.getString("session_id"),
            status = o.getString("status"),
            temperatureClass = o.getString("temperature_class"),
            toteLocationId = o.getString("tote_location_id"),
            items = items,
        )
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
