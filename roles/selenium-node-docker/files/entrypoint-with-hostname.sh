#!/bin/sh
set -eu

container_id="$(
  grep -o '/var/lib/docker/containers/[^/]*/hostname' /proc/self/mountinfo \
    | head -n1 \
    | sed 's#^/var/lib/docker/containers/##; s#/hostname$##'
)"

if [ -n "$container_id" ]; then
  export HOSTNAME="$container_id"
fi

exec /opt/bin/entry_point.sh "$@"
