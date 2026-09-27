package com.obieda.fulfillos.domain

data class ParsedLocation(
    val canonical: String,
    val floor: String?,
    val classification: String?,
    val fixture: String?,
    val aisle: Int?,
    val level: String?,
    val slot: Int?,
    val temperature: TemperatureClass,
    val handling: HandlingClass,
    val logical: Boolean,
    val pickable: Boolean,
    val sellable: Boolean,
)

enum class TemperatureClass { AMBIENT, CHILLED, FROZEN }
enum class HandlingClass { STANDARD, HAZ, HRV, RETURNS, DAMAGE, SPECIAL }

object LocationParser {
    private val physical = Regex(
        "^(?:P-(\\d+)-)?(?:(HAZ|HRV)-)?([A-Z])(\\d{3})([A-Z])(\\d{3})$"
    )
    private val hrvCompact = Regex("^(?:P-(\\d+)-)?HRV(\\d{3})([A-Z])(\\d{3})$")

    fun parse(input: String): ParsedLocation {
        val value = input.trim().uppercase().replace(" ", "")
        return when (value) {
            "TSCRET001" -> logical(value, TemperatureClass.AMBIENT, HandlingClass.RETURNS)
            "TSCRETCHL01" -> logical(value, TemperatureClass.CHILLED, HandlingClass.RETURNS)
            "TSCRETFRZ01" -> logical(value, TemperatureClass.FROZEN, HandlingClass.RETURNS)
            "DMG" -> logical(value, TemperatureClass.AMBIENT, HandlingClass.DAMAGE)
            "SPECIAL" -> logical(value, TemperatureClass.AMBIENT, HandlingClass.SPECIAL)
            else -> parsePhysical(value)
        }
    }

    private fun logical(id: String, temperature: TemperatureClass, handling: HandlingClass) =
        ParsedLocation(id, null, handling.name, null, null, null, null, temperature, handling, true, false, false)

    private fun parsePhysical(value: String): ParsedLocation {
        hrvCompact.matchEntire(value)?.let { hrv ->
            val floor = hrv.groupValues[1].ifBlank { "1" }
            val aisle = hrv.groupValues[2].toInt()
            val level = hrv.groupValues[3]
            val slot = hrv.groupValues[4].toInt()
            return ParsedLocation(
                canonical = "P-$floor-HRV${aisle.toString().padStart(3, '0')}$level${slot.toString().padStart(3, '0')}",
                floor = floor, classification = "HRV", fixture = null, aisle = aisle, level = level, slot = slot,
                temperature = TemperatureClass.AMBIENT, handling = HandlingClass.HRV, logical = false, pickable = true, sellable = true,
            )
        }
        val m = physical.matchEntire(value) ?: error("Unsupported location: $value")
        val floor = m.groupValues[1].ifBlank { "1" }
        val classification = m.groupValues[2].ifBlank { null }
        val fixture = m.groupValues[3]
        val aisle = m.groupValues[4].toInt()
        val level = m.groupValues[5]
        val slot = m.groupValues[6].toInt()
        val temperature = when (fixture) {
            "C" -> TemperatureClass.CHILLED
            "F" -> TemperatureClass.FROZEN
            else -> TemperatureClass.AMBIENT
        }
        val handling = when (classification) {
            "HAZ" -> HandlingClass.HAZ
            "HRV" -> HandlingClass.HRV
            else -> HandlingClass.STANDARD
        }
        val canonical = buildString {
            append("P-").append(floor).append('-')
            if (classification != null) append(classification).append('-')
            append(fixture).append(aisle.toString().padStart(3, '0'))
            append(level).append(slot.toString().padStart(3, '0'))
        }
        return ParsedLocation(canonical, floor, classification, fixture, aisle, level, slot, temperature, handling, false, true, true)
    }

    fun levelColorName(level: String): String? = when (level.uppercase()) {
        "A" -> "GREEN"
        "B" -> "BLUE"
        "C" -> "YELLOW"
        else -> null
    }
}
