_<h1 align="center">Wyng</h1>_
<p align="center">
Fast incremental backups for logical volumes.
</p>

### Introduction

Wyng is able to deliver faster incremental backups for logical
volumes and disk images. It accesses *copy-on-write* metadata (instead of comparing all data
for each backup) to instantly find changes since the last backup.
Combined with its efficient archive format, Wyng can also very quickly reclaim space
from older backup sessions.

Having nearly instantaneous access to volume changes and a nimble archival format
enables backing up even terabyte-sized volumes multiple times per hour with little
impact on system resources.

Wyng pushes data to archives in a stream-like fashion, which avoids writing temporary
caches of data to disk. And Wyng's ingenious snapshot rotation avoids common
_aging snapshot_ space consumption pitfalls.

Wyng also doesn't require the source admin system to ever mount processed volumes or
to handle them as anything other than blocks, so it safely handles
untrusted data in guest filesystems to bolster container-based security.


### Status

Public release v0.3 with a range of features including:

 - Incremental backups of Linux logical volumes

 - Supported destinations: Local filesystem, Virtual machine or SSH host

 - Send, receive, verify and list contents

 - Fast pruning of old backup sessions

 - Basic archive management such as add/delete volume and auto-pruning

 - Data deduplication

 - Marking and selecting snapshots with user-defined tags

Beta release v0.8 major enhancements:

 - Btrfs and XFS source volumes

 - Authenticated encryption with auth caching & timeout
 
 - Fast differential receive based on available snapshots

 - Simpler authentication of non-encrypted archives
 
 - Overall faster detection of changed/unchanged volumes

 - Metadata compression

 - Mountpoints no longer required at destination

 - Simple selection of archives and local paths: Choose any local or dest each time you run Wyng

 - Multiple volumes can now be specified for most Wyng commands

 Wyng is released under a GPL license and comes with no warranties expressed or implied.


v0.8beta1 Requirements & Setup
---

Before starting:

* Python 3.8 or greater is required for basic operation.

* For encryption and top performance, the _python3-pycryptodome_ and _python3-zstd_ packages
should be installed, respectively.

* Volumes to be backed-up must reside locally in one of the following snapshot-capable
storage types:  LVM thin-provisioned pool, Btrfs subvolume, or XFS/reflink capable filesystem.

* For backing up from LVM, _thin-provisioning-tools & lvm2_ must be present on the source system.

* The destination system where the Wyng archive is stored (if different from source) should
also have python3, plus a basic Unix command set and filesystem (i.e. a typical Linux or BSD
system). Otherwise, FUSE may be used to access remote storage using sftp or s3 protocols
without concern for python or Unix commands.

* See the 'Testing' section below for tips and caveats about using the alpha and beta versions.

Wyng is distributed as a single Python executable with no complex
supporting modules or other program files; it can be placed in '/usr/local/bin'
or another place of your choosing.

Archives can be created with `wyng arch-init`:

```

wyng arch-init --dest=ssh://me@exmaple.com:/home/me/mylaptop.backup

...or...

wyng arch-init --dest=file:/mnt/drive1/mylaptop.backup


```

The examples above create a 'mylaptop.backup' directory on the destination.
The `--dest` argument includes the destination type, remote system (where applicable)
and directory path.


## Operation

Run Wyng using the following commands and arguments in the form of:

**wyng command \<parameters> [volume_name]**

### Command summary

| _Command_ | _Description_  |
|---------|---|
| **list** _[volume_name]_    | List volumes or volume sessions.
| **send** _[volume_name]_    | Perform a backup of enabled volumes.
| **receive** _volume_name [*]_   | Restore volume(s) from the archive.
| **verify** _volume_name [*]_    | Verify volumes' data integrity.
| **prune** _[volume_name] [*]_   | Remove older backup sessions to recover archive space.
| **monitor**                 | Collect volume change metadata & rotate snapshots.
| **diff** _volume_name [*]_      | Compare local volume with archived volume.
| **add** _volume_name [*]_       | Add a volume to the configuration.
| **delete** _volume_name_    | Remove entire volume from config and archive.
| **rename** _vol_name_ _new_name_  | Renames a volume in the archive.
| **arch-init**               | Initialize archive configuration.
| **arch-check** _[volume_name] [*]_    | Thorough check of archive data & metadata
| **arch-deduplicate**        | Deduplicate existing data in archive.
| **version**                 | Print the Wyng version and exit.


