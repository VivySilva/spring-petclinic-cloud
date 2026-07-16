#!/bin/bash
# ============================================================
# ORQUESTRADOR DE MÚLTIPLOS EXPERIMENTOS
# Roda o run_experiment.sh em loop N vezes para gerar
# dados estatisticamente relevantes para o modelo de ML.
# ============================================================

NUM_EXECUCOES=10
PAUSA_ENTRE_EXECUCOES_SEGUNDOS=30

echo "=========================================================="
echo " INICIANDO BATERIA DE $NUM_EXECUCOES EXPERIMENTOS"
echo "=========================================================="
echo " Cada execução rodará as configurações do run_experiment.sh"
echo " Pausa de $PAUSA_ENTRE_EXECUCOES_SEGUNDOS segundos entre execuções."
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
        echo " -> Iniciando período de resfriamento (cooldown) de $PAUSA_ENTRE_EXECUCOES_SEGUNDOS segundos..."
        echo " -> Isso permite que as métricas do cluster voltem ao estado normal."
        
        # Pausa com contagem regressiva
        for (( c=$PAUSA_ENTRE_EXECUCOES_SEGUNDOS; c>0; c-- ))
        do
            printf "\r Aguardando: %d s " "$c"
            sleep 1
        done
        echo -e "\r Cooldown finalizado. Preparando próxima execução...\n"
    fi
done

echo ""
echo "=========================================================="
echo " PARABÉNS! BATERIA DE $NUM_EXECUCOES EXPERIMENTOS CONCLUÍDA!"
echo " Verifique a pasta collect_data/ para ver todos os CSVs gerados."
echo "=========================================================="
