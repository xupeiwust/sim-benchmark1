#!/usr/bin/env bash
# Point apt at a fast mirror for the duration of the sourcing script, and put
# the upstream sources back before it exits.
#
#   . /path/to/apt_mirror.sh     # honours $APT_MIRROR; a no-op when unset
#
# $APT_MIRROR is the SCHEME AND HOST ONLY -- the suite paths are already in the
# sources file and the sed below keeps them:
#
#   APT_MIRROR=https://mirrors.example.edu           correct
#   APT_MIRROR=https://mirrors.example.edu/debian    wrong: yields /debian/debian
#                                                    and every Release 404s
#
# Why this is scoped rather than a lasting edit
# ---------------------------------------------
# These images cannot be built in reasonable time on a China-hosted builder
# against `deb.debian.org` / `archive.ubuntu.com` — apt stalls part-way through
# the package index and retries indefinitely. Rewriting the sources fixes that.
#
# Rewriting them *permanently* trades one problem for a worse one: the image
# then carries a mirror that resolves on exactly one network. That happened.
# Three domain images were built against Volcengine's internal
# `mirrors.ivolces.com`, worked on that cloud, and on a second host every
# in-container `apt-get` failed with `Could not resolve` — which surfaced not as
# a build error but as an agent that could not be set up, one paid trial later.
# Nothing in the version manifest showed it, because the manifest checks pip
# package versions and this is a file.
#
# So: every script that uses apt sources this, and every one of them restores on
# exit. A layer is fast while it builds and upstream when it is done.
#
# The restore deliberately does NOT run `apt-get update` afterwards. Refreshing
# the cache against upstream is exactly the slow operation this exists to avoid,
# and it is not needed: each script runs its own `apt-get update` first.

_apt_sources() {
  ls /etc/apt/sources.list /etc/apt/sources.list.d/*.sources \
     /etc/apt/sources.list.d/*.list 2>/dev/null || true
}

_apt_mirror_restore() {
  local f
  for f in $(_apt_sources); do
    [ -f "$f.orig-upstream" ] && mv -f "$f.orig-upstream" "$f"
  done
  return 0
}

if [ -n "${APT_MIRROR:-}" ]; then
  for _f in $(_apt_sources); do cp "$_f" "$_f.orig-upstream"; done
  unset _f
  sed -i -E "s#https?://(deb\.debian\.org|security\.debian\.org|archive\.ubuntu\.com|security\.ubuntu\.com)#${APT_MIRROR}#g" $(_apt_sources) 2>/dev/null || true
  # On ANY exit, including a failed build — a broken build must not be able to
  # leave a host-specific mirror behind either.
  trap _apt_mirror_restore EXIT
fi
