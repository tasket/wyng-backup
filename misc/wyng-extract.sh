#!/usr/bin/env bash

# wyng-extract.sh  -  Simple disk image extractor for Wyng archives.
#  Copyright Christopher Laprise 2018-2022 / tasket@protonmail.com
#  Licensed under GNU General Public License v3. See file 'LICENSE'.


set -eo pipefail
LC_ALL=C

echo "Wyng archive extractor, V0.3.x 20221101"

hashw=64;  addrw=17;  delimw=1;  uniqw=$(( hashw + delimw + addrw ))

while getopts "so:lt:cd" opt; do
  case $opt in
    s)  opt_sparse=1;;
    o)  outopt="$OPTARG";;
    l)  opt_list=1;;
    t)  sestag="$OPTARG";;
    c)  opt_check=1;;
    d)  opt_sparse=1; opt_diff=1;;
    \?) opterr=1;;
  esac
done
shift $(( OPTIND - 1 ))

if [ -n "$outopt" ]; then
  outvol=`realpath "$outopt"`
elif [ -z "$opt_check" ] && [ -z "$opt_list" ]; then
  opterr=1
fi
if [ -n "$opterr" ] || [ -z "$1" ] || [ -z "$2" ]; then
  echo 'Usage: wyng-extract.sh -l <wyng-dir-path> [volume-name]'
  echo '          List volume details.'
  echo
  echo '       wyng-extract.sh -c <wyng-dir-path> <volume-name>'
  echo '          Check volume intergrity.'
  echo
  echo '       wyng-extract.sh [-t session/tag] [-s] -o <save-path> <wyng-dir-path> <volume-name>'
  echo '          Extract and save volume. Use -s for sparse mode, -t to select session.'
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
  echo "Error: Path $voldir nor found."
  exit 1
fi

tmpdir=/tmp/wyng-extract
if [ -e $tmpdir ]; then mv $tmpdir $tmpdir.old; fi
rm -rf $tmpdir $tmpdir.old  &&  mkdir $tmpdir


( cd "$voldir";  curdir=`pwd`

  # Check that format version is 1 or 2
  arch_ver=`grep '^format_ver =' volinfo | awk '{print $3}'`
  case $arch_ver in
    1|2)  format_ver=$arch_ver;;
    *)    echo "Error: Did not find a compatible format.";  exit 1;;
  esac

  echo "Getting metadata for volume $volname."
  ln=`grep -E '^last =' volinfo`;   read one two s_last <<<"$ln"
  cp volinfo $tmpdir;  sed -E '/\[volumes/q' ../archive.ini >$tmpdir/archive.ini

  # Add session column to manifests and create symlinks using sequence number.
  if [ -z "$sestag" ]; then sestag=${s_last:2}; fi
  session=$s_last
  while [ ! ${session,,} = 'none' ]; do
    ln=`grep '^previous =' $session/info`;  read one two s_prev <<<"$ln"
    if [ -z "$sesnames" ] && [ ! "${session:2}" = "$sestag" ]; then session=$s_prev;  continue; fi

    ln=`grep '^sequence =' $session/info`;  read one two sequence <<<"$ln"
    sed 's|$| S_'$sequence'|'  $session/manifest  >$tmpdir/m_$sequence
    ln -s "$curdir/$session" $tmpdir/S_$sequence

    sesnames="$session $sesnames";  session=$s_prev
  done

  # List sessions and exit.
  if [ -n "$opt_list" ]; then
    for ses in $sesnames; do
      echo ${ses:2};  sed -n 's|^tag |  tag |;T;p' $ses/info
    done
    exit 0
  fi

  if [ -z "$sesnames" ]; then echo "Error: Session not found."; exit 1; fi
  echo -n "$sesnames"  >$tmpdir/sesnames
)


if [ -n "$opt_list" ]; then exit 0; fi


