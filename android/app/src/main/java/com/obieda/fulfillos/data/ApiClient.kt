package com.obieda.fulfillos.data

import com.obieda.fulfillos.BuildConfig
import com.obieda.fulfillos.domain.PendingPickEvent
import java.net.HttpURLConnection
import java.net.URL

/**
 * Deliberately tiny reference transport. Production should use generated OpenAPI models,
 * structured JSON parsing, certificate policy and richer telemetry.
 */
class ApiClient {
    @Volatile var accessToken: String? = null

    data class Result(val code: Int, val body: String)

    fun postPick(event: PendingPickEvent): Result {
        val json = """{
          "event_id":"${escape(event.eventId)}",
          "client_seq":${event.clientSeq},
          "task_item_id":"${escape(event.taskItemId)}",
          "location_id":"${escape(event.locationId)}",
          "product_id":"${escape(event.productId)}",
          "qty":${event.qty},
          "barcode":${event.barcode?.let { "\"${escape(it)}\"" } ?: "null"}
        }""".trimIndent()
        return request("/tasks/${event.taskId}/scan", json)
    }

    fun getTask(taskId: String): Result = request("/tasks/$taskId", null, "GET")

    private fun request(path: String, json: String?, method: String = "POST"): Result {
        val conn = URL(BuildConfig.API_BASE_URL + path).openConnection() as HttpURLConnection
        return try {
            conn.requestMethod = method
            conn.connectTimeout = 5_000
            conn.readTimeout = 8_000
            conn.setRequestProperty("Accept", "application/json")
            accessToken?.let { conn.setRequestProperty("Authorization", "Bearer $it") }
            if (json != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(json.toByteArray()) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            Result(code, stream?.bufferedReader()?.use { it.readText() }.orEmpty())
        } finally {
            conn.disconnect()
        }
    }

    private fun escape(s: String) = s.replace("\\", "\\\\").replace("\"", "\\\"")
}
