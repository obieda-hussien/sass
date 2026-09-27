"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  createAvailabilityHold,
  directAssignTask,
  getAvailabilityHolds,
  getDispatchWorkers,
  getOperationalPerformance,
  getShipments,
  getSlottingSuggestions,
  managerLogin,
  resumeAvailabilityHold,
  searchOperationalOrders,
  type AvailabilityHold,
  type DispatchWorker,
  type OrderSearchResult,
  type PerformanceRow,
} from "../../lib/api";

const domains = ["AMBIENT", "CHILLED", "FROZEN", "PRODUCE", "HAZ", "HRV"];

function minutesLabel(seconds: number | null) {
  if (seconds == null) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m ${rest}s`;
}

function stateClass(state: string) {
  return state.toLowerCase().replaceAll("_", "-");
}

export default function OperationsPage() {
  const [token, setToken] = useState("");
  const [loginUser, setLoginUser] = useState("supervisor");
  const [loginPassword, setLoginPassword] = useState("");
  const [workers, setWorkers] = useState<DispatchWorker[]>([]);
  const [holds, setHolds] = useState<AvailabilityHold[]>([]);
  const [orders, setOrders] = useState<OrderSearchResult[]>([]);
  const [performance, setPerformance] = useState<PerformanceRow[]>([]);
  const [slotting, setSlotting] = useState<Array<Record<string, any>>>([]);
  const [shipments, setShipments] = useState<Array<Record<string, any>>>([]);
  const [query, setQuery] = useState("");
  const [fromAt, setFromAt] = useState("");
  const [toAt, setToAt] = useState("");
  const [selectedTask, setSelectedTask] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [holdForm, setHoldForm] = useState({
    scope_type: "DOMAIN",
    scope_value: "CHILLED",
    reason: "OPERATIONAL_HOLD",
    notes: "",
    duration: "manual",
    hard_stop: false,
  });

  useEffect(() => {
    const saved = window.localStorage.getItem("fulfillos_admin_token");
    if (saved) setToken(saved);
  }, []);

  async function refresh(activeToken = token) {
    if (!activeToken) return;
    try {
      const [workerData, holdData, perfData, slotData, shipmentData] = await Promise.all([
        getDispatchWorkers(activeToken, selectedTask || undefined),
        getAvailabilityHolds(activeToken),
        getOperationalPerformance(activeToken),
        getSlottingSuggestions(activeToken, 30),
        getShipments(activeToken),
      ]);
      setWorkers(workerData.workers);
      setHolds(holdData.holds);
      setPerformance(perfData.rows);
      setSlotting(slotData.suggestions);
      setShipments(shipmentData.shipments);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not refresh operations");
    }
  }

  useEffect(() => {
    if (!token) return;
    void refresh(token);
    const timer = window.setInterval(() => void refresh(token), 5_000);
    return () => window.clearInterval(timer);
  }, [token, selectedTask]);

  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await managerLogin(loginUser, loginPassword);
      if (!["TEAM_LEADER", "SUPERVISOR", "ADMIN"].includes(result.role.toUpperCase())) {
        throw new Error("Team leader, supervisor or admin role required");
      }
      window.localStorage.setItem("fulfillos_admin_token", result.access_token);
      setToken(result.access_token);
      setLoginPassword("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  async function runSearch(event?: FormEvent) {
    event?.preventDefault();
    if (!token) return;
    setBusy(true);
    try {
      const result = await searchOperationalOrders(token, {
        q: query || undefined,
        from: fromAt ? new Date(fromAt).toISOString() : undefined,
        to: toAt ? new Date(toAt).toISOString() : undefined,
        limit: 200,
      });
      setOrders(result.orders);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Order search failed");
    } finally {
      setBusy(false);
    }
  }

  async function createHold(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setBusy(true);
    try {
      let expiresAt: string | null = null;
      if (holdForm.duration !== "manual") {
        const minutes = Number(holdForm.duration);
        expiresAt = new Date(Date.now() + minutes * 60_000).toISOString();
      }
      const result = await createAvailabilityHold(token, {
        site_id: "DEMO",
        scope_type: holdForm.scope_type,
        scope_value: holdForm.scope_value,
        reason: holdForm.reason,
        notes: holdForm.notes || null,
        hard_stop: holdForm.hard_stop,
        expires_at: expiresAt,
      });
      setNotice(
        `${holdForm.scope_value} paused · ${result.impact.affected_skus} SKUs affected · ${result.impact.fully_unavailable_skus} fully unavailable`,
      );
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not pause fulfillment");
    } finally {
      setBusy(false);
    }
  }

  async function resume(holdId: string) {
    if (!token) return;
    setBusy(true);
    try {
      await resumeAvailabilityHold(token, holdId);
      setNotice("Fulfillment hold resumed");
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not resume hold");
    } finally {
      setBusy(false);
    }
  }

  async function assign(taskId: string, worker: DispatchWorker) {
    if (!token || !worker.dispatchable) return;
    setBusy(true);
    try {
      await directAssignTask(token, taskId, worker.user_id, "CONTROL_TOWER_ASSIGN");
      setNotice(`Order assigned to ${worker.full_name}`);
      setSelectedTask("");
      await Promise.all([refresh(token), runSearch()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Assignment failed");
    } finally {
      setBusy(false);
    }
  }

  const activeHolds = holds.filter((item) => item.active && item.effective);
  const availableWorkers = workers.filter((item) => item.dispatchable);
  const activeShipments = shipments.filter((item) => item.status !== "COMPLETED");
  const ordersToday = useMemo(
    () => performance.reduce((sum, item) => sum + item.orders, 0),
    [performance],
  );
  const unitsToday = useMemo(
    () => performance.reduce((sum, item) => sum + item.items, 0),
    [performance],
  );

  if (!token) {
    return (
      <main className="shell operationsShell">
        <div className="peopleTopline"><a href="/">← Control Tower</a></div>
        <section className="panel authPanel">
          <p className="eyebrow">OPERATIONS CONTROL</p>
          <h1 className="peopleTitle">Warehouse Operations</h1>
          <p className="subtitle">Dispatch, availability, order history, receiving and operational intelligence.</p>
          <form className="formStack" onSubmit={login}>
            <label><span>Supervisor username</span><input value={loginUser} onChange={(e) => setLoginUser(e.target.value)} required /></label>
            <label><span>Password</span><input type="password" value={loginPassword} onChange={(e) => setLoginPassword(e.target.value)} required /></label>
            {error && <div className="alert">{error}</div>}
            <button className="primaryButton" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="shell operationsShell">
      <header className="peopleHeader">
        <div>
          <div className="peopleTopline"><a href="/">← Control Tower</a><a href="/people">People & Payroll</a></div>
          <p className="eyebrow">FULFILLOS · OPERATIONS V0.3</p>
          <h1 className="peopleTitle">Operations Console</h1>
          <p className="subtitle">One picker, one active order. Server-owned claims. Zone-aware inventory and receiving workflows.</p>
        </div>
        <div className="peopleActions">
          <button onClick={() => void refresh()} disabled={busy}>Refresh</button>
          <button onClick={() => {
            window.localStorage.removeItem("fulfillos_admin_token");
            setToken("");
          }}>Sign out</button>
        </div>
      </header>

      {notice && <section className="noticeBox">{notice}</section>}
      {error && <section className="alert">{error}</section>}

      <section className="headlineGrid opsHeadline">
        <article className="heroCard"><span>Available pickers</span><strong>{availableWorkers.length}</strong><small>{workers.length} picker accounts visible</small></article>
        <article className="heroCard"><span>Orders / units</span><strong>{ordersToday} / {unitsToday}</strong><small>Selected performance window</small></article>
        <article className="heroCard critical"><span>Active zone holds</span><strong>{activeHolds.length}</strong><small>Physical stock is kept separate</small></article>
      </section>

      <section className="panel opsSection">
        <div className="panelHeading">
          <div><p className="eyebrow">LIVE DISPATCH</p><h2>Picker availability</h2></div>
          {selectedTask && <span className="chip">Assigning task {selectedTask.slice(0, 8)}</span>}
        </div>
        <div className="workerGrid">
          {workers.map((worker) => (
            <article className={`workerCard ${worker.dispatchable ? "workerAvailable" : "workerBlocked"}`} key={worker.user_id}>
              <div className="workerTop">
                <div><strong>{worker.full_name}</strong><small>@{worker.username}</small></div>
                <span className={`statePill state-${stateClass(worker.state)}`}>{worker.state}</span>
              </div>
              <div className="workerFacts">
                <span>Active: {worker.active_task_id ? worker.active_task_id.slice(0, 8) : "none"}</span>
                <span>Qual: {worker.qualifications.join(", ") || "standard"}</span>
                <span>Battery: {worker.device?.battery_percent ?? "—"}%</span>
                <span>Last bin: {worker.device?.last_location_id ?? "—"}</span>
              </div>
              {!worker.dispatchable && <p className="blockReason">{worker.reasons.join(" · ")}</p>}
              {selectedTask && (
                <button className="primaryButton" disabled={!worker.dispatchable || busy} onClick={() => void assign(selectedTask, worker)}>
                  Assign this order
                </button>
              )}
            </article>
          ))}
        </div>
      </section>

      <section className="panelGrid operationsGrid">
        <article className="panel">
          <div className="panelHeading"><div><p className="eyebrow">FULFILLMENT AVAILABILITY</p><h2>Pause an area</h2></div></div>
          <div className="domainChips">
            {domains.map((domain) => {
              const blocked = activeHolds.some((hold) => hold.scope_type === "DOMAIN" && hold.scope_value === domain);
              return <button key={domain} className={blocked ? "domainChip blocked" : "domainChip"} onClick={() => setHoldForm({...holdForm, scope_type:"DOMAIN", scope_value:domain})}>{domain} · {blocked ? "PAUSED" : "OPEN"}</button>;
            })}
          </div>
          <form className="opsForm" onSubmit={createHold}>
            <label><span>Scope</span><select value={holdForm.scope_type} onChange={(e) => setHoldForm({...holdForm, scope_type:e.target.value})}><option>DOMAIN</option><option>ZONE</option><option>AISLE</option><option>BIN</option><option>SKU</option><option>SITE</option></select></label>
            <label><span>Value</span><input value={holdForm.scope_value} onChange={(e) => setHoldForm({...holdForm, scope_value:e.target.value.toUpperCase()})} required /></label>
            <label><span>Reason</span><select value={holdForm.reason} onChange={(e) => setHoldForm({...holdForm, reason:e.target.value})}><option>OPERATIONAL_HOLD</option><option>TEMPERATURE_ISSUE</option><option>EQUIPMENT_FAILURE</option><option>INVENTORY_AUDIT</option><option>CLEANING</option><option>SAFETY_ISSUE</option><option>STAFFING</option><option>RESTOCKING</option><option>POWER_ISSUE</option></select></label>
            <label><span>Duration</span><select value={holdForm.duration} onChange={(e) => setHoldForm({...holdForm, duration:e.target.value})}><option value="manual">Until resumed</option><option value="15">15 minutes</option><option value="30">30 minutes</option><option value="60">1 hour</option><option value="120">2 hours</option></select></label>
            <label className="wideField"><span>Notes</span><input value={holdForm.notes} onChange={(e) => setHoldForm({...holdForm, notes:e.target.value})} /></label>
            <label className="checkField"><input type="checkbox" checked={holdForm.hard_stop} onChange={(e) => setHoldForm({...holdForm, hard_stop:e.target.checked})} /><span>Emergency hard stop: block picking from existing orders too</span></label>
            <button className="primaryButton wideField" disabled={busy}>Pause fulfillment</button>
          </form>
        </article>

        <article className="panel">
          <div className="panelHeading"><div><p className="eyebrow">ACTIVE HOLDS</p><h2>Paused scopes</h2></div><span className="chip">{activeHolds.length}</span></div>
          <div className="holdList">
            {activeHolds.length === 0 ? <div className="empty compactEmpty"><span>✓</span><div><strong>All configured areas open</strong><p>No effective fulfillment holds.</p></div></div> : activeHolds.map((hold) => (
              <div className="holdRow" key={hold.id}>
                <div><strong>{hold.scope_type} · {hold.scope_value}</strong><small>{hold.reason} · {hold.hard_stop ? "hard stop" : "new orders only"}</small></div>
                <button onClick={() => void resume(hold.id)} disabled={busy}>Resume</button>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="panel opsSection">
        <div className="panelHeading"><div><p className="eyebrow">ORDER EXPLORER</p><h2>Order ID · SPOO · picker · date/time</h2></div></div>
        <form className="searchBar" onSubmit={runSearch}>
          <input placeholder="Order ID, SPOO / last 4, or username" value={query} onChange={(e) => setQuery(e.target.value)} />
          <input type="datetime-local" value={fromAt} onChange={(e) => setFromAt(e.target.value)} />
          <input type="datetime-local" value={toAt} onChange={(e) => setToAt(e.target.value)} />
          <button className="primaryButton" disabled={busy}>Search</button>
        </form>
        <div className="orderCards">
          {orders.map((order) => (
            <article className="orderCard" key={order.order_id}>
              <div className="orderTop">
                <div><strong>{order.external_ref ?? order.order_id}</strong><small>{order.picker ? `@${order.picker.username}` : "Unassigned"} · {order.status}</small></div>
                {order.task_id && !order.picker && <button className="miniAction" onClick={() => setSelectedTask(order.task_id ?? "")}>Assign</button>}
              </div>
              <div className="orderFacts"><span>{order.sku_count} SKU</span><span>{order.picked_units}/{order.requested_units} units</span><span>{order.bag_count} bags</span><span>{order.pick_finished_at ? new Date(order.pick_finished_at).toLocaleString() : "Not finished"}</span></div>
              {order.bags.length > 0 && <div className="bagRow">{order.bags.map((bag) => <code key={bag.bag_no}>Bag {bag.bag_no} · {bag.spoo_masked}</code>)}</div>}
              <details><summary>Items</summary>{order.items.map((item) => <div className="itemLine" key={item.product_id}><span>{item.title}</span><strong>{item.picked_qty}/{item.requested_qty}{item.shorted_qty ? ` · short ${item.shorted_qty}` : ""}</strong></div>)}</details>
            </article>
          ))}
          {orders.length === 0 && <div className="empty compactEmpty"><span>⌕</span><div><strong>Search orders</strong><p>Use ID, SPOO, username, or a date/time window.</p></div></div>}
        </div>
      </section>

      <section className="panelGrid operationsGrid">
        <article className="panel">
          <div className="panelHeading"><div><p className="eyebrow">PICKER METRICS</p><h2>Operational performance</h2></div></div>
          <div className="tableWrap"><table><thead><tr><th>Picker</th><th>Orders</th><th>Items</th><th>Bags</th><th>Late SLAM</th><th>Avg pick</th></tr></thead><tbody>{performance.map((row) => <tr key={row.user_id}><td>{row.full_name}</td><td>{row.orders}</td><td>{row.items}</td><td>{row.bags}</td><td>{row.late_slam} ({row.late_slam_rate}%)</td><td>{minutesLabel(row.avg_pick_seconds)}</td></tr>)}</tbody></table></div>
          <p className="policyNote">These are operational facts for review; promotion and pay changes are never automatic from a score.</p>
        </article>

        <article className="panel">
          <div className="panelHeading"><div><p className="eyebrow">DEMAND INTELLIGENCE</p><h2>Slotting suggestions</h2></div></div>
          <div className="slottingList">{slotting.slice(0, 10).map((item) => <div className="slotRow" key={String(item.product_id)}><div><strong>{String(item.title)}</strong><small>{String(item.asin ?? "")} · {Number(item.picked_units)} units / 30d</small></div><span>{Array.isArray(item.current_aisles) ? item.current_aisles.join(", ") : "—"}</span></div>)}</div>
          <p className="policyNote">Suggestions only. Moving a SKU requires an explicit operations decision.</p>
        </article>
      </section>

      <section className="panel opsSection">
        <div className="panelHeading"><div><p className="eyebrow">INBOUND</p><h2>Shipment & stow pipeline</h2></div><span className="chip">{activeShipments.length} active</span></div>
        <div className="shipmentGrid">{activeShipments.map((shipment) => <article className="shipmentCard" key={String(shipment.id)}><div><strong>{String(shipment.label)}</strong><small>{String(shipment.shipment_type)} · {String(shipment.storage_domain)}</small></div><span className={`statePill state-${stateClass(String(shipment.status))}`}>{String(shipment.status)}</span><div className="shipmentStats"><span>Expected {Number(shipment.expected_units)}</span><span>Received {Number(shipment.received_units)}</span><span>Damaged {Number(shipment.damaged_units)}</span><span>Missing {Number(shipment.missing_units)}</span></div>{shipment.stow_overdue && <p className="blockReason">Stow target exceeded · {Number(shipment.elapsed_minutes)}m / {Number(shipment.target_stow_minutes)}m</p>}</article>)}</div>
      </section>
    </main>
  );
}
