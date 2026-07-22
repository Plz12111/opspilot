const state = {
  incidents: [], selectedId: null, workspace: null, filter: 'all', eventSource: null,
  evaluation: null, currentView: 'incidents'
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed (${response.status})`);
  }
  return response.status === 204 ? null : response.json();
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[character]);
}

function formatTime(value) {
  if (!value) return '-';
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'
  }).format(new Date(value));
}

function badge(value) {
  return `<span class="badge ${escapeHtml(value)}">${escapeHtml(value)}</span>`;
}

function icons() {
  if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.8 } });
}

function toast(message) {
  const element = $('#toast');
  element.textContent = message;
  element.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { element.hidden = true; }, 2800);
}

async function loadSummary() {
  const summary = await api('/api/v1/dashboard/summary');
  $('#metric-active').textContent = summary.active_incidents;
  $('#metric-human').textContent = summary.needs_human;
  $('#metric-approvals').textContent = summary.pending_approvals;
  $('#metric-runbooks').textContent = summary.runbook_documents;
}

function percent(value) { return `${(Number(value) * 100).toFixed(1)}%`; }

async function loadEvaluation() {
  if (!state.evaluation) state.evaluation = await api('/api/v1/evaluations/latest');
  renderEvaluation();
}

function renderEvaluation() {
  const report = state.evaluation;
  const baseline = report.baseline.metrics;
  const candidate = report.candidate.metrics;
  $('#evaluation-status').innerHTML = `${badge(report.candidate.passed ? 'PASS' : 'FAIL')}<span class="badge">${candidate.case_count} cases</span><span class="badge">${report.stability.repetitions} runs</span>`;
  $('#evaluation-metrics').innerHTML = [
    ['Top-1 accuracy', percent(candidate.top1_accuracy), `${report.top1_delta >= 0 ? '+' : ''}${percent(report.top1_delta)} vs v1`],
    ['Top-3 recall', percent(candidate.top3_recall), `${report.top3_delta >= 0 ? '+' : ''}${percent(report.top3_delta)} vs v1`],
    ['Citation validity', percent(candidate.citation_validity), `${percent(candidate.critical_evidence_recall)} critical evidence`],
    ['Prediction stability', percent(report.stability.top1_agreement), `${report.stability.repetitions} deterministic runs`]
  ].map(([label, value, note]) => `<div class="evaluation-metric"><span>${label}</span><strong>${value}</strong><small>${note}</small></div>`).join('');
  $('#dataset-digest').textContent = `Dataset ${report.dataset_digest.slice(0, 12)}`;
  const rows = [
    ['Top-1 accuracy', baseline.top1_accuracy, candidate.top1_accuracy],
    ['Top-3 recall', baseline.top3_recall, candidate.top3_recall],
    ['Tool success', baseline.tool_success_rate, candidate.tool_success_rate],
    ['Citation validity', baseline.citation_validity, candidate.citation_validity]
  ];
  $('#comparison-chart').innerHTML = rows.map(([label, before, after]) => `<div class="comparison-row"><strong>${label}</strong><div class="comparison-bars"><div class="comparison-track"><div class="comparison-fill" style="width:${before * 100}%"></div></div><div class="comparison-track"><div class="comparison-fill candidate" style="width:${after * 100}%"></div></div><span class="comparison-values">v1 ${percent(before)} · v2 ${percent(after)}</span></div><span class="comparison-delta">${after - before >= 0 ? '+' : ''}${percent(after - before)}</span></div>`).join('');
  const cases = report.candidate.cases;
  const passed = cases.filter((item) => item.top1_correct).length;
  $('#case-summary').textContent = `${passed} Top-1 pass · ${cases.length - passed} needs analysis`;
  $('#case-grid').innerHTML = cases.map((item, index) => `<button type="button" class="case-cell ${item.top1_correct ? '' : 'failed'}" aria-label="${escapeHtml(item.case_id)}: ${item.top1_correct ? 'Top-1 pass' : 'Top-1 fail'}" data-tooltip="${escapeHtml(item.case_id)} · ${escapeHtml(item.predicted_root_causes[0] || 'undetermined')}">${String(index + 1).padStart(2, '0')}</button>`).join('');
  $('#experiment-facts').innerHTML = [
    ['Candidate', report.candidate.baseline_name],
    ['Average input', `${candidate.average_input_tokens.toFixed(1)} tokens`],
    ['Estimated suite cost', `$${candidate.estimated_suite_cost_usd.toFixed(6)}`],
    ['Cost delta', `$${report.cost_delta_usd.toFixed(6)}`],
    ['P95 local latency', `${candidate.p95_latency_ms} ms`],
    ['Prohibited actions', percent(candidate.prohibited_action_rate)]
  ].map(([label, value]) => `<div class="experiment-fact"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`).join('');
  icons();
}

async function switchView(name) {
  state.currentView = name;
  $$('.view-switch').forEach((button) => {
    const active = button.dataset.view === name;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  $('#incident-metrics').hidden = name !== 'incidents';
  $('#incident-workspace').hidden = name !== 'incidents';
  $('#evaluation-view').hidden = name !== 'evaluation';
  if (name === 'evaluation') {
    closeRunEvents();
    try { await loadEvaluation(); } catch (error) { toast(error.message); }
  } else connectLatestRun();
}

function filteredIncidents() {
  const terminal = new Set(['RESOLVED', 'CLOSED', 'CANCELLED']);
  if (state.filter === 'all') return state.incidents;
  if (state.filter === 'active') return state.incidents.filter((item) => !terminal.has(item.status));
  return state.incidents.filter((item) => item.status === state.filter);
}

function renderIncidents() {
  const incidents = filteredIncidents();
  $('#incident-count').textContent = `${incidents.length} items`;
  $('#incident-list').innerHTML = incidents.length ? incidents.map((incident) => `
    <button class="incident-row ${incident.id === state.selectedId ? 'selected' : ''}" data-incident-id="${escapeHtml(incident.id)}" type="button">
      <div class="incident-row-top">${badge(incident.severity)}${badge(incident.status)}</div>
      <strong>${escapeHtml(incident.title)}</strong>
      <div class="incident-row-bottom"><span>${escapeHtml(incident.service)} · ${escapeHtml(incident.environment)}</span><span>${formatTime(incident.started_at)}</span></div>
    </button>
  `).join('') : '<div class="side-empty">没有符合筛选条件的 Incident</div>';
  $$('.incident-row').forEach((row) => row.addEventListener('click', () => selectIncident(row.dataset.incidentId)));
}

async function loadIncidents() {
  state.incidents = await api('/api/v1/incidents?limit=100');
  renderIncidents();
  if (!state.selectedId && state.incidents.length) {
    const requested = new URLSearchParams(window.location.search).get('incident');
    const selected = state.incidents.some((item) => item.id === requested) ? requested : state.incidents[0].id;
    await selectIncident(selected);
  }
}

async function selectIncident(id) {
  if (id !== state.selectedId) closeRunEvents();
  state.selectedId = id;
  const url = new URL(window.location.href);
  url.searchParams.set('incident', id);
  window.history.replaceState({}, '', url);
  renderIncidents();
  $('#empty-state').hidden = true;
  $('#incident-detail').hidden = false;
  state.workspace = await api(`/api/v1/incidents/${encodeURIComponent(id)}/workspace`);
  renderWorkspace();
  connectLatestRun();
}

function renderWorkspace() {
  const { incident, runs, tool_calls: calls, run_events: events, evidence, actions } = state.workspace;
  $('#incident-id').textContent = incident.id;
  $('#incident-title').textContent = incident.title;
  $('#incident-meta').innerHTML = `${badge(incident.severity)}${badge(incident.status)}<span>${escapeHtml(incident.service)}</span><span>${escapeHtml(incident.environment)}</span><span>Started ${formatTime(incident.started_at)}</span>`;
  $('#action-service').value = incident.service;
  $('#evidence-count').textContent = evidence.length;
  renderDiagnosis(runs[0]);
  renderTimeline(runs, calls, events || []);
  renderEvidence(evidence);
  renderActions(actions);
  const activeRun = runs[0] && ['PENDING', 'RUNNING'].includes(runs[0].status);
  $('#run-investigation').disabled = Boolean(activeRun);
  icons();
}

function renderDiagnosis(run) {
  const band = $('#diagnosis-band');
  if (!run) {
    band.innerHTML = '<strong>尚未运行调查</strong><p>启动调查后，这里会显示证据约束的诊断摘要。</p>';
    $('#run-status').textContent = 'No run';
    return;
  }
  const diagnosis = run.diagnosis || {};
  const active = ['PENDING', 'RUNNING'].includes(run.status);
  band.innerHTML = `<div class="diagnosis-meta">${badge(run.status)}${active ? '<span class="live-indicator"><i></i> LIVE</span>' : `<span class="badge">Confidence ${Number(diagnosis.confidence || 0).toFixed(2)}</span><span class="badge">${(diagnosis.evidence_ids || []).length} citations</span>`}</div><strong>${active ? 'Investigation in progress' : 'Latest diagnosis'}</strong><p>${escapeHtml(diagnosis.summary || run.error || (active ? 'Collecting evidence and evaluating the investigation plan.' : 'No diagnosis'))}</p>`;
  $('#run-status').textContent = `${run.steps_used}/${run.step_budget} steps · ${formatTime(run.ended_at || run.started_at || run.created_at)}`;
}

function eventPresentation(event) {
  const payload = event.payload || {};
  const presentations = {
    'run.queued': ['clock-3', 'Investigation queued', `${payload.step_budget || '-'} step budget`],
    'run.started': ['play', 'Investigation started', `Execution attempt ${payload.attempt || 1}`],
    'plan.created': ['list-checks', 'Plan created', `${(payload.steps || []).length} observation steps`],
    'tool.started': ['loader-circle', payload.tool_name || 'Tool started', `Step ${payload.step || '-'}`],
    'tool.completed': [payload.status === 'SUCCESS' ? 'check' : 'triangle-alert', payload.tool_name || 'Tool completed', payload.error || `${payload.latency_ms || 0} ms · ${payload.evidence_count || 0} evidence`],
    'synthesis.completed': ['brain-circuit', 'Diagnosis synthesized', `Confidence ${Number(payload.confidence || 0).toFixed(2)}`],
    'run.completed': ['circle-check-big', 'Investigation completed', `${payload.steps_used || 0} steps · ${payload.evidence_count || 0} evidence`],
    'run.failed': ['circle-x', 'Investigation failed', payload.error || 'Unknown error']
  };
  return presentations[event.event_type] || ['activity', event.event_type, 'Progress event'];
}

function renderTimeline(runs, calls, events) {
  const latest = runs[0];
  if (!latest) {
    $('#timeline').innerHTML = '<div class="side-empty">No investigation timeline</div>';
    return;
  }
  const runEvents = events.filter((event) => event.run_id === latest.id).sort((a, b) => a.sequence - b.sequence);
  if (runEvents.length) {
    $('#timeline').innerHTML = runEvents.map((event) => {
      const [icon, title, detail] = eventPresentation(event);
      return `<div class="timeline-item">
        <span class="timeline-icon ${event.event_type === 'tool.started' ? 'running' : ''}"><i data-lucide="${icon}" aria-hidden="true"></i></span>
        <div class="timeline-copy"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>
        <span class="timeline-time">#${event.sequence} · ${formatTime(event.created_at)}</span>
      </div>`;
    }).join('');
    return;
  }
  const items = calls.filter((call) => call.run_id === latest.id);
  $('#timeline').innerHTML = items.map((call) => `
    <div class="timeline-item">
      <span class="timeline-icon"><i data-lucide="${call.status === 'SUCCESS' ? 'check' : call.status === 'TIMEOUT' ? 'clock-alert' : 'x'}" aria-hidden="true"></i></span>
      <div class="timeline-copy"><strong>${escapeHtml(call.tool_name)}</strong><span>${escapeHtml(call.error || `${call.latency_ms} ms`)}</span></div>
      <span class="timeline-time">${badge(call.status)}</span>
    </div>
  `).join('') || '<div class="side-empty">No tool calls recorded</div>';
}

function renderEvidence(evidence) {
  $('#evidence-list').innerHTML = evidence.length ? evidence.map((item) => `
    <article class="evidence-item">
      <div class="evidence-head"><div>${badge(item.source_type.toUpperCase())} <strong>${escapeHtml(item.attributes.heading || item.attributes.title || item.id)}</strong></div><span class="source-uri">${formatTime(item.collected_at)}</span></div>
      <span class="source-uri">${escapeHtml(item.source_uri)}</span>
      <pre>${escapeHtml(item.content.slice(0, 1400))}</pre>
    </article>
  `).join('') : '<div class="side-empty">No evidence collected</div>';
}

function actionButtons(action) {
  if (action.status === 'PENDING_APPROVAL') return `<button class="button primary" data-action-approve="${action.id}">批准</button><button class="button secondary" data-action-reject="${action.id}">拒绝</button>`;
  if (action.status === 'APPROVED') return `<button class="button primary" data-action-execute="${action.id}">执行</button>`;
  return '';
}

function renderActions(actions) {
  $('#action-list').innerHTML = actions.length ? actions.map((action) => `
    <article class="action-item">
      <div class="action-head"><strong>${escapeHtml(action.action_type)}</strong>${badge(action.status)}</div>
      <p>${escapeHtml(action.service)} · ${escapeHtml(action.target_environment)} · Risk ${escapeHtml(action.risk)}</p>
      <p>${escapeHtml(action.reason)}</p>
      ${action.approval ? `<p>Decision: ${escapeHtml(action.approval.approver)} · ${formatTime(action.approval.decided_at)}</p>` : ''}
      <div class="action-controls">${actionButtons(action)}</div>
    </article>
  `).join('') : '<div class="side-empty">当前 Incident 没有修复动作</div>';
  $$('[data-action-approve]').forEach((button) => button.addEventListener('click', () => decideAction(button.dataset.actionApprove, 'approve')));
  $$('[data-action-reject]').forEach((button) => button.addEventListener('click', () => decideAction(button.dataset.actionReject, 'reject')));
  $$('[data-action-execute]').forEach((button) => button.addEventListener('click', () => executeAction(button.dataset.actionExecute)));
}

async function refreshSelected() {
  if (state.selectedId) {
    state.workspace = await api(`/api/v1/incidents/${encodeURIComponent(state.selectedId)}/workspace`);
    renderWorkspace();
  }
  await Promise.all([loadSummary(), loadIncidents()]);
}

function closeRunEvents() {
  if (state.eventSource) state.eventSource.close();
  state.eventSource = null;
}

function connectLatestRun() {
  closeRunEvents();
  const run = state.workspace?.runs?.[0];
  if (!run || !['PENDING', 'RUNNING'].includes(run.status)) return;
  const known = (state.workspace.run_events || [])
    .filter((event) => event.run_id === run.id)
    .reduce((maximum, event) => Math.max(maximum, event.sequence), 0);
  const source = new EventSource(`/api/v1/runs/${encodeURIComponent(run.id)}/events?after=${known}`);
  state.eventSource = source;
  source.onmessage = async (message) => {
    const event = JSON.parse(message.data);
    if (state.workspace?.runs?.[0]?.id !== event.run_id) return;
    const events = state.workspace.run_events || (state.workspace.run_events = []);
    const index = events.findIndex((item) => item.id === event.id);
    if (index >= 0) events[index] = event;
    else events.push(event);
    const runState = state.workspace.runs[0];
    if (event.event_type === 'run.started') runState.status = 'RUNNING';
    renderWorkspace();
    if (['run.completed', 'run.failed', 'run.cancelled'].includes(event.event_type)) {
      closeRunEvents();
      await refreshSelected();
      toast(event.event_type === 'run.completed' ? 'Investigation completed' : 'Investigation stopped');
    }
  };
  source.onerror = () => {
    if (state.eventSource === source && source.readyState === EventSource.CLOSED) closeRunEvents();
  };
}

async function runInvestigation() {
  const button = $('#run-investigation');
  button.disabled = true;
  try {
    const run = await api(`/api/v1/incidents/${encodeURIComponent(state.selectedId)}/investigate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ step_budget: 6 }) });
    toast('Investigation queued');
    await refreshSelected();
    if (state.workspace?.runs?.[0]?.id === run.id) connectLatestRun();
  } catch (error) { toast(error.message); }
  finally {
    const active = state.workspace?.runs?.[0] && ['PENDING', 'RUNNING'].includes(state.workspace.runs[0].status);
    button.disabled = Boolean(active);
  }
}

