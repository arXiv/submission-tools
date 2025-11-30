#!/bin/bash

set -euo pipefail
IFS=$'\n\t'

# add proper reporting in case of -e errors, bash only
# see: https://utcc.utoronto.ca/~cks/space/blog/programming/BashGoodSetEReports
trap 'echo "Exit status $? at line $LINENO from: $BASH_COMMAND"' ERR


make app2023.docker
make app2025.docker
make EXTRA_DOCKER_ARGS=-d TEX2PDF_CPUS=3 TEX2PDF_WORKERS=3 app2023.run
make EXTRA_DOCKER_ARGS=-d TEX2PDF_CPUS=10 TEX2PDF_WORKERS=20 app2025.proxy.run-sandbox
