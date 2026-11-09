export type ChannelKind = "social" | "marketplace" | "website" | "email" | "direct" | "ads" | "other";
export type ContactStatus = "lead" | "prospect" | "customer" | "inactive";
export type StageKind = "open" | "won" | "lost";
export type PostStatus = "idea" | "draft" | "scheduled" | "published";
export type ActivityKind = "note" | "call" | "email" | "meeting" | "dm" | "task";

export interface User { id: number; email: string; name: string }

export interface Channel {
  id: number; name: string; kind: ChannelKind; platform: string; handle: string; url: string;
  followers: number; monthly_cost: number; active: boolean; notes: string; created_at: string;
  contacts?: number; open_deals?: number; won_revenue?: number; posts?: number; views?: number; engagement?: number; total_views?: number;
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
    contacts: number; new_contacts: number; customers: number; open_deals: number;
    pipeline_value: number; weighted_pipeline: number; won_revenue: number; won_deals: number; won_revenue_total: number;
    win_rate: number | null; closed_deals: number; followers: number; posts_published: number; views: number;
    views_gained: number | null; views_history_since: string | null; views_lifetime: number;
    engagement_rate: number | null; monthly_channel_cost: number;
  };
  channels: { channel_id: number | null; channel: string; leads: number; won: number; pipeline: number; views: number; lifetime_views?: number }[];
  funnels: { id: number; name: string; total: number; conversion: number | null;
             stages: { id: number; name: string; kind: StageKind; count: number; value: number }[] }[];
  upcoming_posts: Post[];
  open_tasks: Activity[];
}

export interface ProviderField {
  key: string; label: string; secret: boolean; required: boolean; placeholder: string; help: string;
  kind: "text" | "select" | "json_file"; options: string[]; default: string;
}
export interface Provider {
  key: string; name: string; platform: string; channel_kind: string; summary: string; syncs: string[];
  fields: ProviderField[]; steps: string[]; docs_url: string; default_interval: number;
}
export interface Integration {
  id: number; provider: string; name: string; channel_id: number | null; channel_name: string | null;
  config: Record<string, string>; saved_secrets: string[]; secrets_ok: boolean; enabled: boolean;
  sync_interval_minutes: number; last_sync_at: string | null; next_sync_at: string | null; last_status: "never" | "ok" | "error" | "running";
  last_error: string; last_result: Record<string, unknown> & { warnings?: string[] }; created_at: string;
}

export interface VisitorSite { id: number; name: string; hostname: string; enabled: boolean }
export interface VisitorReport {
  visitors: number; visits: number; page_views: number; start: string; end: string;
  timezone: string; fetched_at: string; warnings: string[]; stale: boolean; error: string;
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

export interface EmailRow {
  id: number; account: string; gm_msgid: string; thread_id: string; direction: "in" | "out";
  from_name: string; from_email: string; to_addrs: string; cc_addrs: string; subject: string; snippet: string;
  labels: string; unread: boolean; bulk: boolean; contact_id: number | null; contact_name: string | null;
  sent_at: string | null; attachment_count: number; gmail_url: string;
}
export interface EmailDetail extends EmailRow {
  body_text: string; body_html: string; message_id: string;
  attachments: { name: string; type: string; size: number }[];
  thread: { id: number; direction: "in" | "out"; from_name: string; from_email: string; subject: string; snippet: string; sent_at: string | null }[];
}
export interface EmailPage { items: EmailRow[]; total: number }

export type PublishPlatform = "facebook" | "instagram" | "tiktok" | "youtube";
export interface PublishTargetOption {
  integration_id: number; platform: PublishPlatform; name: string; enabled: boolean; channel_id: number | null;
  channel_name: string | null; ready: boolean; note: string; account: string; public_media: boolean | null;
}
export interface MediaItem { id: number; filename: string; kind: "image" | "video"; mime: string; size: number; width: number; height: number; url: string }
export interface PublishTarget {
  id: number; platform: PublishPlatform; name: string; integration_id: number | null; options: Record<string, unknown>;
  status: "pending" | "posting" | "processing" | "posted" | "failed" | "canceled"; url: string; external_id: string;
  error: string; attempts: number; post_id: number | null; posted_at: string | null;
}
export interface PublishJob {
  id: number; title: string; text: string; link: string; status: "scheduled" | "posting" | "done" | "partial" | "failed" | "canceled";
  scheduled_at: string | null; created_at: string; finished_at: string | null; media_deleted: boolean;
  media: MediaItem[]; targets: PublishTarget[];
}

export interface ConversationRow {
  id: number; source: string; integration_id: number | null; external_id: string; contact_id: number | null;
  title: string; avatar_url: string; last_message: string; last_message_at: string | null; unread: number;
  can_reply: boolean; reply_note: string;
}
export interface ChatMessage { id: number; direction: "in" | "out"; sender_name: string; kind: string; body: string; sent_at: string | null; }
export interface MessagesStatus {
  integration_id: number; name: string; source: string; enabled: boolean; signed_in: boolean;
  status: "active" | "waiting_approval" | "error" | "not_signed_in" | "unknown";
  error: string; checked_at: string | null; activated_at: string | null; every_minutes: number;
  recheck_minutes: number | null;
}
export interface ConversationDetail extends ConversationRow { messages: ChatMessage[]; }
export interface OAuthInfo {
  name: string; signed_in: boolean; account: string; missing_scopes: string; redirect_in_link: boolean;
  saved: string; suggested: string; callback_path: string;
}
export interface TikTokCreatorInfo {
  creator_nickname?: string; creator_username?: string; creator_avatar_url?: string;
  privacy_level_options?: string[]; comment_disabled?: boolean; duet_disabled?: boolean; stitch_disabled?: boolean;
  max_video_post_duration_sec?: number;
}

export interface SchedulerLane { last_tick: string | null; running_id: number | null; running_name: string; running_seconds: number | null; ok: boolean; }
export interface SchedulerStatus { enabled: boolean; healthy: boolean; started_at: string | null; lanes: { sales: SchedulerLane; stats: SchedulerLane }; }
