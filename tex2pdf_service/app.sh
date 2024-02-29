#!/bin/barh
cd /home/worker
if [ -z "$WORKERS" ]; then
    WORKERS=4
fi
export WORKERS
if [ -z "$PORT" ]; then
    PORT=8080
fi
export PORT
export TEXMFHOME=/usr/local/texlive/2023
. /home/worker/venv/bin/activate
echo "{\"message\": \"uvicorn --host 0.0.0.0 --port $PORT --log-config app-logging.conf --workers $WORKERS tex2pdf.tex2pdf_api:app\", \"level\": \"INFO\"}"
uvicorn --host 0.0.0.0 --port $PORT --log-config app-logging.conf --workers $WORKERS tex2pdf.tex2pdf_api:app