( cd $tmpdir

  # Get a list of manifest files, sorted by sequence in filename, as 'm_last' and 'm_therest'.
  ln=`find . -name 'm_*' -exec basename '{}' \; | sort --reverse -V | tr '\n' ' '`
  read m_last m_therest <<<"$ln"
  read sesnames  <<< `cat sesnames`

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
    zstd)  DECOMPRESS="zstdcat";    COMPRESS="zstd --no-check -T2 -$compr_level";;
    zlib)  DECOMPRESS="unpigz -cz"; COMPRESS="pigz -z -$compr_level";;
    bz2)   DECOMPRESS="bzcat";      COMPRESS="bzip2 -$compr_level";;
  esac

  case $hashtype in
    sha256)   HASH_CHECK="sha256sum";;
    blake2b)  HASH_CHECK="b2sum -l $(( hashw * 4 ))";;
  esac

  # Parse manifest fields: 1=digest, 2=first fname segment, 3=second fname seg, 4=session
  mregex='^(\S+)\s+x(\S{9})(\S+)\s+(S_\S+)'

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
      echo "Error: Sparse mode not yet supported with zlib compression."
      exit 1
    fi

    # Make local vol correct size for comparison
    if [ ! -b "$outvol" ]; then
      truncate --size $volsize "$outvol"
    elif lvm lvdisplay "$outvol" >/dev/null; then
      lvm lvresize -L ${volsize}B "$outvol" 2>/dev/null
    fi

    for ((i=0; i<volsize; i=i+megachunksize)); do
      echo -en "Hashing volume $i \r"
      dd if="$outvol" bs=$chunksize count=$chunks skip=$i iflag=skip_bytes status=none \
      |  split -d -a 5 -b $chunksize - CHK/

      cd CHK

      # Compress chunk files
      find . -name '*[0-9][0-4]'  |  xargs -r $COMPRESS  ||  touch ../cmprfail  &
      find . -name '*[0-9][5-9]'  |  xargs -r $COMPRESS  ||  touch ../cmprfail  &
      wait
      if [ -e ../cmprfail ]; then
        echo "Compression error."; exit 1
      fi

      # Hash the chunk files, remove extension, convert 2nd col to hex fname
      find . -type f -printf '%f\n' \
      |  xargs -r $HASH_CHECK  |  sed -E 's|\..+$||'  |  sort -k2,2  \
      |  awk -v i="$i" -v cs="$chunksize" '{ printf "%s x%.16x\n", $1, $2 * cs + i }' \
      >>../local-manifest

      cd ..;   rm -f CHK/*
    done

    echo -en "\nCreating diff index..."
    sort -um -k2,2 $m_last $m_therest  |  sed -E '/ x'$lastchunk'/q; s|^0\s+|'$zhash' |' \
    |  sort -ms -k2,2 - local-manifest  |  uniq -u -w $uniqw  |  sort -um -k2,2  \
    |  sed -E 's|^'$zhash'|0|'  \
    >diff-manifest

    if [ -n "$opt_diff" ]; then
      echo '---'
      cat diff-manifest
      exit $(( `wc -l diff-manifest | cut -d ' ' -f1` > 0 ))
    fi

    # Create a zerofill manifest for the extraction merge-sort.
    # This will fill-in any address gaps in the diff as zero chunks.
    sed -E 's|^\S+|0|' local-manifest  >zerofill-manifest

    # Zeros from diff-manifest must be 'punched' into local volume since
    # final step uses zeros for sparse seeking. Needs optimizing.
    echo -en "\nFilling zeros..."
    sed -E 's|^0\s+(\S+)\s*.*|0\1|; t; d' diff-manifest  \
    |  xargs -i -r $HOLEPUNCH -z -l $chunksize -o {} "$outvol"

    echo -en "\nChecking volume hashes..."
    sed -E '/^0 x/ d; s|'"$mregex"'|\1 \4/\2/x\2\3|;' diff-manifest  \
    |  $HASH_CHECK -c --status

    # Change the merge-sort inputs to use the differential versions during extraction.
    m_last=diff-manifest
    m_therest=zerofill-manifest

  elif [ "$opt_check" = 1 ]; then
    # Test entire arch volume integrity against manifest hashes.
    echo -n "Checking volume hashes..."

    sort -umd -k2,2 $m_last $m_therest  |  sed -E "/ x$lastchunk/q" \
    |  sed -E '/^0 x/ d; s|'"$mregex"'|\1 \4/\2/x\2\3|;' \
    |  $HASH_CHECK -c --status

    exit 0
  fi


  echo -en "\nExtracting data to $outvol..."

  # Set local volume to correct size.
  if [ ! -b "$outvol" ]; then
    if [ -z "$opt_sparse" ]; then rm -f "$outvol"; fi
    truncate --size $volsize "$outvol"
  elif lvm lvdisplay "$outvol" >/dev/null; then
    if [ -z "$opt_sparse" ]; then blkdiscard "$outvol"; fi
    lvm lvresize -L ${volsize}B "$outvol" 2>/dev/null || true
  fi
  if [ ! -e "$outvol" ]; then
    echo "Error: Output/save path does not exist!"
    exit 1
  fi

  # Merge-sort complete manifest & convert to simple filenames for decompressor,
  # then pipe data to dd.
  sort -um -k2,2 $m_last $m_therest  |  sed -E "/ x$lastchunk/q" \
  |  sed -E 's|^0 x.*|ZERO|; t; s|'"$mregex"'|\4/\2/x\2\3|'  \
  |  xargs $DECOMPRESS -f  \
  |  dd of="$outvol"  obs=$chunksize conv=sparse,notrunc,nocreat

  sync
)

echo
echo "OK"
rm -r $tmpdir
