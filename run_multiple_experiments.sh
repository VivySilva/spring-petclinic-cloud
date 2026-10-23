#!/bin/bash
# ============================================================
# ORQUESTRADOR DE MÚLTIPLOS EXPERIMENTOS AUTOMATIZADO
# Executa baterias de testes variando as cargas (RPS)
# para coletar os dados completos de desempenho e auto-scaling.
# ============================================================

# Cargas a serem testadas (RPS)
CARGAS=(6 60 120 180 240 300)

# Quantidade de repetições para cada patamar de carga
REPETICOES_POR_CARGA=3

# Pasta onde os novos CSVs serão salvos (isolada da configuração antiga)
DIR_SAIDA="collect_data_v2"

PAUSA_MINIMA_SEGUNDOS=120       # Tempo mínimo de espera após cada experimento (cooldown)
TIMEOUT_READY_SEGUNDOS=300     # Tempo máximo de espera pelos pods (5 min)
NAMESPACE="spring-petclinic"

TOTAL_EXECUCOES=$(( ${#CARGAS[@]} * REPETICOES_POR_CARGA ))

# ── Aguarda todos os pods ficarem Ready ──────────────────────────────────────
wait_pods_ready() {
    echo ""
    echo " -> Aguardando pods ficarem prontos e HPA desescalar (timeout: ${TIMEOUT_READY_SEGUNDOS}s)..."
    local elapsed=0
    while [ $elapsed -lt $TIMEOUT_READY_SEGUNDOS ]; do
        # Conta pods que NÃO estão Running/Ready
        local not_ready
        not_ready=$(sudo k3s kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
            | grep -v "Running" | grep -v "Completed" | wc -l)
        if [ "$not_ready" -eq 0 ]; then
            echo " -> Todos os pods estão prontos e estabilizados! ✓"
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
echo " INICIANDO BATERIA COMPLETA DE EXPERIMENTOS"
echo "=========================================================="
echo " Cargas a testar:         ${CARGAS[*]} RPS"
echo " Repetições por carga:    $REPETICOES_POR_CARGA"
echo " Total de execuções:      $TOTAL_EXECUCOES"
echo " Pasta de destino:        $DIR_SAIDA/"
echo " Cooldown entre testes:   ${PAUSA_MINIMA_SEGUNDOS}s + verificação ativa de pods"
echo " Pressione Ctrl+C a qualquer momento para abortar tudo."
echo "=========================================================="
echo ""

# Cria a pasta de saída se não existir
mkdir -p "$DIR_SAIDA"

execucao_atual=0

for carga in "${CARGAS[@]}"
do
    for (( rep=1; rep<=REPETICOES_POR_CARGA; rep++ ))
    do
        execucao_atual=$((execucao_atual + 1))

        echo "=========================================================="
        echo " EXECUÇÃO $execucao_atual DE $TOTAL_EXECUCOES"
        echo " CARGA ATUAL: $carga RPS (Repetição $rep de $REPETICOES_POR_CARGA)"
        echo "=========================================================="

        # Executa o experimento com a carga e pasta corretas
        OUTPUT_DIR="$DIR_SAIDA" bash run_experiment.sh "$carga"

        # Se não for a última execução geral, faz o resfriamento
        if [ $execucao_atual -lt $TOTAL_EXECUCOES ]; then
            echo ""
            echo " -> Execução $execucao_atual concluída."
            echo " -> Cooldown mínimo de ${PAUSA_MINIMA_SEGUNDOS} segundos para os pods desescalarem..."

            # Pausa mínima com contagem regressiva
            for (( c=PAUSA_MINIMA_SEGUNDOS; c>0; c-- ))
            do
                printf "\r -> Aguardando resfriamento: %d s " "$c"
                sleep 1
            done
            echo ""

            # Espera ativa: verifica se todos os pods voltaram ao estado Ready
            wait_pods_ready
            echo ""
        fi
    done
done

echo ""
echo "=========================================================="
echo " PARABÉNS! TODAS AS $TOTAL_EXECUCOES EXECUÇÕES FORAM CONCLUÍDAS!"
echo " Todos os dados foram salvos com sucesso na pasta: $DIR_SAIDA/"
echo " Próximo passo recomendado:"
echo "   python preprocess.py --input_dir $DIR_SAIDA --output dataset_final_v2.csv"
echo "=========================================================="
