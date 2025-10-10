_<h1 align="center">Wyng</h1>_
<p align="center">
Faster incremental backups for logical volumes and disk images.
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

Wyng pushes data to archives in a stream-like fashion, which avoids temporary data
caches and re-processing data. And Wyng's ingenious snapshot rotation avoids common
_aging snapshot_ space consumption pitfalls.

Wyng also doesn't require the source admin system to ever mount processed volumes or
to handle them as anything other than blocks, so it safely handles
untrusted data in guest file systems to bolster container-based security.


### Status

<table style="border-style:none; padding:0px;">
    <tr vertical-align="center" style="border-style:none;">
        <td align="center" style="border-style:none; width:50px"><img src="../media/info1.svg" height=42 /></td>
        <td style="border-style:none;"><b>Notice: Wyng project has moved to <a href="https://codeberg.org/tasket/wyng-backup">Codeberg.org!</b></a></td>
</tr></table>

Release candidate with a range of features including:

 - Incremental backups of Linux logical volumes from Btrfs and Thin-provisioned LVM

 - Supported destinations: Local file system, Virtual machine or SSH host

 - Fast pruning of old backup sessions

 - Basic archive management such as add/delete volume and auto-pruning

 - Automatic creation & management of local snapshots

 - Data deduplication

 - Marking and selecting archived snapshots with user-defined tags

Version 0.8 major enhancements:

 - Reflink local storage support

 - Authenticated encryption with auth caching

 - Full data & metadata integrity checking

 - Fast differential receive based on local snapshots

 - Overall faster operation

 - Change autoprune behavior with --apdays

 - Configure defaults in /etc/wyng/wyng.ini

 - Simple selection of archives and local paths: Choose any _local_ or _dest_ each time you run Wyng

 - Multiple volumes can now be specified for most Wyng commands; send and receive support multiple storage pools

 Wyng is released under a GPL license and comes with no warranties expressed or implied.


Wyng v0.8 Requirements & Setup
---

Before starting:

* Python 3.8 or greater is required for basic operation.

* For encryption and top performance, the _python3-pycryptodome_ and _python3-zstd_ packages
should be installed, respectively.

* Volumes to be backed-up should reside locally in one of the following snapshot-capable
storage types:  LVM thin-provisioned pool or reflink-capable file system such as Btrfs. Otherwise, volumes may be imported from or saved to other file systems at standard (slower) speeds.

* For backing up from LVM, _thin-provisioning-tools & lvm2_ must be present on the source system.  For Btrfs, the `btrfs` command must be present.

* The destination system where the Wyng archive is stored (if different from source) should
also have python3, plus a basic Unix command set and file system (i.e. a typical Linux or BSD
system). Otherwise, _samba_, FUSE, etc. may be used to access remote storage using smb, sftp, s3 or other protocols
without concern for python or Unix commands.

* See the 'Testing' section below for tips and caveats about using the alpha and beta versions.


## Getting Started

Wyng is distributed as a single Python executable with no complex
supporting modules or other program files; it can be placed in '/usr/local/bin'
or another place of your choosing:

```
sudo cp -a wyng-backup/src/wyng /usr/local/bin
```

Archives can be created with `wyng arch-init`:

```
sudo wyng arch-init --dest=ssh://me@example.com:/home/me/mylaptop.backup

...or...

sudo wyng arch-init --dest=file:/mnt/drive2/mylaptop.backup
```

The examples above create a 'mylaptop.backup' directory on the destination.
The `--dest` argument includes the destination type, remote system (where applicable)
and directory path.

Next you can start making backups with `wyng send`:

```
sudo wyng send --dest=file:/mnt/drive2/mylaptop.backup --local=volgrp1/pool1 root-volume home-volume
```

This command sends two volumes 'root-volume' and 'home-volume' from the LVM thin pool 'volgrp1/pool1' to the destination archive.

<br/>
 
## Operation

Run Wyng using the following commands and arguments in the form of:

**wyng \[--options] command \[volume_names] \[--options]**


### Command summary

| _Command_ | _Description_  |
|---------|---|
| **list** _[volume_name]_    | List volumes or volume sessions
| **send** _[volume_name]_    | Perform a backup of enabled volumes
| **receive** _volume_name [*]_   | Restore volume(s) from the archive
| **verify** _volume_name [*]_    | Verify volumes' data integrity
| **prune** _[volume_name] [*]_   | Remove older backup sessions to recover archive space
| **delete** _volume_name_    | Remove entire volume from config and archive
| **rename** _vol_name_ _new_name_  | Renames a volume in the archive
| **arch-init**               | Create a new Wyng archive
| **arch-deduplicate**        | Deduplicate existing data in an archive
| **version**                 | Print the Wyng version and exit


### Advanced commands

| _Command_ | _Description_  |
|---------|---|
| **monitor**                     | Collect volume change metadata & rotate snapshots
| **diff** _volume_name [*]_      | Compare local volume with archived volume
| **add** _volume_name [*]_       | Adds a volume name without session data to the archive
| **arch-check** _[volume_name] [*]_ | Thorough check of archive data & metadata

<br/>

### Command details

#### send

