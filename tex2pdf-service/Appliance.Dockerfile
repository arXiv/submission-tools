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
    DEBIAN_FRONTEND=noninteractive apt-get install --no-install-suggests --no-install-recommends -y default-libmysqlclient-dev pkgconf build-essential && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /var/log/dpkg.log

RUN useradd -m -d $WORKER_HOME -s /bin/bash -g users -u 1000 worker
RUN chown worker:users $WORKER_HOME
USER worker
WORKDIR $WORKER_HOME
COPY tex2pdf-service/poetry.lock tex2pdf-service/pyproject.toml ./
# Bring the local tex2pdf-tools tree into the build context so we can overlay
# it on top of the GitHub-pinned copy that poetry installs.
COPY tex2pdf-tools/ /tmp/tex2pdf-tools/
# poetry is BROKEN wrt to installing multiple packages from same git repo
# see https://github.com/python-poetry/poetry/issues/6958
# RUN poetry config installer.parallel false
# install runtime deps - uses $POETRY_VIRTUALENVS_IN_PROJECT internally
RUN poetry install --no-root --without=dev
# Replace the pinned arxiv-tex2pdf-tools wheel with one built from the local
# source so the image carries the working-tree version, not the GitHub commit
# pinned in poetry.lock.
RUN poetry run pip install --no-deps /tmp/tex2pdf-tools

# copy this afterwards to avoid re-installing poetry deps on each docker build
COPY tex2pdf-service/tex2pdf/ ./tex2pdf/
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
COPY tex2pdf-service/texlive/common/texmf.cnf /usr/local/texlive/${TEXLIVE_BASE_RELEASE}/

COPY --from=arxiv-texlive-builder $WORKER_HOME $WORKER_HOME

COPY tex2pdf-service/bin/bwrap-tex.sh /usr/local/bin/bwrap-tex.sh

# -M don't create home since we copied it above
RUN useradd -M -d $WORKER_HOME -s /bin/bash -g users -u 1000 worker
RUN chown worker:users $WORKER_HOME
USER worker
WORKDIR $WORKER_HOME

# application specific changes
ENV PYTHONPATH=$WORKER_HOME
COPY tex2pdf-service/app-logging.conf .
COPY tex2pdf-service/app-logging.json .
COPY tex2pdf-service/hypercorn-config.toml .
COPY tex2pdf-service/app.sh ./app.sh
CMD ["/bin/bash", "app.sh"]
