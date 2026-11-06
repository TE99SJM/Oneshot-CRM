import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Badge, BarList, Empty, Stat, statusTone } from "../components/ui";
import { dateTime, money, num, pct } from "../format";
import { channelName, useCrm } from "../store/crmStore";
import { toastError } from "../store/toastStore";
import type { Dashboard } from "../types";

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const channels = useCrm((s) => s.channels);

  const load = () => api.get<Dashboard>("/dashboard").then(setData).catch(toastError);
  useEffect(() => { load(); }, []);

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
      </header>

      {isEmpty && (
        <div className="card callout">
          <strong>Your CRM is empty.</strong> Add a <Link to="/channels">channel</Link> and a <Link to="/contacts">contact</Link>,
          or load sample data from <Link to="/settings">Settings</Link> to explore every screen.
        </div>
      )}

      <section className="stats">
        <Stat label="Won revenue (30d)" value={money(k.won_revenue_30d)} sub={`${money(k.won_revenue_total)} all time`} />
        <Stat label="Open pipeline" value={money(k.pipeline_value)} sub={`${money(k.weighted_pipeline)} weighted · ${k.open_deals} deals`} />
        <Stat label="Win rate" value={pct(k.win_rate)} sub="won ÷ closed deals" />
        <Stat label="Contacts" value={num(k.contacts)} sub={`+${k.new_contacts_30d} in 30d · ${k.customers} customers`} />
        <Stat label="Audience" value={num(k.followers)} sub="followers / subscribers" />
        <Stat label="Views (30d)" value={num(k.views_30d)} sub={`${k.posts_published_30d} posts · ${pct(k.engagement_rate_30d)} engagement`} />
      </section>

      <section className="grid-2">
        <div className="card">
          <h3>Revenue by channel</h3>
          <BarList rows={data.channels.filter((c) => c.won > 0).map((c) => ({ label: c.channel, value: c.won, tone: "green" }))} format={money} />
        </div>
        <div className="card">
          <h3>Leads by source channel</h3>
          <BarList rows={data.channels.filter((c) => c.leads > 0).sort((a, b) => b.leads - a.leads)
            .map((c) => ({ label: c.channel, value: c.leads }))} />
        </div>
      </section>

      <section className="grid-2">
        <div className="card">
          <h3>Won revenue, last 6 months</h3>
          <div className="columns">
            {data.revenue_by_month.map((m) => {
              const max = Math.max(1, ...data.revenue_by_month.map((x) => x.won));
              return (
                <div key={m.month} className="column" title={money(m.won)}>
                  <div className="column-val mono">{m.won ? money(m.won) : ""}</div>
                  <div className="column-bar" style={{ height: `${(m.won / max) * 100}%` }} />
                  <div className="column-label">{new Date(`${m.month}-15`).toLocaleDateString(undefined, { month: "short" })}</div>
                </div>
              );
            })}
          </div>
        </div>
        <div className="card">
          <h3>Funnels</h3>
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
    </div>
  );
}
