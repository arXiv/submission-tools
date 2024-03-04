app_tag := arxiv-tex2pdf-app
app_name := tex2pdf_app
app_port := 6301
dockerport := 8080

TEX2PDF_CPUS := $(shell echo $${TEX2PDF_CPUS:-4})
TEX2PDF_WORKERS := $(shell echo $${TEX2PDF_WORKERS:-8})
TEX2PDF_DOCKER_PLATFORM := $(shell echo $${TEX2PDF_DOCKER_PLATFORM:-linux/amd64})

APP_DOCKER_RUN := docker run --cpus ${TEX2PDF_CPUS} --rm -p ${app_port}:${dockerport} -e PORT=${dockerport} -e WORKERS=${TEX2PDF_WORKERS} --name ${app_name} --security-opt="no-new-privileges=true" 

.PHONY: HELLO app.docker app.run app.stop bootstrap

default: HELLO venv/lib/python3.10/site-packages/fastapi

HELLO:
	@echo To see the README of this Makefile, type "make help"
	@echo Local HTTP port is ${app_port}
	@echo Docker command params is:
	@echo ${APP_DOCKER_RUN}


venv:
	python3 -m venv venv
	. venv/bin/activate && pip install --upgrade pip

venv/bin/poetry: venv
	. venv/bin/activate && pip install poetry

venv/lib/python3.10/site-packages/fastapi: venv/bin/poetry
	. venv/bin/activate && poetry install

bootstrap: venv/lib/python3.10/site-packages/fastapi

#-#
#-# Command: help
#-#   show this message
help:
	@awk '/^#-#/ { print substr($$0, 5)}' Makefile

#-#
#-# Command: app.docker
#-#   builds the applience docker image
app.docker:
	@if [ -n "$$INSIDE_EMACS" ]; then \
	  echo "Detected Emacs shell mode, stopping."; \
	  exit 1; \
	fi
	@echo "PLATFORM: ${PLATFORM}"
	@echo "dockerport: ${app_port}"
	@echo "tag: ${appl_tag}"
	@echo "name: ${app_name}"
	docker buildx build -f ./Appliance.Dockerfile  --platform=${TEX2PDF_DOCKER_PLATFORM} -t ${app_tag} .

#-#
#-# Command: app.run
#-#   runs the appliance container with the terminal attached (for test)
app.run: app.stop
	${APP_DOCKER_RUN} -it ${app_tag} 

#-#
#-# Command: app.stop
#-#   stops the appliance container
app.stop:
	-docker container kill ${app_name}
	-docker container rm ${app_name}

#-#
#-# Command: sh
#-#   runs a bash shell in the container to look inside of it
app.sh: app.stop
	${APP_DOCKER_RUN}  -v ${HOME}/Downloads:/home/worker/Downloads -w /home/worker -it ${app_tag} /bin/bash