### Parameters / Options summary

| _Option_                      | _Description_
|-------------------------------|--------------
--local=_vg/pool_  _...or..._    | Storage pool containing local volumes.
--local=_/absolute/path_    | 
--dest=_type:location_   | (arch-init) Destination of backup archive.
--session=_date-time[,date-time]_ | Select a session or session range by date-time or tag (receive, verify, prune).
--authmin=_N_          | Remember authentication for N minutes.
--volex=_volname_      | Exclude volumes (send, monitor, list, prune).
--dedup, -d            | Use deduplication for send (see notes).
--all-before           | Select all sessions before the specified _--session date-time_ (prune).
--autoprune=off        | Automatic pruning by calendar date.
--keep=_date-time_     | Specify date-time or tag of sessions to keep (prune).
--tag=tagname[,desc]   | Use session tags (send, list).
--save-to=_path_       | Save volume to _path_ (receive).
--sparse               | Receive volume data sparsely (implies --sparse-write)
--sparse-write         | Overwrite local data only where it differs (receive)
--use-snapshot         | Use snapshots when available for faster `receive`.
--remap                | Remap volume during `send` or `diff`.
--encrypt=_cipher_     | Set encryption mode or _'off'_ (default: _'xchacha20-t3'_)
--compression          | (arch-init) Set compression type:level.
--hashtype             | (arch-init) Set data hash algorithm: _hmac-sha256_ or _blake2b_.
--chunk-factor         | (arch-init) Set archive chunk size.
--meta-dir=_path_      | Use a different metadata dir than the default.
--unattended, -u       | Don't prompt for interactive input.
--clean                | Perform garbage collection (arch-check) or medata removal (delete).
--force                | Not used with most commands.
--verbose              | Increase details.
--quiet                | Shhh...
--debug                | Debug mode

#### send

Performs a backup by storing volume data to a new session in the archive.  If the volume
already exists in the archive, incremental mode is automatically used.

```

wyng send my_big_volume --local=vg/pool --dest=file:/mnt/drive1/mylaptop.backup


```

A `send` operation may refuse to backup a volume if there is not enough space on the
destination. One way to avoid this situation is to specify `--autoprune=on` which
will cause Wyng to remove older backup sessions from the archive when space is needed.


#### receive

