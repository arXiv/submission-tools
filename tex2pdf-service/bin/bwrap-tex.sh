#!/bin/sh
# bwrap-tex.sh
set -eu

#engine="$1"
#work_dir="$(dirname "$2")"
#tex_file="$(basename "$2")"

# Requires bubblewrap v0.11.0 for overlay support
#
# Suggestion from Max with adjustments of the lib paths
#bwrap \
#    --unshare-all --unshare-user \
#    --disable-userns \
#    --new-session \
#    --clearenv \
#    --as-pid-1 \
#    --uid 65534 --gid 65534 \
#    --cap-drop ALL \
#    --ro-bind /lib/x86_64-linux-gnu/libdl.so.2 /lib/x86_64-linux-gnu/libdl.so.2 \
#    --ro-bind /lib/x86_64-linux-gnu/libm.so.6 /lib/x86_64-linux-gnu/libm.so.6 \
#    --ro-bind /lib/x86_64-linux-gnu/libc.so.6 /lib/x86_64-linux-gnu/libc.so.6 \
#    --ro-bind /lib64/ld-linux-x86-64.so.2 /lib64/ld-linux-x86-64.so.2 \
#    --ro-bind /usr/lib/locale/ /usr/lib/locale/ \
#    --ro-bind /usr/local/texlive/2023/texmf-dist/ /usr/local/texlive/2023/texmf-dist/ \
#    --ro-bind /usr/local/texlive/2023/bin/x86_64-linux/lualatex /usr/local/texlive/2023/bin/x86_64-linux/lualatex \
#    --ro-bind /usr/local/texlive/2023/bin/x86_64-linux/pdflatex /usr/local/texlive/2023/bin/x86_64-linux/pdflatex \
#    --setenv PATH /usr/local/texlive/2023/bin/x86_64-linux \
#    --overlay-src /usr/local/texlive/2023/texmf-var/ --tmp-overlay /usr/local/texlive/2023/texmf-var/ \
#    --overlay-src "$work_dir" --tmp-overlay /home/nobody/work/ \
#    --bind "$work_dir/$pdf_file" "/home/nobody/work/$pdf_file" \
#    --chdir /home/nobody/work/ \
#    "$engine" "$tex_file"

# does not work directly:
# - fails with network -> add --share-net
# - fails with 
#	bwrap: Can't make overlay mount on /newroot/home/nobody/work/ with options upperdir=/tmp-overlay-upper-0,workdir=/tmp-overlay-work-0,lowerdir=/oldroot/home/worker,userxattr: Invalid argument
#   on overlays, so use bind-mont

echo "bubblewrapping call $*" >&2

bwrap \
    --unshare-all --share-net \
    --new-session \
    --clearenv \
    --as-pid-1 \
    --uid 65534 --gid 65534 \
    --cap-drop ALL \
    --ro-bind /etc/profile /etc/profile \
    --ro-bind /bin/ /bin/ \
    --ro-bind /lib/x86_64-linux-gnu/libdl.so.2 /lib/x86_64-linux-gnu/libdl.so.2 \
    --ro-bind /lib/x86_64-linux-gnu/libm.so.6 /lib/x86_64-linux-gnu/libm.so.6 \
    --ro-bind /lib/x86_64-linux-gnu/libc.so.6 /lib/x86_64-linux-gnu/libc.so.6 \
    --ro-bind /lib64/ld-linux-x86-64.so.2 /lib64/ld-linux-x86-64.so.2 \
    --ro-bind /usr/lib/locale/ /usr/lib/locale/ \
    --ro-bind /usr/local/texlive/ /usr/local/texlive/ \
    --setenv PATH /bin \
    --bind . /home/nobody/work/ \
    --chdir /home/nobody/work/ \
    $*

