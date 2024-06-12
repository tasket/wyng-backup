#!/bin/bash

# Simple non-destructive conversion of a directory to a Btrfs subvolume.

set -e

if ! [ $(id -u) = 0 ]; then
  echo Must be root user. Exiting.
  exit 1
fi

dir=$1
echo $dir
if [ -z "$dir" ]; then
  echo Please specify a directory to convert.
  exit 1
fi

if ! [ -d ${dir} ]; then
  echo Not a directory: $dir
  exit 1
fi

echo
echo Convert \"$dir\" to a Btrfs subvolume
read -p "ARE YOU SURE? (Y/N): " ans
case $ans in
  [Yy] ) echo Starting... ;;
     * ) exit 1;;
esac

if [ $(stat --printf %i ${dir}) = 256 ]; then
  echo Path is already a subvolume.
  exit 1
fi

tsuffix=$(date +%s)
btrfs subvolume create "$dir"-$tsuffix
shopt -s dotglob
mv -v "$dir"/* "$dir"-$tsuffix
rmdir "$dir"
echo
mv -vT "$dir"-$tsuffix "$dir"

echo Done.
