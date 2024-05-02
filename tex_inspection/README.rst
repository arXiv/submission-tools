Tex Inspection
--------------

A library that inspects the arXiv submission

00readme
========

In AutoTex, arXiv defined its own file format and directives. However, it is proprietary, and the functionality fell short of its usefulness. The Cornell documentation for use is at https://confluence.cornell.edu/display/arXiv/00README

As a part of modernizing arXiv TeX compilation process, 00readme is extended to host the improved features, and the standard file formats.

AutoTex 00README
________________

In AutoTex, 00README.TXT supports following directives:


+--------------+---------------------------------------+
| directive    | description                           |
+==============+=======================================+
| toplevel*    | Tex compilation toplevel file         |
+--------------+---------------------------------------+
| ignored*     | ignored file                          |
+--------------+---------------------------------------+
| included*    | included file. Used but not toplevel  |
+--------------+---------------------------------------+
| keepcomments*| dvips to use -K1 option               |
+--------------+---------------------------------------+
| landscape*   | Uses landscape mode                   |
+--------------+---------------------------------------+
| nohyperref** | No Hyperref                           |
+--------------+---------------------------------------+
| nstamp       | No watermarking text                  |
+--------------+---------------------------------------+
| fontmap*     | Font map for tex compilation options  |
+--------------+---------------------------------------+


Tex2PDF 00README
As mentioned, Tex2PDF service supports JSON, YAML and TOML files. They are
distinguished by the file name extension. ".json" for JSON format, ".yml" or ".yaml"
for YAML format, and ".toml" for TOML format.

It must be at the toplevel file of submission archive, and may not include more than
one 00readme. When multiple 00readme appears in the toplevel, the compilation may fail.

The Tex2PDF 00README are divided into 3 sections. "compilation", "sources" and "postprocess".

Compilation

+--------------+---------------------------------------+
| directive    | description                           |
+==============+=======================================+
| compiler     | Tex compilation                       |
+--------------+---------------------------------------+
| fontmaps     | List of fontmap files                 |
+--------------+---------------------------------------+

The valid compiler choices are “tex”, “latex”, “pdflatex”. (“pdftex” is not available at the moment)

Note that, `nohyperref` has been deprecated due to its difficulty of maintaining the feature.
Sources
In the sources section, it lists the files to compile. Unlike AutoTex 00readme, there is no need
to explicitly ignore or designated as included file.

+--------------+---------------------------------------+
| directive    | description                           |
+==============+=======================================+
| filename     | Tex compilation file name             |
+--------------+---------------------------------------+
| keep_comments| dvips command to use -K1              |
+--------------+---------------------------------------+
| orientation  | landscape - Compile in landscape mode |
+--------------+---------------------------------------+
| ignored*     | True or "YES"                         |
+--------------+---------------------------------------+
| included*    | True or "YES"                         |
+--------------+---------------------------------------+
| appended     | Appended files are simply appended to |
|              | the PDF after TeX compilation.        |
+--------------+---------------------------------------+


\* - If the file should not be compiled, omitting from the source list is recommended.

Appended file corresponds to the AutoTex's feature where the image files are appended to the PDF.
When Tex2PDF 00README is not used, similar to AutoTex, it finds the unused graphics files in the toplevel, and appended to the PDF. It is therefore recommended to explicitly designate the graphics files when the submission archive contains such files.

Post process

+------------------+---------------------------------------+
| directive        | description                           |
+==================+=======================================+
| stamp            | False or "NO"                         |
+------------------+---------------------------------------+
| assembling_files | List of file names to combine         |
+------------------+---------------------------------------+

00README examples
=================

Example 00readme.yaml with landscape document::

  compilation:
    compiler: pdflatex
  sources:
    - name: main.tex
    - name: appendix1.tex
      orientation: landscape
    - name: appendix2.jpg
      appended: True


Example 00readme.yaml with font maps::

  compilation:
    compiler: latex
    fontmaps: ["myfontmap1.txt", "myfontmap2.txt"]
  sources:
    - name: main.tex
