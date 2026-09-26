from __future__ import annotations

from .models import InventoryBalance, Task


def inventory_balance_dict(balance: InventoryBalance) -> dict:
    return {
        "product": {
            "sku": balance.product.sku,
            "title": balance.product.title,
            "temperatureClass": balance.product.temperature_class,
            "handlingClass": balance.product.handling_class,
        },
        "location": {
            "code": balance.location.code,
            "kind": balance.location.kind,
            "temperatureClass": balance.location.temperature_class,
            "handlingClass": balance.location.handling_class,
        },
        "onHand": balance.on_hand,
        "reserved": balance.reserved,
        "available": balance.available,
        "version": balance.version,
    }


def task_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "orderId": task.order_id,
        "state": task.state,
        "version": task.version,
        "associateId": task.associate_id,
        "offeredAt": task.offered_at.isoformat() if task.offered_at else None,
        "acceptedAt": task.accepted_at.isoformat() if task.accepted_at else None,
        "completedAt": task.completed_at.isoformat() if task.completed_at else None,
        "cancelReason": task.cancel_reason,
        "recoveryReason": task.recovery_reason,
        "lines": [
            {
                "id": line.id,
                "sequence": line.sequence,
                "sku": line.product.sku,
                "title": line.product.title,
                "locationCode": line.location.code,
                "requiredQty": line.required_qty,
                "pickedQty": line.picked_qty,
                "shortQty": line.short_qty,
                "remainingQty": max(
                    0, line.required_qty - line.picked_qty - line.short_qty
                ),
            }
            for line in task.lines
        ],
    }
