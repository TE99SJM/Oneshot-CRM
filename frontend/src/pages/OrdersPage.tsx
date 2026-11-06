import { ReactNode, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Badge, Drawer, Empty, Stat } from "../components/ui";
import { dateTime, money2 as money, num } from "../format";
import { toastError } from "../store/toastStore";
import type { Json, OrderDetail, OrderPage, OrderRow } from "../types";

const STATE_TONE: Record<string, string> = { COMPLETED: "green", OPEN: "amber", CANCELED: "red", DRAFT: "neutral" };
const STATE_LABEL: Record<string, string> = { COMPLETED: "Completed", OPEN: "Open", CANCELED: "Canceled", DRAFT: "Draft" };
const PAGE = 50;

const label = (s?: string | null) => (s ? s.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : "");
const cents = (m?: Json) => (m && typeof m.amount === "number" ? money(m.amount / 100) : "—");

function StateBadge({ o }: { o: Pick<OrderRow, "state" | "refunded" | "total"> }) {
  if (o.refunded > 0 && o.refunded >= o.total) return <Badge tone="red">Refunded</Badge>;
  return (
    <>
      <Badge tone={STATE_TONE[o.state] ?? "neutral"}>{STATE_LABEL[o.state] ?? label(o.state)}</Badge>
      {o.refunded > 0 && <> <Badge tone="amber">Partly refunded</Badge></>}
    </>
  );
}

