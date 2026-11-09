import { useEffect, useState } from "react";
import { Period, PeriodPicker, loadPeriod, periodInfo, savePeriod, tzOffset } from "../components/Period";
import StatChartModal, { MetricKey } from "../components/StatChartModal";
import SiteVisitors from "../components/SiteVisitors";
import { CombinedByType, CombinedGroup } from "../components/ChannelData";
import { SeriesPoint, TrendChart } from "../components/TrendChart";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Badge, BarList, Empty, Stat, statusTone } from "../components/ui";
import { dateTime, money, num, pct } from "../format";
import { channelName, useCrm } from "../store/crmStore";
import { toastError } from "../store/toastStore";
import type { Dashboard } from "../types";

const shortDate = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [period, setPeriodState] = useState<Period>(loadPeriod);
  const [chart, setChart] = useState<MetricKey | null>(null);
  const [revenue, setRevenue] = useState<{ bucket: string; points: SeriesPoint[] } | null>(null);
  const channels = useCrm((s) => s.channels);
  const [combined, setCombined] = useState<CombinedGroup[]>([]);
  const info = periodInfo(period);
  const setPeriod = (p: Period) => { savePeriod(p); setPeriodState(p); };

  const load = () => {
    const q = { start: info.start, end: info.end, tz_offset: tzOffset() };
    api.get<Dashboard>("/dashboard", q).then(setData).catch(toastError);
    api.get<{ bucket: string; points: SeriesPoint[] }>("/dashboard/series/won_revenue", q).then(setRevenue).catch(() => setRevenue(null));
    api.get<{ groups: CombinedGroup[] }>("/metrics/combined", q).then((r) => setCombined(r.groups)).catch(() => setCombined([]));
  };
  useEffect(() => { load(); }, [info.start, info.end]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setInterval(load, 5 * 60000); return () => clearInterval(t); }, [info.start, info.end]); // eslint-disable-line react-hooks/exhaustive-deps

  async function completeTask(id: number) {
    await api.patch(`/activities/${id}`, { done: true }).catch(toastError);
    load();
  }

  if (!data) return <div className="muted">Loading dashboard…</div>;
  const k = data.kpis;
  const isEmpty = k.contacts === 0 && channels.length === 0;

  return (
    <div className="page">
      <header className="page-head">
        <div><h1>Dashboard</h1><p className="muted">Social reach, sales pipeline and revenue across every channel.</p></div>
        <PeriodPicker value={period} onChange={setPeriod} testId="dashboard-period" />
      </header>

      <div className="period-banner card" data-testid="dashboard-period-banner">
        Showing <strong>{info.label}</strong> <span className="muted">· {info.range}</span>
        <span className="muted small period-hint">“Open pipeline”, “Audience” and “Lifetime views” are always right now. Use “View chart” on a metric to see it over time.</span>
        {k.views_gained === null && k.views_lifetime > 0 && (
          <span className="muted small period-hint" data-testid="views-history-hint">
            Views gained per period appears once the CRM has a daily view total from before {info.short === "all time" ? "the start" : "this period started"}
            {k.views_history_since ? ` (it started saving on ${shortDate(k.views_history_since)})` : ""}. Until then the views card counts views on videos posted in this period.
          </span>
        )}
      </div>

      {isEmpty && (
        <div className="card callout">
          <strong>Your CRM is empty.</strong> Add a <Link to="/channels">channel</Link> and a <Link to="/contacts">contact</Link>,
          or load sample data from <Link to="/settings">Settings</Link> to explore every screen.
        </div>
      )}

      <section className="stats">
        <Stat label="Won revenue" period={info.short} value={money(k.won_revenue)} sub={`${k.won_deals} deals won · ${money(k.won_revenue_total)} all time`}
          onClick={() => setChart("won_revenue")} testId="stat-won_revenue" />
        <Stat label="Open pipeline" period="right now" value={money(k.pipeline_value)} sub={`${money(k.weighted_pipeline)} weighted · ${k.open_deals} deals`}
          onClick={() => setChart("open_pipeline")} testId="stat-open_pipeline" />
        <Stat label="Win rate" period={info.short} value={pct(k.win_rate)} sub={`won ÷ ${k.closed_deals} closed deals`}
          onClick={() => setChart("win_rate")} testId="stat-win_rate" />
        <Stat label="Contacts" period="total" value={num(k.contacts)} sub={`+${k.new_contacts} in ${info.short} · ${k.customers} customers`}
          onClick={() => setChart("contacts")} testId="stat-contacts" />
        <Stat label="Audience" period="right now" value={num(k.followers)} sub="followers / subscribers"
          onClick={() => setChart("audience")} testId="stat-audience" />
        {k.views_gained !== null ? (
          <Stat label="Views gained" period={info.short} value={num(k.views_gained)}
            sub={`all channels · ${num(k.views)} on ${k.posts_published} new posts`}
            onClick={() => setChart("views_gained")} testId="stat-views" />
        ) : (
          <Stat label="Views on new posts" period={info.short} value={num(k.views)}
            sub={`${k.posts_published} posts in ${info.short} · ${pct(k.engagement_rate)} engagement`}
            onClick={() => setChart("views")} testId="stat-views" />
        )}
        <Stat label="Lifetime views" period="all time" value={num(k.views_lifetime)}
          sub={k.views_history_since ? `all channels · daily history since ${shortDate(k.views_history_since)}` : "all channels · sync to fill in"}
          onClick={() => setChart("views_total")} testId="stat-views-lifetime" />
      </section>

      <CombinedByType groups={combined} periodShort={info.short} />

      <SiteVisitors start={info.start} end={info.end} label={info.label} />

      <section className="grid-2">
        <div className="card">
          <h3>Revenue by channel <span className="muted small">· {info.label}</span></h3>
          <BarList rows={data.channels.filter((c) => c.won > 0).map((c) => ({ label: c.channel, value: c.won, tone: "green" }))} format={money} />
        </div>
        <div className="card">
          <h3>New leads by source channel <span className="muted small">· {info.label}</span></h3>
          <BarList rows={data.channels.filter((c) => c.leads > 0).sort((a, b) => b.leads - a.leads)
            .map((c) => ({ label: c.channel, value: c.leads }))} />
        </div>
      </section>

      <section className="grid-2">
        <div className="card" data-testid="views-by-channel">
          <h3>{k.views_gained !== null ? "Views gained" : "Views on new posts"} by channel <span className="muted small">· {info.label}</span></h3>
          <BarList rows={data.channels.filter((c) => c.views > 0).sort((a, b) => b.views - a.views)
            .map((c) => ({ label: c.channel, value: c.views }))} format={num} />
        </div>
        <div className="card" data-testid="lifetime-views-by-channel">
          <h3>Lifetime views by channel <span className="muted small">· all time</span></h3>
          <BarList rows={data.channels.filter((c) => (c.lifetime_views ?? 0) > 0).sort((a, b) => (b.lifetime_views ?? 0) - (a.lifetime_views ?? 0))
            .map((c) => ({ label: c.channel, value: c.lifetime_views ?? 0 }))} format={num} />
        </div>
      </section>

      <section className="grid-2">
        <div className="card">
          <div className="row-between"><h3>Won revenue <span className="muted small">· {info.label}</span></h3>
            <button className="btn btn-sm" onClick={() => setChart("won_revenue")}>Full screen ↗</button></div>
          {revenue && revenue.points.some((p) => p.value) ? (
            <div className="mini-chart clickable" onClick={() => setChart("won_revenue")}>
              <TrendChart points={revenue.points} bucket={revenue.bucket} format={(n) => money(n)} yLabel="Won revenue (USD)" compact />
            </div>
          ) : <Empty title={`No won revenue in ${info.label.toLowerCase()}`} />}
        </div>
        <div className="card">
          <h3>Funnels <span className="muted small">· deals started in {info.label.toLowerCase()}</span></h3>
          {data.funnels.length === 0 && <Empty title="No funnels yet"><Link to="/pipeline">Create one</Link></Empty>}
          {data.funnels.map((f) => (
            <div key={f.id} className="funnel-mini">
              <div className="row-between"><strong>{f.name}</strong><span className="muted small">{f.total} deals · {pct(f.conversion)} won</span></div>
              <div className="funnel-steps">
                {f.stages.map((s) => (
                  <div key={s.id} className={`funnel-step step-${s.kind}`} title={`${s.name}: ${s.count} deals, ${money(s.value)}`}>
                    <span className="mono">{s.count}</span><span className="small">{s.name}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="grid-2">
        <div className="card">
          <div className="row-between"><h3>Upcoming content (14 days)</h3><Link to="/content" className="small">Calendar →</Link></div>
          {data.upcoming_posts.length === 0 ? <Empty title="Nothing scheduled" /> : (
            <ul className="list">
              {data.upcoming_posts.map((p) => (
                <li key={p.id}>
                  <div><strong>{p.title}</strong><div className="muted small">{channelName(channels, p.channel_id)} · {dateTime(p.scheduled_at)}</div></div>
                  <Badge tone={statusTone[p.status]}>{p.status}</Badge>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="card">
          <div className="row-between"><h3>Open follow-ups</h3><Link to="/tasks" className="small">All tasks →</Link></div>
          {data.open_tasks.length === 0 ? <Empty title="All caught up" /> : (
            <ul className="list">
              {data.open_tasks.map((t) => (
                <li key={t.id}>
                  <div><strong>{t.summary}</strong><div className={`small ${t.overdue ? "text-red" : "muted"}`}>{t.overdue ? "Overdue · " : "Due "}{dateTime(t.due_at)}</div></div>
                  <button className="btn btn-sm" onClick={() => completeTask(t.id)}>Done</button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
      {chart && <StatChartModal metric={chart} period={period} onClose={() => setChart(null)} />}
    </div>
  );
}
