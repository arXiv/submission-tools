app_tag := arxiv-tex2pdf-app
app_name := tex2pdf_app
app_port := 6301
dockerport := 8080

ROOT_DIR := $(shell pwd)
TEX2PDF_CPUS := $(shell echo $${TEX2PDF_CPUS:-4})
TEX2PDF_WORKERS := $(shell echo $${TEX2PDF_WORKERS:-8})
TEX2PDF_DOCKER_PLATFORM := $(shell echo $${TEX2PDF_DOCKER_PLATFORM:-linux/amd64})

APP_DOCKER_RUN := docker run --cpus ${TEX2PDF_CPUS} --rm -p ${app_port}:${dockerport} -e PORT=${dockerport} -e WORKERS=${TEX2PDF_WORKERS} --name ${app_name} --security-opt="no-new-privileges=true" 

.PHONY: HELLO app.docker app.run app.stop bootstrap

default: HELLO venv/lib/python3.11/site-packages/fastapi

HELLO:
	@echo To see the README of this Makefile, type "make help"
	@echo Local HTTP port is ${app_port}
	@echo Docker command params is:
	@echo ${APP_DOCKER_RUN}


venv:
	python3.11 -m venv venv
	. venv/bin/activate && pip install --upgrade pip

venv/bin/poetry: venv
	. venv/bin/activate && pip install poetry

venv/lib/python3.11/site-packages/fastapi: venv/bin/poetry
	. venv/bin/activate && poetry install

bootstrap: venv/lib/python3.11/site-packages/fastapi

#-#
#-# Command: help
#-#   show this message
help:
	@awk '/^#-#/ { print substr($$0, 5)}' Makefile

texlive/2023/texmf-arxiv/tex/latex/contrib/edpsciences/aa.cls:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/contrib/edpsciences/
	cd texlive/2023/texmf-arxiv/tex/latex/contrib/edpsciences/ && curl -o macro-latex-aa.zip https://www.aanda.org/doc_journal/instructions/macro/aa/macro-latex-aa.zip
	cd texlive/2023/texmf-arxiv/tex/latex/contrib/edpsciences/ && unzip macro-latex-aa.zip
	rm -f texlive/2023/texmf-arxiv/tex/latex/contrib/edpsciences/macro-latex-aa.zip

texlive/2023/texmf-arxiv/tex/latex/contrib/jhep/jheppub.sty:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/contrib/jhep/
	curl -L -s -o $@ https://jhep.sissa.it/jhep/help/JHEP/TeXclass/DOCS/jheppub.sty

texlive/2023/texmf-arxiv/tex/latex/contrib/eptcs/eptcs.cls:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/contrib/eptcs/
	curl -L -s -o @ https://raw.githubusercontent.com/EPTCS/style/main/eptcs.cls

texlive/2023/texmf-arxiv/tex/latex/emulateapj/apjfonts.sty:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/emulateapj/
	curl -L -s -o $@ https://hea-www.harvard.edu/~alexey/emulateapj/apjfonts.sty

texlive/2023/texmf-arxiv/tex/latex/contrib/agu/agujournal2019.cls:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/contrib/agu/
	curl -L -s -o texlive/2023/texmf-arxiv/tex/latex/contrib/agu/august-2022-latex-templates.zip https://www.agu.org/-/media/files/publications/august-2022-latex-templates.zip
	cd texlive/2023/texmf-arxiv/tex/latex/contrib/agu/ && unzip august-2022-latex-templates.zip && mv ./August-2022-latex-templates/*.cls ./August-2022-latex-templates/*.sty ./ 
	rm -fr texlive/2023/texmf-arxiv/tex/latex/contrib/agu/August-2022-latex-templates/ texlive/2023/texmf-arxiv/tex/latex/contrib/agu/august-2022-latex-templates.zip

texlive/2023/texmf-local/tex/generic/misc/diagrams.sty:
	mkdir -p texlive/2023/texmf-local/tex/generic/misc/
	curl -L -s -o $@ https://www.paultaylor.eu/diagrams/diagrams.sty

texlive/2023/texmf-arxiv/tex/latex/misc/slashbox.sty:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/misc
	curl -L -s -o $@ https://mirrors.ctan.org/macros/latex/contrib/slashbox/slashbox.sty

texlive/2023/texmf-arxiv/tex/latex/misc/widetext.sty:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/misc/
	curl -L -s -o $@ https://git.physics.itmo.ru/k.ladutenko/Asymmetry-plasma/raw/master/widetext.sty

texlive/2023/texmf-arxiv/tex/latex/misc/mn2e.cls:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/misc/
	curl -L -s -o $@ https://mirrors.ctan.org/macros/latex/contrib/mnras/LEGACY/mn2e.cls

texlive/2023/texmf-arxiv/tex/latex/latex209/obsolete/contrib/misc/picins.sty:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/latex209/obsolete/contrib/misc/
	curl -L -s -o $@ https://mirrors.ctan.org/macros/latex209/contrib/picins/picins.sty

texlive/2023/texmf-arxiv/tex/latex/contrib/sif/epl2/epl2.cls:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/contrib/sif/
	cd texlive/2023/texmf-arxiv/tex/latex/contrib/sif/ && curl -L -s -o epl2.zip https://www.sif.it/static/SIF/resources/public/files/epl2.zip && unzip epl2.zip epl2/epl2.cls
	rm texlive/2023/texmf-arxiv/tex/latex/contrib/sif/epl2.zip

texlive/2023/texmf-arxiv/tex/latex/misc/tmlr.sty:
	mkdir -p texlive/2023/texmf-arxiv/tex/latex/misc/
	curl -L -s -o $@ https://raw.githubusercontent.com/JmlrOrg/tmlr-style-file/main/tmlr.sty

ADDITIONS := \
  texlive/2023/texmf-arxiv/tex/latex/contrib/eptcs/eptcs.cls \
  texlive/2023/texmf-arxiv/tex/latex/contrib/edpsciences/aa.cls \
  texlive/2023/texmf-arxiv/tex/latex/contrib/jhep/jheppub.sty \
  texlive/2023/texmf-arxiv/tex/latex/contrib/agu/agujournal2019.cls \
  texlive/2023/texmf-arxiv/tex/latex/contrib/sif/epl2/epl2.cls \
  texlive/2023/texmf-arxiv/tex/latex/emulateapj/apjfonts.sty \
  texlive/2023/texmf-arxiv/tex/latex/misc/mn2e.cls \
  texlive/2023/texmf-arxiv/tex/latex/misc/slashbox.sty \
  texlive/2023/texmf-arxiv/tex/latex/misc/widetext.sty \
  texlive/2023/texmf-arxiv/tex/latex/misc/tmlr.sty \
  texlive/2023/texmf-arxiv/tex/latex/latex209/obsolete/contrib/misc/picins.sty \
  texlive/2023/texmf-local/tex/generic/misc/diagrams.sty

#-#
#-# Command: app.docker
#-#   builds the applience docker image
app.docker: ${ADDITIONS}
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
