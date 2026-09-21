from prometheus_client import Counter, Gauge, Histogram

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1, 2, 5)
HTTP_REQUESTS = Counter(
    "sentinel_http_requests_total",
    "Respostas observadas pela API",
    ["route", "method", "outcome", "traffic"],
)
HTTP_DURATION = Histogram(
    "sentinel_http_request_duration_seconds",
    "Duração HTTP",
    ["route", "method", "outcome", "traffic"],
    buckets=BUCKETS,
)
ADMISSION = Counter("sentinel_admission_total", "Decisões de admissão", ["stage", "result"])
INFLIGHT = Gauge("sentinel_requests_inflight", "Requests admitidos ativos", ["stage"])
ADMISSION_WAIT = Histogram(
    "sentinel_admission_wait_seconds", "Tempo da decisão de admissão", ["stage"], buckets=BUCKETS
)
DB_POOL = Gauge("sentinel_db_pool_connections", "Ocupação do pool", ["pool", "state"])
DB_WAIT = Histogram(
    "sentinel_db_pool_wait_seconds", "Aquisição de conexão", ["pool"], buckets=BUCKETS
)
DB_TIMEOUTS = Counter("sentinel_db_pool_timeouts_total", "Timeout de aquisição", ["pool"])
DB_QUERIES = Counter("sentinel_db_queries_total", "Consultas por operação", ["operation"])
CACHE_REQUESTS = Counter("sentinel_cache_requests_total", "Resultados cache", ["result"])
CACHE_FILL = Counter("sentinel_cache_fill_total", "Preenchimento cache", ["result"])
CACHE_DURATION = Histogram(
    "sentinel_cache_duration_seconds", "Tempo cache", ["operation"], buckets=BUCKETS
)
ERP_REQUESTS = Counter("sentinel_erp_requests_total", "Chamadas ERP", ["outcome"])
ERP_DURATION = Histogram(
    "sentinel_erp_duration_seconds", "Duração ERP", ["outcome"], buckets=BUCKETS
)
ERP_RETRIES = Counter("sentinel_erp_retries_total", "Retentativas ERP")
ERP_CIRCUIT = Gauge("sentinel_erp_circuit_open", "Circuito ERP aberto")
LOOP_LAG = Gauge("sentinel_event_loop_lag_seconds", "Atraso do event loop")

for stage in ("entry", "auth", "tenant"):
    INFLIGHT.labels(stage).set(0)
    for result in ("accepted", "rejected"):
        ADMISSION.labels(stage, result).inc(0)
for operation in ("auth", "stores", "summary", "sales", "dataset"):
    DB_QUERIES.labels(operation).inc(0)
for result in ("hit", "miss", "error"):
    CACHE_REQUESTS.labels(result).inc(0)
for result in ("owner", "contended", "timeout"):
    CACHE_FILL.labels(result).inc(0)
for pool in ("data", "auth"):
    DB_TIMEOUTS.labels(pool).inc(0)
