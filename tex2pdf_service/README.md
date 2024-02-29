# Tex-to-PDF service

arXiv's next generation TeX compilation based on TexLive Docker container.

## How to build Docker Image

### Prerequisite

* docker
* make

`make app.docker` builds the docker image.

## How to run Tex-to-PDF service

`make app.run` runs the docker image. 
The HTTP port used for the doker is 6301, which is mentioned in Makefile.
Once the docker starts, open the web browser with 
http://localhost:6301/docs
.

## How to compile your submission

First, you need create a compressed TAR archive file with your TeX sources 
just as you'd prepare for the arXiv submission.

From the browser, navigate to 
http://localhost:6301/docs#/default/convert_pdf_convert__post

and click "Try it out"

Give the submission archive file to "incoming" by using Choose File. Hit Execute button.

When TeX-to-PDF finishes, it returns a compressed tar archive file, different from one you 
uploaded. Please open the archive file, and it returns the "outcome" file in the top
level directory, and "out" directory that contains the compiled PDF file, 
TeX command log file and other artifacts created by the commands used. 

The PDF file in the "out" directory is the same name as the archive file you 
uploaded. For example, if the submission archive file is "my-paper.tar.gz",
"out" directory should contains "my-paper.pdf", and outcome file is named
"outcome-my-paper.json".

## outcome JSON file

The format and contents of outcome file is still in development and may change
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
log file from the tex command. This is intended for examining the each step of 
running TeX compilation.
