export type ChannelKind = "social" | "marketplace" | "website" | "email" | "direct" | "ads" | "other";
export type ContactStatus = "lead" | "prospect" | "customer" | "inactive";
export type StageKind = "open" | "won" | "lost";
export type PostStatus = "idea" | "draft" | "scheduled" | "published";
export type ActivityKind = "note" | "call" | "email" | "meeting" | "dm" | "task";

export interface User { id: number; email: string; name: string }

export interface Channel {
  id: number; name: string; kind: ChannelKind; platform: string; handle: string; url: string;
  followers: number; monthly_cost: number; active: boolean; notes: string; created_at: string;
  contacts?: number; open_deals?: number; won_revenue?: number; posts?: number; views?: number; engagement?: number;
}

export interface Contact {
  id: number; first_name: string; last_name: string; email: string; phone: string; company: string;
  status: ContactStatus; source_channel_id: number | null; tags: string; notes: string;
  created_at: string; updated_at: string;
}

export interface Stage { id: number; name: string; position: number; probability: number; kind: StageKind }
export interface Funnel { id: number; name: string; description: string; created_at: string; stages: Stage[] }

export interface Deal {
  id: number; title: string; value: number; status: StageKind; funnel_id: number; stage_id: number;
  contact_id: number | null; channel_id: number | null; expected_close: string | null; closed_at: string | null;
  notes: string; created_at: string; updated_at: string;
}

export interface Post {
  id: number; channel_id: number | null; title: string; body: string; status: PostStatus;
  scheduled_at: string | null; published_at: string | null; url: string;
  views: number; likes: number; comments: number; shares: number; clicks: number; created_at: string;
  external_source?: string; external_id?: string;
}

export interface Activity {
  id: number; kind: ActivityKind; summary: string; contact_id: number | null; deal_id: number | null;
  due_at: string | null; done: boolean; created_at: string; overdue?: boolean;
}

export interface Dashboard {
  kpis: {
    contacts: number; new_contacts_30d: number; customers: number; open_deals: number;
    pipeline_value: number; weighted_pipeline: number; won_revenue_30d: number; won_revenue_total: number;
    win_rate: number | null; followers: number; posts_published_30d: number; views_30d: number;
    engagement_rate_30d: number | null; monthly_channel_cost: number;
  };
  channels: { channel_id: number | null; channel: string; leads: number; won: number; pipeline: number; views: number }[];
  funnels: { id: number; name: string; total: number; conversion: number | null;
             stages: { id: number; name: string; kind: StageKind; count: number; value: number }[] }[];
  revenue_by_month: { month: string; won: number }[];
  upcoming_posts: Post[];
  open_tasks: Activity[];
}

export interface ProviderField {
  key: string; label: string; secret: boolean; required: boolean; placeholder: string; help: string;
  kind: "text" | "select"; options: string[]; default: string;
}
export interface Provider {
  key: string; name: string; platform: string; channel_kind: string; summary: string; syncs: string[];
  fields: ProviderField[]; steps: string[]; docs_url: string;
}
export interface Integration {
  id: number; provider: string; name: string; channel_id: number | null; channel_name: string | null;
  config: Record<string, string>; saved_secrets: string[]; secrets_ok: boolean; enabled: boolean;
  sync_interval_minutes: number; last_sync_at: string | null; last_status: "never" | "ok" | "error" | "running";
  last_error: string; last_result: Record<string, unknown> & { warnings?: string[] }; created_at: string;
}

export interface OrderRow {
  id: number; source: string; external_id: string; channel_id: number | null; channel_name: string | null;
  contact_id: number | null; deal_id: number | null; location_id: string; location_name: string; reference: string;
  state: string; source_name: string; customer_name: string; customer_email: string; customer_phone: string;
  currency: string; subtotal: number; discount_total: number; tax_total: number; tip_total: number;
  service_charge_total: number; total: number; refunded: number; net: number; processing_fee: number;
  item_count: number; items_summary: string; fulfillment_type: string; fulfillment_state: string;
  payment_summary: string; receipt_url: string; ordered_at: string | null; updated_at_ext: string | null;
  closed_at: string | null; synced_at: string | null;
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = any;
export interface OrderDetail extends OrderRow { raw: Json; payments: Json[] }
export interface OrderSummary { orders: number; gross: number; refunded: number; net: number; fees: number; tax: number; tips: number; average: number }
export interface OrderPage { items: OrderRow[]; total: number; summary: OrderSummary }
