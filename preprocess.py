"""
preprocess.py — Pré-processador de dados de observabilidade
============================================================
Transforma os CSVs brutos do Prometheus, Loki e Zipkin em uma única
tabela estruturada, pronta para treinamento de ML.

LÓGICA:
  - Cada linha do dataset final = 1 minuto × 1 serviço × 1 nó físico
  - Prometheus : pivota de formato longo para largo (cada métrica vira coluna)
  - Zipkin     : agrega traces por minuto/serviço (médias + throughput)
  - Loki       : conta logs e erros por minuto/serviço
  - As 3 fontes são unidas por (timestamp_min + service)

SAÍDA: dataset_final.csv (~33 colunas)

USO:
    python preprocess.py
    python preprocess.py --input_dir collect_data --output dataset_final.csv
    python preprocess.py --min_date 2026-06-01   # filtra dados antigos/incompatíveis

REQUISITOS:
    pip install pandas numpy
"""

import os
import glob
import argparse
import pandas as pd
import numpy as np

# ============================================================
# CONFIGURAÇÃO
# ============================================================

INPUT_DIR   = "collect_data"
OUTPUT_FILE = "dataset_final.csv"

# Mapeamento: prefixo de sub-rede do pod -> IP Tailscale do nó físico
# Ajuste se os IPs do Tailscale mudarem
NODE_IP_MAP = {
    "10.42.0": "100.109.58.70",   # notebook-vivy (control-plane)
    "10.42.1": "100.69.100.11",   # augusto-almondes (worker)
    "10.42.2": "100.110.60.101",  # macbookair-vivy (worker / MySQL)
}

# Apenas estes serviços entrarão no dataset final
TARGET_SERVICES = [
    "api-gateway",
    "customers-service",
    "vets-service",
    "visits-service",
]

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def instance_to_node_ip(instance: str) -> str:
    """
    Converte o IP interno do pod (10.42.0.77:8080) no IP Tailscale
    do nó físico que hospeda aquele pod.
    """
    subnet = ".".join(str(instance).split(".")[:3])
    return NODE_IP_MAP.get(subnet, instance.split(":")[0])


def parse_labels(label_str: str) -> dict:
    """
    Converte a string de labels salva pelo collect_data.py em um
    dicionário Python. Ex: "{'area': 'heap', 'id': 'Eden Space'...}"
    """
    try:
        return eval(str(label_str))
    except Exception:
        return {}


def service_from_zipkin(services_list: str) -> str:
    """
    Extrai o microsserviço de negócio de uma trace do Zipkin.
    Remove o 'api-gateway' (que é apenas o roteador de entrada).
    Ex: "api-gateway|customers-service" -> "customers-service"
    """
    services = [s.strip() for s in str(services_list).split("|")]
    business = [s for s in services if s != "api-gateway"]
    return business[0] if business else services[0]


# ============================================================
# ETAPA 1: PROMETHEUS  (formato longo -> largo)
# ============================================================

def _topology_fallback_by_date(ts) -> str:
    """
    Fallback para arquivos coletados antes da coluna 'network_topology'
    existir. Mapeia a data da coleta para o cenário de rede correto.

    Regra baseada no histórico do projeto:
      - Até 15/Jul/2026 : redes separadas (cada máquina em Wi-Fi diferente)
      - 16/Jul/2026+   : mesma rede (todos no mesmo roteador)
    Para estender, adicione mais IFs com datas e descrições.
    """
    try:
        if hasattr(ts, 'date'):
            d = ts.date()
        else:
            d = pd.Timestamp(ts).date()
        import datetime
        if d >= datetime.date(2026, 7, 16):
            return "same_network"
        else:
            return "distributed"
    except Exception:
        return "distributed"

