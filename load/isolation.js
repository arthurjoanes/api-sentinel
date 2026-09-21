import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';
if (__ENV.SENTINEL_LAB !== '1') throw new Error('Use python scripts/review.py; carga exige stack descartável.');
const credentials = JSON.parse(open('/secrets/demo.json'));
const normalLatency = new Trend('normal_success_latency', true);
const normalFailures = new Counter('normal_failures');
const hotQuota = new Counter('hot_quota');
export const options = {
  scenarios: {
    hot: { executor: 'constant-arrival-rate', exec: 'hot', rate: 60, timeUnit: '1s', duration: '20s', preAllocatedVUs: 8, maxVUs: 20 },
    normal: { executor: 'constant-arrival-rate', exec: 'normal', rate: 5, timeUnit: '1s', duration: '20s', preAllocatedVUs: 2, maxVUs: 4 },
  },
  summaryTrendStats: ['med','p(95)','p(99)','max'],
  thresholds: { dropped_iterations: ['count==0'], normal_failures: ['count==0'] },
};
export function hot() {
  const response = http.get(`${__ENV.BASE_URL}/v1/stores/1/summary?start=2026-01-01&end=2026-03-01`, {headers:{Authorization:`Bearer ${credentials.tenant_a}`},timeout:'3s',tags:{name:'hot'}});
  if (response.status === 429) hotQuota.add(1);
}
export function normal() {
  const response = http.get(`${__ENV.BASE_URL}/v1/stores/4/summary?start=2026-01-01&end=2026-03-01`, {headers:{Authorization:`Bearer ${credentials.tenant_b}`},timeout:'3s',tags:{name:'normal'}});
  normalFailures.add(response.status === 200 ? 0 : 1);
  if (response.status === 200) normalLatency.add(response.timings.duration);
}
export function handleSummary(data) {
  data.sentinel = {offered_rate_a:60,offered_rate_b:5,duration_seconds:20};
  return {'/artifacts/load-isolation.json':JSON.stringify(data,null,2),stdout:JSON.stringify({completed:data.metrics.iterations.values.count,dropped:data.metrics.dropped_iterations?.values.count || 0,normal_failures:data.metrics.normal_failures.values.count,normal_latency:data.metrics.normal_success_latency.values})+'\n'};
}
