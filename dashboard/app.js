const metrics = document.querySelector('#metrics');
const tasks = document.querySelector('#tasks');
const health = document.querySelector('#health');
const refresh = document.querySelector('#refresh');

function metric(label, value) {
  return `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`;
}
function fmt(seconds) {
  const s = Math.max(0, Number(seconds || 0));
  const m = Math.floor(s / 60); const r = s % 60;
  return `${String(m).padStart(2,'0')}:${String(r).padStart(2,'0')}`;
}
async function load() {
  try {
    const r = await fetch('/dashboard/summary');
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    health.textContent = 'Live'; health.className = 'status ok';
    const c = d.task_counts || {};
    metrics.innerHTML = [
      metric('Waiting / Ready', c.READY || 0),
      metric('Offered', c.OFFERED || 0),
      metric('Picking', c.PICKING || 0),
      metric('Picked', c.PICKED || 0),
      metric('Recovery', d.orders_recovery_required || 0),
      metric('Devices online', d.devices_online || 0),
    ].join('');
    tasks.innerHTML = (d.active_tasks || []).map(t => {
      const total = t.expected_units || 0;
      const picked = t.picked_units || 0;
      const pc = total ? Math.min(100, Math.round(picked * 100 / total)) : 0;
      const overdue = t.effective_elapsed_seconds > t.target_seconds && t.target_seconds > 0;
      return `<tr>
        <td>${t.task_id.slice(0,8)}</td>
        <td><span class="badge ${t.recovery_required ? 'warn' : 'good'}">${t.task_status}</span></td>
        <td><span class="bar"><i style="width:${pc}%"></i></span>${pc}%</td>
        <td>${picked}/${total}</td>
        <td><span class="badge ${overdue ? 'warn' : ''}">${fmt(t.effective_elapsed_seconds)} / ${fmt(t.target_seconds)}</span></td>
        <td>v${t.server_version}</td>
        <td>${t.recovery_required ? 'Required' : '—'}</td>
      </tr>`;
    }).join('') || `<tr><td colspan="7" class="muted">No active tasks yet.</td></tr>`;
  } catch (e) {
    health.textContent = 'Disconnected'; health.className = 'status';
    console.error(e);
  }
}
refresh.addEventListener('click', load);
load(); setInterval(load, 3000);
