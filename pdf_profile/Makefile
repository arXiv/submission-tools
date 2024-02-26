.PHONY: HELLO bootstrap

default: HELLO bootstrap

HELLO:
	@echo To see the README of this Makefile, type "make help"

venv:
	python3 -m venv venv
	. venv/bin/activate && pip install --upgrade pip

venv/bin/poetry: venv
	. venv/bin/activate && pip install poetry

venv/lib/python3.10/site-packages/fastapi: venv/bin/poetry
	. venv/bin/activate && poetry install

#-#
#-# Command: bootstrap
#-#   show this message
bootstrap: venv/lib/python3.10/site-packages/fastapi

#-#
#-# Command: help
#-#   show this message
help:
	@awk '/^#-#/ { print substr($$0, 5)}' Makefile

