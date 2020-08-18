#!/usr/bin/env bash

# wyng-extract.sh  -  Simple disk image extractor for Wyng archives.
#  Copyright Christopher Laprise 2018-2020 / tasket@protonmail.com
#  Licensed under GNU General Public License v3. See file 'LICENSE'.


set -eo pipefail
LC_ALL=C

if [ "$1" = "-c" ] & [ -d "$2" ]; then
  voldir="$2"
  outfile=/dev/null
  do_check=1
  shift
else
  do_check=0
fi

if [ $do_check = 0 ] & [ -d "$1" ] & [ -n "$2" ]; then
  voldir="$1"
  outfile=`readlink -f "$2"`
fi

if [ -z "$voldir" ]; then
  echo "Usage: wyng-extract -c <path-to-volume-dir>"
  echo "       wyng-extract <path-to-volume-dir> <output-file>"
  exit 1
fi

volname=`basename "$voldir"`
tmpdir=/tmp/wyng-extract
rm -rf $tmpdir  &&  mkdir $tmpdir

( cd "$voldir";  curdir=`pwd`

  if ! grep -q '^format_ver = 1$' volinfo; then
    echo "Error: Did not find a compatible format."
    exit 1
  fi
  echo "Getting metadata for volume $volname."
  cp volinfo $tmpdir;  sed -E '/\[volumes/q' ../archive.ini >$tmpdir/archive.ini

  # Add session column to manifests and create symlinks using sequence number.
  for session in S_*[!t][!m][!p]; do
    ln=`grep '^sequence =' $session/info`;  read one two sequence <<<"$ln"
    sed 's|$| S_'$sequence'|'  $session/manifest  >$tmpdir/m_$sequence
    ln -s "$curdir/$session" $tmpdir/S_$sequence
  done
)

( cd $tmpdir
  # Get a list of manifest files, sorted by sequence in filename, as 'm_last' and 'm_therest'.
  ln=`find . -name 'm_*' -exec basename '{}' \; | sort --reverse -V | tr '\n' ' '`
  read m_last m_therest <<<"$ln"

  # Get volume size, chunk size, compression, hash type and last chunk address.
  ln=`grep -E '^volsize =' S_${m_last#m_}/info`;  read one two volsize <<<"$ln"
  ln=`grep -E '^chunksize ='  archive.ini`;       read one two chunksize <<<"$ln"
  ln=`grep -E '^compression ='  archive.ini`;     read one two compr <<<"$ln"
  ln=`grep -E '^hashtype ='  archive.ini`;        read one two hashtype <<<"$ln"
  lastchunk=`printf '%016x' $(( ($volsize - 1) - (($volsize - 1) % $chunksize) ))`
  echo "Volume size = $volsize bytes."

  case $compr in
    zlib)  DECOMPRESS="unpigz -cz";;
    bz2)   DECOMPRESS="bzcat";;
  esac

  case $hashtype in
    sha256)   HASH_CHECK="sha256sum";;
    blake2b)  HASH_CHECK="b2sum";;
  esac

  # Parse manifest fields: 1=digest, 2=first fname segment, 3=second fname seg, 4=session
  mregex='^(\S+)\s+x(\S{9})(\S+)\s+(S_\S+)'

  # Test data integrity against manifest hashes.
  if [ $do_check = 1 ]; then
    echo -n "Checking volume hashes..."

    sort -umd -k2,2 $m_last $m_therest  |  sed -E "/ x$lastchunk/q" \
    |  sed -E '/^0 x/ d; s|'"$mregex"'|\1 \4/\2/x\2\3|;' \
    |  $HASH_CHECK -c --status

    exit 0
  fi

  echo -n "Extracting volume data to $outfile..."
  truncate --size $chunksize ZERO

  sort -umd -k2,2 $m_last $m_therest  |  sed -E "/ x$lastchunk/q" \
  |  sed -E 's|^0 x.*|ZERO|; t; s|'"$mregex"'|\4/\2/x\2\3|' \
  |  xargs $DECOMPRESS -f \
  |  dd of="$outfile" conv=sparse
)

echo "OK"
rm -r $tmpdir
