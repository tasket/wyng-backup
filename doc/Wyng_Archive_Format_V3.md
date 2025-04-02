Wyng Archive Format V3
======================

Document version 0.9.7, date 2025-03-28  
Author:  Christopher Laprise,  tasket@protonmail.com  

Home URLs:  
  https://github.com/tasket/wyng-backup  
  https://codeberg.org/tasket/wyng-backup  

Copyright 2023 Christopher Laprise, see 'License' section.

## Introduction

The Wyng archive format is designed to store and manage raw disk volumes including logical
volumes, disk image files & block devices for backup and archival purposes.  It leverages the
efficiency of common Unix-like filesystems as opposed to monolithic databases, which in turn
facilitates quick addition and removal of incremental snapshots as well as data de-duplication.
Authentication of data in either encrypted or cleartext form is also supported.

## General Overview

#### Directory Structure:

```
NAME                                    DESCRIPTION
mylaptop.backup/                        archive dir
    ├── archive.ini                     archive metadata root
    ├── archive.salt                    archive encryption salt
    ├── salt.bak                        backup copy of salt
    ├── Vol_ab1234/                     volume dir 'Vol_hexnum'
    │   ├── volinfo                     volume metadata
    │   │
    │   ├── S_20230101-120101/          session 0 dir 'S_date-time'
    │   │   ├── info                    session 0 metadata
    │   │   ├── manifest.z              session 0 manifest: chunk hash list
    │   │   └── 000000000/              chunk dir for range 0x000000000XXXXXXX
    │   │       ├── x0000000000000000   data chunk
    │   │       ├── x0000000000020000   data chunk
    │   │       ├── x0000000000040000   data chunk
    │   │       ├── x0000000000060000   data chunk
    │   │       ├── x0000000000080000   data chunk
    │   │       ├── x00000000000a0000   data chunk
    │   │       │   [...]               data chunks...
    │   │       └── x0000000002e00000   data chunk
    │   │
    │   ├── S_20230101-130101/          session 1 dir
    │   │   ├── info                    session 1 metadata
    │   │   ├── manifest.z              session 1 manifest
    │   │   └── 000000000/              chunk dir for range 0x000000000XXXXXXX
    │   │       ├── x0000000000080000   data chunk
    │   │       ├── x0000000001b40000   data chunk
    │   │       └── x0000000002e00000   data chunk
```

Wyng archives are directories similar to Apple OS X _sparsebundles_ in which volume data is divided
into chunk files which are named for their respective addresses (offsets) within the volume.  This
simple hierarchical structure also accomodates multiple volumes and multiple sessions (or snapshots)
for each volume.  The top-level dir is named
by the user and contains subdirs for each volume named 'Vol\_XXXXXX' (hex).  Beneath the volume dirs
are session subdirs named 'S\_YYYYMMDD-HHMMSS' (date-time) which have subdirs named after the
9 most-significant digits (MSD) of the hexadecimal address ranges in the volume.  Within the address
MSD dirs are the data chunk files.

Metadata files within an archive are also hierarchical, with _archive.ini_ forming the root which holds global variables and a volume list pointing to volume dirs and hash values to validate each volume's _volinfo_ file.  Similarly, each _volinfo_ has a list pointing to the volume's session
subdirs along with the hash values to validate session _info_ files.  And each session's _info_
file contains a hash to validate the session's _manifest.z_ file.  Each volume may also have a file named _session_, a json list of session names showing their actual sequencing unaffected by local time zone.

Finally, _manifest.z_ contains a simple list of the volume data chunks contained in that session,
referencing each chunk's address within the volume and its hash value (or '0' for all-zero chunks).
The manifest for the oldest session contains a contiguous list of chunks, while newer
session manifests list only chunks that have changed since the prior session.

## Write operations

The major causes of change in a Wyng archive are the Wyng program's `send`, `prune` and `delete`
commands.

For example, a `send` operation will deposit data chunks into a new session dir suffixed with '-tmp',
and then rename the dir without the suffix when the session transfer is complete.  The data chunks
themselves may be either regular binary files or space-saving hard links to existing data
chunk files when de-duplication is used.  There is no expectation of chunk files ever being updated
or re-written except when they are replaced with hard links; they are intended mainly to be moved to
other session dirs or to be deleted.

New or changed metadata files are saved initially with a '.tmp' extension for the object in
question, and then "zipper"-saved up the hierarchy to _archive.ini.tmp_ with updated hashes for
each changed file.  The '.tmp' files are then "zipper" renamed up the hierarchy without the
extension to replace the old metadata.  For a Wyng `send` operation, the following metadata
files must be created or updated: _manifest.z, info, volinfo, archive.ini_.

## Read operations

Accessing a volume session so that it appears as a complete data snapshot over the volume's
entire address range involves combining all of the volume's session manifests up to that point
(but not later ones) in a merge-unique operation keyed on the manifest's chunk address column.
For example, the following shell commands combine two decoded session manifests to create a
complete representation of the latter session:

