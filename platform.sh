#!/bin/bash

# ==============================================================================
# XinDL Platform Manager
# Interactive menu for deploying and monitoring your bot
# ==============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Load Config
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
else
    echo -e "${RED}[!] Error: No local .env file found. Please create one from .env.example!${NC}"
    exit 1
fi

if [ -z "$SERVER_IP" ] || [ -z "$SERVER_PASSWORD" ]; then
    echo -e "${RED}[!] Error: SERVER_IP or SERVER_PASSWORD is missing in your .env file.${NC}"
    exit 1
fi

SERVER_USER=${SERVER_USER:-root}
PROJECT_DIR=${PROJECT_DIR:-/opt/XinDL}

function deploy_bot() {
    find . -type f -name '._*' -delete && find . -depth -type d -empty -delete
    echo -e "\n${YELLOW}[*] Starting Deployment...${NC}"
    
    if ! command -v sshpass &> /dev/null; then
        echo -e "${RED}[!] Error: 'sshpass' is required.${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}[*] Compressing local project for upload...${NC}"
    tar --exclude='venv' --exclude='.git' --exclude='data' --exclude='downloads' --exclude='__pycache__' -czf /tmp/xindl_deploy.tar.gz .
    
    echo -e "${YELLOW}[*] Creating target directory on server...${NC}"
    sshpass -p "$SERVER_PASSWORD" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$SERVER_USER@$SERVER_IP" "mkdir -p $PROJECT_DIR"
    
    echo -e "${YELLOW}[*] Uploading project files to server...${NC}"
    sshpass -p "$SERVER_PASSWORD" scp -o StrictHostKeyChecking=no /tmp/xindl_deploy.tar.gz "$SERVER_USER@$SERVER_IP:$PROJECT_DIR/"
    echo -e "${GREEN}[+] Upload complete.${NC}"
    rm /tmp/xindl_deploy.tar.gz
    
    echo -e "${YELLOW}[*] Configuring and deploying on remote server...${NC}"
    sshpass -p "$SERVER_PASSWORD" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$SERVER_USER@$SERVER_IP" PROJECT_DIR="$PROJECT_DIR" 'bash -s' << 'EOF'
        RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
        set -e
        trap 'echo -e "${RED}[!] An error occurred during remote deployment.${NC}"' ERR

        if ! command -v docker &> /dev/null; then
            echo -e "${YELLOW}[*] Installing Docker...${NC}"
            curl -fsSL https://get.docker.com -o get-docker.sh
            CHANNEL=stable sh get-docker.sh
            rm get-docker.sh
        fi

        cd "$PROJECT_DIR"
        tar -xzf xindl_deploy.tar.gz
        rm xindl_deploy.tar.gz

        echo -e "${YELLOW}[*] Starting containers...${NC}"
        docker compose down || true
        docker compose up -d --build
        docker image prune -f
        
        echo -e "${GREEN}[+] Deployment Completed Successfully!${NC}"
EOF
}

function view_logs() {
    echo -e "\n${CYAN}[*] Fetching live logs (Press Ctrl+C to exit)...${NC}"
    sshpass -p "$SERVER_PASSWORD" ssh -t -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$SERVER_USER@$SERVER_IP" "cd $PROJECT_DIR && docker compose logs --tail=50 -f"
}

function view_status() {
    echo -e "\n${CYAN}[*] Checking service status...${NC}"
    sshpass -p "$SERVER_PASSWORD" ssh -t -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$SERVER_USER@$SERVER_IP" "cd $PROJECT_DIR && docker compose ps"
}

# Main Menu Loop
while true; do
    echo -e "\n${BLUE}==========================================${NC}"
    echo -e "${BLUE}        XinDL Platform Manager            ${NC}"
    echo -e "${BLUE}==========================================${NC}"
    echo -e "Server: ${GREEN}${SERVER_IP}${NC} | User: ${GREEN}${SERVER_USER}${NC}"
    echo -e "------------------------------------------"
    echo -e "1) 🚀 Deploy / Update Bot"
    echo -e "2) 📋 View Live Logs"
    echo -e "3) 📊 Check Docker Status"
    echo -e "4) 🚪 Exit"
    echo -e "------------------------------------------"
    read -p "Select an option [1-4]: " choice

    case $choice in
        1) deploy_bot ;;
        2) view_logs ;;
        3) view_status ;;
        4) echo -e "${GREEN}Goodbye!${NC}"; exit 0 ;;
        *) echo -e "${RED}Invalid option. Please select 1-4.${NC}" ;;
    esac
done
