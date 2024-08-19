# defaults for these values are set in cicd/appliance.yaml
# and need to be passed via --build-arg, see Makefile
ARG TEXLIVE_BASE_RELEASE
ARG TEXLIVE_BASE_IMAGE_DATE
FROM gcr.io/arxiv-development/arxiv-texlive/arxiv-texlive-base-${TEXLIVE_BASE_RELEASE}-${TEXLIVE_BASE_IMAGE_DATE} AS arxiv-texlive-base
ARG TEXLIVE_BASE_RELEASE

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    WORKER_HOME="/home/worker" \
    VENV_PATH="/home/worker/.venv" \
    PORT=8080

ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

# install the arXiv specific changes:
# - special settings in texmf.cnf
COPY texlive/common/texmf.cnf /usr/local/texlive/${TEXLIVE_BASE_RELEASE}/

RUN useradd -m -d $WORKER_HOME -s /bin/bash -g users -u 1000 worker
USER worker
WORKDIR $WORKER_HOME
COPY tex2pdf/ ./tex2pdf/
COPY poetry.lock pyproject.toml ./
# poetry is BROKEN wrt to installing multiple packages from same git repo
# see https://github.com/python-poetry/poetry/issues/6958
RUN poetry config installer.parallel false
# install runtime deps - uses $POETRY_VIRTUALENVS_IN_PROJECT internally
RUN poetry install --without=dev


# application specific changes
ENV PYTHONPATH=$WORKER_HOME
COPY app-logging.conf .
COPY app-logging.json .
COPY hypercorn-config.toml .
COPY app.sh ./app.sh
CMD ["/bin/bash", "app.sh"]
