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
REQUISICOES_POR_SEGUNDO=300
NAMESPACE="spring-petclinic"

# Caminho do script Python de coleta
SCRIPT_COLETA="/mnt/c/Users/vivys/Documents/spring-petclinic-cloud/collect_data.py"

# ============================================================
#  CÁLCULO INTERNO (não edite abaixo)
# ============================================================

DURACAO_SEGUNDOS=$((DURACAO_MINUTOS * 60))
PAUSA_MS=$(echo "scale=3; 1 / $REQUISICOES_POR_SEGUNDO" | bc)
API_URL="http://localhost:30080"

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
    echo "  Dados salvos em: /mnt/c/Users/vivys/Documents/spring-petclinic-cloud/collect_data/"
    echo "  Veja o resumo de requests no log do k6 acima."
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

# --- Passo 1: Verifica conectividade ---
echo "[1/4] Verificando acesso aos serviços NodePort..."
echo "      (Se pedir senha sudo, digite agora)"
sudo -v


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
echo "      Usando k6 para carga concorrente a $REQUISICOES_POR_SEGUNDO RPS..."
echo "      Pressione Ctrl+C para interromper antes do tempo."
echo ""

# Executa o k6 e repassa as variáveis de ambiente
k6 run --env API_URL="$API_URL" --env RPS="$REQUISICOES_POR_SEGUNDO" --env DURATION="${DURACAO_MINUTOS}m" "/mnt/c/Users/vivys/Documents/spring-petclinic-cloud/k6_script.js"

cleanup

