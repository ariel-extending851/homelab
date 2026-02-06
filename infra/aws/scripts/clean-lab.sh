#!/bin/bash

# Cores para facilitar a leitura
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}==================================================${NC}"
echo -e "${RED}   💣 PROTOCOLO DE DESTRUIÇÃO - AWS NUKE (LOOP)   ${NC}"
echo -e "${YELLOW}==================================================${NC}"

# 1. Verifica em qual conta estamos logados
echo "Verificando credenciais atuais..."
IDENTITY=$(aws sts get-caller-identity --output json)
ACCOUNT_ID=$(echo $IDENTITY | grep -o '"Account": "[^"]*' | cut -d'"' -f4)
ARN=$(echo $IDENTITY | grep -o '"Arn": "[^"]*' | cut -d'"' -f4)

echo -e "Você está prestes a limpar a conta:"
echo -e "🆔 Account ID: ${GREEN}$ACCOUNT_ID${NC}"
echo -e "👤 User ARN:   ${GREEN}$ARN${NC}"
echo ""
echo -e "${RED}⚠️  CUIDADO: Isso vai rodar o aws-nuke 5 VEZES com --force.${NC}"
echo -e "${RED}    Todos os recursos não filtrados serão DESTRUÍDOS.${NC}"
echo ""

# 2. Pergunta de confirmação
read -p "Tem certeza absoluta que deseja continuar? Digite 'SIM' para confirmar: " CONFIRM

if [ "$CONFIRM" != "SIM" ]; then
    echo "Operação cancelada pelo usuário."
    exit 1
fi

echo ""
echo -e "${YELLOW}Iniciando em 5 segundos... (Pressione Ctrl+C para cancelar)${NC}"
for i in {5..1}; do echo -n "$i... "; sleep 1; done
echo "GO! 🚀"

# 3. O Loop de Insistência (Seu trecho original melhorado)
TOTAL_ATTEMPTS=5

for (( i=1; i<=TOTAL_ATTEMPTS; i++ ))
do
    echo ""
    echo -e "${YELLOW}--------------------------------------------------${NC}"
    echo -e "${YELLOW}   Tentativa de Nuke $i de $TOTAL_ATTEMPTS ${NC}"
    echo -e "${YELLOW}--------------------------------------------------${NC}"

    # Executa o nuke.
    # --force é usado para não pedir o alias a cada loop
    aws-nuke run --config config.yml --profile default --no-dry-run --force

    if [ $i -lt $TOTAL_ATTEMPTS ]; then
        echo ""
        echo -e "${GREEN}⏳ Aguardando 10 segundos para estabilização da AWS...${NC}"
        sleep 10
    fi
done

echo ""
echo -e "${GREEN}✅ Processo de loop finalizado.${NC}"
echo "Recomendação: Verifique o console AWS para garantir que tudo sumiu."
