#!/usr/bin/env bash

# wyng-extract.sh  -  Simple disk image extractor for Wyng archives.
#  Copyright Christopher Laprise 2018-2020 / tasket@protonmail.com
#  Licensed under GNU General Public License v3. See file 'LICENSE'.


set -eo pipefail
LC_ALL=C

echo "Wyng archive extractor, V0.2.4 20200907"

formatver=1
hashw=64;  addrw=17;  delimw=1;  uniqw=$(( hashw + delimw + addrw ))

while getopts "so:c" opt; do
  case $opt in
    s)  opt_sparse=1;;
    o)  outopt="$OPTARG";;
    c)  opt_check=1;;
    \?) opterr=1;;
  esac
done
shift $(( OPTIND - 1 ))

if [ -n "$outopt" ]; then
  ## outvol=`readlink -f "$outopt"`
  outvol="$outopt"
elif [ -z "$opt_check" ]; then
  opterr=1
fi
if [ -n "$opterr" ] || [ -z "$1" ] || [ -z "$2" ]; then
  echo "Usage: wyng-extract.sh -c <wyng-dir-path> <volume-name>"
  echo "       wyng-extract.sh [-s] -o <save-path> <wyng-dir-path> <volume-name>"
  exit 1
fi

if [ -b "$outvol" ]; then
  HOLEPUNCH=blkdiscard
else
  HOLEPUNCH=fallocate
fi

volname="$2"
voldir="$1/default/$volname"
if [ ! -e "$voldir" ]; then
  echo "Path $voldir nor found."
  exit 1
fi

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
  ln=`grep -E '^vgname ='  archive.ini`;          read one two vgname <<<"$ln"
  ln=`grep -E '^chunksize ='  archive.ini`;       read one two chunksize <<<"$ln"
  ln=`grep -E '^compression ='  archive.ini`;     read one two compr <<<"$ln"
  ln=`grep -E '^compr_level ='  archive.ini`;     read one two compr_level <<<"$ln"
  ln=`grep -E '^hashtype ='  archive.ini`;        read one two hashtype <<<"$ln"
  lastchunk=`printf '%016x' $(( ($volsize - 1) - (($volsize - 1) % $chunksize) ))`
  echo "Volume size = $volsize bytes."

  case $compr in
    zlib)  DECOMPRESS="unpigz -cz"; COMPRESS="pigz -z -$compr_level";;
    bz2)   DECOMPRESS="bzcat";      COMPRESS="bzip2 -$compr_level";;
  esac

  case $hashtype in
    sha256)   HASH_CHECK="sha256sum";;
    blake2b)  HASH_CHECK="b2sum";;
  esac

  # Parse manifest fields: 1=digest, 2=first fname segment, 3=second fname seg, 4=session
  mregex='^(\S+)\s+x(\S{9})(\S+)\s+(S_\S+)'

  # Test data integrity against manifest hashes.
  if [ "$opt_check" = 1 ]; then
    echo -n "Checking volume hashes..."

    sort -umd -k2,2 $m_last $m_therest  |  sed -E "/ x$lastchunk/q" \
    |  sed -E '/^0 x/ d; s|'"$mregex"'|\1 \4/\2/x\2\3|;' \
    |  $HASH_CHECK -c --status

    exit 0
  fi


  # Hash local volume for sparse mode:
  # Creates a complete 'manifest' from a local volume
  # which is then compared vs Wyng archive manifests.
  chunks=1024 # batch size
  megachunksize=$(( chunksize * chunks ))
  truncate --size $chunksize ZERO
  $COMPRESS -c ZERO >ZERO.c
  ln=`$HASH_CHECK ZERO.c`;  read zhash two <<<"$ln"
  mkdir CHK

  if [ -n "$opt_sparse" ]; then
    if [ "$compr" = "zlib" ]; then
      echo "Sparse mode not yet supported with zlib compression."
      exit 1
    fi

    for ((i=0; i<volsize; i=i+megachunksize)); do
      echo -en "Hashing volume $i \r"
      dd if="$outvol" bs=$chunksize count=$chunks skip=$i iflag=skip_bytes status=none \
      |  split -d -a 5 -b $chunksize - CHK/

      cd CHK

      # Compress chunk files
      find . -name '*[0-9][0-2]'  |  xargs -r $COMPRESS  ||  touch ../cmprfail  &
      find . -name '*[0-9][3-5]'  |  xargs -r $COMPRESS  ||  touch ../cmprfail  &
      find . -name '*[0-9][6-8]'  |  xargs -r $COMPRESS  ||  touch ../cmprfail  &
      find . -name '*[0-9]9'   |  xargs -r $COMPRESS  ||  touch ../cmprfail  &
      wait
      if [ -e ../cmprfail ]; then
        echo "Compression error."; exit 1
      fi

      # Hash the chunk files, remove extension, convert 2nd col to hex fname
      find . -type f -printf '%f\n' \
      |  xargs -r $HASH_CHECK  |  sort -k2,2  |  sed -E 's/\..+$//'  \
      |  awk -v i="$i" -v cs="$chunksize" '{ printf "%s x%.16x\n", $1, $2 * cs + i }' \
      >>../local-manifest

      cd ..;   rm -f CHK/*
    done

    echo -en "\nCreating diff index..."
    sort -um -k2,2 $m_last $m_therest  |  sed -E '/ x'$lastchunk'/q; s|^0\s+|'$zhash' |' \
    |  sort -ms -k2,2 - local-manifest  |  uniq -u -w $uniqw  |  sort -um -k2,2  \
    |  sed -E 's|^'$zhash'|0|'  \
    >diff-manifest

    # Create a zerofill manifest for the extraction merge-sort.
    # This will fill-in any address gaps in the diff as zero chunks.
    sed -E 's|^\S+|0|' local-manifest  >zerofill-manifest

    # Zeros from diff-manifest must be 'punched' into local volume since
    # final step uses zeros for sparse seeking. Needs optimizing.
    echo -en "\nFilling zeros..."
    sed -E 's|^0\s+(\S+)\s*.*|0\1|; t; d' diff-manifest  \
    |  xargs -i -r $HOLEPUNCH -z -l $chunksize -o {} "$outvol"

    # Change the merge-sort inputs to use the differential versions during extraction.
    m_last=diff-manifest
    m_therest=zerofill-manifest

  fi


  echo -en "\nExtracting volume data to $outvol..."

  if [ ! -b "$outvol" ]; then
    if [ -z "$opt_sparse" ]; then rm "$outvol"; fi
    truncate --size $volsize "$outvol"
  elif lvdisplay "$outvol" >/dev/null; then
    if [ -z "$opt_sparse" ]; then blkdiscard "$outvol"; fi
    lvresize -L ${volsize}B "$outvol" 2>/dev/null || true
  fi
  if [ ! -e "$outvol" ]; then
    echo "ERROR: Output/save path does not exist!"
    exit 1
  fi

  sort -um -k2,2 $m_last $m_therest  |  sed -E "/ x$lastchunk/q" \
  |  sed -E 's|^0 x.*|ZERO|; t; s|'"$mregex"'|\4/\2/x\2\3|'  \
  |  xargs $DECOMPRESS -f  \
  |  dd of="$outvol"  obs=$chunksize conv=sparse,notrunc,nocreat

  sync
)

echo
echo "OK"
#rm -r $tmpdir
