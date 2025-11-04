#!/bin/bash
# bwrap-tex.sh
set -eu

echo "bubblewrapping call $*" >&2

tmpdir=`mktemp -d`
trap 'rm -rf -- "$tmpdir"' EXIT

# for TeX Live, bin only the libraries and TeX Live (luatex, xetex etc need a lot of libs)
RO_BIND_TEXLIVE="\
    --ro-bind /lib/x86_64-linux-gnu/ /lib/x86_64-linux-gnu/ \
    --ro-bind /usr/local/texlive/ /usr/local/texlive/ \
"

# for all other program, that is ps2pdf at the moment, we bind the libs as well
# as necessary directories for ghostscript
RO_BIND_BIN="\
    --ro-bind /lib/x86_64-linux-gnu/ /lib/x86_64-linux-gnu/ \
    --ro-bind /usr/share/ghostscript/ /usr/share/ghostscript/ \
    --ro-bind /var/lib/ghostscript/ /var/lib/ghostscript/ \
    --ro-bind /usr/share/color/icc/ghostscript/ /usr/share/color/icc/ghostscript/ \
    --ro-bind /usr/share/fonts/ /usr/share/fonts/ \
    --ro-bind /etc/paperspecs /etc/paperspecs \
"

CMD="$1"
FULLPATH_CMD=$(type -p "$CMD")
case "$FULLPATH_CMD" in
  /usr/bin/*) RO_BIND="$RO_BIND_BIN" ;;
  /usr/local/texlive/*) RO_BIND="$RO_BIND_TEXLIVE" ;;
  *) echo "Unknown location of binary: $FULLPATH_CMD for call $*, exiting." >&2; exit 1 ;;
esac

# comments on the bwrap call:
# - we don't need (and don't want) --clearenv, since the Python code already prepares the env
#   and we need to pass some values (FORCE_SOURCE_DATE etc) forward
# - we use a **custom build** bwrap that disables setting up a loopback net device on init
#   This is necessary otherwise --unshare-net (via --unshare-all) does not work on gvisor
# - we need to bind /dev/null for ps2pdf/gs
# - it would be nice to use --overlay-src/--overlay as in
#     --overlay-src /usr/local/texlive/2023/texmf-var/ --tmp-overlay /usr/local/texlive/2023/texmf-var/
#   but it fails on gvisor
bwrap \
    --unshare-all \
    --new-session \
    --as-pid-1 \
    --uid 65534 --gid 65534 \
    --cap-drop ALL \
    --bind $tmpdir /tmp \
    --ro-bind /etc/profile /etc/profile \
    --ro-bind /bin/ /bin/ \
    --ro-bind /usr/bin/ /usr/bin/ \
    --ro-bind /lib64/ld-linux-x86-64.so.2 /lib64/ld-linux-x86-64.so.2 \
    --ro-bind /usr/lib/locale/ /usr/lib/locale/ \
    $RO_BIND \
    --bind /dev/null /dev/null \
    --setenv PATH /bin \
    --setenv TEXMFVAR /home/nobody/work/texmf-var \
    --bind . /home/nobody/work/ \
    --chdir /home/nobody/work/ \
    $*

