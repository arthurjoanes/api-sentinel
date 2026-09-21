import http from 'k6/http';
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { correctResult } from './contracts.js';
if (__ENV.SENTINEL_LAB !== '1') throw new Error('Use python scripts/review.py; carga exige stack descartável.');

const credentials = JSON.parse(open('/secrets/demo.json'));
const oracle = JSON.parse(open('/artifacts/oracle.json'));
const successLatency = new Trend('success_latency', true);
const errorLatency = new Trend('error_latency', true);
const started = new Counter('started_requests');
const invalid = new Counter('invalid_results');
const accepted = new Counter('accepted');
const quota = new Counter('quota_rejected');
const unavailable = new Counter('service_rejected');
const rate = Number(__ENV.RATE || 10);
const duration = __ENV.DURATION || '20s';
const durationMatch = /^(\d+)(s|m)$/.exec(duration);
const seconds = durationMatch ? Number(durationMatch[1]) * (durationMatch[2] === 'm' ? 60 : 1) : 0;
if (!(rate >= 1 && rate <= 90 && seconds >= 1 && seconds <= 60)) {
  throw new Error('Use RATE entre 1 e 90 e DURATION de até 60s neste laboratório.');
}
const tenant = __ENV.TENANT || 'tenant_a';
const scenarioName = __ENV.SCENARIO || 'steady';
export const options = {
  scenarios: { queries: { executor: 'constant-arrival-rate', rate, timeUnit: '1s', duration,
    preAllocatedVUs: scenarioName === 'pool-pressure' ? 24 : 8, maxVUs: 24, gracefulStop: '4s' } },
  summaryTrendStats: ['avg', 'min', 'med', 'p(95)', 'p(99)', 'max'],
  thresholds: {
    checks: ['rate==1'],
    invalid_results: ['count==0'],
    dropped_iterations: [{ threshold: 'count==0', abortOnFail: false }],
    'http_req_duration': [{ threshold: 'p(99)<3000', abortOnFail: true, delayAbortEval: '10s' }],
  },
};
export default function () {
  started.add(1);
  const store = tenant === 'tenant_b' ? 4 : 1;
  const path = __ENV.REQUEST_PATH || `/v1/stores/${store}/summary?start=2026-01-01&end=2026-03-01`;
  const response = http.get(`${__ENV.BASE_URL || 'http://proxy'}${path}`, {
    headers: { Authorization: `Bearer ${credentials[tenant]}` }, timeout: '3s',
    tags: { name: 'summary' }, responseType: 'text',
  });
  let body = null;
  try { body = response.json(); } catch (_) { /* Rejected by the contract check. */ }
  const correct = response.status === 200 && correctResult(body, 'summary', tenant, oracle);
  invalid.add(response.status === 200 && !correct ? 1 : 0);
  if (response.status === 200) { accepted.add(1); successLatency.add(response.timings.duration); }
  else if (response.status === 429) quota.add(1);
  else if (response.status === 503) unavailable.add(1);
  if (response.status !== 200) errorLatency.add(response.timings.duration);
  const pressureFailure = scenarioName === 'pool-pressure' && response.status === 503
    && ['database_pool_busy','dependency_unavailable','service_saturated','authentication_busy','request_deadline_exceeded'].includes(body?.code);
  const quotaFailure = scenarioName.startsWith('quota-') && response.status === 429 && body?.code === 'tenant_quota_exceeded';
  check(response, { 'conteudo correto ou recusa prevista': () => correct || pressureFailure || quotaFailure });
}
export function handleSummary(data) {
  data.sentinel = { offered_rate: rate, configured_duration: duration, scenario: scenarioName,
    offered_iterations: rate * seconds, tenant,
    started: data.metrics.started_requests?.values.count || 0,
    completed: data.metrics.iterations?.values.count || 0,
    dropped: data.metrics.dropped_iterations?.values.count || 0 };
  return { [`/artifacts/load-${scenarioName}.json`]: JSON.stringify(data, null, 2),
    stdout: JSON.stringify({ scenario: scenarioName, rate,
      completed: data.metrics.iterations?.values.count || 0,
      dropped: data.metrics.dropped_iterations?.values.count || 0,
      accepted: data.metrics.accepted?.values.count || 0,
      quota: data.metrics.quota_rejected?.values.count || 0,
      service: data.metrics.service_rejected?.values.count || 0,
      success_latency: data.metrics.success_latency?.values || {} }) + '\n' };
}
