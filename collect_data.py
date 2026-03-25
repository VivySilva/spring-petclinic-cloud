"""
Script de coleta de dados de observabilidade
Coleta métricas do Prometheus, logs do Loki e traces do Zipkin
e salva em arquivos CSV com timestamp no nome.

REQUISITOS:
    pip install requests

CONFIGURAÇÃO:
    Certifique-se que os port-forwards estão ativos antes de rodar:
        kubectl port-forward svc/prometheus -n spring-petclinic 9090:9090
        kubectl port-forward svc/loki -n spring-petclinic 3100:3100
        kubectl port-forward svc/zipkin -n spring-petclinic 9411:9411

USO:
    python collect_observability.py
"""

import requests
import csv
import time
import os
import re
import json
from datetime import datetime, timezone

# ============================================================
# VARIÁVEIS DE CONFIGURAÇÃO — ajuste conforme necessário
# ============================================================

COLLECTION_INTERVAL_SECONDS = 60       # Frequência de coleta (segundos)
# None = rodar até Ctrl+C | Ex: 60 = 1 hora
COLLECTION_DURATION_MINUTES = None

PROMETHEUS_URL = "http://localhost:9090"
LOKI_URL = "http://localhost:3100"
ZIPKIN_URL = "http://localhost:9411"

OUTPUT_DIR = "collect_data"

SERVICES = [
    "api-gateway",
    "customers-service",
    "vets-service",
    "visits-service",
]

# Paths de ruído a ignorar no Zipkin
IGNORED_PATHS = {"/wpad.dat", "/favicon.ico"}

# ============================================================
# TODAS AS MÉTRICAS DO PROMETHEUS
# ============================================================

PROMETHEUS_METRICS = [
    "application_ready_time_seconds",
    "application_started_time_seconds",
    "disk_free_bytes",
    "disk_total_bytes",
    "executor_active_threads",
    "executor_completed_tasks_total",
    "executor_pool_core_threads",
    "executor_pool_max_threads",
    "executor_pool_size_threads",
    "executor_queue_remaining_tasks",
    "executor_queued_tasks",
    "hikaricp_connections",
    "hikaricp_connections_acquire_seconds_count",
    "hikaricp_connections_acquire_seconds_max",
    "hikaricp_connections_acquire_seconds_sum",
    "hikaricp_connections_active",
    "hikaricp_connections_creation_seconds_count",
    "hikaricp_connections_creation_seconds_max",
    "hikaricp_connections_creation_seconds_sum",
    "hikaricp_connections_idle",
    "hikaricp_connections_max",
    "hikaricp_connections_min",
    "hikaricp_connections_pending",
    "hikaricp_connections_timeout_total",
    "hikaricp_connections_usage_seconds_count",
    "hikaricp_connections_usage_seconds_max",
    "hikaricp_connections_usage_seconds_sum",
    "http_server_requests_seconds_count",
    "http_server_requests_seconds_max",
    "http_server_requests_seconds_sum",
    "jdbc_connections_active",
    "jdbc_connections_idle",
    "jdbc_connections_max",
    "jdbc_connections_min",
    "jvm_buffer_count_buffers",
    "jvm_buffer_memory_used_bytes",
    "jvm_buffer_total_capacity_bytes",
    "jvm_classes_loaded_classes",
    "jvm_classes_unloaded_classes_total",
    "jvm_gc_live_data_size_bytes",
    "jvm_gc_max_data_size_bytes",
    "jvm_gc_memory_allocated_bytes_total",
    "jvm_gc_memory_promoted_bytes_total",
    "jvm_gc_overhead_percent",
    "jvm_gc_pause_seconds_count",
    "jvm_gc_pause_seconds_max",
    "jvm_gc_pause_seconds_sum",
    "jvm_memory_committed_bytes",
    "jvm_memory_max_bytes",
    "jvm_memory_usage_after_gc_percent",
    "jvm_memory_used_bytes",
    "jvm_threads_daemon_threads",
    "jvm_threads_live_threads",
    "jvm_threads_peak_threads",
    "jvm_threads_states_threads",
    "logback_events_total",
    "process_cpu_usage",
    "process_files_max_files",
    "process_files_open_files",
    "process_start_time_seconds",
    "process_uptime_seconds",
    "scrape_duration_seconds",
    "scrape_samples_post_metric_relabeling",
    "scrape_samples_scraped",
    "scrape_series_added",
    "spring_cloud_gateway_routes_count",
    "system_cpu_count",
    "system_cpu_usage",
    "system_load_average_1m",
    "tomcat_sessions_active_current_sessions",
    "tomcat_sessions_active_max_sessions",
    "tomcat_sessions_alive_max_seconds",
    "tomcat_sessions_created_sessions_total",
    "tomcat_sessions_expired_sessions_total",
    "tomcat_sessions_rejected_sessions_total",
    "up",
    "zipkin_reporter_messages_bytes_total",
    "zipkin_reporter_messages_total",
    "zipkin_reporter_queue_bytes",
    "zipkin_reporter_queue_spans",
    "zipkin_reporter_spans_bytes_total",
    "zipkin_reporter_spans_dropped_total",
    "zipkin_reporter_spans_total",
]

