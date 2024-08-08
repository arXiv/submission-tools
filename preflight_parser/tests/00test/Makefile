#
#
# Makefile fuer dipl/tex
#
# GNUMake
#

# special targets

#.SUFFIXES: .bew .bwo .dvi .ps .tex

.PRECIOUS: %.dvi
.PHONY: %.dvi speedup speedup.dvi paper paper.dvi

# definitions
BIBDIR=../bib:$(HOME)/tex/bib
STYDIR=../sty:$(HOME)/tex/sty
BEWDIR=../bew
PICDIR=../pics
TEXFILES=\
	abstract.tex introduction.tex closing.tex \
	paper.tex \
	herbrand-disjunction.tex \
	herbrand-sketches.tex \
	sketches.tex \
	howfast.tex \
	recursive.tex \
	elsart_macros.sty
BIBFILE=currentbib.bib
PICFILES=diagonal.1 diagonal.2 skelett.eps

export TEXINPUTS+=$(STYDIR):$(BEWDIR):$(PICDIR):
export BIBINPUTS=$(BIBDIR):
export MPINPUTS=$(PICDIR):

vpath %.bib $(BIBDIR)
vpath %.sty $(STYDIR)
vpath %.bwo $(BEWDIR)
vpath %.mp  $(PICDIR)
vpath %.eps $(PICDIR)

%.ps: %.dvi
	dvips $<

%.pdf: %.dvi
	dvipdfm $<

first: paper

# explicit rules
paper: paper.ps

paper.ps: paper.dvi $(PICFILES)
paper.pdf: paper.dvi $(PICFILES)

paper.dvi: $(TEXFILES) $(PICFILES)
	latex paper
	bibtex paper
	latex paper
	latex paper

diagonal.1 diagonal.2: diagonal.mp
	mpost diagonal.mp


# clean
clean:
	rm -f *.aux *.log *.bbl *.blg *.idx *.ilg *.ind *~ *.glo 
	rm -f *.lof *.lot *.toc *.bwo *.cb diagonal.*

realclean: clean
	rm -f *.ps *.dvi *.pdf

# eof
