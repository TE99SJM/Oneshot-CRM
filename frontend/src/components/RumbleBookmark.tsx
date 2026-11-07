import { useEffect, useRef } from "react";

/** Bookmarklet that runs on rumble.com in YOUR browser (so Rumble's anti-bot check never sees the server),
 *  reads views/likes/comments from your channel's Videos pages, then opens the CRM to import them. */
export function rumbleBookmarkCode(crmOrigin: string, maxPages = 50): string {
  const code = `(async()=>{const C=${JSON.stringify(crmOrigin)};
if(!/(^|\\.)rumble\\.com$/.test(location.hostname)){alert('Open your Rumble channel page first (rumble.com/c/YourChannel), then click this bookmark.');return}
const m=location.pathname.match(/^\\/(c|user)\\/([^/?#]+)/);if(!m){alert('Open your Rumble channel page (rumble.com/c/YourChannel) first, then click this bookmark.');return}
const base=location.origin+'/'+m[1]+'/'+m[2];const out=[];let fol=null;
const grab=h=>{let n=0;const re=/<rum-videos-grid[^>]*>\\s*<script type="application\\/json">([\\s\\S]*?)<\\/script>/g;let x;
while((x=re.exec(h))){try{(JSON.parse(x[1]).items||[]).forEach(it=>{if(it.object_type&&it.object_type!=='video')return;n++;
if(fol==null&&it.by&&typeof it.by.followers==='number')fol=it.by.followers;
out.push({permalink_id:it.permalink_id,url:it.url,title:it.title,upload_date:it.upload_date||it.live_streamed_on,
views:typeof it.views==='number'?it.views:(it.video_stats||{}).rumble_plays,likes:(it.rumble_votes||{}).num_votes_up,comments:(it.comments||{}).count})})}catch(e){}}return n};
const t=document.title;for(let p=1;p<=${maxPages};p++){document.title='Reading Rumble videos page '+p+'...';
const r=await fetch(base+'/videos'+(p>1?'?page='+p:''),{credentials:'include'});if(!r.ok)break;const h=await r.text();
if(!grab(h))break;if(h.indexOf('page='+(p+1))<0)break}document.title=t;
if(!out.length){alert('No videos found. Open your channel page on rumble.com and try again.');return}
location.href=C+'/integrations?rumble_import=1#d='+encodeURIComponent(JSON.stringify({channel_url:base,followers:fol,videos:out}))})()`;
  return "javascript:" + encodeURIComponent(code.replace(/\n/g, ""));
}

/** React refuses to render javascript: links directly, so the href is set on the element itself. */
export function BookmarkLink({ href, children }: { href: string; children: React.ReactNode }) {
  const ref = useRef<HTMLAnchorElement>(null);
  useEffect(() => { ref.current?.setAttribute("href", href); }, [href]);
  return (
    <a ref={ref} className="btn btn-primary bookmarklet" data-testid="rumble-bookmark" draggable
      onClick={(e) => { e.preventDefault(); alert("Drag this button onto your bookmarks bar instead of clicking it here. Then click the bookmark while you're on your Rumble channel page."); }}>
      {children}
    </a>
  );
}
