import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { dateTime, num } from "../format";
import type { VisitorReport, VisitorSite } from "../types";
import { Badge } from "./ui";

export default function SiteVisitors({ start, end, label }: { start: string; end: string; label: string }) {
  const [sites, setSites] = useState<VisitorSite[] | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    api.get<VisitorSite[]>("/dashboard/site-visitors")
      .then((data) => { if (active) setSites(data); })
      .catch(() => { if (active) setError("Could not load your site connections."); });
    return () => { active = false; };
  }, [retry]);

  return (
    <section className="site-visitors" aria-labelledby="site-visitor-heading" data-testid="site-visitors">
      <div className="row-between site-visitor-heading">
        <div><h2 id="site-visitor-heading">Site Visitor</h2><p className="muted small">{label} · Visitors to each website</p></div>
        <Link className="btn btn-sm" to="/integrations?provider=google_analytics">+ Connect site</Link>
      </div>
      {error ? <div className="card" role="alert">{error} <button className="btn btn-sm" onClick={() => setRetry((n) => n + 1)}>Retry</button></div>
        : sites === null ? <div className="card muted" role="status">Loading sites…</div>
        : sites.length === 0 ? <div className="card site-visitor-empty">
          <strong>See visitors for both of your sites here</strong>
          <p className="muted">Connect Google Analytics for each website to see its visitors, visits and page views.</p>
          <Link className="btn btn-primary" to="/integrations?provider=google_analytics">Connect your first site</Link>
        </div>
        : <div className="grid-2">{sites.map((site) =>
          <SiteCard key={`${site.id}:${site.hostname}:${start}:${end}`} site={site} start={start} end={end} />
        )}</div>}
      {sites && sites.length > 0 && <p className="muted small">Google Analytics visitor counts are unique within each site and period. Dates use each property's time zone; recent traffic may still be processing.</p>}
    </section>
  );
}

function SiteCard({ site, start, end }: { site: VisitorSite; start: string; end: string }) {
  const [report, setReport] = useState<VisitorReport | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(site.enabled);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!site.enabled) return;
    let active = true;
    setLoading(true); setError("");
    api.get<VisitorReport>(`/dashboard/site-visitors/${site.id}`, { start, end, refresh: refresh > 0 })
      .then((data) => { if (active) setReport(data); })
      .catch((err) => { if (active) setError(err instanceof Error ? err.message : "Could not load visitor data."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [site.id, site.enabled, start, end, refresh]);

  return (
    <article className="card site-visitor-card" data-testid={`site-visitors-${site.id}`}>
      <div className="row-between">
        <div><h3>{site.name}</h3><span className="muted small">{site.hostname}</span></div>
        <Badge tone={!site.enabled ? "neutral" : error || report?.stale ? "amber" : "green"}>{!site.enabled ? "Paused" : report?.stale ? "Last available data" : "Google Analytics"}</Badge>
      </div>
      {!site.enabled ? <p className="muted">Enable this site's connection to see visitors.</p>
        : loading && !report ? <p className="muted" role="status">Loading visitors…</p>
        : report ? <>
          <div className="site-visitor-total"><strong>{num(report.visitors)}</strong><span className="muted">visitors</span></div>
          <div className="site-visitor-metrics"><span><strong>{num(report.visits)}</strong> visits</span><span><strong>{num(report.page_views)}</strong> page views</span></div>
          {report.visitors === 0 && <p className="muted small">No visitors reported for this domain in the selected period. If traffic is expected, check your site's Google tag.</p>}
          {report.warnings.map((warning) => <p className="small text-amber" key={warning}>{warning}</p>)}
          <p className="muted small">Updated {dateTime(report.fetched_at)}{report.timezone && ` · ${report.timezone}`}</p>
        </> : null}
      {(error || report?.error) && <p className="text-red small" role="alert">{error || report?.error}</p>}
      <div className="row-between">
        <Link className="small" to={`/integrations?edit=${site.id}`}>Manage connection</Link>
        {site.enabled && <button className="btn btn-sm" disabled={loading} onClick={() => setRefresh((n) => n + 1)}>{loading ? "Updating…" : "Refresh"}</button>}
      </div>
    </article>
  );
}
