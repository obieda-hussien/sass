-- FulfillOS initial PostgreSQL schema
-- Generated from SQLAlchemy metadata; review before production rollout.


CREATE TABLE audit_log (
	id VARCHAR(36) NOT NULL, 
	event_type VARCHAR(64) NOT NULL, 
	entity_type VARCHAR(40) NOT NULL, 
	entity_id VARCHAR(100) NOT NULL, 
	user_id VARCHAR(36), 
	device_id VARCHAR(80), 
	payload_json TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_audit_log_entity_id ON audit_log (entity_id);

CREATE INDEX ix_audit_log_event_type ON audit_log (event_type);

CREATE INDEX ix_audit_log_created_at ON audit_log (created_at);

CREATE INDEX ix_audit_log_entity_type ON audit_log (entity_type);


CREATE TABLE locations (
	id VARCHAR(100) NOT NULL, 
	site_id VARCHAR(32) NOT NULL, 
	floor VARCHAR(16), 
	classification VARCHAR(16), 
	fixture_type VARCHAR(8), 
	aisle INTEGER, 
	level VARCHAR(8), 
	slot INTEGER, 
	temperature_class VARCHAR(16) NOT NULL, 
	handling_class VARCHAR(16) NOT NULL, 
	pickable BOOLEAN NOT NULL, 
	stowable BOOLEAN NOT NULL, 
	logical BOOLEAN NOT NULL, 
	sellable BOOLEAN NOT NULL, 
	active BOOLEAN NOT NULL, 
	color_code VARCHAR(24), 
	PRIMARY KEY (id)
)

;


CREATE TABLE orders (
	id VARCHAR(36) NOT NULL, 
	external_ref VARCHAR(100), 
	status VARCHAR(32) NOT NULL, 
	priority INTEGER NOT NULL, 
	cancellation_reason VARCHAR(200), 
	recovery_required BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (external_ref)
)

;

CREATE INDEX ix_orders_status ON orders (status);


CREATE TABLE products (
	id VARCHAR(36) NOT NULL, 
	asin VARCHAR(24) NOT NULL, 
	title VARCHAR(240) NOT NULL, 
	temperature_class VARCHAR(16) NOT NULL, 
	handling_class VARCHAR(16) NOT NULL, 
	active BOOLEAN NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE UNIQUE INDEX ix_products_asin ON products (asin);


CREATE TABLE users (
	id VARCHAR(36) NOT NULL, 
	username VARCHAR(80) NOT NULL, 
	password_hash VARCHAR(256) NOT NULL, 
	role VARCHAR(32) NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE UNIQUE INDEX ix_users_username ON users (username);


CREATE TABLE barcodes (
	id VARCHAR(36) NOT NULL, 
	code VARCHAR(80) NOT NULL, 
	product_id VARCHAR(36) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
)

;

CREATE UNIQUE INDEX ix_barcodes_code ON barcodes (code);

CREATE INDEX ix_barcodes_product_id ON barcodes (product_id);


CREATE TABLE cycle_count_sessions (
	id VARCHAR(36) NOT NULL, 
	location_id VARCHAR(100) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(location_id) REFERENCES locations (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
)

;

CREATE INDEX ix_cycle_count_sessions_user_id ON cycle_count_sessions (user_id);

CREATE INDEX ix_cycle_count_sessions_location_id ON cycle_count_sessions (location_id);

CREATE INDEX ix_cycle_count_sessions_status ON cycle_count_sessions (status);


CREATE TABLE devices (
	id VARCHAR(80) NOT NULL, 
	trusted BOOLEAN NOT NULL, 
	last_seen_at TIMESTAMP WITH TIME ZONE, 
	last_user_id VARCHAR(36), 
	app_version VARCHAR(40), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(last_user_id) REFERENCES users (id)
)

;


CREATE TABLE inventory_balances (
	id VARCHAR(36) NOT NULL, 
	location_id VARCHAR(100) NOT NULL, 
	product_id VARCHAR(36) NOT NULL, 
	qty_on_hand INTEGER NOT NULL, 
	qty_reserved INTEGER NOT NULL, 
	version INTEGER NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_inventory_balance UNIQUE (location_id, product_id), 
	FOREIGN KEY(location_id) REFERENCES locations (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
)

;

CREATE INDEX ix_inventory_balances_product_id ON inventory_balances (product_id);

CREATE INDEX ix_inventory_balances_location_id ON inventory_balances (location_id);


CREATE TABLE inventory_movements (
	id VARCHAR(36) NOT NULL, 
	event_id VARCHAR(80) NOT NULL, 
	product_id VARCHAR(36) NOT NULL, 
	qty INTEGER NOT NULL, 
	source_location_id VARCHAR(100), 
	destination_location_id VARCHAR(100), 
	reason VARCHAR(40) NOT NULL, 
	order_id VARCHAR(36), 
	task_id VARCHAR(36), 
	user_id VARCHAR(36), 
	device_id VARCHAR(80), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
)

;

CREATE UNIQUE INDEX ix_inventory_movements_event_id ON inventory_movements (event_id);

CREATE INDEX ix_inventory_movements_product_id ON inventory_movements (product_id);


CREATE TABLE order_lines (
	id VARCHAR(36) NOT NULL, 
	order_id VARCHAR(36) NOT NULL, 
	product_id VARCHAR(36) NOT NULL, 
	requested_qty INTEGER NOT NULL, 
	allocated_qty INTEGER NOT NULL, 
	picked_qty INTEGER NOT NULL, 
	shorted_qty INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_id) REFERENCES orders (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
)

;

CREATE INDEX ix_order_lines_product_id ON order_lines (product_id);

CREATE INDEX ix_order_lines_order_id ON order_lines (order_id);


CREATE TABLE cycle_count_entries (
	id VARCHAR(36) NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	product_id VARCHAR(36) NOT NULL, 
	system_qty INTEGER NOT NULL, 
	counted_qty INTEGER NOT NULL, 
	variance INTEGER NOT NULL, 
	applied BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_cycle_count_product UNIQUE (session_id, product_id), 
	FOREIGN KEY(session_id) REFERENCES cycle_count_sessions (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
)

;

CREATE INDEX ix_cycle_count_entries_product_id ON cycle_count_entries (product_id);

CREATE INDEX ix_cycle_count_entries_session_id ON cycle_count_entries (session_id);


CREATE TABLE pick_tasks (
	id VARCHAR(36) NOT NULL, 
	order_id VARCHAR(36) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	assigned_user_id VARCHAR(36), 
	assigned_device_id VARCHAR(80), 
	stage_location_id VARCHAR(100), 
	handoff_ref VARCHAR(100), 
	expected_units INTEGER NOT NULL, 
	server_version INTEGER NOT NULL, 
	client_high_water_seq INTEGER NOT NULL, 
	offered_at TIMESTAMP WITH TIME ZONE, 
	accepted_at TIMESTAMP WITH TIME ZONE, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_id) REFERENCES orders (id), 
	FOREIGN KEY(assigned_user_id) REFERENCES users (id), 
	FOREIGN KEY(assigned_device_id) REFERENCES devices (id)
)

;

CREATE INDEX ix_pick_tasks_status ON pick_tasks (status);

CREATE UNIQUE INDEX ix_pick_tasks_order_id ON pick_tasks (order_id);


CREATE TABLE session_tokens (
	id VARCHAR(36) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	device_id VARCHAR(80) NOT NULL, 
	access_hash VARCHAR(128) NOT NULL, 
	refresh_hash VARCHAR(128) NOT NULL, 
	access_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	refresh_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id)
)

;

CREATE INDEX ix_session_tokens_device_id ON session_tokens (device_id);

CREATE UNIQUE INDEX ix_session_tokens_refresh_hash ON session_tokens (refresh_hash);

CREATE INDEX ix_session_tokens_user_id ON session_tokens (user_id);

CREATE UNIQUE INDEX ix_session_tokens_access_hash ON session_tokens (access_hash);


CREATE TABLE unpack_sessions (
	id VARCHAR(36) NOT NULL, 
	temperature_class VARCHAR(16) NOT NULL, 
	tote_location_id VARCHAR(100) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	device_id VARCHAR(80) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tote_location_id) REFERENCES locations (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(device_id) REFERENCES devices (id)
)

;

CREATE INDEX ix_unpack_sessions_tote_location_id ON unpack_sessions (tote_location_id);

CREATE INDEX ix_unpack_sessions_status ON unpack_sessions (status);

CREATE INDEX ix_unpack_sessions_user_id ON unpack_sessions (user_id);

CREATE INDEX ix_unpack_sessions_device_id ON unpack_sessions (device_id);


CREATE TABLE downtime_segments (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ended_at TIMESTAMP WITH TIME ZONE, 
	source VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES pick_tasks (id)
)

;

CREATE INDEX ix_downtime_segments_task_id ON downtime_segments (task_id);


CREATE TABLE pick_task_items (
	id VARCHAR(36) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	order_line_id VARCHAR(36) NOT NULL, 
	product_id VARCHAR(36) NOT NULL, 
	source_location_id VARCHAR(100) NOT NULL, 
	planned_qty INTEGER NOT NULL, 
	picked_qty INTEGER NOT NULL, 
	sequence INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES pick_tasks (id), 
	FOREIGN KEY(order_line_id) REFERENCES order_lines (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(source_location_id) REFERENCES locations (id)
)

;

CREATE INDEX ix_pick_task_items_task_id ON pick_task_items (task_id);

CREATE INDEX ix_pick_task_items_source_location_id ON pick_task_items (source_location_id);

CREATE INDEX ix_pick_task_items_order_line_id ON pick_task_items (order_line_id);

CREATE INDEX ix_pick_task_items_product_id ON pick_task_items (product_id);


CREATE TABLE scan_events (
	id VARCHAR(80) NOT NULL, 
	task_id VARCHAR(36) NOT NULL, 
	client_seq INTEGER NOT NULL, 
	device_id VARCHAR(80) NOT NULL, 
	user_id VARCHAR(36) NOT NULL, 
	event_type VARCHAR(32) NOT NULL, 
	status VARCHAR(24) NOT NULL, 
	payload_json TEXT NOT NULL, 
	server_version_after INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES pick_tasks (id)
)

;

CREATE INDEX ix_scan_events_task_id ON scan_events (task_id);


CREATE TABLE unpack_entries (
	id VARCHAR(36) NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	event_id VARCHAR(80) NOT NULL, 
	product_id VARCHAR(36) NOT NULL, 
	qty INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES unpack_sessions (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
)

;

CREATE INDEX ix_unpack_entries_product_id ON unpack_entries (product_id);

CREATE INDEX ix_unpack_entries_session_id ON unpack_entries (session_id);

CREATE UNIQUE INDEX ix_unpack_entries_event_id ON unpack_entries (event_id);