# ============================================================
# AUXILIARES
# ============================================================


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def resolve_instance_to_service():
    mapping = {}
    try:
        response = requests.get(f"{PROMETHEUS_URL}/api/v1/targets", timeout=10)
        data = response.json()
        for target in data.get("data", {}).get("activeTargets", []):
            instance = target.get("labels", {}).get("instance", "")
            discovered = target.get("discoveredLabels", {})
            service = discovered.get("__meta_kubernetes_pod_label_app", "")
            if instance and service:
                mapping[instance] = service
    except Exception as e:
        print(f"  [PROMETHEUS] Erro ao resolver instâncias: {e}")
    return mapping


def parse_log_line(raw):
    """
    Parseia linha de log no formato Spring Boot:
    2026-03-09 16:09:09.348  INFO [service,traceId,spanId] 1 --- [thread] logger : message

    Linhas sem esse formato (SQL Hibernate, stack traces) ficam só em 'message'.
    """
    result = {}
    try:
        obj = json.loads(raw)
        log_str = obj.get("log", raw).strip()
    except Exception:
        log_str = str(raw).strip()

    # Regex com raw string para evitar perda de barras invertidas
    pattern = r"^\S+ \S+\s+(\w+)\s+\[([^\]]*)\]\s+\d+\s+---\s+\[([^\]]*)\]\s+(\S+)\s+:\s+(.*)$"
    match = re.match(pattern, log_str)
    if match:
        trace_info = match.group(2).split(",")
        result["level"] = match.group(1)
        result["trace_id"] = trace_info[1].strip() if len(
            trace_info) > 1 else ""
        result["span_id"] = trace_info[2].strip() if len(
            trace_info) > 2 else ""
        result["thread"] = match.group(3).strip()
        result["logger"] = match.group(4).strip()
        result["message"] = match.group(5).strip()
    else:
        level_match = re.search(r"\b(INFO|WARN|ERROR|DEBUG|TRACE)\b", log_str)
        result["level"] = level_match.group(1) if level_match else ""
        result["message"] = log_str
    return result


# ============================================================
# COLETA PROMETHEUS
# ============================================================

def collect_prometheus(collected_at, instance_map, filepath):
    file_exists = os.path.exists(filepath)
    fieldnames = ["collected_at", "metric_timestamp", "metric_name",
                  "service", "instance", "labels", "value"]

    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        collected = 0
        for metric_name in PROMETHEUS_METRICS:
            try:
                query = f'{metric_name}{{job="spring-petclinic"}}'
                response = requests.get(
                    f"{PROMETHEUS_URL}/api/v1/query",
                    params={"query": query},
                    timeout=10
                )
                data = response.json()
                if data.get("status") == "success":
                    for result in data["data"]["result"]:
                        metric_labels = result.get("metric", {})
                        instance = metric_labels.get("instance", "")
                        service = instance_map.get(instance, "")
                        
                        # Extrai o timestamp em que o prometheus registrou a métrica
                        metric_time = float(result["value"][0])
                        metric_timestamp = datetime.fromtimestamp(metric_time, tz=timezone.utc).isoformat()
                        
                        writer.writerow({
                            "collected_at":     collected_at,
                            "metric_timestamp": metric_timestamp,
                            "metric_name":      metric_name,
                            "service":          service,
                            "instance":         instance,
                            "labels":           str(metric_labels),
                            "value":            result["value"][1],
                        })
                        collected += 1
            except Exception as e:
                print(f"  [PROMETHEUS] Erro na métrica '{metric_name}': {e}")

        print(f"  [PROMETHEUS] {collected} linhas coletadas")


# ============================================================
# COLETA LOKI
# ============================================================

