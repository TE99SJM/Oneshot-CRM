import { FormEvent, ReactNode, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { DateRangePicker, Range, defaultRange } from "../components/DateRange";
import { api } from "../api/client";
import { Badge, Drawer, Empty, Stat } from "../components/ui";
import { dateTime, money2 as money, num } from "../format";
import { toastError, useToasts } from "../store/toastStore";
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
  const [store, setStore] = useState("");
  const [range, setRange] = useState<Range>(() => defaultRange());
  const { from, to } = range;
  const pickRange = (preset: string) => setRange(defaultRange(preset));
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);

  const query = useCallback(() => {
    const p: Record<string, string> = {};
    if (q.trim()) p.q = q.trim();
    if (state) p.state = state;
    if (fulfillment) p.fulfillment = fulfillment;
    if (store) p.source = store;
    if (from) p.date_from = from;
    if (to) p.date_to = to;
    return p;
  }, [q, state, fulfillment, store, from, to]);

  useEffect(() => {
    const t = setTimeout(() => {
      api.get<OrderPage>("/orders", { ...query(), limit: PAGE, offset }).then(setData).catch(toastError);
    }, 200);
    return () => clearTimeout(t);
  }, [query, offset]);
  useEffect(() => setOffset(0), [q, state, fulfillment, store, from, to]);

  const exportCsv = () => {
    const qs = new URLSearchParams(query()).toString();
    api.download(`/orders/export.csv${qs ? `?${qs}` : ""}`, "orders.csv").catch(toastError);
  };

  const s = data?.summary;
  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Orders</h1><p className="muted">Orders from Square, eBay and TikTok Shop with items, payment, shipping and refund details. Shows the last 30 days unless you pick another range.</p></div>
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
        <select value={store} onChange={(e) => setStore(e.target.value)} aria-label="Store" data-testid="order-store">
          <option value="">All stores</option><option value="square">Square</option><option value="ebay">eBay</option><option value="tiktok_shop">TikTok Shop</option>
        </select>
        <select value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">All statuses</option><option value="OPEN">Open</option><option value="COMPLETED">Completed</option><option value="CANCELED">Canceled</option>
        </select>
        <select value={fulfillment} onChange={(e) => setFulfillment(e.target.value)}>
          <option value="">All fulfillment</option><option value="SHIPMENT">Shipping</option><option value="PICKUP">Pickup</option>
          <option value="DELIVERY">Delivery</option><option value="DIGITAL">Digital</option>
        </select>
        <DateRangePicker value={range} onChange={setRange} testId="order-range" />
      </div>

      <div className="card table-wrap">
        {!data ? <Empty title="Loading…" /> : data.items.length === 0 ? (
          (from || to || q || state || fulfillment || store) ? (
            <Empty title="No orders match">
              Nothing in this date range or filter. Try <button className="link-btn" onClick={() => { pickRange("all"); setQ(""); setState(""); setFulfillment(""); setStore(""); }}>showing all orders</button>.
            </Empty>
          ) : (
            <Empty title="No orders yet">
              Orders appear here after you connect Square, eBay or TikTok Shop on the <Link to="/integrations">Integrations</Link> page and it syncs.
            </Empty>
          )
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

  if (o?.source === "tiktok_shop") {
    return (
      <Drawer title={<>TikTok Shop order #{o.reference} <StateBadge o={o} /></>} onClose={onClose}>
        <TikTokShopDetail o={o} showRaw={showRaw} setShowRaw={setShowRaw} onChanged={() => api.get<OrderDetail>(`/orders/${id}`).then(setO).catch(toastError)} />
      </Drawer>
    );
  }
  if (o?.source === "ebay") {
    return (
      <Drawer title={<>eBay order #{o.reference} <StateBadge o={o} /></>} onClose={onClose}>
        <EbayDetail o={o} showRaw={showRaw} setShowRaw={setShowRaw} />
      </Drawer>
    );
  }

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

const amt = (a?: Json) => (a && a.value !== undefined ? money(Math.abs(Number(a.value))) : "");
const ebayAddr = (a?: Json) => (a ? [a.addressLine1, a.addressLine2,
  [a.city, a.stateOrProvince, a.postalCode].filter(Boolean).join(" "), a.countryCode].filter(Boolean).join(", ") : "");
const TRACK: Record<string, string> = {
  USPS: "https://tools.usps.com/go/TrackConfirmAction?tLabels=", UPS: "https://www.ups.com/track?tracknum=",
  FEDEX: "https://www.fedex.com/fedextrack/?trknbr=", DHL: "https://www.dhl.com/us-en/home/tracking.html?tracking-id=",
};

function EbayDetail({ o, showRaw, setShowRaw }: { o: OrderDetail; showRaw: boolean; setShowRaw: (v: boolean) => void }) {
  const raw = o.raw ?? {};
  const ps = raw.pricingSummary ?? {};
  const pay = raw.paymentSummary ?? {};
  const buyer = raw.buyer ?? {};
  const reg = buyer.buyerRegistrationAddress ?? {};
  const items: Json[] = raw.lineItems ?? [];
  const tracking: Json[] = o.payments ?? [];
  const collected = items.flatMap((li) => (li.ebayCollectAndRemitTaxes ?? []) as Json[]);
  const collectedTotal = collected.reduce((s, t) => s + Math.abs(Number(t.amount?.value ?? 0)), 0);
  const refunds: Json[] = pay.refunds ?? [];
  const cancel = raw.cancelStatus ?? {};
  return (
    <div className="order-detail">
      <KV rows={[
        ["Placed", dateTime(o.ordered_at)], ["Shipped", o.closed_at ? dateTime(o.closed_at) : ""],
        ["Last updated", dateTime(o.updated_at_ext)], ["Marketplace", o.location_name], ["Channel", o.channel_name],
        ["Sales record #", raw.salesRecordReference], ["eBay order ID", <code key="id">{o.external_id}</code>],
        ["Payment status", label(raw.orderPaymentStatus)], ["Shipping status", label(raw.orderFulfillmentStatus)],
        ["Pipeline deal", o.deal_id ? <Link key="d" to="/pipeline">View in Pipeline</Link> : ""],
      ]} />
      <div className="row">
        <a className="btn btn-sm" href={o.receipt_url} target="_blank" rel="noreferrer">Open in eBay Seller Hub ↗</a>
      </div>

      <Section title="Buyer">
        <KV rows={[["Name", o.customer_name], ["eBay username", buyer.username],
          ["Email", o.customer_email ? <a key="e" href={`mailto:${o.customer_email}`}>{o.customer_email}</a> : ""],
          ["Phone", o.customer_phone], ["Registered address", ebayAddr(reg.contactAddress)],
          ["Tax address", buyer.taxAddress ? [buyer.taxAddress.city, buyer.taxAddress.stateOrProvince, buyer.taxAddress.postalCode, buyer.taxAddress.countryCode].filter(Boolean).join(" ") : ""],
          ["Contact", o.contact_id ? <Link key="c" to="/contacts">View in Contacts</Link> : ""],
          ["Checkout note", raw.buyerCheckoutNotes]]} />
      </Section>

      <Section title={`Items (${num(o.item_count)})`}>
        <table className="table compact">
          <thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Price</th><th className="num">Total</th></tr></thead>
          <tbody>
            {items.map((li, i) => (
              <tr key={li.lineItemId ?? i}>
                <td>
                  <strong>{li.legacyItemId ? <a href={`https://www.ebay.com/itm/${li.legacyItemId}`} target="_blank" rel="noreferrer">{li.title}</a> : li.title}</strong>
                  {(li.variationAspects ?? []).length > 0 && <div className="muted small">{(li.variationAspects as Json[]).map((a) => `${a.name}: ${a.value}`).join(" · ")}</div>}
                  {li.sku && <div className="muted small">SKU {li.sku}</div>}
                  {(li.appliedPromotions ?? []).map((p: Json, j: number) => <div key={j} className="muted small">Promo: {p.description} −{amt(p.discountAmount)}</div>)}
                  {li.soldFormat && <div className="muted small">{label(li.soldFormat)} · {label(li.lineItemFulfillmentStatus)}</div>}
                  {li.lineItemFulfillmentInstructions?.shipByDate && <div className="muted small">Ship by {dateTime(li.lineItemFulfillmentInstructions.shipByDate)}</div>}
                  {(li.refunds ?? []).map((r: Json, j: number) => <div key={j} className="muted small">Refunded {amt(r.amount)} {r.refundDate ? `on ${dateTime(r.refundDate)}` : ""}</div>)}
                </td>
                <td className="num">{li.quantity}</td>
                <td className="num">{amt(li.lineItemCost)}</td>
                <td className="num">{amt(li.total) || amt(li.lineItemCost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Totals">
        <KV rows={[
          ["Item subtotal", amt(ps.priceSubtotal)], ["Discount", ps.priceDiscount ? `−${amt(ps.priceDiscount)}` : ""],
          ["Shipping charged", amt(ps.deliveryCost)], ["Shipping discount", ps.deliveryDiscount ? `−${amt(ps.deliveryDiscount)}` : ""],
          ["Tax you collected", Number(ps.tax?.value) ? amt(ps.tax) : ""], ["Adjustment", amt(ps.adjustment)], ["Other fees", amt(ps.fee)],
          ["Order total", <strong key="t">{money(o.total)}</strong>],
          ["Sales tax eBay collected", collectedTotal ? `${money(collectedTotal)} (paid by buyer, sent to the state by eBay)` : ""],
          ["Refunded", o.refunded ? `−${money(o.refunded)}` : ""],
          ["Net sale", <strong key="n">{money(o.net)}</strong>],
          ["eBay fees", o.processing_fee ? `−${money(o.processing_fee)}` : ""],
          ["You keep (approx.)", <strong key="k">{money(o.net - o.processing_fee)}</strong>],
          ["eBay says due to you", amt(pay.totalDueSeller)],
        ]} />
      </Section>

      <Section title="Shipping">
        {(raw.fulfillmentStartInstructions ?? []).map((fi: Json, i: number) => {
          const st = fi.shippingStep?.shipTo ?? {};
          return (
            <KV key={i} rows={[["Type", label(fi.fulfillmentInstructionsType)], ["Ship to", st.fullName], ["Company", st.companyName],
              ["Address", ebayAddr(st.contactAddress)], ["Phone", st.primaryPhone?.phoneNumber], ["Email", st.email],
              ["Service", fi.shippingStep?.shippingServiceCode], ["Carrier", fi.shippingStep?.shippingCarrierCode],
              ["Estimated delivery", fi.minEstimatedDeliveryDate ? `${dateTime(fi.minEstimatedDeliveryDate)} – ${dateTime(fi.maxEstimatedDeliveryDate)}` : ""],
              ["Shipped by eBay", fi.ebaySupportedFulfillment ? "Yes" : ""]]} />
          );
        })}
        {tracking.length === 0 ? <p className="muted small">No tracking uploaded yet.</p> : tracking.map((t, i) => {
          const base = TRACK[(t.shippingCarrierCode ?? "").toUpperCase()];
          return (
            <KV key={t.fulfillmentId ?? i} rows={[
              ["Carrier", t.shippingCarrierCode], ["Tracking #", base ? <a key="t" href={base + t.shipmentTrackingNumber} target="_blank" rel="noreferrer">{t.shipmentTrackingNumber}</a> : t.shipmentTrackingNumber],
              ["Shipped", t.shippedDate ? dateTime(t.shippedDate) : ""]]} />
          );
        })}
      </Section>

      <Section title="Payment">
        {(pay.payments ?? []).length === 0 && <p className="muted small">No payment details recorded.</p>}
        {(pay.payments as Json[] | undefined ?? []).map((p, i) => (
          <KV key={p.paymentReferenceId ?? i} rows={[["Method", p.paymentMethod === "EBAY" ? "eBay managed payments" : label(p.paymentMethod)],
            ["Status", label(p.paymentStatus)], ["Amount", amt(p.amount)], ["Paid at", p.paymentDate ? dateTime(p.paymentDate) : ""],
            ["Holds", (p.paymentHolds ?? []).map((h: Json) => `${label(h.holdState)} ${amt(h.holdAmount)} ${h.holdReason ?? ""}`).join("; ")],
            ["Reference", p.paymentReferenceId]]} />
        ))}
      </Section>

      {(refunds.length > 0 || (cancel.cancelState && cancel.cancelState !== "NONE_REQUESTED")) && (
        <Section title="Refunds & cancellation">
          {refunds.map((r, i) => <KV key={r.refundId ?? i} rows={[["Refund", amt(r.amount)], ["Status", label(r.refundStatus)],
            ["Date", r.refundDate ? dateTime(r.refundDate) : ""], ["Reference", r.refundReferenceId]]} />)}
          {cancel.cancelState && cancel.cancelState !== "NONE_REQUESTED" && (
            <KV rows={[["Cancellation", label(cancel.cancelState)],
              ...((cancel.cancelRequests ?? []) as Json[]).map((c): [string, ReactNode] => [`Requested by ${label(c.cancelInitiator)}`, `${c.cancelReason ?? ""} ${c.cancelRequestedDate ? dateTime(c.cancelRequestedDate) : ""}`])]} />
          )}
        </Section>
      )}

      <Section title="Everything eBay sent">
        <button className="btn btn-sm" onClick={() => setShowRaw(!showRaw)}>{showRaw ? "Hide" : "Show"} full order data</button>
        {showRaw && <pre className="raw-json">{JSON.stringify({ order: raw, shipping_fulfillments: tracking }, null, 2)}</pre>}
      </Section>
    </div>
  );
}

const ttMoney = (v: unknown) => (v === undefined || v === null || v === "" ? "" : money(Number(v)));
const ttAddr = (a?: Json) => (a ? (a.full_address as string) || [a.address_line1, a.address_line2, a.address_detail,
  ...((a.district_info ?? []) as Json[]).map((d) => d.address_name).reverse(), a.postal_code].filter(Boolean).join(", ") : "");
const trackLink = (provider: string, tn: string) => {
  const key = Object.keys(TRACK).find((k) => provider.toUpperCase().replace(/\s/g, "").includes(k));
  return key ? <a href={`${TRACK[key]}${encodeURIComponent(tn)}`} target="_blank" rel="noreferrer">{tn}</a> : tn;
};

function TikTokShopDetail({ o, showRaw, setShowRaw, onChanged }: { o: OrderDetail; showRaw: boolean; setShowRaw: (v: boolean) => void; onChanged: () => void }) {
  const raw = o.raw ?? {};
  const pay = raw.payment ?? {};
  const addr = raw.recipient_address ?? {};
  const lines: Json[] = raw.line_items ?? [];
  const tracking: Json[] = o.payments ?? [];
  const sellerShips = raw.shipping_type !== "TIKTOK" && raw.fulfillment_type !== "FULFILLMENT_BY_TIKTOK";
  const canShip = sellerShips && ["AWAITING_SHIPMENT", "PARTIALLY_SHIPPING"].includes(raw.status);
  // group identical SKUs (TikTok lists one line per unit)
  const grouped = Object.values(lines.reduce((acc: Record<string, Json>, li) => {
    const k = `${li.sku_id ?? li.product_name}-${li.sku_name ?? ""}`;
    acc[k] = acc[k] ? { ...acc[k], qty: acc[k].qty + 1 } : { ...li, qty: 1 };
    return acc;
  }, {}));
  return (
    <div className="order-detail">
      <KV rows={[
        ["Placed", dateTime(o.ordered_at)], ["Shipped", o.closed_at ? dateTime(o.closed_at) : ""],
        ["Last updated", dateTime(o.updated_at_ext)], ["Shop", o.location_name], ["Channel", o.channel_name],
        ["Status", label(raw.status)], ["Ships by", raw.shipping_type === "TIKTOK" ? "TikTok shipping label" : "You (seller shipping)"],
        ["Delivery", raw.delivery_option_name], ["TikTok order ID", <code key="id">{o.external_id}</code>],
        ["Pipeline deal", o.deal_id ? <Link key="d" to="/pipeline">View in Pipeline</Link> : ""],
      ]} />
      {o.receipt_url && <a className="btn btn-sm" href={o.receipt_url} target="_blank" rel="noreferrer">Open in TikTok Seller Center ↗</a>}

      <Section title="Buyer">
        <KV rows={[["Name", o.customer_name], ["Email", o.customer_email ? `${o.customer_email} (TikTok relay address)` : ""],
          ["Phone", o.customer_phone], ["Buyer note", raw.buyer_message],
          ["Contact", o.contact_id ? <Link key="c" to={`/contacts?open=${o.contact_id}`}>Open contact</Link> : ""]]} />
      </Section>

      <Section title={`Items (${num(lines.length)})`}>
        <table className="table compact">
          <thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Price</th><th className="num">Total</th></tr></thead>
          <tbody>
            {grouped.map((li, i) => (
              <tr key={li.id ?? i}>
                <td>
                  <div className="row-tight">
                    {li.sku_image && <img className="item-thumb" src={li.sku_image} alt="" />}
                    <div>
                      <strong>{li.product_name}</strong>
                      <div className="muted small">{[li.sku_name && li.sku_name !== "Default" ? li.sku_name : "", li.seller_sku ? `SKU ${li.seller_sku}` : "", label(li.display_status)].filter(Boolean).join(" · ")}</div>
                    </div>
                  </div>
                </td>
                <td className="num">{li.qty}</td>
                <td className="num">{ttMoney(li.sale_price)}</td>
                <td className="num">{li.sale_price !== undefined ? money(Number(li.sale_price) * li.qty) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Payment">
        <KV rows={[["Products", ttMoney(pay.original_total_product_price ?? pay.sub_total)],
          ["Seller discount", pay.seller_discount && Number(pay.seller_discount) ? `−${ttMoney(pay.seller_discount)}` : ""],
          ["TikTok discount", pay.platform_discount && Number(pay.platform_discount) ? `−${ttMoney(pay.platform_discount)} (TikTok pays this)` : ""],
          ["Shipping", ttMoney(pay.shipping_fee)], ["Tax", ttMoney(pay.tax)],
          ["Buyer paid", <strong key="t">{ttMoney(pay.total_amount)}</strong>], ["Method", raw.payment_method_name],
          ["Paid", raw.paid_time ? dateTime(new Date(Number(raw.paid_time) * 1000).toISOString()) : ""]]} />
        <p className="muted small">TikTok fees and payouts are in Seller Center → Finance.</p>
      </Section>

      <Section title="Shipping">
        <KV rows={[["Ship to", addr.name], ["Address", ttAddr(addr)], ["Phone", addr.phone_number]]} />
        {tracking.length > 0 && (
          <KV rows={tracking.map((t, i): [string, ReactNode] => [`Package ${i + 1}${t.provider ? ` (${t.provider})` : ""}`, trackLink(String(t.provider ?? ""), String(t.tracking_number))])} />
        )}
        {canShip ? <MarkShipped o={o} onDone={onChanged} />
          : sellerShips ? null : <p className="muted small">TikTok ships this order with its own label; print it in Seller Center.</p>}
      </Section>

      <Section title="Everything TikTok Shop sent">
        <button className="btn btn-sm" onClick={() => setShowRaw(!showRaw)}>{showRaw ? "Hide" : "Show"} full order data</button>
        {showRaw && <pre className="raw-json">{JSON.stringify(raw, null, 2)}</pre>}
      </Section>
    </div>
  );
}

function MarkShipped({ o, onDone }: { o: OrderDetail; onDone: () => void }) {
  const [providers, setProviders] = useState<{ id: string; name: string }[] | null>(null);
  const [provider, setProvider] = useState("");
  const [tracking, setTracking] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const push = useToasts((s) => s.push);
  useEffect(() => {
    api.get<{ id: string; name: string }[]>(`/orders/${o.id}/shipping-providers`).then(setProviders)
      .catch((e) => { setProviders([]); setErr(e instanceof Error ? e.message : String(e)); });
  }, [o.id]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post<{ warning?: string }>(`/orders/${o.id}/ship`, { tracking_number: tracking.trim(), shipping_provider_id: provider });
      push(r.warning || "Marked as shipped in TikTok Shop.", "success");
      onDone();
    } catch (e2) { toastError(e2); } finally { setBusy(false); }
  };
  return (
    <form className="ship-form" onSubmit={submit} data-testid="tts-ship">
      <h4>Mark as shipped</h4>
      {err && <div className="warn-box small">{err}</div>}
      <div className="row">
        <select value={provider} onChange={(e) => setProvider(e.target.value)} required aria-label="Carrier">
          <option value="">{providers === null ? "Loading carriers…" : "Carrier…"}</option>
          {(providers ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input value={tracking} onChange={(e) => setTracking(e.target.value)} placeholder="Tracking number" required minLength={3} />
        <button className="btn btn-primary btn-sm" disabled={busy || !provider || tracking.trim().length < 3}>{busy ? "Sending…" : "Mark shipped"}</button>
      </div>
      <p className="muted small">Sends the tracking number to TikTok Shop and updates the buyer. Ship within your handling time to avoid late-shipment marks.</p>
    </form>
  );
}
