app_tag := public-tex2pdf-app

app_2023_name := public_tex2pdf_2023_app
app_2023_port := 6301
app_2024_name := public_tex2pdf_2024_app
app_2024_port := 6302
app_2025_name := public_tex2pdf_2025_app
app_2025_port := 6303

dockerport := 8080

TEXLIVE_2023_BASE_RELEASE := 2023
TEXLIVE_2023_BASE_IMAGE_DATE := 2023-05-21
base_2023_tag_version := ${TEXLIVE_2023_BASE_RELEASE}-${TEXLIVE_2023_BASE_IMAGE_DATE}
TEXLIVE_2024_BASE_RELEASE := 2024
TEXLIVE_2024_BASE_IMAGE_DATE := 2024-12-29
base_2024_tag_version := ${TEXLIVE_2024_BASE_RELEASE}-${TEXLIVE_2024_BASE_IMAGE_DATE}
TEXLIVE_2025_BASE_RELEASE := 2025
TEXLIVE_2025_BASE_IMAGE_DATE := 2025-08-03
base_2025_tag_version := ${TEXLIVE_2025_BASE_RELEASE}-${TEXLIVE_2025_BASE_IMAGE_DATE}

ROOT_DIR := $(shell pwd)
TEX2PDF_CPUS := $(shell echo $${TEX2PDF_CPUS:-4})
TEX2PDF_WORKERS := $(shell echo $${TEX2PDF_WORKERS:-8})
TEX2PDF_DOCKER_PLATFORM := $(shell echo $${TEX2PDF_DOCKER_PLATFORM:-linux/amd64})

EXTRA_DOCKER_ARGS ?= 

APP_DOCKER_RUN := docker run --cpus ${TEX2PDF_CPUS} --rm -e PORT=${dockerport} -e WORKERS=${TEX2PDF_WORKERS} --security-opt="no-new-privileges=true" ${EXTRA_DOCKER_ARGS}

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
#-#   builds the appliance docker images for 2023, 2024, and 2025
app.docker: app2023.docker app2024.docker app2025.docker


app2023.docker:
	@if [ -n "$$INSIDE_EMACS" ]; then \
	  echo "Detected Emacs shell mode, stopping."; \
	  exit 1; \
	fi
	@echo "PLATFORM: ${PLATFORM}"
	@echo "dockerport: ${app_2023_port}"
	@echo "tag: ${app_tag}-${base_2023_tag_version}:latest"
	docker buildx build -f ./Appliance.Dockerfile \
		--progress=plain \
		--build-arg TEXLIVE_BASE_RELEASE=${TEXLIVE_2023_BASE_RELEASE} \
		--build-arg TEXLIVE_BASE_IMAGE_DATE=${TEXLIVE_2023_BASE_IMAGE_DATE} \
		--build-arg GIT_COMMIT_HASH=$(shell git rev-parse --short HEAD) \
		--platform=linux/amd64 -t ${app_tag}-${base_2023_tag_version}:latest .

app2024.docker:
	@if [ -n "$$INSIDE_EMACS" ]; then \
	  echo "Detected Emacs shell mode, stopping."; \
	  exit 1; \
	fi
	@echo "PLATFORM: ${PLATFORM}"
	@echo "dockerport: ${app_2024_port}"
	@echo "tag: ${app_tag}-${base_2024_tag_version}:latest"
	docker buildx build -f ./Appliance.Dockerfile \
		--progress=plain \
		--build-arg TEXLIVE_BASE_RELEASE=${TEXLIVE_2024_BASE_RELEASE} \
		--build-arg TEXLIVE_BASE_IMAGE_DATE=${TEXLIVE_2024_BASE_IMAGE_DATE} \
		--build-arg GIT_COMMIT_HASH=$(shell git rev-parse --short HEAD) \
		--platform=linux/amd64 -t ${app_tag}-${base_2024_tag_version}:latest .

app2025.docker:
	@if [ -n "$$INSIDE_EMACS" ]; then \
	  echo "Detected Emacs shell mode, stopping."; \
	  exit 1; \
	fi
	@echo "PLATFORM: ${PLATFORM}"
	@echo "dockerport: ${app_2025_port}"
	@echo "tag: ${app_tag}-${base_2025_tag_version}:latest"
	docker buildx build -f ./Appliance.Dockerfile \
		--progress=plain \
		--build-arg TEXLIVE_BASE_RELEASE=${TEXLIVE_2025_BASE_RELEASE} \
		--build-arg TEXLIVE_BASE_IMAGE_DATE=${TEXLIVE_2025_BASE_IMAGE_DATE} \
		--build-arg GIT_COMMIT_HASH=$(shell git rev-parse --short HEAD) \
		--platform=linux/amd64 -t ${app_tag}-${base_2025_tag_version}:latest .


# Our test setup is:
# - default proxy enabled container: 2024
# - 2023 is a possible proxy target
# - 2025 is defined but not listed in the TEX2PDF_SCOPES, but is allowed to be selected
#        via ZZRM.texlive_version

#-#
#-# Command: app.run
#-#   runs the appliance container with the terminal attached (for test)
app.run: app.stop app2023.run app2024.run app2025.run

app2023.run:
	${APP_DOCKER_RUN} -it --name ${app_2023_name} -p ${app_2023_port}:${dockerport} \
		${app_tag}-${base_2023_tag_version}:latest

# 2024 is run a the frontend proxy and thus needs the env vars set for proxying,
# and also needs to run on the host network

app2024.run:
	${APP_DOCKER_RUN} -it --name ${app_2024_name} -p ${app_2024_port}:${dockerport} \
		${app_tag}-${base_2024_tag_version}:latest

app2024.proxy.run:
	${APP_DOCKER_RUN} -it --name ${app_2024_name} -p ${app_2024_port}:${dockerport} \
        --env-file tests/local-proxy-test.env \
        --network host \
		${app_tag}-${base_2024_tag_version}:latest

app2025.run:
	${APP_DOCKER_RUN} -it --name ${app_2025_name} -p ${app_2025_port}:${dockerport} \
		${app_tag}-${base_2025_tag_version}:latest

app2025.proxy.run:
	${APP_DOCKER_RUN} -it --name ${app_2025_name} -p ${app_2025_port}:${dockerport} \
        --env-file tests/local-proxy-test-2025.env \
        --network host \
		${app_tag}-${base_2025_tag_version}:latest

app2025.run-sandbox:
	${APP_DOCKER_RUN} --runtime=runsc -d -it --name ${app_2025_name} -p ${app_2025_port}:${dockerport} \
		-e ENABLE_SANDBOX=1 \
		${app_tag}-${base_2025_tag_version}:latest

#-#
#-# Command: app.stop
#-#   stops the appliance container
app.stop:
	-docker container kill ${app_2023_name}
	-docker container rm ${app_2023_name}
	-docker container kill ${app_2024_name}
	-docker container rm ${app_2024_name}
	-docker container kill ${app_2025_name}
	-docker container rm ${app_2025_name}

#-#
#-# Command: sh
#-#   runs a bash shell in the container to look inside of it
app.sh: app.stop
	${APP_DOCKER_RUN}  -v ${HOME}/Downloads:/home/worker/Downloads -w /home/worker -it ${app_tag}-${base_tag_version}:latest  /bin/bash