export default function OrdersPage() {
  const [data, setData] = useState<OrderPage | null>(null);
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const [fulfillment, setFulfillment] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);

  const query = useCallback(() => {
    const p: Record<string, string> = {};
    if (q.trim()) p.q = q.trim();
    if (state) p.state = state;
    if (fulfillment) p.fulfillment = fulfillment;
    if (from) p.date_from = from;
    if (to) p.date_to = to;
    return p;
  }, [q, state, fulfillment, from, to]);

  useEffect(() => {
    const t = setTimeout(() => {
      api.get<OrderPage>("/orders", { ...query(), limit: PAGE, offset }).then(setData).catch(toastError);
    }, 200);
    return () => clearTimeout(t);
  }, [query, offset]);
  useEffect(() => setOffset(0), [q, state, fulfillment, from, to]);

  const exportCsv = () => {
    const qs = new URLSearchParams(query()).toString();
    api.download(`/orders/export.csv${qs ? `?${qs}` : ""}`, "orders.csv").catch(toastError);
  };

  const s = data?.summary;
  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Orders</h1><p className="muted">Every order from your store, with items, payment, shipping and refund details.</p></div>
        <button className="btn" onClick={exportCsv}>Export CSV</button>
      </header>

      <div className="stats">
        <Stat label="Orders" value={num(s?.orders)} sub={s && s.orders ? `avg ${money(s.average)}` : undefined} />
        <Stat label="Gross sales" value={money(s?.gross)} sub={s ? `tax ${money(s.tax)} · tips ${money(s.tips)}` : undefined} />
        <Stat label="Refunded" value={money(s?.refunded)} />
        <Stat label="Net sales" value={money(s?.net)} sub={s ? `fees ${money(s.fees)} · after fees ${money(s.net - s.fees)}` : undefined} />
      </div>

      <div className="toolbar">
        <input className="search" placeholder="Search customer, item, email, order #…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">All statuses</option><option value="OPEN">Open</option><option value="COMPLETED">Completed</option><option value="CANCELED">Canceled</option>
        </select>
        <select value={fulfillment} onChange={(e) => setFulfillment(e.target.value)}>
          <option value="">All fulfillment</option><option value="SHIPMENT">Shipping</option><option value="PICKUP">Pickup</option>
          <option value="DELIVERY">Delivery</option><option value="DIGITAL">Digital</option>
        </select>
        <label className="row small">From <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="row small">To <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      </div>

      <div className="card table-wrap">
        {!data ? <Empty title="Loading…" /> : data.items.length === 0 ? (
          <Empty title="No orders yet">
            Orders appear here after you connect Square on the <Link to="/integrations">Integrations</Link> page and it syncs.
          </Empty>
        ) : (
          <table className="table orders-table">
            <thead><tr>
              <th>Date</th><th>Order</th><th>Customer</th><th>Items</th><th>Status</th><th>Fulfillment</th><th>Payment</th>
              <th className="num">Total</th><th className="num">Net</th>
            </tr></thead>
            <tbody>
              {data.items.map((o) => (
                <tr key={o.id} className="clickable" onClick={() => setOpen(o.id)} data-testid={`order-${o.id}`}>
                  <td className="nowrap">{dateTime(o.ordered_at)}</td>
                  <td><strong>#{o.reference}</strong><div className="muted small">{o.source_name || o.location_name}</div></td>
                  <td>{o.customer_name || <span className="muted">Guest</span>}<div className="muted small">{o.customer_email}</div></td>
                  <td className="items-cell" title={o.items_summary}>{o.items_summary || "—"}</td>
                  <td><StateBadge o={o} /></td>
                  <td>{label(o.fulfillment_type) || "—"}<div className="muted small">{label(o.fulfillment_state)}</div></td>
                  <td className="small">{o.payment_summary || "—"}</td>
                  <td className="num">{money(o.total)}</td>
                  <td className="num"><strong>{money(o.net)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && data.total > PAGE && (
        <div className="row pager">
          <button className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>← Newer</button>
          <span className="muted small">{offset + 1}–{Math.min(offset + PAGE, data.total)} of {num(data.total)}</span>
          <button className="btn btn-sm" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Older →</button>
        </div>
      )}
      {open !== null && <OrderDrawer id={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="order-section"><h3>{title}</h3>{children}</section>;
}

function KV({ rows }: { rows: [string, ReactNode][] }) {
  const shown = rows.filter(([, v]) => v !== undefined && v !== null && v !== "" && v !== "—");
  if (!shown.length) return null;
  return <dl className="kv">{shown.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>;
}

function address(a?: Json) {
  if (!a) return "";
  return [a.address_line_1, a.address_line_2, a.address_line_3,
    [a.locality, a.administrative_district_level_1, a.postal_code].filter(Boolean).join(" "), a.country]
    .filter(Boolean).join(", ");
}

function OrderDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const [o, setO] = useState<OrderDetail | null>(null);
  const [showRaw, setShowRaw] = useState(false);
  useEffect(() => { api.get<OrderDetail>(`/orders/${id}`).then(setO).catch(toastError); }, [id]);
  const raw = o?.raw ?? {};

  return (
    <Drawer title={o ? <>Order #{o.reference} <StateBadge o={o} /></> : "Order"} onClose={onClose}>
      {!o ? <p className="muted">Loading…</p> : (
        <div className="order-detail">
          <KV rows={[
            ["Placed", dateTime(o.ordered_at)], ["Completed", o.closed_at ? dateTime(o.closed_at) : ""],
            ["Last updated", dateTime(o.updated_at_ext)], ["Sold through", o.source_name], ["Location", o.location_name],
            ["Channel", o.channel_name], ["Square order ID", <code key="id">{o.external_id}</code>],
            ["Pipeline deal", o.deal_id ? <Link key="d" to="/pipeline">View in Pipeline</Link> : ""],
          ]} />
          <div className="row">
            <a className="btn btn-sm" href="https://app.squareup.com/dashboard/orders/overview" target="_blank" rel="noreferrer" title={`Search for order ${o.external_id}`}>Square orders ↗</a>
            {o.receipt_url && <a className="btn btn-sm" href={o.receipt_url} target="_blank" rel="noreferrer">Receipt ↗</a>}
          </div>

          <Section title="Customer">
            <KV rows={[["Name", o.customer_name || "Guest"], ["Email", o.customer_email ? <a key="e" href={`mailto:${o.customer_email}`}>{o.customer_email}</a> : ""],
              ["Phone", o.customer_phone], ["Contact", o.contact_id ? <Link key="c" to="/contacts">View in Contacts</Link> : ""],
              ["Square customer ID", raw.customer_id]]} />
          </Section>

          <Section title={`Items (${num(o.item_count)})`}>
            <table className="table compact">
              <thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Price</th><th className="num">Total</th></tr></thead>
              <tbody>
                {(raw.line_items ?? []).map((li: Json, i: number) => (
                  <tr key={li.uid ?? i}>
                    <td>
                      <strong>{li.name || "Item"}</strong>{li.variation_name && <span className="muted"> · {li.variation_name}</span>}
                      {(li.modifiers ?? []).map((m: Json, j: number) => <div key={j} className="muted small">+ {m.name} {cents(m.total_price_money ?? m.base_price_money)}</div>)}
                      {(li.applied_discounts ?? []).length > 0 && <div className="muted small">Discount {cents(li.total_discount_money)}</div>}
                      {li.note && <div className="muted small">Note: {li.note}</div>}
                      {li.item_type && li.item_type !== "ITEM" && <div className="muted small">{label(li.item_type)}</div>}
                    </td>
                    <td className="num">{li.quantity}{li.quantity_unit?.measurement_unit ? "" : ""}</td>
                    <td className="num">{cents(li.base_price_money)}</td>
                    <td className="num">{cents(li.total_money)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section title="Totals">
            <KV rows={[
              ["Subtotal", money(o.subtotal)],
              ...((raw.discounts ?? []) as Json[]).map((d): [string, ReactNode] => [`Discount: ${d.name || label(d.type)}${d.percentage ? ` (${d.percentage}%)` : ""}`, `−${cents(d.applied_money ?? d.amount_money)}`]),
              ...((raw.service_charges ?? []) as Json[]).map((c): [string, ReactNode] => [`Charge: ${c.name || "Service charge"}`, cents(c.total_money ?? c.applied_money ?? c.amount_money)]),
              ...((raw.taxes ?? []) as Json[]).map((t): [string, ReactNode] => [`Tax: ${t.name || "Tax"}${t.percentage ? ` (${t.percentage}%)` : ""}`, cents(t.applied_money)]),
              ...(!(raw.taxes ?? []).length && o.tax_total ? [["Tax", money(o.tax_total)] as [string, ReactNode]] : []),
              ["Tip", o.tip_total ? money(o.tip_total) : ""],
              ["Rounding", raw.rounding_adjustment ? cents(raw.rounding_adjustment.amount_money) : ""],
              ["Total", <strong key="t">{money(o.total)}</strong>],
              ["Refunded", o.refunded ? `−${money(o.refunded)}` : ""],
              ["Net sale", <strong key="n">{money(o.net)}</strong>],
              ["Square fees", o.processing_fee ? `−${money(o.processing_fee)}` : ""],
              ["You keep", o.processing_fee ? <strong key="k">{money(o.net - o.processing_fee)}</strong> : ""],
            ]} />
          </Section>

          {(raw.fulfillments ?? []).length > 0 && (
            <Section title="Fulfillment">
              {(raw.fulfillments as Json[]).map((f, i) => {
                const d = f.shipment_details ?? f.pickup_details ?? f.delivery_details ?? f.digital_details ?? {};
                const r = d.recipient ?? {};
                return (
                  <KV key={f.uid ?? i} rows={[
                    ["Type", label(f.type)], ["Status", label(f.state)], ["Recipient", r.display_name],
                    ["Email", r.email_address], ["Phone", r.phone_number], ["Address", address(r.address)],
                    ["Carrier", d.carrier], ["Shipping method", d.shipping_type],
                    ["Tracking #", d.tracking_url ? <a key="tr" href={d.tracking_url} target="_blank" rel="noreferrer">{d.tracking_number || "Track"}</a> : d.tracking_number],
                    ["Shipping note", d.shipping_note], ["Pickup time", d.pickup_at ? dateTime(d.pickup_at) : ""],
                    ["Pickup note", d.note], ["Delivery note", d.note && f.delivery_details ? d.note : ""],
                    ["Shipped", d.shipped_at ? dateTime(d.shipped_at) : ""], ["Placed", d.placed_at ? dateTime(d.placed_at) : ""],
                  ]} />
                );
              })}
            </Section>
          )}

          <Section title="Payment">
            {o.payments.length === 0 && (raw.tenders ?? []).length === 0 && <p className="muted small">No payment details recorded.</p>}
            {o.payments.map((p: Json) => {
              const card = p.card_details?.card ?? {};
              return (
                <KV key={p.id} rows={[
                  ["Method", card.card_brand ? `${label(card.card_brand)} ••${card.last_4}` : label(p.source_type)],
                  ["Card type", label(card.card_type)], ["Entry", label(p.card_details?.entry_method)],
                  ["Wallet", label(p.wallet_details?.brand)], ["Status", label(p.status)],
                  ["Amount", cents(p.amount_money)], ["Tip", p.tip_money ? cents(p.tip_money) : ""],
                  ["Refunded", p.refunded_money ? cents(p.refunded_money) : ""],
                  ["Fee", (p.processing_fee ?? []).length ? (p.processing_fee as Json[]).map((f) => cents(f.amount_money)).join(" + ") : ""],
                  ["Buyer email", p.buyer_email_address], ["Billing address", address(p.billing_address)],
                  ["Shipping address", address(p.shipping_address)], ["Receipt #", p.receipt_number],
                  ["Note", p.note], ["Paid at", dateTime(p.created_at)], ["Payment ID", <code key="p">{p.id}</code>],
                ]} />
              );
            })}
            {o.payments.length === 0 && (raw.tenders as Json[] | undefined ?? []).map((t, i) => (
              <KV key={t.id ?? i} rows={[["Method", t.card_details?.card ? `${label(t.card_details.card.card_brand)} ••${t.card_details.card.last_4}` : label(t.type)],
                ["Amount", cents(t.amount_money)], ["Tip", t.tip_money ? cents(t.tip_money) : ""], ["Fee", t.processing_fee_money ? cents(t.processing_fee_money) : ""]]} />
            ))}
          </Section>

          {((raw.refunds ?? []).length > 0 || (raw.returns ?? []).length > 0) && (
            <Section title="Refunds & returns">
              {(raw.refunds as Json[] | undefined ?? []).map((r, i) => (
                <KV key={r.id ?? i} rows={[["Refund", cents(r.amount_money)], ["Status", label(r.status)], ["Reason", r.reason]]} />
              ))}
              {(raw.returns as Json[] | undefined ?? []).map((r, i) => (
                <KV key={r.uid ?? i} rows={[["Returned items", (r.return_line_items ?? []).map((li: Json) => `${li.name} ×${li.quantity}`).join(", ")]]} />
              ))}
            </Section>
          )}

          {(raw.note || raw.ticket_name || raw.reference_id || raw.metadata) && (
            <Section title="Notes">
              <KV rows={[["Order note", raw.note], ["Ticket", raw.ticket_name], ["Reference", raw.reference_id],
                ["Metadata", raw.metadata ? <code key="m">{JSON.stringify(raw.metadata)}</code> : ""]]} />
            </Section>
          )}

          <Section title="Everything Square sent">
            <button className="btn btn-sm" onClick={() => setShowRaw(!showRaw)}>{showRaw ? "Hide" : "Show"} full order data</button>
            {showRaw && <pre className="raw-json">{JSON.stringify({ order: raw, payments: o.payments }, null, 2)}</pre>}
          </Section>
        </div>
      )}
    </Drawer>
  );
}
