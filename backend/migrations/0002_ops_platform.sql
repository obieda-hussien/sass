-- FulfillOS v0.3 operations platform
-- Apply after 0001_initial.sql. Designed for PostgreSQL 17.

CREATE TABLE worker_runtime_states (
    user_id VARCHAR(36) PRIMARY KEY REFERENCES users(id),
    state VARCHAR(40) NOT NULL DEFAULT 'AVAILABLE',
    activity_ref VARCHAR(120),
    reason VARCHAR(240),
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_worker_runtime_states_state ON worker_runtime_states(state);

CREATE TABLE worker_state_events (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    from_state VARCHAR(40),
    to_state VARCHAR(40) NOT NULL,
    activity_ref VARCHAR(120),
    reason VARCHAR(240),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_worker_state_events_user_id ON worker_state_events(user_id);
CREATE INDEX ix_worker_state_events_to_state ON worker_state_events(to_state);
CREATE INDEX ix_worker_state_events_created_at ON worker_state_events(created_at);

CREATE TABLE worker_qualifications (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    qualification VARCHAR(40) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    granted_by_user_id VARCHAR(36) REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_worker_qualification UNIQUE(user_id, qualification)
);
CREATE INDEX ix_worker_qualifications_user_id ON worker_qualifications(user_id);
CREATE INDEX ix_worker_qualifications_qualification ON worker_qualifications(qualification);

CREATE TABLE active_pick_leases (
    user_id VARCHAR(36) PRIMARY KEY REFERENCES users(id),
    task_id VARCHAR(36) NOT NULL UNIQUE REFERENCES pick_tasks(id),
    device_id VARCHAR(80) REFERENCES devices(id),
    mode VARCHAR(24) NOT NULL DEFAULT 'CLAIM',
    acquired_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX ix_active_pick_leases_task_id ON active_pick_leases(task_id);

CREATE TABLE pick_offers (
    id VARCHAR(36) PRIMARY KEY,
    task_id VARCHAR(36) NOT NULL REFERENCES pick_tasks(id),
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    status VARCHAR(24) NOT NULL DEFAULT 'OPEN',
    offered_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    closed_at TIMESTAMPTZ,
    CONSTRAINT uq_pick_offer_user UNIQUE(task_id, user_id)
);
CREATE INDEX ix_pick_offers_task_id ON pick_offers(task_id);
CREATE INDEX ix_pick_offers_user_id ON pick_offers(user_id);
CREATE INDEX ix_pick_offers_status ON pick_offers(status);

CREATE TABLE fulfillment_holds (
    id VARCHAR(36) PRIMARY KEY,
    site_id VARCHAR(32) NOT NULL DEFAULT 'DEMO',
    scope_type VARCHAR(24) NOT NULL,
    scope_value VARCHAR(120) NOT NULL,
    reason VARCHAR(48) NOT NULL,
    notes TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    hard_stop BOOLEAN NOT NULL DEFAULT FALSE,
    starts_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ,
    created_by_user_id VARCHAR(36) REFERENCES users(id),
    ended_by_user_id VARCHAR(36) REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ
);
CREATE INDEX ix_fulfillment_holds_site_id ON fulfillment_holds(site_id);
CREATE INDEX ix_fulfillment_holds_scope_type ON fulfillment_holds(scope_type);
CREATE INDEX ix_fulfillment_holds_scope_value ON fulfillment_holds(scope_value);
CREATE INDEX ix_fulfillment_holds_reason ON fulfillment_holds(reason);
CREATE INDEX ix_fulfillment_holds_active ON fulfillment_holds(active);

CREATE TABLE order_bags (
    id VARCHAR(36) PRIMARY KEY,
    order_id VARCHAR(36) NOT NULL REFERENCES orders(id),
    task_id VARCHAR(36) NOT NULL REFERENCES pick_tasks(id),
    bag_no INTEGER NOT NULL,
    spoo_code VARCHAR(120) NOT NULL UNIQUE,
    closed_by_user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    closed_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_order_bag_number UNIQUE(order_id, bag_no)
);
CREATE INDEX ix_order_bags_order_id ON order_bags(order_id);
CREATE INDEX ix_order_bags_task_id ON order_bags(task_id);
CREATE UNIQUE INDEX ix_order_bags_spoo_code ON order_bags(spoo_code);
CREATE INDEX ix_order_bags_closed_by_user_id ON order_bags(closed_by_user_id);
CREATE INDEX ix_order_bags_closed_at ON order_bags(closed_at);

CREATE TABLE pick_exceptions (
    id VARCHAR(36) PRIMARY KEY,
    event_id VARCHAR(80) NOT NULL UNIQUE,
    task_id VARCHAR(36) NOT NULL REFERENCES pick_tasks(id),
    task_item_id VARCHAR(36) NOT NULL REFERENCES pick_task_items(id),
    order_id VARCHAR(36) NOT NULL REFERENCES orders(id),
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    location_id VARCHAR(100) NOT NULL REFERENCES locations(id),
    product_id VARCHAR(36) NOT NULL REFERENCES products(id),
    exception_type VARCHAR(32) NOT NULL,
    reason VARCHAR(80) NOT NULL,
    qty INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX ix_pick_exceptions_event_id ON pick_exceptions(event_id);
CREATE INDEX ix_pick_exceptions_task_id ON pick_exceptions(task_id);
CREATE INDEX ix_pick_exceptions_task_item_id ON pick_exceptions(task_item_id);
CREATE INDEX ix_pick_exceptions_order_id ON pick_exceptions(order_id);
CREATE INDEX ix_pick_exceptions_user_id ON pick_exceptions(user_id);
CREATE INDEX ix_pick_exceptions_location_id ON pick_exceptions(location_id);
CREATE INDEX ix_pick_exceptions_product_id ON pick_exceptions(product_id);
CREATE INDEX ix_pick_exceptions_exception_type ON pick_exceptions(exception_type);
CREATE INDEX ix_pick_exceptions_reason ON pick_exceptions(reason);
CREATE INDEX ix_pick_exceptions_created_at ON pick_exceptions(created_at);

CREATE TABLE inventory_alerts (
    id VARCHAR(36) PRIMARY KEY,
    alert_type VARCHAR(40) NOT NULL,
    product_id VARCHAR(36) REFERENCES products(id),
    location_id VARCHAR(100) REFERENCES locations(id),
    severity VARCHAR(16) NOT NULL DEFAULT 'MEDIUM',
    status VARCHAR(24) NOT NULL DEFAULT 'OPEN',
    source_ref VARCHAR(120),
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ
);
CREATE INDEX ix_inventory_alerts_alert_type ON inventory_alerts(alert_type);
CREATE INDEX ix_inventory_alerts_product_id ON inventory_alerts(product_id);
CREATE INDEX ix_inventory_alerts_location_id ON inventory_alerts(location_id);
CREATE INDEX ix_inventory_alerts_status ON inventory_alerts(status);
CREATE INDEX ix_inventory_alerts_created_at ON inventory_alerts(created_at);

CREATE TABLE replenishment_tasks (
    id VARCHAR(36) PRIMARY KEY,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id),
    source_location_id VARCHAR(100) NOT NULL REFERENCES locations(id),
    destination_location_id VARCHAR(100) NOT NULL REFERENCES locations(id),
    qty INTEGER NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'READY',
    trigger VARCHAR(40) NOT NULL DEFAULT 'SHORT',
    source_ref VARCHAR(120),
    assigned_user_id VARCHAR(36) REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX ix_replenishment_tasks_product_id ON replenishment_tasks(product_id);
CREATE INDEX ix_replenishment_tasks_source_location_id ON replenishment_tasks(source_location_id);
CREATE INDEX ix_replenishment_tasks_destination_location_id ON replenishment_tasks(destination_location_id);
CREATE INDEX ix_replenishment_tasks_status ON replenishment_tasks(status);
CREATE INDEX ix_replenishment_tasks_assigned_user_id ON replenishment_tasks(assigned_user_id);

CREATE TABLE shipments (
    id VARCHAR(36) PRIMARY KEY,
    label VARCHAR(120) NOT NULL UNIQUE,
    shipment_type VARCHAR(40) NOT NULL DEFAULT 'VENDOR',
    storage_domain VARCHAR(24) NOT NULL DEFAULT 'AMBIENT',
    status VARCHAR(24) NOT NULL DEFAULT 'CREATED',
    dock_ref VARCHAR(80),
    inbound_location_id VARCHAR(120),
    expected_units INTEGER NOT NULL DEFAULT 0,
    received_units INTEGER NOT NULL DEFAULT 0,
    damaged_units INTEGER NOT NULL DEFAULT 0,
    missing_units INTEGER NOT NULL DEFAULT 0,
    target_stow_minutes INTEGER NOT NULL DEFAULT 120,
    opened_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_by_user_id VARCHAR(36) REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX ix_shipments_label ON shipments(label);
CREATE INDEX ix_shipments_shipment_type ON shipments(shipment_type);
CREATE INDEX ix_shipments_storage_domain ON shipments(storage_domain);
CREATE INDEX ix_shipments_status ON shipments(status);
CREATE INDEX ix_shipments_created_at ON shipments(created_at);

CREATE TABLE shipment_lines (
    id VARCHAR(36) PRIMARY KEY,
    shipment_id VARCHAR(36) NOT NULL REFERENCES shipments(id),
    product_id VARCHAR(36) NOT NULL REFERENCES products(id),
    expected_qty INTEGER NOT NULL DEFAULT 0,
    received_qty INTEGER NOT NULL DEFAULT 0,
    damaged_qty INTEGER NOT NULL DEFAULT 0,
    missing_qty INTEGER NOT NULL DEFAULT 0,
    lot_code VARCHAR(80),
    expires_on DATE,
    CONSTRAINT uq_shipment_product UNIQUE(shipment_id, product_id)
);
CREATE INDEX ix_shipment_lines_shipment_id ON shipment_lines(shipment_id);
CREATE INDEX ix_shipment_lines_product_id ON shipment_lines(product_id);

CREATE TABLE receiving_sessions (
    id VARCHAR(36) PRIMARY KEY,
    shipment_id VARCHAR(36) NOT NULL REFERENCES shipments(id),
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    device_id VARCHAR(80) NOT NULL REFERENCES devices(id),
    status VARCHAR(24) NOT NULL DEFAULT 'OPEN',
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX ix_receiving_sessions_shipment_id ON receiving_sessions(shipment_id);
CREATE INDEX ix_receiving_sessions_user_id ON receiving_sessions(user_id);
CREATE INDEX ix_receiving_sessions_device_id ON receiving_sessions(device_id);
CREATE INDEX ix_receiving_sessions_status ON receiving_sessions(status);

CREATE TABLE stow_tasks (
    id VARCHAR(36) PRIMARY KEY,
    shipment_id VARCHAR(36) NOT NULL REFERENCES shipments(id),
    product_id VARCHAR(36) NOT NULL REFERENCES products(id),
    source_location_id VARCHAR(100) NOT NULL REFERENCES locations(id),
    destination_location_id VARCHAR(100) REFERENCES locations(id),
    qty INTEGER NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'READY',
    assigned_user_id VARCHAR(36) REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX ix_stow_tasks_shipment_id ON stow_tasks(shipment_id);
CREATE INDEX ix_stow_tasks_product_id ON stow_tasks(product_id);
CREATE INDEX ix_stow_tasks_source_location_id ON stow_tasks(source_location_id);
CREATE INDEX ix_stow_tasks_status ON stow_tasks(status);
CREATE INDEX ix_stow_tasks_assigned_user_id ON stow_tasks(assigned_user_id);

CREATE TABLE inventory_lots (
    id VARCHAR(36) PRIMARY KEY,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id),
    location_id VARCHAR(100) NOT NULL REFERENCES locations(id),
    lot_code VARCHAR(80) NOT NULL,
    expires_on DATE,
    qty INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_inventory_lot UNIQUE(product_id, location_id, lot_code)
);
CREATE INDEX ix_inventory_lots_product_id ON inventory_lots(product_id);
CREATE INDEX ix_inventory_lots_location_id ON inventory_lots(location_id);
CREATE INDEX ix_inventory_lots_expires_on ON inventory_lots(expires_on);

CREATE TABLE shift_sessions (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES users(id),
    scheduled_start_at TIMESTAMPTZ NOT NULL,
    scheduled_end_at TIMESTAMPTZ NOT NULL,
    clock_in_at TIMESTAMPTZ NOT NULL,
    clock_out_at TIMESTAMPTZ,
    status VARCHAR(24) NOT NULL DEFAULT 'OPEN',
    late_minutes INTEGER NOT NULL DEFAULT 0,
    early_leave_minutes INTEGER NOT NULL DEFAULT 0,
    overtime_minutes INTEGER NOT NULL DEFAULT 0,
    worked_minutes INTEGER NOT NULL DEFAULT 0,
    attendance_entry_id VARCHAR(36) REFERENCES attendance_entries(id),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_shift_sessions_user_id ON shift_sessions(user_id);
CREATE INDEX ix_shift_sessions_status ON shift_sessions(status);

CREATE TABLE attendance_computations (
    attendance_entry_id VARCHAR(36) PRIMARY KEY REFERENCES attendance_entries(id),
    scheduled_end_at TIMESTAMPTZ NOT NULL,
    early_leave_minutes INTEGER NOT NULL DEFAULT 0,
    worked_minutes INTEGER NOT NULL DEFAULT 0,
    calculated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE payroll_policies (
    user_id VARCHAR(36) PRIMARY KEY REFERENCES users(id),
    late_deduction_cents_per_minute INTEGER NOT NULL DEFAULT 0,
    early_leave_deduction_cents_per_minute INTEGER NOT NULL DEFAULT 0,
    auto_apply_attendance_deductions BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by_user_id VARCHAR(36) REFERENCES users(id),
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE device_telemetry (
    device_id VARCHAR(80) PRIMARY KEY REFERENCES devices(id),
    battery_percent INTEGER,
    connectivity VARCHAR(24),
    last_location_id VARCHAR(120),
    updated_at TIMESTAMPTZ NOT NULL
);
