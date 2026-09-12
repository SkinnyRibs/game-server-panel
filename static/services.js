'use strict';

async function monitorV2(){
  overview=await api('/overview');
  if(view!=='Monitor')return;
  const h=overview.health;
  $('#surface').innerHTML=heading(h?'Host overview':'Health overview','Live host health and active issues. Service inventory has moved to its own workspace.',`<div class="live">● &nbsp; UPDATED ${new Date(overview.sampled_at*1000).toLocaleTimeString()}</div>`)+(h?`<div class="grid">${metric('CPU utilization',h.cpu_percent.toFixed(1),'%',h.cpu_percent,h.cpu_count+' logical cores · load '+h.load[0].toFixed(2))}${metric('Memory',h.memory.percent.toFixed(1),'%',h.memory.percent,bytes(h.memory.used)+' of '+bytes(h.memory.total))}${metric('Root disk',h.disk.percent.toFixed(1),'%',h.disk.percent,bytes(h.disk.free)+' available')}${metric('Host uptime',duration(h.uptime),'',null,'Swap '+bytes(h.swap.used)+' / '+bytes(h.swap.total))}</div><div class="columns"><article class="card"><div class="section-title"><h2>Host activity</h2><small>Cumulative since boot</small></div><div class="kv"><span>Network received / sent</span><strong>${bytes(h.network.received)} / ${bytes(h.network.sent)}</strong></div><div class="kv"><span>Disk read / written</span><strong>${bytes(h.io?.read)} / ${bytes(h.io?.write)}</strong></div><div class="kv"><span>Load · 1 / 5 / 15 min</span><strong>${h.load.map(value=>value.toFixed(2)).join(' / ')}</strong></div></article><article class="card"><div class="section-title"><h2>Attention</h2><small>${overview.issues.length} issues</small></div>${overview.issues.length?overview.issues.map(issue=>`<div class="issue">${e(issue)}</div>`).join(''):'<div class="issue ok">● All monitored services match their expected state.</div>'}</article></div>`:'<article class="card empty">Host metrics are available to administrators only.</article>');
}

async function servicesV2(){
  overview=await api('/overview');
  if(view!=='Services')return;
  const roots=Object.values(catalog.roots);
  const visibleIds=new Set(overview.servers.map(service=>service.id));
  const fileOnlyIds=[...new Set(roots.map(root=>root.server))].filter(id=>!visibleIds.has(id));
  const services=[...overview.servers,...fileOnlyIds.map(id=>({id,label:catalog.servers[id]?.label||id,permissions:me.grants[id]||{},fileOnly:true}))];
  $('#surface').innerHTML=heading('Services','Live container state and permitted controls. Select a game service to open its approved persistent file tree.',`<div class="live">● &nbsp; UPDATED ${new Date(overview.sampled_at*1000).toLocaleTimeString()}</div>`)+`<div class="table-wrap"><table class="services-table"><thead><tr><th>Service</th><th>State</th><th>Availability</th><th>Controls</th></tr></thead><tbody>${services.map(service=>{
    const hasFiles=roots.some(root=>root.server===service.id);
    const serviceCell=hasFiles?`<button class="service-link" data-service-files="${e(service.id)}" aria-label="Open files for ${e(service.label)}"><span>${e(service.label)}</span><small>Open persistent file tree</small></button>`:`<div class="service-static"><span>${e(service.label)}</span><small>${service.readonly?'Infrastructure · no file root':'No approved file root'}</small></div>`;
    const stateCell=service.fileOnly?'<span class="muted">—</span>':`<span class="badge ${e(service.state)}">${e(service.state)}</span>`;
    const availability=service.fileOnly?'<span>Status hidden</span>':`${e(service.status)}<span class="muted">Expected: ${e(service.expected)}</span>`;
    return `<tr><td data-label="Service">${serviceCell}</td><td data-label="State">${stateCell}</td><td data-label="Availability">${availability}</td><td data-label="Controls"><div class="actions">${controls(service.id,service.label,service.permissions)}</div></td></tr>`;
  }).join('')}</tbody></table>${services.length?'':'<div class="empty">No service or file access has been granted to this account.</div>'}</div>${controlOnly()}`;
  bind('[data-service-files]',async element=>{
    fileServer=element.dataset.serviceFiles;fileAlias='';filePath='';fileTreeCache.clear();fileTreeOpen.clear();view='Files';shell();await render();
  });
  bindControls();
}