def process_prometheus(input_dir: str) -> pd.DataFrame:
    print("\n[1/4] Processando Prometheus...")

    files = glob.glob(os.path.join(input_dir, "prometheus_metrics_*.csv"))
    if not files:
        print("  AVISO: Nenhum arquivo prometheus_metrics_*.csv encontrado!")
        return pd.DataFrame()

    print(f"  Arquivos encontrados: {len(files)}")
    dfs = []
    for f in files:
        try:
            dfs.append(pd.read_csv(f, low_memory=False))
        except Exception as e:
            print(f"  ERRO ao ler {f}: {e}")

    df = pd.concat(dfs, ignore_index=True)
    print(f"  Linhas brutas: {len(df):,}")

    # Limpeza e enriquecimento
    df["value"]        = pd.to_numeric(df["value"], errors="coerce")
    df["collected_at"] = pd.to_datetime(df["collected_at"], utc=True)
    df["timestamp_min"]= df["collected_at"].dt.floor("min")
    df["node_ip"]      = df["instance"].apply(instance_to_node_ip)
    df["labels_dict"]  = df["labels"].apply(parse_labels)

    # ----------------------------------------------------------
    # Topologia de rede:
    #   - Dados novos (jul/2026+): lê a coluna 'network_topology' gravada
    #     pelo collect_data.py no momento da coleta.
    #   - Dados antigos (sem a coluna): fallback automático por data.
    #     06/Jul/2026 = redes separadas | 16/Jul/2026+ = mesma rede
    # ----------------------------------------------------------
    if "network_topology" in df.columns:
        # Preenche apenas as linhas que não têm o valor (arquivos antigos misturados)
        df["network_topology"] = df["network_topology"].fillna(
            df["collected_at"].apply(_topology_fallback_by_date)
        )
    else:
        df["network_topology"] = df["collected_at"].apply(_topology_fallback_by_date)

    topology_counts = df["network_topology"].value_counts().to_dict()
    print(f"  Topologias detectadas: {topology_counts}")

    # ----------------------------------------------------------
    # Número de nós (computadores) no cluster:
    #   - Dados novos: lê a coluna 'cluster_nodes' do CSV
    #   - Dados antigos: detecta automaticamente contando quantos
    #     node_ips distintos apareceram naquele minuto nos dados brutos
    # ----------------------------------------------------------
    if "cluster_nodes" in df.columns:
        df["cluster_nodes"] = pd.to_numeric(df["cluster_nodes"], errors="coerce")
        # Para linhas antigas (NaN), auto-detecta pelo número de node_ips distintos
        auto_nodes = (df.groupby("timestamp_min")["node_ip"]
                        .transform("nunique"))
        df["cluster_nodes"] = df["cluster_nodes"].fillna(auto_nodes)
    else:
        # Auto-detecta para todos os dados (arquivos sem a coluna)
        df["cluster_nodes"] = (df.groupby("timestamp_min")["node_ip"]
                                 .transform("nunique"))

    df["cluster_nodes"] = df["cluster_nodes"].astype(int)
    node_counts = df["cluster_nodes"].value_counts().sort_index().to_dict()
    print(f"  Nós por janela detectados: {node_counts}")

    # Remove duplicatas exatas
    df = df.drop_duplicates(subset=["collected_at", "metric_name", "instance", "labels"])

    # Chave de agrupamento final
    key = ["timestamp_min", "service", "node_ip"]

    # Extrai topologia e número de nós por minuto/serviço/nó (primeira ocorrência)
    topology_df = (df.sort_values("collected_at")
                     .groupby(key)
                     .agg(network_topology=("network_topology", "first"),
                          cluster_nodes=("cluster_nodes", "first"))
                     .reset_index())

    results = []  # lista de DataFrames parciais, um por métrica

    # ----------------------------------------------------------
    # 1.1 Métricas de GAUGE simples (média por janela de 1 minuto)
    # ----------------------------------------------------------
    simple_gauges = {
        "process_cpu_usage":           "cpu_process",
        "system_cpu_usage":            "cpu_system",
        "system_load_average_1m":      "load_1m",
        "jvm_gc_overhead_percent":     "gc_overhead_percent",
        "hikaricp_connections_active": "db_connections_active",
        "hikaricp_connections_idle":   "db_connections_idle",
        "hikaricp_connections_pending":"hikaricp_pending",
        "jvm_threads_live_threads":    "threads_live",
    }
    for metric, col in simple_gauges.items():
        sub = df[df["metric_name"] == metric].copy()
        if sub.empty:
            continue
        agg = (sub.groupby(key)["value"]
                  .mean()
                  .reset_index()
                  .rename(columns={"value": col}))
        results.append(agg)
        print(f"  ✓ {metric:45s} -> {col}")

    # ----------------------------------------------------------
    # 1.2 hikaricp_connections_timeout_total
    #     (contador acumulado — usamos o valor máximo do minuto)
    # ----------------------------------------------------------
    sub = df[df["metric_name"] == "hikaricp_connections_timeout_total"].copy()
    if not sub.empty:
        agg = (sub.groupby(key)["value"]
                  .max()
                  .reset_index()
                  .rename(columns={"value": "hikaricp_timeout_count"}))
        results.append(agg)
        print(f"  ✓ {'hikaricp_connections_timeout_total':45s} -> hikaricp_timeout_count")

    # ----------------------------------------------------------
    # 1.3 jvm_memory_used_bytes  (apenas área = heap)
    #     Soma todas as pools de heap: Eden + Old Gen + Survivor
    # ----------------------------------------------------------
    sub = df[df["metric_name"] == "jvm_memory_used_bytes"].copy()
    sub["area"] = sub["labels_dict"].apply(lambda d: d.get("area", ""))
    heap_used = (sub[sub["area"] == "heap"]
                 .groupby(key)["value"]
                 .sum()
                 .reset_index()
                 .rename(columns={"value": "memory_heap_used_bytes"}))
    if not heap_used.empty:
        results.append(heap_used)
        print(f"  ✓ {'jvm_memory_used_bytes (area=heap)':45s} -> memory_heap_used_bytes")

    # ----------------------------------------------------------
    # 1.4 jvm_memory_max_bytes  (apenas área = heap)
    # ----------------------------------------------------------
    sub = df[df["metric_name"] == "jvm_memory_max_bytes"].copy()
    sub["area"] = sub["labels_dict"].apply(lambda d: d.get("area", ""))
    heap_max = (sub[sub["area"] == "heap"]
                .groupby(key)["value"]
                .sum()
                .reset_index()
                .rename(columns={"value": "memory_heap_max_bytes"}))
    if not heap_max.empty:
        results.append(heap_max)
        print(f"  ✓ {'jvm_memory_max_bytes (area=heap)':45s} -> memory_heap_max_bytes")

    # ----------------------------------------------------------
    # 1.5 Métricas HTTP (CONTADORES — usamos delta entre leituras)
    #     http_requests_total = quantas requisições naquele minuto
    #     http_requests_duration_s = segundos totais gastos
    # ----------------------------------------------------------
    for metric, col in [
        ("http_server_requests_seconds_count", "http_requests_total"),
        ("http_server_requests_seconds_sum",   "http_requests_duration_s"),
    ]:
        sub = df[df["metric_name"] == metric].copy()
        if sub.empty:
            continue
        # Soma todas as labels (status, uri, method) por instância e minuto
        sub_agg = (sub.groupby(["timestamp_min", "service", "node_ip", "instance"])["value"]
                      .sum()
                      .reset_index())
        # Calcula o delta (diferença) entre leituras consecutivas da mesma instância
        sub_agg = sub_agg.sort_values(["service", "node_ip", "instance", "timestamp_min"])
        sub_agg["delta"] = (sub_agg
                            .groupby(["service", "instance"])["value"]
                            .diff()
                            .fillna(0)
                            .clip(lower=0))   # evita negativos por reinício do pod
        agg = (sub_agg.groupby(key)["delta"]
                      .sum()
                      .reset_index()
                      .rename(columns={"delta": col}))
        results.append(agg)
        print(f"  ✓ {metric:45s} -> {col} (delta)")

    # ----------------------------------------------------------
    # 1.6 http_server_requests_seconds_max (maior latência)
    # ----------------------------------------------------------
    sub = df[df["metric_name"] == "http_server_requests_seconds_max"].copy()
    if not sub.empty:
        agg = (sub.groupby(key)["value"]
                  .max()
                  .reset_index()
                  .rename(columns={"value": "http_requests_max_latency_s"}))
        results.append(agg)
        print(f"  ✓ {'http_server_requests_seconds_max':45s} -> http_requests_max_latency_s")

    # ----------------------------------------------------------
    # 1.7 Rede (CONTADORES — delta)
    # ----------------------------------------------------------
    for metric, col in [
        ("container_network_receive_bytes_total",  "net_rx_bytes"),
        ("container_network_transmit_bytes_total", "net_tx_bytes"),
    ]:
        sub = df[df["metric_name"] == metric].copy()
        if sub.empty:
            continue
        sub = sub.sort_values(["service", "node_ip", "instance", "timestamp_min"])
        sub["delta"] = (sub.groupby(["service", "instance"])["value"]
                           .diff()
                           .fillna(0)
                           .clip(lower=0))
        agg = (sub.groupby(key)["delta"]
                  .sum()
                  .reset_index()
                  .rename(columns={"delta": col}))
        results.append(agg)
        print(f"  ✓ {metric:45s} -> {col} (delta)")

    if not results:
        print("  ERRO: Nenhuma métrica Prometheus foi extraída.")
        return pd.DataFrame()

    # Merge progressivo de todas as métricas parciais
    base = results[0]
    for r in results[1:]:
        base = base.merge(r, on=key, how="outer")

    # Junta a topologia de rede
    base = base.merge(topology_df, on=key, how="left")

    base = base[base["service"].isin(TARGET_SERVICES)]
    print(f"\n  Prometheus processado: {len(base):,} linhas × {len(base.columns)} colunas")
    return base


