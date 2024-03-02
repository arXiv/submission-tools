# NOTE - This Dockerfile is expected to run from tex2pdf_service directory
FROM registry.gitlab.com/islandoftex/images/texlive:TL2023-2023-05-21-full
RUN apt update && apt install -y python3-venv inkscape python3-pygments
RUN useradd -rm -d /home/worker -s /bin/bash -g users -u 1000 worker

# Allow statements and log messages to immediately appear in the Cloud Run logs
ENV PYTHONUNBUFFERED True
ENV PORT 8080

RUN apt-get clean autoclean && apt-get autoremove --yes
RUN rm -rf /var/lib/{apt,dpkg,cache,log}/ /usr/local/texlive/texmf-local
# Add Norbert key
RUN curl -fsSL https://www.preining.info/rsa.asc | tlmgr key add -

ENV TEXMFHOME /usr/local/texlive/2023
RUN echo "Meaning of life is 42" > /home/worker/hello.txt
RUN chown -R worker:users /home/worker
RUN chown -R worker /usr/local/texlive/2023

WORKDIR /usr/local/texlive/2023
COPY texlive/2023/texmf-arxiv/ ./texmf-arxiv/
COPY texlive/2023/texmf-local/ ./texmf-local/
COPY texlive/2023/texmf.cnf .
RUN chown -R worker texmf.cnf ./texmf-arxiv/ ./texmf-local/

USER worker
WORKDIR /home/worker
ENV TEXMFHOME /usr/local/texlive/2023
COPY pyproject.toml .
COPY poetry.lock .
RUN python -m venv ./venv
RUN . venv/bin/activate && \
    pip install --upgrade pip && \
    pip install poetry lockfile && \
    venv/bin/poetry install ; exit 0
RUN mkdir -p texlive/2023
RUN tlmgr info --json --verify-repo=none > texlive/2023/tlmgr-info.json; exit 0
#COPY app-logging.conf .
COPY app-logging.json .
#
RUN tlmgr update --self; exit 0
# RUN tlmgr update --all; exit 0
RUN tlmgr update minted; exit 0
RUN tlmgr repository add https://mirror.ctan.org/systems/texlive/tlcontrib tlcontrib; exit 0
RUN tlmgr pinning add tlcontrib "*"; exit 0
COPY texlive/2023/tex-packages.txt ./texlive/2023/tex-packages.txt
RUN tlmgr install $(cat texlive/2023/tex-packages.txt); exit 0
RUN mktexlsr; exit 0
COPY tex2pdf/ ./tex2pdf/
ENV TEXMFHOME /usr/local/texlive/2023
ENV PYTHONPATH /home/worker
COPY app.sh ./app.sh
CMD ["/bin/bash", "app.sh"]