Retrieves a volume instance (using the latest session ID
if `--session` isn't specified) from the archive and saves it to either the volume's
original path or the path specified with `--save-to`.  The `--local` option may also be
specified when not using `--save-to`.
If `--session` is used, only one date-time is accepted. The volume
name is required.

```

wyng receive vm-work-private --local=vg/pool --dest=file:/mnt/drive1/mylaptop.backup


```

...restores a volume called 'vm-work-private' to 'myfile.img' in
the default _local_ pool.

Its possible to receive to any valid file path or block device using the `--save-to` option,
which can be used in place of `--local`.
For any save path, Wyng will try to discard old data before receiving unless `--sparse`,
`--sparse-write` or `--use-snapshot` options are used.


#### verify

The `verify` command is similar to `receive` without saving the data. For both
`receive` and `verify` modes, an error will be reported with a non-zero exit
code if the received data does not pass integrity checks.


#### prune

Quickly reclaims space on a backup drive by removing
any prior backup session you specify; it does this
without re-writing data blocks or compromising volume integrity.

To use, supply a single exact date-time in _YYYYMMDD-HHMMSS_ format to remove a
specific session, or two date-times representing a range:

```
wyng prune --session=20180605-000000,20180701-140000 --dest=file:/mnt/drive1/mylaptop.backup
```

...removes backup sessions from midnight on June 5 through 2pm on July 1 for all
volumes. Alternately, `--all-before` may be used with a single `--session` date-time
to prune all sessions prior to that time.

If volume names aren't specified, `prune` will operate across all
enabled volumes.

The `--keep` option can accept a single date-time or a tag in the form `^tagID`.
Matching sessions will be excluded from pruning and autopruning.


#### monitor

Frees disk space that is cumulatively occupied by aging snapshots, thereby addressing a
common resource usage issue with snapshot-based backups.
After harvesting their change metadata, the older snapshots are replaced with
new ones. Running `monitor` isn't strictly necessary, but it only takes a few seconds
and is good to run on a frequent, regular basis if you have some volumes that are
very active. Volume names may also be
specified if its desired to monitor only certain volumes.

This rule in /etc/cron.d runs `monitor` every 20 minutes:

```
*/20 * * * * root su -l -c '/usr/local/bin/wyng monitor'
```

#### diff

Compare a local volume snapshot with the archive and report any differences.
This is useful for diagnostics and can also be useful after a verification
error has occurred. The `--remap` option will record any differences into the
volume's current change map, resulting in those blocks being scanned on
the next `send`.


#### add

Adds new, empty volumes to the archive.  On subsequent `send`, Wyng will backup
the volume data if it present.


#### delete

Removes a volume's Wyng-managed snapshots, config and metadata from the source system and
all of its *data* from the destination archive (everything deleted except the source
volume). Use with caution!

An alternate form of `delete` will remove all Wyng archive-related metadata (incl. snapshots) from the
local system without affecting the archive on the destination:

```

wyng delete --clean

```

Alternately, using `delete --clean --all` will remove all known Wyng metadata from the local system,
including any snapshots from the `--local` path.

#### rename
```

wyng rename oldname newname

```

Renames a volume _'oldname'_ in the archive to _'newname'_. Note: This will rename only the
archive volume, _not_ your source volume.


#### arch-deduplicate

De-duplicates the entire archive by removing repeating patterns. This can save space
on the destination's drive while keeping the archived volumes intact.

De-duplication can also be performed incrementally by using `--dedup` with `send`.


```

wyng arch-deduplicate

```


#### arch-init

Initialize a new backup archive configuration...
```

wyng arch-init --dest=file:/mnt/backups/archive1

```

Initialize a new backup archive with storage parameters...
```

wyng arch-init --dest=file:/mnt/backups/mybackup --compression=zstd:7

```


#### arch-check

Intensive check of archive integrity, reading each session completely starting with
the newest and working back to the oldest. This differs from `verify` which first bulids a complete
index for the volume and then checks only/all data referenced in the index.

Using `--session=newest` provides a 'verify the last session' function (useful after an incremental
backup). Otherwise, supplying a date-time will make `arch-check` start the check from that point and
then continue working toward the oldest session. Session ranges are not yet supported.

Depending on how `arch-check` is used, the verification process can be shorter _or much longer_
than using `verify` as the latter is always the size of a volume snapshot. The longest, most
complete form `arch-check` is to supply no parameters, which checks all sessions in all volumes.



#### Options/Parameters for arch-init

`--dest` (see below)


`--compression` accepts the forms `type` or `type:level`. The three types available are `zstd` (zstandard), plus `zlib` and `bz2` (bzip2). Note that Wyng will only default
to `zstd` when the 'python3-zstd' package is installed; otherwise it will fall back to the less
capable `zlib`. (default=zstd:3)


`--hashtype` accepts a value of either _'blake2b'_ or _'hmac-sha256'_ (default).
The digest size is 256 bits.


`--chunk-factor` sets the pre-compression data chunk size used within the destination archive.
Accepted range is an integer exponent from '1' to '6', resulting in a chunk size of 64kB for
factor '1', 128kB for factor '2', 256kB for factor '3' and so on. To maintain a good
space efficiency and performance balance, a factor of '2' or greater is suggested for archives
that will store volumes larger than about 100GB. (default=2)


`--encrypt` selects the encryption cipher/mode. See _Testing_ section for description of choices.

Note that _encrypt, compression, hashtype_ and _chunk-factor_ cannot be changed for an archive once it is initialized.


### General Options

`--dest=URL`

This option tells Wyng where to access the archive. It accepts one of the following forms:

| _URL Form_ | _Destination Type_
|----------|-----------------
|__file:__/path                           | Local filesystem
|__ssh:__//user@example.com[:port][/path]      | SSH server
|__qubes:__//vm-name[/path]                     | Qubes virtual machine
|__qubes-ssh:__//vm-name:me@example.com[:port][/path]  | SSH server via a Qubes VM


`--local`

Takes one of two forms: Either the source volume group and pool as 'vgname/poolname'
or a file path on a reflink-capable filesystem such as Btrfs or XFS (for Btrfs the path should
end at a subvolume).  Required for commands `send`, `monitor` and `diff` (and `receive` when
not using `--saveto`).


`--session=<date-time>[,<date-time>]` OR
`--session=^<tag>[,^<tag>]`

Session allows you to specify a single date-time or tag spec for the`receive`, `verify`, `diff`,
and `arch-check` commands. Using a tag selects the last session having that tag. When specifying
a tag, it must be prefixed by a `^` carat.

For `prune`, specifying
a tag will have different effects: a single spec using a tag will remove only each individual session
with that tag, whereas a tag in a dual (range) spec will define an inclusive range anchored at the first
instance of the tag (when the tag is the first spec) or the last instance (when the tag is the
second range spec). Also, date-times and tags may be used together in a range spec.


`--volex=<volume1> [--volex=<volume2> *]`

Exclude one or more volumes from processing. May be used with commands that operate on multiple
volumes in a single invocation, such as `send`.  volex is useful in cases where a volume is
in the archive, but frequent automatic backups aren't needed.  Or when certain volumes should
be excluded from prune, monitor, etc.

**Please note:** volex syntax had to be changed from the v0.3 option syntax which used a comma to
specify multiple volumes.


`--sparse-write`

Used with `receive`, the sparse-write mode tells Wyng not to create a brand-new local volume and
results in the data being sparsely written into the existing volume instead. This is useful if
the existing
local volume is a clone/snapshot of another volume and you wish to save local disk space. It is also
best used when the backup/archive storage is local (i.e. fast USB drive or similar) and you don't
want the added CPU usage of full `--sparse` mode.


`--sparse`

The sparse mode can be used with the `receive` command to intelligently retreive and overwrite
an existing
local volume so that only the differences between local and archived volumes will be fetched
from the archive and written to the local volume. This results in reduced network
usage at the expense of some extra CPU usage on the local machine, and also uses
less local disk space when snapshots are a factor.  The best situation for sparse mode is when
you want to restore/revert a large volume with a containing a limited number of changes
over a low-bandwidth connection.


`--use-snapshot` _(experimental)_

A faster-than-sparse option that uses a snapshot as the baseline for the
`receive`, if one is available.  Use with `--sparse` if you want Wyng to fall back to
sparse mode when snapshots are not already present.


`--dedup`, `-d`

When used with the `send` command, data chunks from the new backup will be sent only if
they don't already exist somewhere in the archive. Otherwise, a link will be used saving
disk space and possibly time and bandwith.

The tradeoff for deduplicating is longer startup time for Wyng, in addition to using more
memory and CPU resources during backups. Using `--dedup` works best if you are backing-up
multiple volumes that have a lot of the same content and/or you are backing-up over a slow
Internet link.


`--autoprune=(off | on | min | full)`

Autoprune may be used with either the `prune` or `send` commands and will cause Wyng to
automatically remove older backup sessions according to date criteria. When used with `send`
specifically, the autopruning process will only be triggered if the destination filessytem is
low on free space.

The criteria are currently hard-coded to remove all sessions older than 366 days,
and to thin-out the number of sessions older than 32 days down to a rate of 2 sessions
every 7 days.
In the future these parameters can be reconfigured by the user.

Selectable modes are:

__off__ is the current default.

__on__ removes more sessions than _min_ as space is needed, while trying to retain any/all older sessions
whenever available storage space allows.

__min__ removes sessions before the 366 day mark, but no thinning-out is performed.

__full__ removes all sessions that are due to expire according to above criteria.


`--tag=<tagname[,description]>`

With `send`, attach a tag name of your choosing to the new backup session/snapshot; this may be
repeated on the command line to add multiple tags. Specifying an empty '' tag will cause Wyng
to ask for one or more tags to be manually input; this also causes `list` to display tag
information when listing sessions.


### Configuration files

Wyng will look in _'/etc/wyng/wyng.ini'_ for option defaults.  For options that are flags with
no value like `--dedup`, use a _1_ or _0_ to indicate _enable_ or _disable_ (yes or no).
For options allowing multiple entries per command line, in the .ini use multiple lines with the
2nd item onward indented by at least one space.

An example _wyng.ini_ file:

```
[var-global-default]
dedup = 1
authmin = 10
autoprune = full
dest = qubes-ssh://sshfs:user@192.168.0.8/home/user/wyng.backup
local = /mnt/btrfs01/vms
volex = misc/caches.img
  misc/deprecated_apps.img
  windows10_recovery.vmdk
```


### Tips

* To reduce the size of incremental backups it may be helpful to remove cache
files, if they exist in your source volume(s). Typically, the greatest cache space
consumption comes from web browsers, so
volumes holding paths like /home/user/.cache can impacted by this, depending
on the amount and type of browser use associated with the volume. Three possible
approaches are to clear caches on browser exit, delete /home/user/.cache dirs on
system/container shutdown (this reasonably assumes cached data is expendable),
or to mount .cache on a separate volume that is not configured for backup.

* If you've changed your local path without first running `wyng delete --clean` to
remove snapshots, there may be unwanted snapshots remaining under your old volume group
or local directory.  LVM snapshots can be found with the patterns `*.tick` and `*.tock` with
the tag "wyng";  Btrfs/XFS snapshots can be found with `sn*.wyng?`.
Deleting them can prevent unecessary consumption of disk space.


### Troubleshooting notes

* Since v0.4alpha3, Wyng may appear at first to not recognize older alpha archives.
This is because Wyng no longer adds '/wyng.backup040/default' to the `--dest` path. To access the
archives simply add those two dirs to the end of your `--dest` URLs.  Alternately, you can rename
those subdirs to a single dir of your choosing.


* Backup sessions shown in `list` output may be seemingly (but not actually) out of
order if the system's local time shifts
substantially between backups, such as when moving between time zones (including DST).
If this results in undesired selections with `--session` ranges, its possible
to nail down the precisely desired range by observing the output of
`list volumename` and using exact date-times from the listing.


### Testing

* Wyng v0.4alpha3 and later no longer create or require the `wyng.backup040/default`
directory structure.  This means whatever you specify
in `--dest` is all there is to the archive path.  It also means accessing an alpha1 or
alpha2 archive will require you to either include those dirs explicitly in your --dest path
or rename '../wyng.backup040/default' to something else you prefer to use.

* Encryption is still considered a new feature and various crypto modes are available for
testing, with `--encrypt=xchacha20-t3` currently being the default.

Currently the testing designations of the new modes are:

- `xchacha20-t2` — Using a 192-bit random nonce; fast.
- `xchacha20-t3` — Using HMAC-SHA256(rnd||msg) function; safe.
- `xchacha20-t4` — Using HMAC-SHA256(rnd||hash) function; see below.
- `xchacha20-tc` — Counter based; fast with certain risks.  See issue [158](https://github.com/tasket/wyng-backup/issues/158).
- `off` — Turns off Wyng's authentication and encryption.

Note that the _t2, t3 & tc_ modes use methods recommended by the _libsodium_
project, the experts on encryption using the XChaCha20 cipher.  The _t4_ mode is an
attempt to combine the best aspects of safety and speed (issue [161](https://github.com/tasket/wyng-backup/issues/161).

Of course, Wyng still works with BYOE (bring your own encryption) and can turn off its own internal
encryption.

* Testing goals are basically stability, usability, security and efficiency. Compatibility
is also a valued topic, where source systems are generally expected to be a fairly recent
Linux distro or Qubes OS. Destination systems can vary a lot, they just need to have Python and
Unix commands or support a compatible FUSE protocol such as sshfs(sftp) or s3.

* If you wish to run Wyng operations that may want to roll back later,
its possible to "backup the backup" in a relatively quick manner using a hardlink copy:
```
sudo cp -rl /dest/path/wyng.backup /dest/path/wyng.backup-02

...or...

rsync -a --hard-links --delete source dest
```

The `rsync` command is also suitable for efficiently updating an archive copy, since it can
delete files that are no longer present in the origin archive (`cp` is not suitable for
this purpose).



Donations
---
<a href="https://liberapay.com/tasket/donate"><img alt="Donate using Liberapay" src="media/lp_donate.svg" height=54></a>

<a href="https://www.patreon.com/tasket"><img alt="Donate with Patreon" src="media/become_a_patron_button.png" height=50></a>

If you like Wyng or my other efforts, monetary contributions are welcome and can
be made through [Liberapay](https://liberapay.com/tasket/donate)
or [Patreon](https://www.patreon.com/tasket).

