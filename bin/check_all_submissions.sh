#!/usr/bin/env bash

incremental=0
if [ "$1" = "-inc" ] ; then
  incremental=1
  shift
fi

if [ -z "$1" ] ; then
  echo "Need directory of submissions as first argument" >&2
  exit 1
fi

TL_PATH=${ARXIV_TEXLIVE_BIN:-"$HOME/tl/arxiv/2023/bin/x86_64-linux"}
if [ -x "$TL_PATH/pdflatex" ] ; then
  export PATH="$TL_PATH":$PATH
  # make sure the default settings in the dedicated texmf.cnf in arxiv/2023/texmf.cnf is used
  unset TEXMFLOCAL
  unset TEXMFHOME
fi

percent () {
  local p=00$(($1*100000/$2))
  printf -v "$3" %.2f ${p::-3}.${p: -3}
}

percentBar ()  {
  local prct totlen=$((8*$2)) lastchar barstring blankstring;
  printf -v prct %.2f "$1"
  ((prct=10#${prct/.}*totlen/10000, prct%8)) &&
      printf -v lastchar '\\U258%X' $(( 16 - prct%8 )) ||
          lastchar=''
  printf -v barstring '%*s' $((prct/8)) ''
  printf -v barstring '%b' "${barstring// /\\U2588}$lastchar"
  printf -v blankstring '%*s' $(((totlen-prct)/8)) ''
  printf -v "$3" '%s%s' "$barstring" "$blankstring"
}

do_one () {
  start_time=$(date +%s)
  mkdir -p json
  mkdir -p __tmp__
  rm -rf __tmp__/*
  tar -C __tmp__ -xf $1
  bn=$(basename $1 .tar.gz)
  (python -m tex2pdf.preflight_parser __tmp__ | json_pp) > json/$bn.json 2> json/$bn.log
  # remove .log file if it has 0 size
  if ! [ -s json/$bn.log ] ; then
    rm json/$bn.log
  fi
  rm -rf __tmp__/*
  end_time=$(date +%s)
  runtime=$((end_time-start_time))
  echo "$runtime" > json/$bn.time
}

shopt -s nullglob
files=("$1"/*.tar.gz)
nr_files=${#files[@]}
for i in "${!files[@]}"; do
  percent "$i" "$nr_files" perct
  percentBar $perct 20 bar
  printf '\r\e[47;30m%s\e[0m%6.2f%%' "$bar" "$perct"
  if [ $incremental = 1 ] ; then
    bn=$(basename "${files[$i]}" .tar.gz)
    if [ -r json/$bn.json ] ; then
      continue
    fi
  fi
  do_one "${files[$i]}"
done


