#!/bin/bash
# ============================================================
# ORQUESTRADOR COMPLETO DO EXPERIMENTO
# Rode este script no terminal do Ubuntu (WSL)
# ============================================================
# Faz tudo automaticamente:
#   1. Abre os port-forwards do K3s
#   2. Inicia o collect_data.py em segundo plano
#   3. Estressando a aplicação pelo tempo configurado
#   4. Encerra tudo e mostra o resumo
# ============================================================

# ============================================================
#  VARIÁVEIS DE CONFIGURAÇÃO — edite aqui conforme necessidade
# ============================================================

DURACAO_MINUTOS=5
REQUISICOES_POR_SEGUNDO=20
NAMESPACE="spring-petclinic"

# Caminho do script Python de coleta
SCRIPT_COLETA="/mnt/c/Users/vivys/Documents/spring-petclinic-cloud/collect_data.py"

# ============================================================
#  CÁLCULO INTERNO (não edite abaixo)
# ============================================================

DURACAO_SEGUNDOS=$((DURACAO_MINUTOS * 60))
PAUSA_MS=$(echo "scale=3; 1 / $REQUISICOES_POR_SEGUNDO" | bc)
API_URL="http://localhost:80"

ENDPOINTS=(
    "$API_URL/api/customer/owners"
    "$API_URL/api/customer/owners/1"
    "$API_URL/api/vet/vets"
    "$API_URL/api/visit/owners/1/pets/1/visits"
)

contador_ok=0
contador_erros=0
pid_coleta=""
pids_pf=()

# ============================================================
#  FUNÇÃO DE LIMPEZA
# ============================================================
cleanup() {
    echo ""
    echo ""
    echo "[4/4] Encerrando todos os processos..."

    [ -n "$pid_coleta" ] && kill "$pid_coleta" 2>/dev/null && echo "      collect_data.py encerrado."

    for pid in "${pids_pf[@]}"; do
        kill "$pid" 2>/dev/null
    done
    pkill -f "k3s kubectl port-forward" 2>/dev/null
    echo "      Port-forwards encerrados."

    echo ""
    echo "========================================"
    echo "   EXPERIMENTO CONCLUIDO!"
    echo "========================================"
    echo "  Requisicoes OK:  $contador_ok"
    echo "  Erros de rede:   $contador_erros"
    echo "  Dados salvos em: /mnt/c/Users/vivys/Documents/spring-petclinic-cloud/collect_data/"
    echo "========================================"
    echo ""
    exit 0
}

trap cleanup SIGINT SIGTERM

# ============================================================
#  INÍCIO
# ============================================================

echo ""
echo "========================================"
echo "   INICIANDO EXPERIMENTO DE ESTRESSE"
echo "========================================"
echo "  Duração:             $DURACAO_MINUTOS minutos"
echo "  Requisições/segundo: $REQUISICOES_POR_SEGUNDO RPS"
echo "  Total estimado:      ~$((DURACAO_SEGUNDOS * REQUISICOES_POR_SEGUNDO)) requisições"
echo "========================================"
echo ""

# --- Passo 1: Autentica sudo e abre port-forwards ---
echo "[1/4] Abrindo port-forwards..."
echo "      (Se pedir senha, digite agora)"
sudo -v

pkill -f "k3s kubectl port-forward" 2>/dev/null
sleep 1

sudo k3s kubectl port-forward svc/api-gateway  -n $NAMESPACE 80:80   &
pids_pf+=($!)
echo "      api-gateway  -> localhost:80"

sudo k3s kubectl port-forward svc/prometheus   -n $NAMESPACE 9090:9090 &
pids_pf+=($!)
echo "      prometheus   -> localhost:9090"

sudo k3s kubectl port-forward svc/loki         -n $NAMESPACE 3100:3100 &
pids_pf+=($!)
echo "      loki         -> localhost:3100"

sudo k3s kubectl port-forward svc/zipkin       -n $NAMESPACE 9411:9411 &
pids_pf+=($!)
echo "      zipkin       -> localhost:9411"

echo "      Aguardando as portas ficarem prontas..."
sleep 5

# --- Verifica se a porta do API Gateway está respondendo ---
if ! curl -sf "$API_URL/api/customer/owners" > /dev/null 2>&1; then
    echo ""
    echo "  AVISO: API Gateway não respondeu em $API_URL"
    echo "  Aguardando mais 10 segundos..."
    sleep 10
fi

# --- Passo 2: Inicia a coleta de dados ---
echo ""
echo "[2/4] Iniciando coleta de dados (collect_data.py)..."
python3 "$SCRIPT_COLETA" &
pid_coleta=$!
sleep 2
echo "      Coleta iniciada com PID: $pid_coleta"

# --- Passo 3: Estresse ---
echo ""
echo "[3/4] Estressando a aplicação por $DURACAO_MINUTOS minuto(s)..."
echo "      Pressione Ctrl+C para interromper antes do tempo."
echo ""

fim=$((SECONDS + DURACAO_SEGUNDOS))

while [ $SECONDS -lt $fim ]; do
    idx=$((RANDOM % ${#ENDPOINTS[@]}))
    url="${ENDPOINTS[$idx]}"

    if curl -sf "$url" -o /dev/null --max-time 5 2>/dev/null; then
        contador_ok=$((contador_ok + 1))
    else
        contador_erros=$((contador_erros + 1))
    fi

    total=$((contador_ok + contador_erros))
    if [ $((total % 5)) -eq 0 ]; then
        restante=$((fim - SECONDS))
        printf "\r      OK: %d | Erros: %d | Restante: %ds   " \
            "$contador_ok" "$contador_erros" "$restante"
    fi

    sleep "$PAUSA_MS"
done

cleanup
