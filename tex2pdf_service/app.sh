#!/bin/bash
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
# uvicorn --host 0.0.0.0 --port $PORT --log-config app-logging.conf --workers $WORKERS tex2pdf.tex2pdf_api:app
# granian --http 2 --interface asgi --no-ws --host 0.0.0.0 --port $PORT --log-config app-logging.json --workers $WORKERS tex2pdf.tex2pdf_api:app
hypercorn --config hypercorn-config.toml --bind 0.0.0.0:$PORT --log-config app-logging.conf --workers $WORKERS tex2pdf.tex2pdf_api:app
