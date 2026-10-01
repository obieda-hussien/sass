"use client";

import { FormEvent, useState } from "react";
import { createShipment, resolveShipmentIssue, lookupCatalogProduct, registerCatalogProduct, activateCatalogProduct, type CatalogProduct } from "../../lib/api";
import { shipmentBarcode } from "../../lib/shipment-barcode";

type Shipment = Record<string, any>;
const zones = ["AMBIENT", "CHILLED", "FROZEN", "PRODUCE", "HAZ", "HRV"];
const blankLine = () => ({ product_id: "", expected_qty: "1", expires_on: "", lot_code: "" });

function ShipmentDateField({ label, value, onChange, min }: { label: string; value: string; onChange: (value: string) => void; min?: string }) {
  const selected = value ? new Date(`${value}T00:00:00`) : null;
  const readable = selected && !Number.isNaN(selected.getTime())
    ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric" }).format(selected)
    : "Choose from the calendar";
  return <label>{label}<input type="date" dir="ltr" value={value} min={min} onChange={(event) => onChange(event.target.value)} /><small className="shipmentDateHint">{readable}</small></label>;
}

function CatalogItemHelper({ token, identifier, storageDomain, onReady }: { token: string; identifier: string; storageDomain: string; onReady: () => void }) {
  const [checked, setChecked] = useState("");
  const [product, setProduct] = useState<CatalogProduct | null>(null);
  const [sku, setSku] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const code = identifier.trim();
  async function check() {
    setBusy(true); setError(""); setChecked("");
    try {
      const result = await lookupCatalogProduct(token, code);
      setProduct(result.product); setChecked(code); setSku(""); setTitle("");
      if (result.product?.active) onReady();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not check item"); }
    finally { setBusy(false); }
  }
  async function save(activate = false) {
    setBusy(true); setError("");
    try {
      const result = activate && product
        ? await activateCatalogProduct(token, product.id)
        : await registerCatalogProduct(token, { barcode: code, sku: sku.trim(), title: title.trim(), storage_domain: storageDomain });
      setProduct(result); onReady();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not save product"); }
    finally { setBusy(false); }
  }
  return <div className="catalogItemHelper">
    <button type="button" disabled={busy || !code} onClick={() => void check()}>{busy ? "Checking / saving…" : "Check / register item"}</button>
    {error && <p className="blockReason" role="alert">{error}</p>}
    {checked === code && product && <div className="catalogResult"><strong dir="auto">{product.title}</strong><p>SKU: {product.sku} · {product.temperature_class}/{product.handling_class} · {product.active ? "Active" : "Inactive"}</p>
      {!product.active && <button type="button" disabled={busy} onClick={() => void save(true)}>Activate this product</button>}
    </div>}
    {checked === code && !product && <div className="catalogRegistration">
      <p>Barcode {code} is not registered. Enter the real item name and a SKU. An existing SKU links this barcode to that product without changing its name or storage rules.</p>
      <label>Product SKU <input maxLength={24} value={sku} placeholder="Model / SKU number" onChange={(event) => setSku(event.target.value)} /></label>
      <label>Product name <input maxLength={240} value={title} dir="auto" placeholder="Name on the product packaging" onChange={(event) => setTitle(event.target.value)} /></label>
      <small>New product storage zone: {storageDomain}. Registration adds catalog information; stock is counted when received.</small>
      <button type="button" disabled={busy || !sku.trim()} onClick={() => void save()}>Save product / link barcode</button>
    </div>}
  </div>;
}

function Barcode({ code }: { code: string }) {
  // Legacy labels may contain characters which cannot fit Code 128 B.
  // The caller uses the immutable UUID for those older manifests.
  const { bars, width } = shipmentBarcode(code);
  return <figure className="shipmentBarcode">
    <svg viewBox={`0 0 ${width} 65`} role="img" aria-label={`Shipment barcode ${code}`} xmlns="http://www.w3.org/2000/svg">
      <rect width={width} height="65" fill="white" />
      {bars.map((bar, index) => <rect key={index} x={bar.x} y="0" width={bar.width} height="65" fill="black" />)}
    </svg>
    <figcaption>{code}</figcaption>
  </figure>;
}

function Manifest({ shipment, onClose }: { shipment: Shipment; onClose: () => void }) {
  const code = /^[\x20-\x7e]+$/.test(String(shipment.label)) ? String(shipment.label) : String(shipment.id);
  return <div className="manifestBackdrop" role="dialog" aria-modal="true" aria-label="Shipment manifest">
    <div className="manifestContainer">
      <div className="manifestActions"><button type="button" onClick={() => window.print()}>Print / Save PDF</button><button type="button" onClick={onClose}>Close</button></div>
      <article id="shipment-print-sheet" className="manifestSheet" dir="auto">
        <header><Barcode code={code} /><div><h1>FulfillOS · تفاصيل الشحنة</h1><strong>{String(shipment.label)}</strong><p>Scan the barcode to open receiving · اسكان الباركود لفتح الشحنة</p></div></header>
        <dl className="manifestMeta">
          <div><dt>Supplier / المورد</dt><dd>{shipment.supplier_name || "—"}</dd></div>
          <div><dt>Purchase order / رقم أمر الشراء</dt><dd>{shipment.purchase_order_ref || shipment.label}</dd></div>
          <div><dt>Order date / تاريخ الطلب</dt><dd>{shipment.order_date || "—"}</dd></div>
          <div><dt>Delivery window / فترة الشحن</dt><dd>{shipment.delivery_from || "—"} → {shipment.delivery_to || "—"}</dd></div>
          <div><dt>Zone / زون التسكين</dt><dd>{shipment.storage_domain}</dd></div>
          <div><dt>Ship to / عنوان الشحن</dt><dd>{shipment.shipping_address || "—"}</dd></div>
        </dl>
        <table><thead><tr><th>Item barcode / باركود الصنف</th><th>SKU</th><th>Item / الصنف</th><th>Expected / المطلوب</th><th>Received / المستلم</th><th>Rejected / المرفوض</th><th>Expiry / الصلاحية</th></tr></thead>
          <tbody>{(shipment.lines || []).map((line: Shipment) => <tr key={line.id}><td>{line.barcode || "—"}</td><td>{line.asin || line.product_id}</td><td dir="auto">{line.title}</td><td>{line.expected_qty}</td><td>{line.received_qty}</td><td>{line.damaged_qty}</td><td>{line.expires_on || ""}</td></tr>)}</tbody>
        </table>
        <p>Expected {shipment.expected_units} · Good {shipment.received_units} · Rejected {shipment.damaged_units} · Missing {shipment.remaining_expected_units}</p>
        {shipment.notes && <p dir="auto">{shipment.notes}</p>}
        <footer>Shipment ID: {shipment.id} · Report damaged/expired items through Issues before stowing.</footer>
      </article>
    </div>
  </div>;
}

export function ShipmentManifestButton({ shipment }: { shipment: Shipment }) {
  const [visible, setVisible] = useState(false);
  return <><button type="button" onClick={() => setVisible(true)}>Barcode & shipment sheet</button>{visible && <Manifest shipment={shipment} onClose={() => setVisible(false)} />}</>;
}

export function ShipmentCreateForm({ token, onCreated }: { token: string; onCreated: () => void | Promise<void> }) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<Shipment | null>(null);
  const [form, setForm] = useState({ label: "", supplier_name: "", purchase_order_ref: "", shipment_type: "VENDOR", storage_domain: "AMBIENT", order_date: "", delivery_from: "", delivery_to: "", shipping_address: "", notes: "" });
  const [lines, setLines] = useState([blankLine()]);
  const update = (key: keyof typeof form, value: string) => setForm((current) => ({ ...current, [key]: value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      const result = await createShipment(token, {
        ...form, label: form.label.trim(),
        order_date: form.order_date || null, delivery_from: form.delivery_from || null, delivery_to: form.delivery_to || null,
        lines: lines.map((line) => ({ product_id: line.product_id.trim(), expected_qty: Number(line.expected_qty), expires_on: line.expires_on || null, lot_code: line.lot_code || null })),
      });
      setCreated(result); setExpanded(false); setLines([blankLine()]);
      setForm((current) => ({ ...current, label: "", purchase_order_ref: "", notes: "" }));
      await onCreated();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not create shipment"); }
    finally { setBusy(false); }
  }

  return <div className="shipmentCreate">
    <button type="button" onClick={() => setExpanded(!expanded)}>{expanded ? "Close creation form" : "+ Create shipment"}</button>
    <p>Generate a unique code, print the manifest, then scan its barcode on any signed-in PDA.</p>
    {error && <p role="alert" className="blockReason">{error}</p>}
    {created && <div className="shipmentCreated"><strong>Shipment {String(created.label)} created.</strong><ShipmentManifestButton shipment={created} /></div>}
    {expanded && <form onSubmit={(event) => void submit(event)}><fieldset disabled={busy}>
      <div className="shipmentFormGrid">
        <label>Shipment code <input value={form.label} maxLength={48} onChange={(e) => update("label", e.target.value.toUpperCase())} placeholder="Automatic if blank · e.g. 4ZOXV48Q" /></label>
        <label>Supplier <input placeholder="Supplier name · e.g. QCD2" value={form.supplier_name} maxLength={160} onChange={(e) => update("supplier_name", e.target.value)} /></label>
        <label>Purchase order reference <input placeholder="Number on the purchase order · e.g. 4ZOXV48Q" value={form.purchase_order_ref} maxLength={120} onChange={(e) => update("purchase_order_ref", e.target.value)} /></label>
        <label>Storage zone <select value={form.storage_domain} onChange={(e) => update("storage_domain", e.target.value)}>{zones.map((zone) => <option key={zone}>{zone}</option>)}</select></label>
        <label>Shipment type <select value={form.shipment_type} onChange={(e) => update("shipment_type", e.target.value)}>{["VENDOR", "TRANSFER", "RETURN"].map((kind) => <option key={kind}>{kind}</option>)}</select></label>
        <ShipmentDateField label="Order date" value={form.order_date} onChange={(value) => update("order_date", value)} />
        <ShipmentDateField label="Delivery from" value={form.delivery_from} onChange={(value) => update("delivery_from", value)} />
        <ShipmentDateField label="Delivery to" min={form.delivery_from || undefined} value={form.delivery_to} onChange={(value) => update("delivery_to", value)} />
        <label>Shipping address <input value={form.shipping_address} maxLength={500} onChange={(e) => update("shipping_address", e.target.value)} /></label>
        <label>Notes <input value={form.notes} maxLength={1000} onChange={(e) => update("notes", e.target.value)} /></label>
      </div>
      <h3>Expected items</h3><p>Scan/type the product barcode, SKU or internal product ID. Each shipment covers one storage zone.</p>
      {lines.map((line, index) => <div className="shipmentItemRow" key={index}><div className="shipmentLineForm">
        <label>Item barcode / SKU <input required value={line.product_id} onChange={(e) => setLines((current) => current.map((row, i) => i === index ? { ...row, product_id: e.target.value } : row))} /></label>
        <label>Quantity <input required type="number" min="1" step="1" value={line.expected_qty} onChange={(e) => setLines((current) => current.map((row, i) => i === index ? { ...row, expected_qty: e.target.value } : row))} /></label>
        <ShipmentDateField label="Expiry" value={line.expires_on} onChange={(value) => setLines((current) => current.map((row, i) => i === index ? { ...row, expires_on: value } : row))} />
        <label>Lot <input value={line.lot_code} maxLength={80} onChange={(e) => setLines((current) => current.map((row, i) => i === index ? { ...row, lot_code: e.target.value } : row))} /></label>
        <button type="button" disabled={lines.length === 1} aria-label={`Remove item ${index + 1}`} onClick={() => setLines((current) => current.filter((_, i) => i !== index))}>×</button>
      </div><CatalogItemHelper token={token} identifier={line.product_id} storageDomain={form.storage_domain} onReady={() => setError("")} /></div>)}
      <div className="shipmentFormActions"><button type="button" disabled={lines.length >= 500} onClick={() => setLines([...lines, blankLine()])}>+ Add item</button><button type="submit">{busy ? "Creating…" : "Create shipment & barcode"}</button></div>
    </fieldset></form>}
  </div>;
}

export function ShipmentIssues({ token, shipment, onResolved }: { token: string; shipment: Shipment; onResolved: () => void | Promise<void> }) {
  const [resolutions, setResolutions] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  async function resolve(issueId: string) {
    setBusy(issueId); setError("");
    try { await resolveShipmentIssue(token, shipment.id, issueId, resolutions[issueId].trim()); await onResolved(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Could not resolve issue"); }
    finally { setBusy(""); }
  }
  const issues: Shipment[] = shipment.issues || [];
  if (!issues.length) return null;
  return <details className="shipmentIssues"><summary>Issues · {shipment.open_issues} open / {issues.length} total</summary>
    {error && <p role="alert" className="blockReason">{error}</p>}
    {issues.map((issue) => <article key={issue.id}><strong>{issue.issue_type} · {issue.qty} · {issue.status}</strong>
      <p>{issue.title || "Shipment"} · {issue.notes}</p><small>{issue.reported_by} · {issue.created_at}</small>
      {issue.resolution && <p>Resolution: {issue.resolution}</p>}
      {issue.status === "OPEN" && <div><input aria-label="Issue resolution" value={resolutions[issue.id] || ""} maxLength={1000} placeholder="What action was taken?" onChange={(e) => setResolutions((current) => ({ ...current, [issue.id]: e.target.value }))} /><button type="button" disabled={!!busy || (resolutions[issue.id] || "").trim().length < 3} onClick={() => void resolve(issue.id)}>{busy === issue.id ? "Saving…" : "Resolve issue"}</button></div>}
    </article>)}
  </details>;
}
