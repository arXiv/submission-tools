
#echo "$1"
tar -xf ../outcome-$1
log="$(cat outcome-*.json | jq .converters[0].runs[-1].log)"
#if echo -e "$log" | grep -F -q 'runsystem(repstopdf' ; then
#  echo " repstopdf"
#fi
#if echo -e "$log" | grep -F -q 'hyperref must be loaded before hyperxmp' ; then
#  echo " hyperxmp"
#fi
#if echo -e "$log" | grep -F -q '<argument> \@testpach \ifcase \@chclass \@classz \or' ; then
#  echo " revtex"
#fi
#if echo -e "$log" | grep -F -q 'theHalgorithm already defined' ; then
#  echo " theHalgorithm"
#fi
#if echo -e "$log" | grep -F -q 'is wrong format version - expected 3.3' ; then
#  echo " biblatex33"
#fi
#if echo -e "$log" | grep -F -q 'Package minted Error: Missing definition for highlighting style' ; then
#  echo "$1"
#  echo " minted"
#fi
#if echo -e "$log" | grep -F -q '\selectlanguage{\english}' ; then
#  echo "$1"
#  echo " english"
#fi
#if echo -e "$log" | grep -F -q 'Shell escape needed to create graphic! Use the' ; then
#  echo "$1"
#  echo " tikzexternal"
#fi
if echo -e "$log" | grep -F -q 'orcidlink.sty:67: LaTeX Error: Command \orcidlogo already defined.' ; then
  echo "$1"
  echo " orcidlink"
fi
rm *.json