```
p=mylaptop.backup/Vol_ab1234
sort -umsd -k2,2 $p/S_20230101-120101/manifest $p/S_20230101-130101/manifest >/tmp/ab1234
```

A third column can be automatically added to indicate the session
subdirs where each chunk is stored.
This results in a list with each chunk's hash, address and path for the
volume's entire range at that session's point in time.  (See the Wyng function 'merge_manifests()'
for implementation details.)

## Compression and hash types

Selectable compression types are: _zstd_ (zstandard), _zlib_ and _bz2_ (bzip2). All objects except for
salt files are compressed.  All compressed objects use the same type selected by the user except for
the _archive.ini BODY_ which always uses _gzip_.

Hash type can be either _blake2b_ or _hmac-sha256_, uniform for an entire archive, with hashes
stored as 256-bit 'URL safe' base64 strings.

## Archive integrity

The Wyng format + code enforces a strict integrity regime by embedding each object's hash (digest)
into the 'parent' metadata that references it.  On Wyng startup, each data and metadata validation
step is performed on a file immediately after it is decrypted and before it is decompressed,
although _archive.ini_ is unique in this respect as the archive root.

The validation chain is:  

archive.ini --\> volinfo --\> info --\> manifest.z --\> chunk files

Without _authentication_ of the _archive.ini_ root, this process functions like a strong internal
consistency check.  However, with authentication of the root, that authentication extends
to the entire archive.  For encrypted archives, an authenticating cipher is always used for
metadata starting at the root.  Users may also authenticate _archive.ini_ independently, such as
with a PGP signature; this allows authentication of un-encrypted Wyng archives.

## Encryption

Wyng archives employ a combination of XChaCha20-Poly1305 AEAD and XChaCha20 ciphers for metadata and
data, respectively.  Each cipher uses a 256-bit key derrived from a passphrase and a 256-bit salt.

Re-keying is _not_ implemented and all keys are static.  However, the cipher's 192-bit
nonces are used to their full extent with each nonce being generated by _libsodium_-recommended
methods including a protected 80-bit counter and a keyed hash of _m || rnd_, as well as
a keyed hash of _Hk || rnd_.  In counter mode, the
counter for each key is mirrored between the _archive.ini_ and the local cache of the
_archive.salt_, with the highest value of the two used at runtime.  Specifics of each
encryption mode's key, counter, nonce and ciphertext handling can be found in
Wyng's _DataCryptography_ class.

Since authentication carries a performance penalty, and since
Wyng's internal integrity checking extends authentication from the root to all other files, a
non-authenticating cipher is typically used for data chunks.

## Data Structures

### archive.ini

METADATA ROOT

##### HEADER

| Content       | Field Name    | Type    | Length (Bytes) | Desc |
|:--------------|:--------------|:--------|:-------|:-----|
|'[WYNG03]\x0a' | header prefix | UTF-8   | 9      | File type with version
|'ci = XX\x0a'  | cipher mode   | UTF-8   | 8      | Two digits: cipher type
|_N_-bytes      | BODY          | binary  | _variable_ | gzip and encrypted, or gzip only if 'ci = 00'

##### BODY (ENCRYPTED)

Where encrypted, the metadata files (or _archive.ini_ BODY) each consist of a single _message_,
and are prefixed with the associated _nonce_ and _tag_.  For the _ChaCha20-Poly1305_ cipher,
the precise _message_ layout is:

| Bytes  | Type    | Desc |
|:-------|:--------|:-----|
| 24     | binary  | nonce
| 16     | binary  | AEAD tag
| *      | binary  | msg ciphertext

##### BODY (PLAINTEXT)
(ALL = UTF-8 encoded lines after decryption and decompression, ini config format):

| Attribute or Section Name  | Type       | Desc |
|:---------------------------|:-----------|:-----|
|'[var]'           |         | ini section header
|'uuid = '         | str     | Archive UUID-4
|'updated_at = '   | float   | Unix seconds: Metadata timestamp
|'format_ver = '   | int     | Format version, matches header prefix, Ex. _3_
|'chunksize = '    | int     | Data chunk size,    Ex. _131072_
|'compression = '  | str     | Compression type,   Ex. _zstd_
|'compr_level = '  | int     | Compression level,  Ex. _3_
|'hashtype = '     | str     | Hash type: _blake2b_ or _sha256_
|'ci_mode = '      | str     | Cipher selection, two characters. Must match header 'ci'.
|'dataci_count = ' | int     | Counter for data cipher
|'mci_count = '    | int     | Counter for metadata cipher
|                  | _blank_ |
|'[volumes]'       |         | ini section header: volumes list
|vid[0] ' = '      | 256bit_b64_str | Volume id & hash for compressed 'volinfo' file
|vid[N] ' = '      | 256bit_b64_str | Volume id & hash for [...]
|                  | _blank_ |
|'[in_process]'    |         | ini section header; usually empty
|N ' = '           | str     | Brief enum dict starting with volume id and operation name; describes interrupted write command such as 'delete' or 'merge'


