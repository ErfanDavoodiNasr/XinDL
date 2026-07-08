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
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=15"
RSYNC_EXCLUDES=(
    --exclude 'venv/'
    --exclude '.git/'
    --exclude 'data/'
    --exclude 'downloads/'
    --exclude '__pycache__/'
    --exclude 'cookies/cookies.txt'
    --exclude 'cookies.txt'
    --exclude '.DS_Store'
    --exclude '._*'
)

function remote_exec() {
    sshpass -p "$SERVER_PASSWORD" ssh $SSH_OPTS "$SERVER_USER@$SERVER_IP" "$@"
}

function sync_project() {
    echo -e "${YELLOW}[*] Syncing project files to server...${NC}"

    if remote_exec "command -v rsync >/dev/null"; then
        sshpass -p "$SERVER_PASSWORD" rsync -az --delete \
            "${RSYNC_EXCLUDES[@]}" \
            -e "ssh $SSH_OPTS" \
            ./ "$SERVER_USER@$SERVER_IP:$PROJECT_DIR/"
    else
        echo -e "${YELLOW}[*] rsync not found on server, using compressed archive...${NC}"
        find . -type f -name '._*' -delete
        COPYFILE_DISABLE=1 tar \
            --exclude='venv' --exclude='.git' --exclude='data' \
            --exclude='downloads' --exclude='__pycache__' \
            --exclude='cookies/cookies.txt' --exclude='cookies.txt' \
            --exclude='.DS_Store' \
            -czf /tmp/xindl_deploy.tar.gz .
        remote_exec "mkdir -p $PROJECT_DIR"
        sshpass -p "$SERVER_PASSWORD" scp $SSH_OPTS /tmp/xindl_deploy.tar.gz "$SERVER_USER@$SERVER_IP:$PROJECT_DIR/"
        remote_exec "cd $PROJECT_DIR && tar -xzf xindl_deploy.tar.gz && rm -f xindl_deploy.tar.gz"
        rm -f /tmp/xindl_deploy.tar.gz
    fi

    echo -e "${GREEN}[+] Upload complete.${NC}"
}

function deploy_bot() {
    find . -type f -name '._*' -delete 2>/dev/null || true
    echo -e "\n${YELLOW}[*] Starting Deployment...${NC}"

    if ! command -v sshpass &> /dev/null; then
        echo -e "${RED}[!] Error: 'sshpass' is required.${NC}"
        exit 1
    fi

    remote_exec "mkdir -p $PROJECT_DIR"
    sync_project

    echo -e "${YELLOW}[*] Configuring and deploying on remote server...${NC}"
    remote_exec PROJECT_DIR="$PROJECT_DIR" 'bash -s' << 'EOF'
        RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
        set -e
        trap 'echo -e "${RED}[!] An error occurred during remote deployment.${NC}"' ERR

        if ! command -v docker &> /dev/null; then
            echo -e "${YELLOW}[*] Installing Docker...${NC}"
            curl -fsSL https://get.docker.com -o get-docker.sh
            CHANNEL=stable sh get-docker.sh
            rm -f get-docker.sh
        fi

        if ! command -v rsync &> /dev/null; then
            echo -e "${YELLOW}[*] Installing rsync for faster future deploys...${NC}"
            apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq rsync
        fi

        mkdir -p /etc/docker
        if [ ! -f /etc/docker/daemon.json ] || ! grep -q '"dns"' /etc/docker/daemon.json 2>/dev/null; then
            echo -e "${YELLOW}[*] Configuring Docker DNS...${NC}"
            cat > /etc/docker/daemon.json <<'DOCKERCFG'
{
  "dns": ["8.8.8.8", "8.8.4.4", "1.1.1.1"],
  "max-concurrent-downloads": 10
}
DOCKERCFG
            systemctl restart docker
            sleep 2
        fi

        export DOCKER_BUILDKIT=1
        export COMPOSE_DOCKER_CLI_BUILD=1

        cd "$PROJECT_DIR"

        echo -e "${YELLOW}[*] Building and starting containers (host networking)...${NC}"
        docker compose up -d --build --remove-orphans

        echo -e "${GREEN}[+] Deployment Completed Successfully!${NC}"
        docker compose ps
EOF
}

function view_logs() {
    echo -e "\n${CYAN}[*] Fetching live logs (Press Ctrl+C to exit)...${NC}"
    sshpass -p "$SERVER_PASSWORD" ssh -t $SSH_OPTS "$SERVER_USER@$SERVER_IP" "cd $PROJECT_DIR && docker compose logs --tail=50 -f"
}

function view_status() {
    echo -e "\n${CYAN}[*] Checking service status...${NC}"
    sshpass -p "$SERVER_PASSWORD" ssh -t $SSH_OPTS "$SERVER_USER@$SERVER_IP" "cd $PROJECT_DIR && docker compose ps && echo && docker compose logs --tail=20 bot"
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
