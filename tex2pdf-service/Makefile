app_tag := public-tex2pdf-app
app_name := public_tex2pdf_app
app_port := 6301
dockerport := 8080

TEXLIVE_BASE_RELEASE := 2023
TEXLIVE_BASE_IMAGE_DATE := 2023-05-21
base_tag_version := ${TEXLIVE_BASE_RELEASE}-${TEXLIVE_BASE_IMAGE_DATE}


ROOT_DIR := $(shell pwd)
TEX2PDF_CPUS := $(shell echo $${TEX2PDF_CPUS:-4})
TEX2PDF_WORKERS := $(shell echo $${TEX2PDF_WORKERS:-8})
TEX2PDF_DOCKER_PLATFORM := $(shell echo $${TEX2PDF_DOCKER_PLATFORM:-linux/amd64})

APP_DOCKER_RUN := docker run --cpus ${TEX2PDF_CPUS} --rm -p ${app_port}:${dockerport} -e PORT=${dockerport} -e WORKERS=${TEX2PDF_WORKERS} --name ${app_name} --security-opt="no-new-privileges=true"

.PHONY: HELLO app.docker app.run app.stop

default: HELLO

HELLO:
	@echo To see the README of this Makefile, type "make help"
	@echo Local HTTP port is ${app_port}
	@echo Docker command params is:
	@echo ${APP_DOCKER_RUN}


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
	docker buildx build -f ./Appliance.Dockerfile \
		--progress=plain \
	        --build-arg TEXLIVE_BASE_RELEASE=${TEXLIVE_BASE_RELEASE} \
		--build-arg TEXLIVE_BASE_IMAGE_DATE=${TEXLIVE_BASE_IMAGE_DATE} \
		--build-arg GIT_COMMIT_HASH=$(shell git rev-parse --short HEAD) \
		--platform=linux/amd64 -t ${app_tag}-${base_tag_version}:latest .

#-#
#-# Command: app.run
#-#   runs the appliance container with the terminal attached (for test)
app.run: app.stop
	${APP_DOCKER_RUN} -it ${app_tag}-${base_tag_version}:latest

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
	${APP_DOCKER_RUN}  -v ${HOME}/Downloads:/home/worker/Downloads -w /home/worker -it ${app_tag}-${base_tag_version}:latest  /bin/bash


