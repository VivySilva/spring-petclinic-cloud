#!/bin/bash
# ============================================================
# PORT-FORWARDS — Rode esse script no terminal do Ubuntu (WSL)
# Ele abre todas as portas necessárias e fica rodando.
# Pressione Ctrl+C para fechar tudo.
# ============================================================

NAMESPACE="spring-petclinic"

echo ""
echo "========================================"
echo "   ABRINDO PORT-FORWARDS DO CLUSTER"
echo "========================================"

# Autentica o sudo UMA VEZ aqui (guarda a credencial por ~15min)
# Isso permite que os processos em segundo plano usem sudo sem pedir senha
echo "Digite sua senha sudo para abrir as portas:"
sudo -v

pkill -f "k3s kubectl port-forward" 2>/dev/null
sleep 1

# Abre os 4 tunnels em segundo plano
sudo k3s kubectl port-forward --address 0.0.0.0 svc/api-gateway  -n $NAMESPACE 8080:80 &
PID_GW=$!
echo "  api-gateway  -> localhost:8080 (PID $PID_GW)"

sudo k3s kubectl port-forward --address 0.0.0.0 svc/prometheus   -n $NAMESPACE 9090:9090 &
PID_PROM=$!
echo "  prometheus   -> localhost:9090 (PID $PID_PROM)"

sudo k3s kubectl port-forward --address 0.0.0.0 svc/loki         -n $NAMESPACE 3100:3100 &
PID_LOKI=$!
echo "  loki         -> localhost:3100 (PID $PID_LOKI)"

sudo k3s kubectl port-forward --address 0.0.0.0 svc/zipkin       -n $NAMESPACE 9411:9411 &
PID_ZIPKIN=$!
echo "  zipkin       -> localhost:9411 (PID $PID_ZIPKIN)"

echo "========================================"
echo "  Portas abertas! Deixe esse terminal"
echo "  aberto e rode o run_experiment.ps1"
echo "  no PowerShell."
echo ""
echo "  Pressione Ctrl+C para encerrar tudo."
echo "========================================"
echo ""

# Função para limpar ao sair
cleanup() {
    echo ""
    echo "Encerrando port-forwards..."
    kill $PID_GW $PID_PROM $PID_LOKI $PID_ZIPKIN 2>/dev/null
    echo "Pronto!"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Mantém o script rodando enquanto as portas estiverem abertas
wait