---

### archive.salt

Holds four key salt + counter pairs, with the first two sets for data (slot 0) and metadata (slot 1). Slots 2 and 3 provide salts for derived subkeys for 'Wyng_Nonces' and 'Wyng-Manifest-Hash' contexts, respectively.  The offset for a key slot is calculated as: _(16 + 64) \* slot_.

The key derivation function is _scrypt(passphrase, salt, n=2^19, r=8, p=1, maxmem=640\*1024\*1024, keysize)_.
The subkey derivation function is _HKDF(key, output_size, salt, 'SHA512', slot-2, context)_, where
the SHA-512 hash function is used and _output_size_ is typically 64 (bytes).

The last 104 bytes are comprised of a BLAKE2b hash of all four salts, encrypted with the
metadata cipher (slot 1).  This is used to check the salt file integrity.

| Bytes  | Type    | Desc |
|:-------|:--------|:-----|
| 10     | int     | 80-bit counter, slot 0
| 64     | binary  | 512-bit key salt, slot 0
| 10     | int     | 80-bit counter, slot 1
| 64     | binary  | 512-bit key salt, slot 1
| 10     | int     | NULL / unused
| 64     | binary  | 512-bit key salt, slot 2
| 10     | int     | NULL / unused
| 64     | binary  | 512-bit key salt, slot 3
| 24     | binary  | Salt hash nonce
| 16     | binary  | Salt hash tag
| 64     | binary  | Salt hash, encrypted

---

### volinfo

VOLUME METADATA  
(ALL = UTF-8 encoded lines after decryption and decompression):  
  
| Attribute Name  | Type       | Desc |
|:----------------|:-----------|:-----|
|'name = '        | str        | Volume name (max. 4000 chars or 112 chars for LVM)
|'desc = '        | str        | Volume description (max. 100 chars)
|'S_YYYYMMDD-HHMMSS = ' | 256bit_b64_str | Session name = hash for compressed 'info' file (0 or more occurrences)


---

### info

SESSION METADATA  
(ALL = UTF-8 encoded lines after decryption and decompression):  
  
| Attribute Name   | Type       | Desc |
|:-----------------|:-----------|:-----|
|'localtime = '    | int        | Unix nanoseconds: snapshot timestamp
|'volsize  = '     | int        | Volume size in bytes
|'sequence = '     | int        | Session sequence number
|'previous = '     | str        | Name of previous session or "None" for oldest session
|'permissions  = ' | str        | mode_int:user:group or single char "r\|w"
|'manifesthash = ' | 256bit_b64_str or '0' | manifest hash, or '0' if empty session
|'tag = '          | str        | 'tag_id description' (0 or more occurrences)


---

### manifest.z

DATA CHUNK HASH INDEX

* Named 'manifest' in cache when decrypted and decompressed.
* ASCII 'C' encoded lines after decryption and decompression.
* Plaintext consists of __two columns__ always sorted by column two (xCHUNK_ADDRESS). No headers or sections.
* Single _space_ (0x20) between columns, EOL (0x0a) line termination.
* Single '0' in column one denotes all-zero 'hole' chunk with no associated data chunk file.

  
_256bit_b64_str xCHUNK_ADDRESS_

...or...

0 _xCHUNK_ADDRESS_

---

### x0000000000000000

DATA CHUNK

Each data chunk file is named for the in-volume address (i.e. offset) from which the data was read.
It contains compressed and encrypted series of data blocks from a source volume, which is validated
by the corresponding hash in _manifest.z_.

The chunk sizes before compression and encryption are uniform for each archive, with the
exception of a volume's last chunk which is often smaller.
The chunk size choices at archive creation time are _64KiB / 2 \* (2^N)_, where _N_ is an
integer from 1 to 6.

For the XChacha20 cipher, an encrypted chunk consists of a single _message_
prefixed by a 24-byte _nonce_.  For non-encrypted archives, a file will
begin with a compression header generated by the chosen compression algorithm.
Data chunk contents are processed as _raw data blocks_ with no inspection of internal
content beyond hashing and zero/hole detection.

---

## Glossary

_byte_ – Eight bits; an octet.

_hash_ – A cryptograghic digest of binary data, via either BLAKE2b-256 or SHA-256.

_manifest_ – A list of volume data chunks which identifies each chunk by its hash and address (offset within the volume).

_session_ – A version of a volume during a specific backup session at a specific time; a snapshot copy.

_volume_ – Any contiguous set of binary blocks, which likely contains a filesystem; a logical volume, disk image or disk partition.

---

## License

Licensed under GNU General Public License v3. See file 'LICENSE'.
Permission to redistribute under similar naming "Wyng Archive Format", "Wyng", "wyng backup", etc.
is granted only for un-modified copies (GPLv3 S.7-c).
