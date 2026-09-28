"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getSummary, type Summary } from "../lib/api";

const associateOrder = [
  "WAITING",
  "OFFERED",
  "PICKING",
  "PACKING_RACKING",
  "BREAK",
  "OTHER_ACTIVITY",
  "OFFLINE",
];

const taskOrder = [
  "READY",
  "OFFERED",
  "PICKING",
  "PACKING_RACKING",
  "STAGED",
  "RECOVERY_REQUIRED",
  "CANCELLED",
  "COMPLETED",
];

function label(value: string) {
  return value
    .toLowerCase()
    .split("_")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

export default function ControlTowerPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    const controller = new AbortController();
    try {
      const result = await getSummary(controller.signal);
      setSummary(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unknown control tower error");
    }
    return () => controller.abort();
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const totalAssociates = useMemo(
    () => Object.values(summary?.associates ?? {}).reduce((a, b) => a + b, 0),
    [summary],
  );
  const activeTasks = useMemo(
    () =>
      Object.entries(summary?.tasks ?? {})
        .filter(([state]) => !["COMPLETED", "CANCELLED"].includes(state))
        .reduce((sum, [, count]) => sum + count, 0),
    [summary],
  );

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">FULFILLOS · LIVE OPERATIONS</p>
          <h1>Control Tower</h1>
          <p className="subtitle">
            Live warehouse overview plus direct entry points to the exact task you need.
            Server-confirmed state refreshes every five seconds.
          </p>
        </div>
        <div className="headerActions">
          <a className="navButton" href="/operations">Operations</a>
          <a className="navButton" href="/people">People & Payroll</a>
          <div className="statusCluster">
            <span className={error ? "statusDot danger" : "statusDot"} />
            <div>
              <strong>{error ? "API degraded" : "Live"}</strong>
              <small>
                {lastUpdated
                  ? `Updated ${lastUpdated.toLocaleTimeString()}`
                  : "Connecting…"}
              </small>
            </div>
            <button onClick={() => void refresh()}>Refresh</button>
          </div>
        </div>
      </header>

      {error && (
        <section className="alert">
          <strong>Control tower data is stale.</strong>
          <span>{error}</span>
        </section>
      )}

      <section className="headlineGrid">
        <article className="heroCard">
          <span>Associates on site</span>
          <strong>{summary ? totalAssociates : "—"}</strong>
          <small>Across operational states</small>
        </article>
        <article className="heroCard">
          <span>Active tasks</span>
          <strong>{summary ? activeTasks : "—"}</strong>
          <small>Excludes completed and cancelled</small>
        </article>
        <article className="heroCard critical">
          <span>Recovery required</span>
          <strong>{summary?.recoveryRequired.length ?? "—"}</strong>
          <small>Needs explicit supervisor resolution</small>
        </article>
      </section>

      <section className="panel moduleGuide">
        <div className="panelHeading">
          <div>
            <p className="eyebrow">QUICK ACTIONS</p>
            <h2>Where do I do what?</h2>
          </div>
          <span className="chip">Start here</span>
        </div>
        <p className="sectionHelp">
          Choose the job, not the page. These links jump directly to the right operational section.
        </p>
        <div className="moduleGrid">
          <a className="moduleCard" href="/operations#dispatch"><span className="moduleTag">LIVE</span><strong>Assign / monitor orders</strong><small>See online pickers, active work and manually assign an unowned order.</small></a>
          <a className="moduleCard" href="/operations#orders"><span className="moduleTag">SEARCH</span><strong>Find an order or SPOO</strong><small>Search by order ID, picker, full SPOO/last digits or time window.</small></a>
          <a className="moduleCard" href="/operations#availability"><span className="moduleTag">CONTROL</span><strong>Pause a zone / freezer / chiller</strong><small>Stop new fulfillment from a domain, zone, aisle, bin or SKU without changing physical stock.</small></a>
          <a className="moduleCard" href="/operations#replenishment"><span className="moduleTag">STOCK</span><strong>Replenishment</strong><small>Generate and monitor low-pick-face replenishment tasks.</small></a>
          <a className="moduleCard" href="/operations#inbound"><span className="moduleTag">INBOUND</span><strong>Receive & stow</strong><small>Watch shipment receiving, damaged/missing quantities and cold-chain stow timing.</small></a>
          <a className="moduleCard" href="/people#onboarding"><span className="moduleTag">PEOPLE</span><strong>Add a new employee</strong><small>Create account, PIN, contact details, role and payroll basics.</small></a>
          <a className="moduleCard" href="/people#team"><span className="moduleTag">TEAM</span><strong>Manage / promote employee</strong><small>Open employee details, promotion history, attendance and approved adjustments.</small></a>
          <a className="moduleCard" href="/people#schedule"><span className="moduleTag">ROTA</span><strong>Build the shift schedule</strong><small>Create shift templates and assign employees to dated shifts.</small></a>
          <a className="moduleCard" href="/system"><span className="moduleTag">ADMIN</span><strong>Audit, permissions & system health</strong><small>Inspect sensitive changes, outbox/telemetry health and explicit access overrides.</small></a>
        </div>
      </section>

      <section className="panelGrid">
        <article className="panel">
          <div className="panelHeading">
            <div>
              <p className="eyebrow">PEOPLE</p>
              <h2>Associate state</h2>
            </div>
          </div>
          <div className="metricList">
            {associateOrder.map((state) => (
              <div className="metricRow" key={state}>
                <div>
                  <span className={`miniDot state-${state.toLowerCase()}`} />
                  {label(state)}
                </div>
                <strong>{summary?.associates[state] ?? 0}</strong>
              </div>
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="panelHeading">
            <div>
              <p className="eyebrow">FULFILLMENT</p>
              <h2>Task pipeline</h2>
            </div>
          </div>
          <div className="metricList">
            {taskOrder.map((state) => (
              <div className="metricRow" key={state}>
                <div>
                  <span className={`miniDot task-${state.toLowerCase()}`} />
                  {label(state)}
                </div>
                <strong>{summary?.tasks[state] ?? 0}</strong>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="panel recoveryPanel">
        <div className="panelHeading">
          <div>
            <p className="eyebrow">EXCEPTIONS</p>
            <h2>Recovery queue</h2>
          </div>
          <span className="chip">Never auto-dismissed</span>
        </div>

        {summary?.recoveryRequired.length ? (
          <div className="tableWrap">
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Order</th>
                  <th>Associate</th>
                  <th>Reason</th>
                  <th>Version</th>
                </tr>
              </thead>
              <tbody>
                {summary.recoveryRequired.map((item) => (
                  <tr key={item.taskId}>
                    <td><code>{item.taskId.slice(0, 8)}</code></td>
                    <td><code>{item.orderId.slice(0, 8)}</code></td>
                    <td>{item.associateId ?? "—"}</td>
                    <td>{item.reason ?? "Unspecified"}</td>
                    <td>v{item.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">
            <span>✓</span>
            <div>
              <strong>No recovery tasks</strong>
              <p>There are no partially committed cancelled orders requiring action.</p>
            </div>
          </div>
        )}
      </section>

      <footer>
        FulfillOS prioritizes committed server state over optimistic UI counters.
      </footer>
    </main>
  );
}