# ============================================================
# ETAPA 2: ZIPKIN  (agrega traces por minuto / serviço)
# ============================================================

def process_zipkin(input_dir: str) -> pd.DataFrame:
    print("\n[2/4] Processando Zipkin...")

    files = glob.glob(os.path.join(input_dir, "zipkin_traces_*.csv"))
    if not files:
        print("  AVISO: Nenhum arquivo zipkin_traces_*.csv encontrado!")
        return pd.DataFrame()

    print(f"  Arquivos encontrados: {len(files)}")
    dfs = []
    for f in files:
        try:
            dfs.append(pd.read_csv(f, low_memory=False))
        except Exception as e:
            print(f"  ERRO ao ler {f}: {e}")

    df = pd.concat(dfs, ignore_index=True)
    # Remove traces duplicados (mesmo trace_id pode aparecer em coletas consecutivas)
    df = df.drop_duplicates(subset=["trace_id"])
    print(f"  Traces únicos: {len(df):,}")

    df["start_timestamp"]    = pd.to_datetime(df["start_timestamp"], utc=True)
    df["timestamp_min"]      = df["start_timestamp"].dt.floor("min")
    df["has_error"]          = (df["has_error"].astype(str).str.lower() == "true").astype(int)
    df["total_duration_ms"]  = pd.to_numeric(df["total_duration_ms"],  errors="coerce")
    df["db_total_duration_ms"] = pd.to_numeric(df["db_total_duration_ms"], errors="coerce").fillna(0)
    df["db_query_count"]     = pd.to_numeric(df["db_query_count"],     errors="coerce").fillna(0)
    df["spans_count"]        = pd.to_numeric(df["spans_count"],        errors="coerce").fillna(0)

    # Atribui o serviço de negócio a cada trace
    df["service"] = df["services_list"].apply(service_from_zipkin)
    df = df[df["service"].isin(TARGET_SERVICES)]

    key = ["timestamp_min", "service"]

    agg = df.groupby(key).agg(
        avg_total_duration_ms    = ("total_duration_ms",    "mean"),
        avg_spans_count          = ("spans_count",          "mean"),
        avg_db_query_count       = ("db_query_count",       "mean"),
        avg_db_total_duration_ms = ("db_total_duration_ms", "mean"),
        error_rate               = ("has_error",            "mean"),
        _trace_count             = ("trace_id",             "count"),
    ).reset_index()

    # MRT = Mean Response Time (em ms)
    agg["mrt_ms"] = agg["avg_total_duration_ms"].round(3)

    # Throughput: quantas requisições chegaram por segundo naquele minuto
    agg["throughput_rps"] = (agg["_trace_count"] / 60.0).round(4)

    # Gargalo de banco: qual % do tempo de resposta foi gasto no banco
    agg["db_bottleneck_ratio"] = (
        agg["avg_db_total_duration_ms"]
        / agg["avg_total_duration_ms"].replace(0, np.nan)
    ).fillna(0).clip(0, 1).round(4)

    agg = agg.drop(columns=["_trace_count"])
    print(f"  Zipkin processado: {len(agg):,} linhas × {len(agg.columns)} colunas")
    return agg


