#!/bin/bash
echo "PWD=$PWD"
echo "WORKDIR=$WORKDIR"
echo "docker run --rm --name latex -v $WORKDIR:/usr/src/app  -w /usr/src/app/in arxiv-gcp-genpdf:latest $*"
exec docker run --rm --name latex -v "$WORKDIR":/usr/src/app -w /usr/src/app/in arxiv-gcp-genpdf:latest $*
