#!/bin/bash
echo "PWD=$PWD"
echo "WORKDIR=$WORKDIR"
echo "TEXINPUTS=$TEXINPUTS"
echo "docker run --rm --name latex -v $WORKDIR:/usr/src/app  -w /usr/src/app/in arxiv-tex2pdf-app:latest $*"
exec docker run --rm --name latex -v "$WORKDIR":/usr/src/app -w /usr/src/app/in arxiv-tex2pdf-app:latest $*