# ============================================================
# ETAPA 3: LOKI  (conta logs e erros por minuto / serviço)
# ============================================================

def process_loki(input_dir: str) -> pd.DataFrame:
    print("\n[3/4] Processando Loki...")

    files = glob.glob(os.path.join(input_dir, "loki_logs_*.csv"))
    if not files:
        print("  AVISO: Nenhum arquivo loki_logs_*.csv encontrado!")
        return pd.DataFrame()

    print(f"  Arquivos encontrados: {len(files)}")
    dfs = []
    for f in files:
        try:
            dfs.append(pd.read_csv(f, low_memory=False))
        except Exception as e:
            print(f"  ERRO ao ler {f}: {e}")

    df = pd.concat(dfs, ignore_index=True)
    print(f"  Linhas de log brutas: {len(df):,}")

    df["timestamp"]     = pd.to_datetime(df["timestamp"], utc=True)
    df["timestamp_min"] = df["timestamp"].dt.floor("min")
    df = df[df["service"].isin(TARGET_SERVICES)]

    # Marca ERROR e WARN como nível de erro
    df["is_error"] = df["level"].str.upper().isin({"ERROR", "WARN"}).astype(int)

    key = ["timestamp_min", "service"]

    agg = df.groupby(key).agg(
        log_count       = ("level",    "count"),
        _error_count    = ("is_error", "sum"),
    ).reset_index()

    agg["log_error_rate"] = (agg["_error_count"] / agg["log_count"]).fillna(0).round(4)
    agg = agg.drop(columns=["_error_count"])

    print(f"  Loki processado: {len(agg):,} linhas × {len(agg.columns)} colunas")
    return agg


