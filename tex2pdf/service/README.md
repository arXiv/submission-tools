# Tex-to-PDF service

arXiv's next generation TeX compilation based on TexLive Docker container.

## How to build Docker Image

### Prerequisite

* Docker
* Make

`make app.docker` builds the Docker image.

## How to run Tex-to-PDF service

`make app.run` runs the Docker image. 
The HTTP port used for the Docker is 6301, which is mentioned in Makefile.
Once the Docker starts, open the web browser with 
http://localhost:6301/docs.

## How to compile your submission

First, you need create a compressed TAR archive file with your TeX sources 
just as you would prepare for an arXiv submission.

From the browser, navigate to 
http://localhost:6301/docs#/default/convert_pdf_convert__post

Click "Try it out"

Select "Choose File" to upload the submission archive file to "incoming".
Click "Execute"

When TeX-to-PDF finishes, it returns a compressed TAR archive file, different from one you 
uploaded. Open the archive file. The top level directory it returns the "outcome" file and the
"out" directory contains the compiled PDF file, TeX command log file,
and other artifacts created by the commands used.

The PDF file in the "out" directory is the same name as the archive file you 
uploaded. For example, if the submission archive file is "my-paper.tar.gz",
the "out" directory should contain "my-paper.pdf", and the outcome file is named
"outcome-my-paper.json".

## outcome JSON file

The format and contents of the outcome file are still in development and may change
over time. When your PDF file does not look right, pay attention to "tex_files".

Most often, the issue is the order and selection of TeX files in the top-level
directory of the submission. 

Each command run is captured in the outcome. For example, each run of pdflatex 
command would have

```json lines
          "args": [
            "/usr/bin/pdflatex",
            "-interaction=batchmode",
            "-file-line-error",
            "-output-format=pdf",
            "main.tex"
          ],
          "stdout": "This is pdfTeX, Version 3.141592653-2.6-1.40.25 (TeX Live 2023) (preloaded format=pdflatex)\n restricted \\write18 enabled.\nentering extended mode\n",
          "stderr": "",
          "return_code": 0,
```

The input and output files are listed for the each run, as well as the
log file from the tex command. This is intended to examine each step when
running the TeX compilation.

## Development and debugging

The development requires "unix-like" environment and would be possible to execute on most Linux, *BSD Unix 
including MacOS(tm), and Windows(tm) WSL. The primary development is done on Linux so far.

    make bootstap

Sets up the virtual env "venv" and installs Python dependencies.

The software is primarily designed to run in a Docker image but it is difficult to 
use the debugger. To support the development, the commands of TexLive Docker image container
can be used via a wrapper shell script that passes/propagates the `WORKDIR` variable to it.

The companion shell script is `bin/docker_pdflatex.sh` which must exist at 
`/usr/local/bin/docker_pdflatex.sh`. If you change the Docker image name, you may have to change
the Docker image name in it. 

    sudo install -m 755 bin/docker_pdflatex.sh /usr/local/bin

In other words, you first must create the Docker image on your local machine in order to run the 
python app in debugger. 

With it, the execution requires:

    LOCAL_EXEC=t uvicorn --host 0.0.0.0 --port=<LOCALHOST_PORT> tex2pdf.tex2pdf_api:app

