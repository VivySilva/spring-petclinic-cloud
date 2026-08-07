#!/bin/bash
# ============================================================
# ORQUESTRADOR DE MÚLTIPLOS EXPERIMENTOS
# Roda o run_experiment.sh em loop N vezes para gerar
# dados estatisticamente relevantes para o modelo de ML.
# ============================================================

NUM_EXECUCOES=6
PAUSA_MINIMA_SEGUNDOS=120       # Tempo mínimo de espera após cada experimento
TIMEOUT_READY_SEGUNDOS=300     # Tempo máximo de espera pelos pods (5 min)
NAMESPACE="spring-petclinic"

# ── Aguarda todos os pods ficarem Ready ──────────────────────────────────────
wait_pods_ready() {
    echo ""
    echo " -> Aguardando pods ficarem prontos (timeout: ${TIMEOUT_READY_SEGUNDOS}s)..."
    local elapsed=0
    while [ $elapsed -lt $TIMEOUT_READY_SEGUNDOS ]; do
        # Conta pods que NÃO estão Running/Ready
        local not_ready
        not_ready=$(sudo k3s kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
            | grep -v "Running" | grep -v "Completed" | wc -l)
        if [ "$not_ready" -eq 0 ]; then
            echo " -> Todos os pods estão prontos! ✓"
            return 0
        fi
        printf "\r -> %d pod(s) ainda não estão prontos. Aguardando... (%ds)" \
            "$not_ready" "$elapsed"
        sleep 10
        elapsed=$((elapsed + 10))
    done
    echo ""
    echo " AVISO: Timeout aguardando pods! Continuando mesmo assim..."
}

echo "=========================================================="
echo " INICIANDO BATERIA DE $NUM_EXECUCOES EXPERIMENTOS"
echo "=========================================================="
echo " Cada execução rodará as configurações do run_experiment.sh"
echo " Pausa mínima de ${PAUSA_MINIMA_SEGUNDOS}s + espera ativa pelos pods."
echo " Pressione Ctrl+C a qualquer momento para abortar tudo."
echo "=========================================================="
echo ""

for (( i=1; i<=NUM_EXECUCOES; i++ ))
do
    echo "=========================================================="
    echo " INICIANDO EXECUÇÃO $i DE $NUM_EXECUCOES"
    echo "=========================================================="

    # Chama o script de experimento principal
    bash run_experiment.sh

    # Se for a última execução, não precisa pausar
    if [ $i -lt $NUM_EXECUCOES ]; then
        echo ""
        echo " -> Execução $i concluída."
        echo " -> Cooldown mínimo de ${PAUSA_MINIMA_SEGUNDOS} segundos..."

        # Pausa mínima com contagem regressiva
        for (( c=PAUSA_MINIMA_SEGUNDOS; c>0; c-- ))
        do
            printf "\r -> Aguardando: %d s " "$c"
            sleep 1
        done
        echo ""

        # Espera ativa: verifica se todos os pods voltaram ao estado Ready
        wait_pods_ready
        echo ""
    fi
done

echo ""
echo "=========================================================="
echo " PARABÉNS! BATERIA DE $NUM_EXECUCOES EXPERIMENTOS CONCLUÍDA!"
echo " Verifique a pasta collect_data/ para ver todos os CSVs gerados."
echo "=========================================================="

