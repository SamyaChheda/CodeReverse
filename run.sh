#!/usr/bin/env bash
# Start the event server on the organiser PC.
cd "$(dirname "$0")"
python3 -c "import flask" 2>/dev/null || { echo "Flask missing. Run: sudo apt install -y python3-flask"; exit 1; }
IP=$(hostname -I | awk '{print $1}')
echo "=============================================="
echo " Participants open :  http://$IP:${CRE_PORT:-5000}/"
echo " Organiser page    :  http://localhost:${CRE_PORT:-5000}/admin"
echo "=============================================="
exec python3 app.py