def collect_loki(collected_at, lookback_seconds, filepath):
    file_exists = os.path.exists(filepath)
    fieldnames = [
        "collected_at", "service", "pod", "timestamp",
        "level", "trace_id", "span_id", "thread", "logger", "message"
    ]

    now_ns = int(time.time() * 1e9)
    start_ns = now_ns - int(lookback_seconds * 1e9)

    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        collected = 0
        for service in SERVICES:
            try:
                loki_query = (
                    f'{{app="{service}"}}'
                    ' != "Watch connection expired"'
                    ' != "resourceVersion"'
                    ' != "actuator/health"'
                    ' != "actuator/info"'
                    ' != "actuator/prometheus"'
                    ' != "CompositeHealth"'
                    ' != "openmetrics-text"'
                    ' != "HttpEntityMethodProcessor"'
                    ' != "/api/v2/spans"'
                    ' != "HttpLogging"'
                    ' != "Mapped to"'
                    ' != "Using "'
                    ' != "Writing ["'
                    ' != "RequestMappingHandlerMapping"'
                    ' != "RequestResponseBodyMethodProcessor"'
                )
                response = requests.get(
                    f"{LOKI_URL}/loki/api/v1/query_range",
                    params={
                        "query": loki_query,
                        "start": start_ns,
                        "end":   now_ns,
                        "limit": 1000,
                    },
                    timeout=15
                )
                data = response.json()
                if data.get("status") == "success":
                    for stream in data["data"]["result"]:
                        pod = stream["stream"].get("pod", "")
                        for ts_ns, raw in stream["values"]:
                            parsed = parse_log_line(raw)
                            writer.writerow({
                                "collected_at": collected_at,
                                "service":      service,
                                "pod":          pod,
                                "timestamp":    datetime.fromtimestamp(int(ts_ns) / 1e9, tz=timezone.utc).isoformat(),
                                "level":        parsed.get("level", ""),
                                "trace_id":     parsed.get("trace_id", ""),
                                "span_id":      parsed.get("span_id", ""),
                                "thread":       parsed.get("thread", ""),
                                "logger":       parsed.get("logger", ""),
                                "message":      parsed.get("message", ""),
                            })
                            collected += 1
            except Exception as e:
                print(f"  [LOKI] Erro no serviço '{service}': {e}")

        print(f"  [LOKI] {collected} linhas coletadas")


# ============================================================
# COLETA ZIPKIN
# ============================================================

def collect_zipkin(collected_at, lookback_seconds, filepath):
    file_exists = os.path.exists(filepath)
    fieldnames = [
        "collected_at", "trace_id", "start_timestamp", "total_duration_ms",
        "spans_count", "unique_services_count", "services_list", "has_error",
        "root_http_method", "root_http_path", "root_http_status",
        "db_query_count", "db_total_duration_ms", "internal_calls_count"
    ]
    lookback_ms = lookback_seconds * 1000

    # Carrega trace_ids já gravados para evitar duplicatas
    seen_trace_ids = set()
    if file_exists:
        with open(filepath, "r", encoding="utf-8") as rf:
            for row in csv.DictReader(rf):
                seen_trace_ids.add(row.get("trace_id", ""))

    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        collected = 0
        for service in SERVICES:
            try:
                response = requests.get(
                    f"{ZIPKIN_URL}/api/v2/traces",
                    params={"serviceName": service,
                            "lookback": lookback_ms, "limit": 500},
                    timeout=15
                )
                for trace in response.json():
                    if not trace: 
                        continue
                    
                    trace_id = trace[0].get("traceId", "")
                    if trace_id in seen_trace_ids:
                        continue
                        
                    min_ts = float('inf')
                    max_end_ts = 0
                    services_set = set()
                    has_error = False
                    
                    root_http_method = ""
                    root_http_path = ""
                    root_http_status = ""
                    
                    db_query_count = 0
                    db_total_duration_ms = 0.0
                    internal_calls_count = 0
                    
                    valid_spans = 0

                    for span in trace:
                        tags = span.get("tags", {})
                        http_path = tags.get("http.path", "")
                        
                        if http_path in IGNORED_PATHS:
                            continue
                            
                        valid_spans += 1
                        
                        svc = span.get("localEndpoint", {}).get("serviceName", "")
                        if svc: services_set.add(svc)
                        
                        if "error" in tags:
                            has_error = True
                            
                        # Métricas DB: Nome da operação é tx ou possui tags de sql
                        op_name = span.get("name", "")
                        if op_name == "tx" or "sql.query" in tags:
                            db_query_count += 1
                            db_total_duration_ms += span.get("duration", 0) / 1000.0
                            
                        # Saltos Internos da arquitetura
                        if span.get("kind") == "CLIENT":
                            internal_calls_count += 1
                            
                        # Info do Root Span (ponto de entrada)
                        if not span.get("parentId"):
                            root_http_method = tags.get("http.method", "")
                            root_http_path = http_path
                            root_http_status = tags.get("http.status_code", "")
                            
                        ts = span.get("timestamp", 0)  # em microsegundos
                        dur = span.get("duration", 0)  # em microsegundos
                        if ts:
                            min_ts = min(min_ts, ts)
                            max_end_ts = max(max_end_ts, ts + dur)
                            
                    if valid_spans == 0 or min_ts == float('inf'):
                        continue
                        
                    duration_ms = round((max_end_ts - min_ts) / 1000.0, 3)
                    start_iso = datetime.fromtimestamp(min_ts / 1e6, tz=timezone.utc).isoformat()
                    
                    writer.writerow({
                        "collected_at":          collected_at,
                        "trace_id":              trace_id,
                        "start_timestamp":       start_iso,
                        "total_duration_ms":     duration_ms,
                        "spans_count":           valid_spans,
                        "unique_services_count": len(services_set),
                        "services_list":         "|".join(services_set),
                        "has_error":             has_error,
                        "root_http_method":      root_http_method,
                        "root_http_path":        root_http_path,
                        "root_http_status":      root_http_status,
                        "db_query_count":        db_query_count,
                        "db_total_duration_ms":  round(db_total_duration_ms, 3),
                        "internal_calls_count":  internal_calls_count
                    })
                    seen_trace_ids.add(trace_id)
                    collected += 1
            except Exception as e:
                print(f"  [ZIPKIN] Erro no serviço '{service}': {e}")

        print(f"  [ZIPKIN] {collected} traces (agregados) coletados")


