#!/bin/sh
set -e

# lvm_setup.sh creates an LVM volume group 'lvmtest-vg' & thin pool 'pool1'
# in a loop device.

# needs root.

# Usage: lvm_setup /path/to/loopfile/dir [--new]

# make the loop device
lvdir="$1"
lvprefix=lvmtest
mkdir -p $lvdir
if [ "$1" = 'new' ]; then
  rm -f $lvdir/pv1
  truncate --size 150M $lvdir/pv1
fi
lodev=$(losetup --show -f $lvdir/pv1)

# make new lvm thin pool
if [ "$2" = '--new' ]; then
  pvcreate $lodev
  vgcreate ${lvprefix}-vg $lodev
  lvcreate -n ${lvprefix}-vg/pool1 -L 100M
  lvcreate -n ${lvprefix}-vg/pool1meta -L 8M
  lvconvert --type thin-pool --poolmetadata ${lvprefix}-vg/pool1meta ${lvprefix}-vg/pool1
  lvcreate -T -V 50M ${lvprefix}-vg/pool1 -n thin1
  #mkfs.ext4 /dev/vg1/thin1
fi

# add random data to 'thin1' volume
#dd if=/dev/urandom of=/dev/${lvprefix}-vg/thin1 bs=1024 count=10000