# ============================================================
# ETAPA 4: JUNÇÃO E DERIVAÇÃO DE MÉTRICAS FINAIS
# ============================================================

def join_and_derive(prom: pd.DataFrame,
                    zipkin: pd.DataFrame,
                    loki: pd.DataFrame) -> pd.DataFrame:
    print("\n[4/4] Unindo as fontes e calculando métricas derivadas...")

    if prom.empty:
        print("  ERRO: Dados do Prometheus vazios. Impossível montar o dataset.")
        return pd.DataFrame()

    df = prom.copy()

    # O Prometheus tem granularidade (timestamp_min, service, node_ip).
    # Zipkin e Loki não têm node_ip — os valores se repetem para cada réplica.
    if not zipkin.empty:
        df = df.merge(zipkin, on=["timestamp_min", "service"], how="left")
        print(f"  Após join com Zipkin : {len(df):,} linhas")

    if not loki.empty:
        df = df.merge(loki,   on=["timestamp_min", "service"], how="left")
        print(f"  Após join com Loki   : {len(df):,} linhas")

    # ----------------------------------------------------------
    # Métricas derivadas
    # ----------------------------------------------------------

    # Utilização de memória heap (%)
    df["memory_utilization_pct"] = (
        df.get("memory_heap_used_bytes", pd.Series(dtype=float))
        / df.get("memory_heap_max_bytes", pd.Series(dtype=float)).replace(0, np.nan)
        * 100
    ).clip(0, 100).round(2)

    # Saturação das conexões de banco (%)
    active = df.get("db_connections_active", pd.Series(0, index=df.index)).fillna(0)
    idle   = df.get("db_connections_idle",   pd.Series(0, index=df.index)).fillna(0)
    df["db_connection_saturation_pct"] = (
        active / (active + idle).replace(0, np.nan) * 100
    ).fillna(0).clip(0, 100).round(2)

    # Taxa de bytes de rede por segundo
    df["net_rx_bps"] = (df.get("net_rx_bytes", 0).fillna(0) / 60.0).round(2)
    df["net_tx_bps"] = (df.get("net_tx_bytes", 0).fillna(0) / 60.0).round(2)

    # -------------------------------------------------------
    # Preenche NaN com 0 para todas as colunas numéricas.
    # Justificativa por coluna:
    #   - db_connections_active/idle, hikaricp_*: NaN para api-gateway
    #     porque ele não usa banco. O valor correto é 0.
    #   - net_rx/tx_bytes: NaN em coletas antigas onde o cAdvisor
    #     não tinha dados. Preenche com 0.
    #   - avg_total_duration_ms, throughput_rps, log_count etc.:
    #     NaN quando não havia tráfego naquele minuto -> 0 é correto.
    # -------------------------------------------------------
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    df[numeric_cols] = df[numeric_cols].fillna(0)

    # ----------------------------------------------------------
    # Ordenação final das colunas
    # ----------------------------------------------------------
    FINAL_COLUMNS = [
        "timestamp_min", "service", "node_ip",
        # Cenário de rede e infraestrutura
        "network_topology", "cluster_nodes",
        # CPU / Carga
        "cpu_process", "cpu_system", "load_1m",
        # Memória
        "memory_heap_used_bytes", "memory_heap_max_bytes", "memory_utilization_pct",
        # GC
        "gc_overhead_percent",
        # HTTP
        "http_requests_total", "http_requests_duration_s", "http_requests_max_latency_s",
        # Banco de dados
        "db_connections_active", "db_connections_idle", "db_connection_saturation_pct",
        "hikaricp_pending", "hikaricp_timeout_count",
        # Rede e Threads
        "net_rx_bytes", "net_tx_bytes", "threads_live",
        # Zipkin
        "avg_total_duration_ms", "avg_spans_count", "avg_db_query_count",
        "avg_db_total_duration_ms", "db_bottleneck_ratio", "error_rate",
        # Derivados
        "mrt_ms", "throughput_rps", "net_rx_bps", "net_tx_bps",
        # Loki
        "log_count", "log_error_rate",
    ]

    # Mantém apenas colunas que existem (tolerante a métricas ausentes)
    cols = [c for c in FINAL_COLUMNS if c in df.columns]
    df = df[cols].sort_values(["timestamp_min", "service", "node_ip"]).reset_index(drop=True)

    print(f"\n  Dataset final: {len(df):,} linhas × {len(df.columns)} colunas")
    return df


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Pré-processador: Prometheus + Zipkin + Loki -> dataset_final.csv"
    )
    parser.add_argument("--input_dir", default=INPUT_DIR,   help="Pasta com os CSVs brutos")
    parser.add_argument("--output",    default=OUTPUT_FILE,  help="Arquivo CSV de saída")
    parser.add_argument("--min_date",  default=None,
                        help="Filtra dados anteriores a esta data (ex: 2026-06-01). "
                             "Use para descartar coletas antigas incompatíveis.")
    args = parser.parse_args()

    print("=" * 65)
    print("  PRÉ-PROCESSAMENTO DE DADOS DE OBSERVABILIDADE")
    print("=" * 65)
    print(f"  Entrada  : {os.path.abspath(args.input_dir)}/")
    print(f"  Saída    : {os.path.abspath(args.output)}")
    print(f"  Data mín.: {args.min_date or 'sem filtro (todos os dados)'}")
    print("=" * 65)

    prom   = process_prometheus(args.input_dir)
    zipkin = process_zipkin(args.input_dir)
    loki   = process_loki(args.input_dir)
    final  = join_and_derive(prom, zipkin, loki)

    # Filtra por data mínima (remove dados de clusters antigos/incompatíveis)
    if args.min_date and not final.empty:
        cutoff = pd.Timestamp(args.min_date, tz="UTC")
        before = len(final)
        final = final[final["timestamp_min"] >= cutoff].reset_index(drop=True)
        print(f"\n  Filtro de data: {before - len(final)} linhas removidas (antes de {args.min_date})")
        print(f"  Linhas restantes: {len(final):,}")

    if final.empty:
        print("\n  ERRO: Dataset final vazio. Verifique os arquivos de entrada.")
        return

    final.to_csv(args.output, index=False)

    print("\n" + "=" * 65)
    print(f"  CONCLUÍDO! Arquivo salvo em: {os.path.abspath(args.output)}")
    print(f"  Linhas   : {len(final):,}")
    print(f"  Colunas  : {len(final.columns)}")
    print(f"\n  Lista de colunas geradas:")
    for i, col in enumerate(final.columns, 1):
        print(f"    {i:2d}. {col}")
    print("\n  Para usar no Google Colab:")
    print("    from google.colab import files")
    print("    files.upload()  # faça upload do dataset_final.csv")
    print("    import pandas as pd")
    print("    df = pd.read_csv('dataset_final.csv', parse_dates=['timestamp_min'])")
    print("    print(df.describe())")
    print("=" * 65)


if __name__ == "__main__":
    main()