# ============================================================
# LOOP PRINCIPAL
# ============================================================

def main():
    ensure_output_dir()

    # Timestamp no nome dos arquivos: DD-MM-HHhMM
    run_ts = datetime.now().strftime("%d-%m-%Hh%M")
    prometheus_file = os.path.join(
        OUTPUT_DIR, f"prometheus_metrics_{run_ts}.csv")
    loki_file = os.path.join(OUTPUT_DIR, f"loki_logs_{run_ts}.csv")
    zipkin_file = os.path.join(OUTPUT_DIR, f"zipkin_traces_{run_ts}.csv")

    duration_seconds = COLLECTION_DURATION_MINUTES * \
        60 if COLLECTION_DURATION_MINUTES else None
    start_time = time.time()
    iteration = 0

    print("=" * 60)
    print("  Coleta de Observabilidade Iniciada")
    print(f"  Intervalo : {COLLECTION_INTERVAL_SECONDS}s")
    print(
        f"  Duração   : {'indefinida (Ctrl+C para parar)' if not duration_seconds else f'{COLLECTION_DURATION_MINUTES} minutos'}")
    print(f"  Saída     : {os.path.abspath(OUTPUT_DIR)}/")
    print(f"  Arquivos  : *_{run_ts}.csv")
    print("=" * 60)

    instance_map = resolve_instance_to_service()
    print(f"  Serviços detectados: {instance_map}\n")

    try:
        while True:
            elapsed = time.time() - start_time
            if duration_seconds and elapsed >= duration_seconds:
                print("\nDuração atingida. Encerrando.")
                break

            iteration += 1

            # Atualiza mapeamento a cada 5 iterações
            if iteration % 5 == 0:
                instance_map = resolve_instance_to_service()

            collected_at = datetime.now(tz=timezone.utc).isoformat()
            print(f"[{collected_at}] Iteração {iteration}")

            collect_prometheus(collected_at, instance_map, prometheus_file)
            collect_loki(
                collected_at, COLLECTION_INTERVAL_SECONDS + 5, loki_file)
            collect_zipkin(collected_at, max(
                120, COLLECTION_INTERVAL_SECONDS + 5), zipkin_file)

            elapsed_iter = time.time() - start_time - (iteration - 1) * \
                COLLECTION_INTERVAL_SECONDS
            sleep_time = COLLECTION_INTERVAL_SECONDS - elapsed_iter
            if sleep_time > 0:
                print(f"  Próxima coleta em {sleep_time:.1f}s...\n")
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n\nColeta interrompida pelo usuário.")

    print(f"\nArquivos gerados em: {os.path.abspath(OUTPUT_DIR)}/")
    print(f"  - prometheus_metrics_{run_ts}.csv")
    print(f"  - loki_logs_{run_ts}.csv")
    print(f"  - zipkin_traces_{run_ts}.csv")


if __name__ == "__main__":
    main()
