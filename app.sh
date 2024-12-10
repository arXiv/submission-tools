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
#export TEXMFHOME=/usr/local/texlive/2023
#. /home/worker/venv/bin/activate
hypercorn --config hypercorn-config.toml --bind 0.0.0.0:$PORT --log-config app-logging.conf --workers $WORKERS tex2pdf.service.tex2pdf_api:app