async function searchRunbooks(event) {
  event.preventDefault();
  const incident = state.workspace.incident;
  const query = $('#runbook-query').value;
  try {
    const params = new URLSearchParams({ q: query, service: incident.service, environment: incident.environment, top_k: '5' });
    const hits = await api(`/api/v1/runbooks/search?${params}`);
    $('#runbook-results').innerHTML = hits.length ? hits.map((hit) => `
      <article class="runbook-item"><div class="runbook-head"><strong>${escapeHtml(hit.title)}</strong><span class="badge">${Number(hit.score).toFixed(3)}</span></div><span class="source-uri">${escapeHtml(hit.heading)} · ${escapeHtml(hit.source_uri)}</span><p>${escapeHtml(hit.content.slice(0, 620))}</p></article>
    `).join('') : '<div class="side-empty">No matching Runbook chunks</div>';
  } catch (error) { toast(error.message); }
}

async function proposeAction(event) {
  if (event.submitter?.value === 'cancel') return;
  event.preventDefault();
  const type = $('#action-type').value;
  const parameters = type === 'restart_service' ? { instances: 1 } : { target_version: $('#action-version').value };
  const payload = {
    incident_id: state.selectedId, action_type: type, target_environment: $('#action-environment').value,
    service: $('#action-service').value, parameters, reason: $('#action-reason').value,
    expires_in_minutes: 15, idempotency_key: `${type}-${state.selectedId}-${Date.now()}`
  };
  try {
    await api('/api/v1/actions', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Actor-Id': 'dashboard-user' }, body: JSON.stringify(payload) });
    $('#action-dialog').close();
    toast('Remediation submitted for approval');
    await refreshSelected();
  } catch (error) { toast(error.message); }
}

async function decideAction(id, decision) {
  try {
    await api(`/api/v1/actions/${id}/${decision}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Actor-Id': 'demo-approver' }, body: JSON.stringify({ comment: `Decision from OpsPilot workspace: ${decision}` }) });
    toast(decision === 'approve' ? 'Action approved' : 'Action rejected');
    await refreshSelected();
  } catch (error) { toast(error.message); }
}

async function executeAction(id) {
  try {
    await api(`/api/v1/actions/${id}/execute`, { method: 'POST', headers: { 'X-Actor-Id': 'dashboard-worker' } });
    toast('Action executed once');
    await refreshSelected();
  } catch (error) { toast(error.message); }
}

function switchTab(name) {
  $$('.tab').forEach((tab) => { const active = tab.dataset.tab === name; tab.classList.toggle('active', active); tab.setAttribute('aria-selected', String(active)); });
  $$('.tab-panel').forEach((panel) => { const active = panel.dataset.panel === name; panel.classList.toggle('active', active); panel.hidden = !active; });
}

function bindEvents() {
  $('#refresh-button').addEventListener('click', refreshSelected);
  $('#incident-filter').addEventListener('change', (event) => { state.filter = event.target.value; renderIncidents(); });
  $('#run-investigation').addEventListener('click', runInvestigation);
  $('#runbook-search-form').addEventListener('submit', searchRunbooks);
  $('#open-action-dialog').addEventListener('click', () => $('#action-dialog').showModal());
  $('#action-type').addEventListener('change', (event) => { $('#action-version-field').hidden = event.target.value !== 'rollback_deployment'; });
  $('#action-form').addEventListener('submit', proposeAction);
  $$('.tab').forEach((tab) => tab.addEventListener('click', () => switchTab(tab.dataset.tab)));
  $$('.view-switch').forEach((button) => button.addEventListener('click', () => switchView(button.dataset.view)));
}

async function initialize() {
  bindEvents();
  icons();
  try { await Promise.all([loadSummary(), loadIncidents()]); }
  catch (error) { toast(error.message); }
}

initialize();
