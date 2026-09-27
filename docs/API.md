# API surface (v0.1)

## Authentication

- `POST /auth/login`
- `POST /auth/refresh`
- `POST /devices/heartbeat`

## Location and inventory

- `GET /locations/parse/{location}`
- `GET /inventory/product/{asin}`
- `GET /inventory/location/{location}`
- `POST /inventory/receive`
- `POST /inventory/move`

## Orders and tasks

- `POST /orders`
- `POST /orders/{order_id}/allocate`
- `POST /orders/{order_id}/cancel`
- `POST /tasks/{task_id}/offer`
- `POST /tasks/{task_id}/accept`
- `GET /tasks/{task_id}`
- `POST /tasks/{task_id}/scan`
- `POST /tasks/{task_id}/sync`

## Technical downtime

- `POST /tasks/{task_id}/downtime/start`
- `POST /tasks/{task_id}/downtime/{segment_id}/stop`

## Supervisor

- `GET /dashboard/summary`
- `GET /dashboard`
- `WS /ws/dashboard`

Production follow-up will split internal commands from public/client APIs, add RBAC scopes, request signatures, rate limits, observability ids and an OpenAPI-generated Kotlin client.