Performs a backup by storing volume data to a new session in the archive.  If the volume
already exists in the archive, incremental mode is automatically used.

```

wyng send my_big_volume --local=vg/pool --dest=file:/mnt/drive2/mylaptop.backup

```

`send` supports automatic pruning of older backup sessions to recover disk space before the new data is sent; set `--autoprune` option to _on_ or _full_ to use this feature.

Volume names for non-LVM storage may include subdirectories, making them relative paths in
the same manner as file paths in `tar`.
For example, `wyng --local=/mnt/pool1 send appvms/personal.img` will send the volume located
at '/mnt/pool1/appvms/personal.img'.

#### receive

Retrieves volumes (using the latest session ID
if `--session` isn't specified) from the archive and saves it to either the `--local`
storage or the path specified with `--save-to` (the latter allows receiving only
one volume at a time).
If `--session` is used, only one date-time is accepted. The volume name is required.

```

wyng receive vm-work-private --local=vg/pool --dest=file:/mnt/drive2/mylaptop.backup

```

...restores a volume called 'vm-work-private' to 'myfile.img' in
the LVM thin pool 'vg/pool'.  Note that `--dest` always refers to the archive location, so
the volume is being restored _from_ '/mnt/drive2/mylaptop.backup'.

For any save path, Wyng will try to discard old data before receiving unless `--sparse`,
`--sparse-write` or `--use-snapshot` options are used.


### list

Displays the volumes contained in a Wyng archive.

```

# Show all volumes with details:
wyng list --verbose

# Show details of volume 'example.img':
wyng list example.img

# Show volumes in a particular backup session:
wyng list --session=20250601-000001

```


#### verify

The `verify` command is similar to `receive` without saving the data. For both
`receive` and `verify` modes, an error will be reported with a non-zero exit
code if the received data does not pass integrity checks.


#### prune

Reclaim space on a backup drive by removing prior backup session(s) you specify.

To use, supply a single exact date-time in _YYYYMMDD-HHMMSS_ format to remove a
specific session, or two date-times representing a range:

```
wyng prune --all --session=20180605-000000,20180701-140000 --dest=file:/mnt/drive2/mylaptop.backup
```

...removes backup sessions from midnight on June 5 through 2pm on July 1 for all
volumes. Alternately, `--all-before` may be used with a single `--session` date-time
to prune all sessions prior to that time.

Exclusions: The `--keep` option can accept a single date-time or a tag in the form `^tagID`.
Matching sessions will be excluded from pruning and autopruning. Also, any volumes with names that match _'wyng-*metadata'_ will be automatically excluded unless the `--all` option was used to select all volumes.

Also see `--autoprune` option below which works with `prune` and `send` commands.


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

Create a new archive on a mounted drive...
```

wyng arch-init --dest=file:/mnt/backups/archive1

```

Create a new archive with stronger compression on a remote system...
```

wyng arch-init --dest=ssh://user@example.com --compression=zstd:7

```

Optional parameters for `arch-init` are _encrypt, compression, hashtype_ and _chunk-factor_.
These cannot be changed for an archive after it is initialized.


#### arch-check

Intensive check of archive integrity, reading each session's _deltas_ completely starting with
the newest and working back to the oldest. This differs from `verify` which first builds a complete index and checks a complete volume.

Using `--session=newest` provides a 'verify the last session' function (useful after an incremental
backup). Otherwise, supplying a date-time will make `arch-check` start the check from that point and
then continue working toward the oldest session. Session ranges are not yet supported.

Depending on how `arch-check` is used, the verification process can be shorter _or much longer_
than using `verify` as the latter is always the size of a volume snapshot. The longest, most
complete form of `arch-check` is to supply no parameters, which checks all sessions in all volumes.



#### monitor

Frees disk space that is cumulatively occupied by aging snapshots, thereby addressing a
common resource usage issue with snapshot-based backups.
After harvesting their change metadata, the older snapshots are replaced with
new ones occupying zero space.  Running `monitor` isn't necessary,
but it only takes a few seconds and is good to run on a frequent, regular basis
if you have some volumes that are write-intensive. Volume names may also be
specified if its desired to monitor only certain volumes.

This rule in /etc/cron.d runs `monitor` every 20 minutes:

```
*/20 * * * * root su -l -c '/usr/local/bin/wyng monitor --all'
```


#### diff

Compare a local volume snapshot with the archive and report any differences.
This is useful for diagnostics and can also be useful after a verification
error has occurred.


#### add

Adds new, empty volume name(s) to the archive.  On subsequent `send -a`, Wyng will backup
the volume data if present.


<br/>

### Parameters / Options summary

| _Option_                      | _Description_
|-------------------------------|--------------
--dest=_URL_           | Location of backup archive.
--local=_vg/pool_  _...or..._    | Storage pool containing local volumes
--local=_/absolute/path_    | 
--authmin=_N_          | Remember authentication for N minutes (default: 5)
--all, -a              | Select all volumes (most cmds); Or clean all snapshots (delete)
--volex=_volname_      | Exclude volumes (send, monitor, list, prune)
--dedup, -d            | Use deduplication for send (see notes)
--session=_date-time[,date-time]_ | Select a session or session range by date-time or tag (receive, verify, prune)
--all-before           | Select all sessions before the specified _--session date-time_ (prune)
--autoprune=off        | Automatic pruning by calendar date
--apdays=_A:B:C:D_     | Number of days to keep or to thin-out older sessions
--keep=_date-time_     | Specify date-time or tag of sessions to keep (prune)
--tag=tagname[,desc]   | Use session tags (send, list)
--sparse               | Receive volume data sparsely (implies --sparse-write)
--sparse-write         | Overwrite local data only where it differs (receive)
--use-snapshot         | Receive from local the local snapshot (receive)
--send-unchanged       | Record unchanged volumes, don't skip them (send)
--unattended, -u       | Don't prompt for interactive input
--clean                | Perform garbage collection (arch-check) or metadata removal (delete)
--verbose              | Increase details
--quiet                | Shhh...


### Advanced Options

| _Option_                      | _Description_
|-------------------------------|--------------
--save-to=_path_       | Save a volume to _path_ (receive).
--vols-from=_json file_ | Specify local:[volumes] sets instead of --local
--import-other-from    | Import volume data from a non-snapshot capable path during `send`
--use-snapshot-diff    | Experimental: Use local snapshot in differential mode (receive)
--session-strict=_on_ | Don't retrieve volume from next-oldest session if no exact session match
--encrypt=_cipher_     | Set encryption mode or _'off'_ (default: _'xchacha20-dgr'_)
--compression          | (arch-init) Set compression type:level
--hashtype             | (arch-init) Set data hash algorithm: _hmac-sha256_ or _blake2b_
--chunk-factor         | (arch-init) Set archive chunk size
--volume-desc          | Set volume description (add, rename, send)
--vid                  | Select volume by ID (delete)
--tar-bypass           | Experimental: Use direct access for file:/ archives (send)
--passcmd=_'command'_  | Read passphrase from output of a wallet/auth app
--upgrade-format       | Upgrade older Wyng archive to current format (arch-check)
--change-uuid          | Change the archive UUID to a new random value (arch-check)
--dry-run              | Make `send` session a dry run, see estimate of changed data
--remap                | Remap volume to current archive during `send` or `diff`
--json                 | Output volume: session info in json format (list)
--force                | Not used with most commands
--force-retry          | Retry in-process transaction again
--force-allow-rollback | Accept archive if it was reverted to an earlier state
--opt-ssh              | Override internal _ssh_ options
--opt-qubes            | Override internal _qvm-run_ options
--purge-tmp            | Remove /tmp data including session logs before exiting
--meta-reduce=_mode:N_ | Reduce or extend local metadata caching
--meta-dir=_path_      | Use a different metadata dir than the default
--config=_file_        | Use alternate config .ini file
--debug                | Debug mode




### Option Details

#### `--dest=<URL>`

This option tells Wyng where to access the archive and has the same meaning for all read or write
commands. It accepts one of the following forms:

| _URL Form_ | _Destination Type_
|----------|-----------------
|__file:__/path                           | Local file system
|__ssh:__//user@example.com[:port][/path]      | SSH server
|__qubes:__//vm-name[/path]                     | Qubes virtual machine
|__qubes-ssh:__//vm-name:me@example.com[:port][/path]  | SSH server via a Qubes VM


#### `--local=<path | volgroup/pool>`

The location of local copy-on-write storage where logical volumes, disk images, etc. reside.  This serves as the _source_ for `send` commands, and as the place where `receive` restores/saves volumes.

This parameter takes one of two forms: Either the source volume group and pool as 'vgname/poolname'
or a directory path on a reflink-capable file system such as Btrfs or XFS (for Btrfs the path should
end at a subvolume).  Required for commands `monitor` and `diff`, `receive` when
not using `--save-to`, and `send` when not using only `--import-other-from`.


#### `--session=<date-time>[,<date-time>]` OR
#### `--session=^<tag>[,^<tag>]`

Session allows you to specify a single date-time or tag spec for the `receive`, `verify`, `diff`, `prune`, `list`, and `arch-check` commands as well as a comma-separated range for `prune`. Using a single tag selects the last session having that tag. When specifying
tags, each must be prefixed by a `^` carat.

For `prune`, specifying either a single date-time or a comma-separated range is possible.
Specifying a tag will have different effects: a single tag spec will remove only each individual session
with that tag, whereas a tag in a dual (range) spec will define an inclusive range anchored at the first
instance of the tag (first spec is a tag) and/or the last instance (when the second spec is a tag). Also, date-times and tags may be used together in a range spec.


#### `--keep=<spec>`

This has the same syntax as `--session` and can be used with `prune` to exclude matched sessions from the pruning process.


#### `--all-before`

Causes `prune` to also remove all sessions before the single specified `--session` date.


#### `--all`

Select all _volumes_.  May be used with `list`, `send`, `receive`, `prune`, `verify`, `diff`, `arch-check` commands.


#### `--volex=<volume1> [--volex=<volume2> *]`

Exclude one or more volumes from processing. May be used with `--all` and commands that operate on multiple volumes in a single invocation, such as `send`.  volex is useful in cases where a volume is
in the archive, but frequent automatic backups aren't needed.  Or when certain volumes should
be excluded from prune, monitor, etc.

**Please note:** volex syntax had to be changed from the v0.3 option syntax which used a comma to
specify multiple volumes.


#### `--sparse-write`

Used with `receive`, the sparse-write mode tells Wyng not to create a brand-new local volume and
results in the data being sparsely written into the existing volume instead. This is useful if
the existing
local volume is a clone/snapshot of another volume and you wish to save local disk space. It is also
best used when the backup/archive storage is local (i.e. fast USB drive or similar) and you don't
want the added CPU usage of full `--sparse` mode.


#### `--sparse`

The sparse mode can be used with the `receive` command to intelligently retrieve and overwrite
an existing
local volume so that only the differences between local and archived volumes will be fetched
from the archive and written to the local volume. This results in reduced network
usage at the expense of some extra CPU usage on the local machine, and also uses
less local disk space when snapshots are a factor.  The best situation for sparse mode is when
you want to restore over a low-bandwidth connection a locally-existing large volume containing a limited number of differences with the archived version to be fetched (for example: using restore from an archive located at a remote server to revert a 100GB volume to yesterday's backup).


#### `--use-snapshot`

Receive a volume instantly from the newest local snapshot, if available. If the snapshot isn't available then `receive` will retrieve the volume data from the archive.

Also use `--sparse` if you want Wyng to fall back to
sparse mode when snapshots are not already present.


#### `--use-snapshot-diff`

Use the newest local snapshot, if one is available, as a baseline for the `receive` process. This can result in greatly accelerated receiving of archived volumes as only the differences between the snapshot and the requested version of the volume will be transferred.

Implies `--use-snapshot`.

#### `--save-to=<path>`

Its possible to receive to any valid file path or block device using the `--save-to` option,
which can be used in place of `--local`.  Only one volume can be received at a time when using `--save-to`.


#### `--tar-bypass` _(experimental)_

Use direct access for file:/ archives during `send`.  This can reduce sending times by
up to 20%.


#### `--dedup`, `-d`

When used with the `send` command, data chunks from the new backup will be sent only if
they don't already exist somewhere in the archive. Otherwise, a link will be used saving
disk space and possibly time and bandwidth.

The trade-off for deduplicating is longer startup time for Wyng, in addition to using more
memory and CPU resources during backups. Using `--dedup` works best if you are backing-up
multiple volumes that have a lot of the same content and/or you are backing-up over a slow
Internet link.


#### `--dry-run`

Have `send` perform a dry run, where no data is saved to the archive. This is useful for testing and also getting an estimate of the amount of data that will be transmitted during a normal `send`. If a volume that had lost its snapshot or delta map is included in a dry run, its map will be re-created automatically saving time on the next `send`.

Since it affects the amount of data transmitted, including the `--dedup` option in the dry run is recommended if you intend to make the actual backup with `--dedup`.


#### `--autoprune=(off | on | full)`

Autoprune may be used with either the `prune` or `send` commands and will cause Wyng to
automatically remove older backup sessions according to date criteria. When used with `send`
specifically, the autopruning process will be triggered in advance of sending new sessions
when using _full_ mode, or in _on_ mode only or if the destination file system is
low on free space.  (See _--apdays_ to specify additional autoprune parameters.)

Selectable modes are:

__off__ is the current default.

__on__ removes _some_ sessions, as space is needed on the destination.

__full__ removes all sessions that are due to expire according to above criteria.

#### `--apdays=A:B:C:D`

Adjust autoprune with the following four parameters:

* __A__: _Days ago_ before which _all_ sessions are removed.  Default is 0 (disabled).
* __B__: Thinning days; the number of days ago before which _some_ sessions will be removed
according to the ratio _D/C_.  Default is 62 days.
* __C__: Number of _days_ for the D/C ratio.  Default is 1.
* __D__: Number of _sessions_ for the D/C ratio.  Default is 2.

An example:  `--apdays=365:31:1:2` will cause autoprune to remove all sessions that are older
than 365 days, and sessions older than 31 days will be thinned-out while preserving
(roughly on average) two sessions per day.


#### `--tag=<tagname[,description]>`

With `send`, assign a tag name of your choosing to the new backup session/snapshot; this may be
repeated on the command line to add multiple tags. Specifying an empty '' or '@' tag will cause Wyng to ask for one or more tags to be manually input; this also causes `list` to display tag
information when listing sessions.

With other commands, session tags are used via the `--session` and `--keep` options.


#### `--authmin=<minutes>`
#### `--passcmd=<command>`

These two options help automate Wyng authentication, and may be used together or separately.

`--authmin` takes a numeric value from -1 to 60 for the
number of minutes to remember the current authentication for subsequent Wyng invocations.
The default authmin time is 2 minutes.  Specifying a -1 will cancel a prior authentication
and 0 will skip storing the authentication.

The `--passcmd` option takes a string representing a shell command that outputs a passphrase
to _stdout_ which
Wyng then reads instead of prompting for passphrase input.  If a prior auth from
`--authmin` is active, this option is ignored and the command will not be executed.


#### `--import-other-from=volname:|:path`

Enables `send`-ing a volume from a path that is not a supported snapshot storage type.  This may
be any regular file or a block device which is seek-able.

When it is specified this option causes slow delta comparisons to be used for the specified volume(s)
instead of the default fast snapshot-based delta comparisons.  It is not recommended for regular
use with large volumes if speed or efficiency are a priority.

The special delimiter used to separate the _volname_ (archive volume name) and the _path_ is ':|:'
which means this option cannot be used to `send` directly to volume names in the archive which
contain that character sequence.


#### `--session-strict=on|off`

For receive, verify, diff: If set to 'on' (the default) Wyng won't retrieve volumes from next-oldest session if the
specified volumes don't have an exact match for the specified session.  When set to 'off'
Wyng will try to retrieve the next-oldest version of the volume if one exists.


#### `--vols-from=_json file_`

Specify both local storage and volume names for `send`, `receive` or `verify` as sets, instead
of using --local and volume names on the command line.  The json file must take the form
of `{local-a: [[volname1, alias1], [volnameN, aliasN], ...], ...]}`.  This allows multiple
local storage sources to be sent/received in a single session.

_Alias_ can be _'null'_ for no alias or any valid name. However, the volume names (or aliases)
must all be unique across different sources as they are stored in the same archive.  Aliases define which local volume name into which an archive volume will be received, or when sending
they indicate a request to actually _rename_ the target volume to the alias.

_Local_ may also be _'null'_ if the command/action does not require it (ex. `verify`).


#### `--meta-reduce=mode:minutes`

Control the degree to which locally cached session metadata is retained or removed when
Wyng exits. This can effect a noticeable reduction in the space that Wyng uses in /var
while trading off a little speed.

___Mode___ is one of _off, on,_ or _extra_: _off_ results in no reduction (all metadata is
retained); _on_ removes uncompressed metadata; _extra_ removes both compressed and uncompressed
metadata.

___Minutes___ is an integer defining the metadata's maximum age in minutes, where '0'
will cause it to be removed immediately when Wyng exits.

The default setting is _'on:3000'_.


#### `--compression`

Accepts the forms `type` or `type:level`. The three types available are `zstd` (zstandard),
plus `zlib` and `bz2` (bzip2). Note that Wyng will only default
to `zstd` when the 'python3-zstd' package is installed; otherwise it will fall back to the less
capable `zlib`. (default=zstd:3)


#### `--hashtype`

Accepts a value of either _'blake2b'_ or _'hmac-sha256'_ (default).  The digest size is 256 bits.


#### `--chunk-factor`

Sets the pre-compression data chunk size used within the destination archive.
Accepted range is an integer exponent from '1' to '6', resulting in a chunk size of 64kB for
factor '1', 128kB for factor '2', 256kB for factor '3' and so on. To maintain a good
space efficiency and performance balance, a factor of '2' or greater is suggested for archives
that will store volumes larger than about 100GB. (default=2)


#### `--encrypt`

Selects the encryption cipher/mode.  The available modes are:

- `xchacha20-dgr` — Using HMAC-SHA256(rnd||hash) function.  This is the default.
- `xchacha20-msr` — Using HMAC-SHA256(rnd||msg) function.
- `xchacha20-ct` — Counter based; fast like _*-dgr_ with different safety trade-offs (see issue [158](https://codeberg.org/tasket/wyng-backup/issues/158)).
- `off` — Turns off Wyng's authentication and encryption.


#### `--local-from=<json_file>`

For efficiently automating Wyng usage with multiple volumes grouped by their associated local storage, json is accepted in the form... `{"local1": [["v-name1","v-alias1"], []*], "local2": []*}`

Used with `send`, all included volumes will be recorded under a single session date-time.  The _alias_ may be specified as null, the same as the vol name, or a different name; when different Wyng will interpret this as a request to rename(!) the archived volume to the alias – use with caution.

Used with `receive`, the alias is used to receive to a volume name that is different than the archived volume's listed name.

Upon completion Wyng may supply a result/error listing in a file at the same json path with the extension ".error".

#### `--force-retry`

Wyng normally re-tries completion of an interrupted (in-process) archive transaction only once and running Wyng afterward will result in "Interrupted process already retried" errors. Using `--force-retry` suppresses the error and allows the transaction to be attempted again.

#### `--vouch=<vflag>`

Allows the user to vouch that a pre-condition outside of Wyng's control has been accounted for, where Wyng would normally refuse and exit with an error.  This can be used to run Wyng on configurations that haven't been thoroughly tested, so caution is urged.

Possible _vflags_:

- 'fs_online_factors' - This must be used with `send` or `monitor` on an unsupported reflink local storage type (i.e. not Btrfs).  It indicates to Wyng that you've prevented, for example, [XFS online](https://codeberg.org/tasket/wyng-backup/issues/277) _fsck_ from running at the same time Wyng is running to maintain the integrity of delta scans.

- 'reflink_fs_<_fstype_\>' - Allow `send` and `monitor` from a reflink filesystem type other than Btrfs, with _fstype_ being the Linux identifier for the unsupported local filesystem (example: _'xfs'_). The _fs_online_factors_ vflag must also be vouched if this is used.


### Configuration files

Wyng will look in _'/etc/wyng/wyng.ini'_ or the file specified via `--config` for option defaults.  For options that are flags with
no value like `--dedup`, use a _1_ or _0_ to indicate _enable_ or _disable_ (yes or no).
For options allowing multiple entries per command line, in the .ini use multiple lines with the
2nd item onward indented by at least one space.

An example _wyng.ini_ file:

```
[var-global-default]
dedup = 1
authmin = 10
autoprune = full
dest = ssh://user@192.168.0.8/home/user/wyng.backup
local = /mnt/btrfs01/vms
volex = misc/caches.img
  misc/deprecated_apps.img
  windows10_recovery.vmdk
```

Note that some options like `debug`, `force` and `config` are ignored in the ini file; they must be used from the command line.


### Verifying Code

Wyng code can be cryptographically verified using either `gpg` directly or via `git`:

```sh
# Import Key
~$ cd wyng-backup
~/wyng-backup$ gpg --import pubkey
gpg: key 1DC4D106F07F1886: public key "Christopher Laprise <tasket@posteo.net>" imported
gpg: Total number processed: 1
gpg:               imported: 1

# GPG Method
~/wyng-backup$ gpg --verify src/wyng.gpg src/wyng

# Git Method
~/wyng-backup$ git verify-commit HEAD

# Output:
gpg: Signature made Sat 26 Aug 2023 04:20:46 PM EDT
gpg:                using RSA key 0573D1F63412AF043C47B8C8448568C8B281C952
gpg: Good signature from "Christopher Laprise <tasket@posteo.net>" [unknown]
gpg:                 aka "Christopher Laprise <tasket@protonmail.com>" [unknown]
```


### Security notes

#### Automated authentication:

Wyng supports two modes of supplying passphrase secrets:  Standard input
and the `--passcmd` option. The former can accept a secret from a pipe or
redirect because when auth is necessary it is always the first input prompt.
However, the prompt may not always occur when `--authmin` value > 0 is used since
the passphrase may not be needed for repeat invocations of Wyng.

#### Persistence of cached archive.ini & archive.salt:

Authentication schemes in general can only verify the authenticity for an
object at any point in time; they aren't well suited to telling us if that object
(i.e. a backup archive) is the most recent update, and so they are vulnerable to rollback
attacks that replace your current archive with an older version (in Wyng this is related to
replay attacks, but not downgrade attacks).  Wyng guards against
such attacks by checking that the time encoded in your locally cached archive.ini isn't newer
than the one in the archive itself on the destination; Wyng also displays the last archive modification time whenever you access it.


#### Protecting and Verifying Archive Authenticity:

With encryption enabled, Wyng provides a kind of built-in verification of archive authenticity;
this is because it uses an AEAD cipher mode.  However, custom verification
(BYOV) is also possible with Wyng and even works on non-encrypted archives.  All you need
to do is sign the 'archive.ini' file from the top archive directory after executing any Wyng
command that changes the archive (i.e. _arch-init, add, send, prune, delete, rename_).

Subsequently, the steps to verify total archive authenticity would be to simply run
`wyng arch-check --dest <URL>` (using Wyng's built-in authenticated encryption), or else using custom
authentication based on GPG, for instance:
```
cd /mnt/backups
gpg --verify laptop1.sig laptop1.backup/archive.ini && wyng arch-check --dest=file:/mnt/backups/laptop1.backup
```
Note that custom signature files should _not_ be stored within the archive directory.

(Although volumes can be verified piecemeal with the `wyng verify` command, it is not suited
to verifying everything within an archive in a timely manner.)

### Known Issues

* Issue [260](https://codeberg.org/tasket/wyng-backup/issues/260): Versions of Wyng v0.8 older than _'20250820'_ may receive a volume incorrectly when `--use-snapshot` is used and the session is older than the most recent.  To resolve the issue the use-snapshot feature was split into two different options: A safe version enabled with `--use-snapshot` which only retrieves a whole snapshot if the specified session is newest, and an experimental version enabled by `--use-snapshot-diff` that can perform differential receive vs the snapshot if the session is older. If you use Wyng with `receive --use snapshot` to retrieve older versions of data then you are strongly urged to upgrade to a current release.

### Tips & Caveats

* Storage paths: Wyng doesn't store the `--local` path in the archive. Normally, this means if you're receiving volumes that must go to different local paths or LVM pools, you must group the volumes into separate invocations of `wyng --local=<path> receive <vols>`, one group of _vols_ for each _path_. However, for automated use of Wyng this can be reduced to a single invocation with the `--local-from` option which accepts volume lists grouped by each local spec. Also, Wyng doesn't care if a volume you're receiving was sent using `--import-other-from`; by default trying to receive such a volume will place it in the `--local` path unless you decide to use `--save-to`.

* [Qubes OS](https://qubes-os.org) users: If you're using Wyng to backup Qubes VMs, you probably want to use the Wyng wrapper made especially for Qubes, [wyng-util-qubes](https://codeberg.org/tasket/wyng-util-qubes), which makes saving & restoring VM settings along with data easy!

* LVM users: Wyng has an internal snapshot manager which creates snapshots of volumes
in addition to any snapshots you may already have on your local storage system.
This can pose a serious challenge to _lvmthin_ (aka thin-provisioned LVM) as the default space
allocated for metadata is often too small for rigorous & repeated snapshot rotation
cycles.  It is recommended to _at least double_ the default _tmeta_ space
on each thin pool used with `wyng send` or `wyng monitor`; see the man page
section _[Manually manage free metadata space of a thin pool LV](https://www.linux.org/docs/man7/lvmthin.html)_ for guidance on using
the `lvextend --poolmetadatasize` command.

* Btrfs users: In general it is a good idea to use disk images on a Btrfs filesystem that is
relatively recent and well-maintained to ensure that fragmentation does not cause
noticeable slowdowns.  The simplest way to maintain a responsive filesystem is to
defragment image files monthly or weekly as it is a single command and typically takes
only a few minutes (there is no need to dismount the images).  For example:

```
      sudo btrfs filesystem defragment -r -t 256K /var/lib/qubes
```

<ul>
Note that while the 'autodefrag' mount option can be used as an alternative, the overall performance may be reduced due to the smaller fragments and constant write-amplification effects. Similarly, enabling Btrfs compression will also have a defragging effect.</ul>

<ul>
Btrfs deduplicators like `bees` or `duperemove` can quickly increase fragmentation
(i.e. undo the effects of defragment) if not used carefully. The `duperemove` docs
indicate that choosing a larger block size will limit fragmentation, making it
preferable to `bees`. The block `-b` value should be matched to the value used for `defragment -t`.</ul>

* Receive/restore and deduplication:  Wyng `receive` can prevent data duplication when there is an existing volume to over-write; in sparse mode it will compare existing data on disk with incoming data from the archive and avoid writing to areas that match.  The `--use-snapshot` option has a similar space-saving effect and may be combined with the _sparse_ options.  However, Wyng cannot tell if any other volumes on the system are related to the volumes being received, and it won't automatically use them as a starting point to reduce consumption of disk space; to attain the 'dedup' effect when restoring its up to you to create snapshots from related volumes at your respective receive paths/LVs before running `wyng --sparse receive`.

* To reduce the size of incremental backups it may be helpful to remove or isolate cache
files, if they exist in your source volumes. Typically, the greatest cache space
consumption comes from web browsers, so
volumes holding paths like /home/user/.cache can be impacted by this, depending
on the amount and type of browser use associated with the volume. Three possible
approaches are to clear caches on browser exit, delete /home/user/.cache dirs on
system/container shutdown (this reasonably assumes cached data is expendable),
or to mount .cache on a separate volume that is not configured for backup.

* If you've changed your local path without first running `wyng delete --clean` to
remove snapshots, there may be orphaned snapshots remaining under your old volume group
or local directory. Deleting them can prevent unnecessary consumption of disk space.  LVM snapshots can be found with the patterns `'*.tick'` and `'*.tock'` with
the tag "wyng".  Btrfs/XFS snapshots can be found with `'sn*.wyng?'`.

* Keeping a [duplicate](https://codeberg.org/tasket/wyng-backup/issues/199) archive or "a backup of the backup" is possible with the following:
```
      mv destpath destpath-incomplete
      rsync -uaHW --delete --no-compress sourcepath/. destpath-incomplete
      mv destpath-incomplete destpath
```

<ul>
The simple rsync example above can become bogged-down with unnecessary transfers because it doesn't take into account when pruning shifts data into different paths.  A `sync-archive.py` script that addresses this performance pitfall is available in the _misc/_ folder.</ul>
<ul>
Note that since a duplicate archive is identical, including internal UUIDs, it should only be kept for an emergency such as when the original archive is no longer available or becomes unusable. Switching back and forth between the original and duplicate for regular archival operations is not supported.</ul>

* _Sending to multiple archives:_ If you have created separate archives (not duplicates as described in the last section) and want to backup one or more volumes to both archives, Wyng can do this seamlessly from non-LVM storage systems such as Btrfs.  With LVM, the --remap option would have to be used each time you switch archives; this slows Wyng down to the pace of a regular incremental backup program, so keeping a duplicate archive using rsync or similar may be preferable.  However, this issue doesn't affect sending different sets of volumes to different archives, only when a specific volume is sent to more than one archive.

* Wyng archives should be stored on Unix-like file systems that were formatted with default or close-to default metadata settings (i.e. _inode_ capacity has not been manually reduced). Any format providing a 16KB:1 (or lower) data-to-inode ratio should work fine regardless of the Wyng chunk size being used.

* Archive file permissions can change when moving an archive to a different system or switching to a different _dest_ protocol (i.e. from _file:_ to _ssh:_). A mis-match of permissions (such as ownership) can result in permission errors that prevent Wyng from completing a command. In such cases using `chown -R` on the archive directory may be necessary (See your OS documentation for details).


### Troubleshooting notes

* If you encounter an error during send/backup that the Btrfs path is "not a subvolume" its probably due to the `--local` path or pool ending in a dir not a subvolume. If you can't adjust the local path to end at an existing subvol, then a dir can be easily converted using `btfs subvol create` and `mv` commands. See the 'misc' project folder for an example dir-to-subvol conversion script.

* A major change in v0.8 is that for `send` and `monitor` Wyng will no longer assume you want to
act on all known volumes if you don't specify any volumes.  You must now use `-a` or `--all`, which
now work for other commands as well.  This change also enables adding new volumes while doing a
complete backup, for instance: `wyng -a send my-new-volume` – updates every volume already
in the archive plus backup 'my-new-volume' as well.

* "BrokenPipeError": A broken pipe can occur for various reasons when a Wyng helper process encounters an error while accessing archive files.  Since the helper is usually remote, the real error isn't immediately shown and Wyng only detects that its pipe to the helper is broken. Viewing the logs in the /tmp/wyng-debug dir will show the underlying error.

* Backup sessions shown in `list` output may be seemingly (but not actually) out of
order if the system's local time shifts
substantially between backups, such as when moving between time zones (including DST).
If this results in undesired selections with `--session` ranges, its possible
to nail down the precisely desired range by observing the output of
`list volumename` and using exact date-times from the listing.

* Wyng locally stores information about backups in two ways:  Snapshots alongside your local
source volumes, and metadata under _/var/lib/wyng_.  It is safe to _delete_
Wyng snapshots without risking the integrity of backups (although `send` will become slower).
However, as with all CoW snapshot based backup tools, you should never attempt to directly mount, alter or otherwise directly utilize a local Wyng snapshot
as this could (very likely) result in future backup sessions being corrupt (this is why Wyng
snapshots are stored as read-only).  If you think you have somehow altered a local Wyng snapshot, you
should consider it corrupt and immediately delete it before the next `send`.
If you're in a pinch and need to use the data in a Wyng snapshot, you should first make your own
copy or snapshot of the Wyng snapshot using `cp --reflink` or `lvcreate -s` and use that instead.

* Error _"Cached metadata is newer"_ indicates that something has reverted the archive to an earlier state.  This could be due to a rollback attack, but could also be the result of your own actions such as keeping multiple copies of the same archive and alternately mounting them at the same location (in which case giving each copy a slightly different dir name can avert this error".  Use the `--force-allow-rollback` option if you need to recover from this error and use the older archive as is.

* Metadata cached under _/var/lib/wyng_ may also be manually deleted.  However, the _archive.\*_
root files in each 'a_*' directory are part of Wyng's defense against rollback attacks, so if you
feel the need to manually reclaim space used in this dir then consider leaving the _archive.\*_
files in place.

* If data corruption in the archive is suspected, use `wyng arch-check` which will scan for errors and show options for recovery.

* If an archive volume becomes damaged and unrecoverable it may be necessary to delete it from the archive by its volume ID by using `wyng delete --vid` instead of the volume name.

### Reporting issues

#### Conduct:

When using the Wyng issues tracker its generally assumed you will do so in good faith based on the technical and UX merits of Wyng and the issue(s) at hand. Here are patterns of use which can land you in the 'bad faith' column:

* Noise-making, consistently invalid or unrelated comments or suggestions
* Gate keeping for other projects
* Assuming the role of a non-user or gadfly; you must have a reasonably earnest users' perspective whether you are a crackerjack developer or someone "just wishing trying it out". This includes "keyword criticism" based only on terms associated with the project but not exhibiting any experience with it nor having familiarity with its theory of operation.
* Bad faith arguments: appeals to authority, gaslightling, know-nothing assumptions, "alternative facts", etc.


### Testing

* The best way to test Wyng updates is to pull from a 'beta' branch or 'fixes' branch and start using the program for send and receive (backup and restore) as well as prune and diff operations (`wyng diff` verifies volumes with additional checking that the archive content is identical to the local copy, which is good for testing).  Usually 'wip' and 'experimental' usually should be avoided unless you have an issue for a bug and a fix has been posted in one of them.  Note that the '08beta' branch is being retired in preparation for the v0.8 full release; its not certain when '09beta' will be started.

* Testing goals are basically stability, usability, security and efficiency. Compatibility
is also a valued topic, where source systems are generally expected to be a fairly recent
Linux distro or Qubes OS. Destination systems can vary a lot, they just need to have Python and
Unix commands or support a compatible FUSE protocol such as sshfs(sftp) or s3.


### Donations

<a href="https://liberapay.com/tasket/donate"><img alt="Donate using Liberapay" src="../media/lp_donate.svg" height=54></a>

<a href="https://ko-fi.com/tasket"><img src="../media/ko-fi.png" height=57></a> <a href="https://ko-fi.com/tasket">Ko-Fi donate</a>

<a href="https://www.buymeacoffee.com/tasket"><img src="../media/buymeacoffee_57.png" height=57></a> <a href="https://www.buymeacoffee.com/tasket">Buy me a coffee!</a>


If you like this project, monetary contributions are welcome and can
be made through [Liberapay](https://liberapay.com/tasket/donate) or [Ko-Fi](https://ko-fi.com/tasket) or [Buymeacoffee](https://www.buymeacoffee.com/tasket).
