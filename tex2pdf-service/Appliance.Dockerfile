# defaults for these values are set in cicd/appliance.yaml
# and need to be passed via --build-arg, see Makefile
# Give default values to silence docker build warnings
# https://docs.docker.com/reference/build-checks/invalid-default-arg-in-from/
ARG TEXLIVE_BASE_RELEASE=2023
ARG TEXLIVE_BASE_IMAGE_DATE=2023-05-21
FROM gcr.io/arxiv-development/arxiv-texlive/arxiv-texlive-base-${TEXLIVE_BASE_RELEASE}-${TEXLIVE_BASE_IMAGE_DATE} AS arxiv-texlive-builder
ARG TEXLIVE_BASE_RELEASE
ARG GIT_COMMIT_HASH

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    WORKER_HOME="/home/worker" \
    VENV_PATH="/home/worker/.venv" \
    PORT=8080 \
    GIT_COMMIT_HASH=${GIT_COMMIT_HASH} \
    TEXLIVE_BASE_RELEASE=${TEXLIVE_BASE_RELEASE}

ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

# we need arxiv-base which depends on mysqlclient which does not have wheels
# and thus needs development tools
RUN apt-get -q update && \
    DEBIAN_FRONTEND=noninteractive apt-get -qy upgrade && \
    DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y default-libmysqlclient-dev pkgconf build-essential && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /var/log/dpkg.log

RUN useradd -m -d $WORKER_HOME -s /bin/bash -g users -u 1000 worker
RUN chown worker:users $WORKER_HOME
USER worker
WORKDIR $WORKER_HOME
COPY poetry.lock pyproject.toml ./
# poetry is BROKEN wrt to installing multiple packages from same git repo
# see https://github.com/python-poetry/poetry/issues/6958
# RUN poetry config installer.parallel false
# install runtime deps - uses $POETRY_VIRTUALENVS_IN_PROJECT internally
RUN poetry install --no-root --without=dev

# copy this afterwards to avoid re-installing poetry deps on each docker build
COPY tex2pdf/ ./tex2pdf/
# second poetry run should only install the current project
RUN poetry install --without=dev

FROM gcr.io/arxiv-development/arxiv-texlive/arxiv-texlive-base-${TEXLIVE_BASE_RELEASE}-${TEXLIVE_BASE_IMAGE_DATE} AS arxiv-texlive-base
ARG TEXLIVE_BASE_RELEASE
ARG GIT_COMMIT_HASH

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    WORKER_HOME="/home/worker" \
    VENV_PATH="/home/worker/.venv" \
    PORT=8080 \
    GIT_COMMIT_HASH=${GIT_COMMIT_HASH} \
    TEXLIVE_BASE_RELEASE=${TEXLIVE_BASE_RELEASE}

# install the arXiv specific changes:
# - special settings in texmf.cnf
COPY texlive/common/texmf.cnf /usr/local/texlive/${TEXLIVE_BASE_RELEASE}/

COPY --from=arxiv-texlive-builder $WORKER_HOME $WORKER_HOME

COPY bin/bwrap-tex.sh /usr/local/bin/bwrap-tex.sh

# -M don't create home since we copied it above
RUN useradd -M -d $WORKER_HOME -s /bin/bash -g users -u 1000 worker
RUN chown worker:users $WORKER_HOME
USER worker
WORKDIR $WORKER_HOME

# application specific changes
ENV PYTHONPATH=$WORKER_HOME
COPY app-logging.conf .
COPY app-logging.json .
COPY hypercorn-config.toml .
COPY app.sh ./app.sh
CMD ["/bin/bash", "app.sh"]
