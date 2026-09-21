import http from 'k6/http';
import execution from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';
import { correctResult } from './contracts.js';

if (__ENV.SENTINEL_LAB !== '1') {
  throw new Error('Use python scripts/review.py; carga exige stack descartavel.');
}
const credentials = JSON.parse(open('/secrets/demo.json'));
const oracle = JSON.parse(open('/artifacts/oracle.json'));
const mode = __ENV.MODE || 'mixed';
const name = __ENV.SCENARIO || mode;
const seconds = Number(__ENV.SECONDS || 15);
const tenants = ['tenant_a', 'tenant_b'];
const routes = ['summary', 'sales', 'stores', 'erp'];
const outcomes = ['valid', 'quota', 'capacity', 'erp_failure', 'invalid', 'other'];
if (!['mixed', 'degraded', 'quota', 'isolation'].includes(mode)
  || !Number.isInteger(seconds) || seconds < 1 || seconds > 30) {
  throw new Error('Cenario/duracao invalidos.');
}

const started = new Counter('started_requests');
const responses = new Counter('responses');
const invalid = new Counter('invalid_results');
const unexpected = new Counter('unexpected_results');
const businessFailures = new Counter('business_failures');
const successLatency = new Trend('success_latency', true);
const errorLatency = new Trend('error_latency', true);
const counts = {};
for (const tenant of tenants) {
  for (const outcome of outcomes) {
    const key = `${tenant}_${outcome}`;
    counts[key] = new Counter(key);
  }
}
const thresholds = {
  dropped_iterations: ['count==0'],
  invalid_results: ['count==0'],
  unexpected_results: ['count==0'],
  business_failures: ['count==0'],
  success_latency: ['p(95)<500', 'p(99)<1500'],
  http_req_duration: [{ threshold: 'p(99)<3000', abortOnFail: true, delayAbortEval: '5s' }],
};
for (const tenant of tenants) {
  for (const route of routes) {
    thresholds[`responses{tenant:${tenant},route:${route}}`] = ['count>=0'];
  }
}
for (const route of ['summary', 'sales', 'stores']) {
  thresholds[`success_latency{route:${route}}`] = ['p(95)<500', 'p(99)<1500'];
}
function arrival(rate, exec, vus) {
  return {
    executor: 'constant-arrival-rate', rate, timeUnit: '1s', duration: `${seconds}s`, exec,
    preAllocatedVUs: vus, maxVUs: vus, gracefulStop: '4s',
  };
}
const scenarios = mode === 'quota'
  ? { hot: arrival(60, 'hot', 20) }
  : mode === 'isolation'
    ? { hot: arrival(60, 'hot', 20), normal: arrival(5, 'normal', 4) }
    : { mixed: arrival(10, 'mixed', 16) };
export const options = {
  scenarios, thresholds, summaryTrendStats: ['med', 'p(95)', 'p(99)', 'max'],
};

function classify(response, body, route, tenant) {
  if (response.status === 200) {
    return correctResult(body, route, tenant, oracle) ? 'valid' : 'invalid';
  }
  if (response.status === 429 && body?.code === 'tenant_quota_exceeded') return 'quota';
  if (response.status === 503 && body?.code === 'service_saturated') return 'capacity';
  if ([503, 504].includes(response.status)
    && ['erp_circuit_open', 'erp_deadline'].includes(body?.code)) return 'erp_failure';
  return 'other';
}

function call(tenant, route) {
  started.add(1);
  const store = oracle.tenants[tenant].store;
  const period = `start=${oracle.start}&end=${oracle.end}`;
  let path = `/v1/stores/${store}/${route}?${period}`;
  if (route === 'stores') path = '/v1/stores';
  else if (route === 'erp') path = `/v1/stores/${store}/availability/SKU-001`;
  else if (route === 'sales') path += '&limit=5';
  const response = http.get(`${__ENV.BASE_URL || 'http://proxy'}${path}`, {
    headers: { Authorization: `Bearer ${credentials[tenant]}` },
    timeout: '3s', tags: { name: route, tenant, route },
  });
  let body = null;
  try { body = response.json(); } catch (_) { /* Invalid/unexpected below. */ }
  const result = classify(response, body, route, tenant);
  const permitted = result === 'valid'
    || (tenant === 'tenant_a' && ['quota', 'isolation'].includes(mode) && result === 'quota')
    || (mode === 'degraded' && route === 'erp' && ['erp_failure', 'capacity'].includes(result));
  if (!permitted) {
    console.error(JSON.stringify({
      unexpected: true, tenant, route, status: response.status, code: body?.code, result,
      request_id: response.headers['X-Request-Id'], instance: response.headers['X-Instance-Id'],
    }));
  }
  for (const key of Object.keys(counts)) counts[key].add(key === `${tenant}_${result}` ? 1 : 0);
  responses.add(1, { tenant, route });
  invalid.add(result === 'invalid' ? 1 : 0);
  unexpected.add(permitted ? 0 : 1);
  businessFailures.add(route !== 'erp' && !permitted ? 1 : 0);
  if (result === 'valid') successLatency.add(response.timings.duration, { tenant, route });
  else errorLatency.add(response.timings.duration, { tenant, route, result });
}

export function mixed() {
  const index = execution.scenario.iterationInTest;
  call(index % 2 ? 'tenant_b' : 'tenant_a', routes[Math.floor(index / 2) % 4]);
}
export function hot() {
  call('tenant_a', routes[execution.scenario.iterationInTest % 3]);
}
export function normal() {
  call('tenant_b', routes[execution.scenario.iterationInTest % 3]);
}
export function handleSummary(data) {
  const count = key => data.metrics[key]?.values?.count || 0;
  const categories = {};
  for (const key of Object.keys(counts)) categories[key] = count(key);
  const rate = mode === 'quota' ? 60 : mode === 'isolation' ? 65 : 10;
  data.sentinel = {
    scenario: name, mode, seconds, offered_per_second: rate, nominal_offered: seconds * rate,
    started: count('started_requests'), completed: count('responses'),
    dropped: count('dropped_iterations'), categories, oracle_sha256: oracle.raw_rows_sha256,
  };
  return {
    [`/artifacts/load-${name}.json`]: JSON.stringify(data, null, 2),
    stdout: JSON.stringify(data.sentinel) + '\n',
  };
}
