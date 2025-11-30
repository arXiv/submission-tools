Options:

gs:
    gs -sDEVICE=pdfwrite -dNOPAUSE -dBATCH -dSAFER -sOutputFile=out.pdf in1.pdf in2.pdf

pypdf:
    from pypdf import PdfWriter
    merger = PdfWriter()
    input1 = open("in1.pdf", "rb")
    input2 = open("in2.pdf", "rb")
    merger.append(input1)
    merger.append(input2)
    output = open("out.pdf", "wb")
    merger.write(output)
    merger.close()
    output.close()

pdftk:
    pdftk in1.pdf in2.pdf cat output out.pdf verbose

qpdf:
    qpdf --empty --pages in1.pdf in2.pdf -- out.pdf



gs: preserves links, slow at times
pdftk: preserves links, slow at GCP (why?)
pdftk: preserves links BUT does not rename annotations, so having section1 in both is bad :-(
qpdf: breaks link


