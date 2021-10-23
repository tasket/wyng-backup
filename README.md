_<h1 align="center">Wyng</h1>_
<p align="center">
Fast incremental backups for logical volumes.
</p>

### Introduction

Wyng is able to deliver faster, more efficient incremental backups for logical
volumes. It accesses logical volume *metadata* (instead of re-scanning data over
and over) to instantly find which *data* has changed since the last backup.
Combined with a Time Machine style storage format, it can also prune older
backups from the archive very quickly, meaning you only ever have to do a full
backup once and can send incremental backups to the same archive indefinitely
and frequently.

Having nearly instantaneous access to volume changes and a nimble archival format
enables backing up even terabyte-sized volumes multiple times per hour with little
impact on system resources.

Wyng sends data as *streams* whenever possible, which avoids writing temporary
caches of data to disk. And Wyng's ingenious snapshot rotation avoids common
_aging snapshot_ space consumption pitfalls.

Wyng also doesn't require the
source admin system to ever mount processed volumes, so it safely handles
untrusted data in guest filesystems to bolster container-based security.


### Status

Public release v0.3 with a range of features including:

 - Incremental backups of Linux thin-provisioned LVM volumes

 - Supported destinations: Local filesystem, Virtual machine or SSH host

 - Send, receive, verify and list contents

 - Fast pruning of old backup sessions

 - Basic archive management such as add/delete volume and auto-pruning

 - Data deduplication

 - Marking and selecting snapshots with user-defined tags

Data verification currently relies on hash tables being safely stored on the
source admin system or encrypted volume. Integrated encryption and key-based
verification are not yet implemented (see notes below for ways to add encryption).

Wyng is released under a GPL license and comes with no warranties expressed or implied.


Requirements & Setup
---

Before starting:

* Thin-provisioning-tools, lvm2, and python >=3.5.4 must be present on the source system. For top
performance, the `python3-zstd` package should be installed before creating an archive.

* The destination system (if different from source) should also have python, plus
a basic Unix command set and filesystem (i.e. a typical Linux or BSD system).

* Volumes to be backed-up must reside in an LVM thin-provisioned pool.

Wyng is currently distributed as a single Python executable with no complex
supporting modules or other program files; it can be placed in '/usr/local/bin'
or another place of your choosing.

Archives are created with `wyng arch-init`:

```

wyng arch-init --local=vg/pool --dest=ssh://me@exmaple.com/mnt/bkdrive

...or...

wyng arch-init --local=vg/pool --dest=internal:/ --subdir=home/user

wyng add my_big_volume


```

The `--dest` argument always ends in a _mountpoint_ (mounted volume) absolute path.
In the second example, the destination system has no unique mountpoint in the
desired backup path, so `--dest` ends with the root '/' path and the `--subdir`
argument is supplied to complete the archive path.

The destination mountpoint is automatically checked to make sure its mounted
before executing certain Wyng commands
including `send`, `receive`, `verify`, `delete` and `prune`.

(See the `arch-init` summary below for more details.)


## Operation

Run Wyng using the following commands and arguments in the form of:

**wyng \<parameters> command [volume_name]**

Please note that dashed parameters are always placed before the command.

### Command summary

| _Command_ | _Description_  |
|---------|---|
| **list** _[volume_name]_    | List volumes or volume sessions.
| **send** _[volume_name]_    | Perform a backup of enabled volumes.
| **receive** _volume_name_   | Restore a volume from the archive.
| **verify** _volume_name_    | Verify a volume against SHA-256 manifest.
| **prune** _[volume_name]_   | Remove older backup sessions to recover archive space.
| **monitor**                 | Collect volume change metadata & rotate snapshots.
| **diff** _volume_name_      | Compare local volume with archived volume.
| **add** _volume_name_       | Add a volume to the configuration.
| **delete** _volume_name_    | Remove entire volume from config and archive.
| **rename** _vol_name_ _new_name_  | Renames a volume in the archive.
| **arch-init**               | Initialize archive configuration.
| **arch-check** _[volume_name]_    | Thorough check of archive data & metadata
| **arch-delete**             | Remove data and metadata for all volumes.
| **arch-deduplicate**        | Deduplicate existing data in archive.
| **version**                 | Print the Wyng version and exit.


### Parameters / Options summary

| _Option_                      | _Description_
|-------------------------------|--------------
--session=_date-time[,date-time]_ | Select a session or session range by date-time or tag (receive, verify, prune).
--keep=_date-time_     | Specify date-time or tag of sessions to keep (prune).
--all-before           | Select all sessions before the specified _--session date-time_ (prune).
--autoprune=off        | Automatic pruning by calendar date. (experimental)
--save-to=_path_       | Save volume to _path_ (receive).
--sparse               | Receive volume data sparsely (implies --sparse-write)
--sparse-write         | Overwrite local data only where it differs (receive)
--remap                | Remap volume during `send` or `diff`.
--from=_type:location_ | Retrieve from a specific unconfigured archive (receive, verify, list, arch-init).
--local=_vg/pool_      | (arch-init) Pool containing local volumes.
--dest=_type:location_ | (arch-init) Destination of backup archive.
--subdir=_dirname_     | Optional subdirectory below mountpoint (--from, --dest)
--compression          | (arch-init) Set compression type:level.
--hashtype             | (arch-init) Set hash algorithm: _sha256_ or _blake2b_.
--chunk-factor         | (arch-init) Set archive chunk size.
--dedup                | Use deduplication for send (see notes).
--clean                | Perform garbage collection (arch-check) or medata removal (delete).
--meta-dir=_path_      | Use a different metadata dir than the default.
--volex=_volname[,*]_  | Exclude volumes (send, monitor, list, prune).
--force                | Needed for arch-delete.
--verbose              | Increase details.
--quiet                | 
-u, --unattended       | Don't prompt for interactive input.
--tag=tagname[,desc]   | Use session tags (send, list).

#### send

Performs a backup by sending volume data to a new archive session; this is always incremental
unless it is the first time a volume is being sent. Each session under an archival volume represents
the entire contents of the source volume at that time, even if only changed data is sent.
All volumes that were added to the archive will be included unless volume names are specified or
`--volex` is used to exclude volumes.

```

wyng send


```

Note: A `send` operation may refuse to backup a volume if there is not enough space on the
destination. One way to avoid this situation is to specify `--autoprune=on` which
will cause Wyng to remove older backup sessions from the archive when space is needed.


#### receive

Retrieves a volume snapshot (using the latest session ID
if `--session` isn't specified) from the archive and saves it to either the volume's
original path or the path specified
with `--save-to`. If `--session` is used, only one date-time or tag is accepted. The volume
name is required.

```

wyng --save-to=myfile.img receive vm-work-private


```

...restores a volume called 'vm-work-private' to 'myfile.img' in
the current folder.

Its possible to specify any valid file path or block
device. However, note that '/dev/_vgname_/_lvname_' is a special form
that indicates you are saving to an LVM volume; Wyng will only auto-create LVs for you
if the save-to path is specified this way.
For any save path, Wyng will try to discard old data before receiving.

_Emergency and Recovery situations:_ The `--from` option may be used to
receive from any Wyng archive that is not currently configured in the current
system. It is specified just like the `--dest` option of `arch-init`, and the
`--local` option may also be added to override the LVM settings:

```

wyng --from=ssh://user@192.168.1.2/mountpoint receive my-volume


```

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

wyng --session=20180605-000000,20180701-140000 prune


```

...removes backup sessions from midnight on June 5 through 2pm on July 1 for all
volumes. Alternately, `--all-before` may be used with a single `--session` date-time
to prune all sessions prior to that time.

If volume names aren't specified, `prune` will operate across all
enabled volumes.

The `--keep` option can accept a single date-time or a tag in the form `^tagID`.
Matching sessions will be excluded from pruning and autopruning.


#### monitor

Frees disk space that is cumulatively occupied by aging LVM
snapshots, thereby addressing a common resource usage issue with snapshot-based
backups. After harvesting their change metadata, the older snapshots are replaced with
new ones. Running `monitor` isn't strictly necessary, but it only takes a few seconds
and is good to run on a frequent, regular basis if you have some volumes that are
very active. Volume names may also be
specified if its desired to monitor only certain volumes.

This rule in /etc/cron.d runs `monitor` every 20 minutes:

```
*/20 * * * * root su -l -c '/usr/local/bin/wyng monitor'
```

#### diff
```

wyng diff vm-work-private


```

Compare a local volume snapshot with the archive and report any differences.
This is useful for diagnostics and can also be useful after a verification
error has occurred. The `--remap` option will record any differences into the
volume's current change map, resulting in those blocks being backed-up on
the next `send`.


#### add
```

wyng add vm-untrusted-private


```
Adds a new entry to the list of volumes configured for backup.


#### delete
```

wyng delete vm-untrusted-private


```

Removes a volume's wyng-managed snapshots, config and metadata from the source system and
all of its *data* from the destination archive (everything deleted except the source
volume). Use with caution!

An alternate form of `delete` will remove all Wyng archive-related metadata (incl. snapshots) from the
local system without affecting the archive on the destination:

```

wyng delete --clean

```

Alternately, using `delete --clean --all` will remove all Wyng metadata from the local system, including
snapshots from any Wyng archive (not just the currently configured archive).

#### rename
```

wyng rename oldname newname

```

Renames a volume _'oldname'_ in the archive to _'newname'_. Note: This will rename only the
archive volume, _not_ your source volume.


#### arch-deduplicate

De-duplicates the entire archive by removing repeating patterns. This can save space
on the destination's drive while keeping the archived volumes intact.

De-duplication can also be performed on an ongoing basis by using `--dedup` with `send`.


```

wyng --dedup arch-deduplicate


```


#### arch-init

Initialize a new backup archive configuration...
```

wyng --local=myvg/mypool --dest=internal:/mountpoint arch-init


```

Initialize a new backup archive with storage parameters...
```

wyng --local=myvg/mypool --dest=internal:/mpoint --chunk-factor=3 --hashtype=blake2b arch-init


```

Import a configuration from an existing archive...
```

wyng --from=internal:/mountpoint arch-init


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


#### arch-delete

Deletes the entire archive on the destination, and all data that was saved in it; also removes
archive metadata from the source system. Use with caution!

```

wyng --force arch-delete


```


#### Options/Parameters for arch-init

`--local` takes the source volume group and pool as 'vgname/poolname' for the `arch-init` command.
These LVM objects don't have to exist before using `arch-init` but they will
have to be there before using `send`.

`--dest` when using `arch-init`, describes the location where backups will be sent.
It accepts one of the following forms, always ending in a mountpoint path:

Note: --local and --dest are required if not using --from.

`--from` accepts a URL like `--dest`, but retrieves the configuration from an existing archive.
This imports the archive's configuration and can permanently save it as the
local configuration. This option can also be used with: list, receive and verify commands.
Note: You can override the archive's LVM settings by specifying `--local`.

| _URL Form_ | _Destination Type_
|----------|-----------------
|__internal:__/path                           | Local filesystem
|__ssh:__//user@example.com/path              | SSH server
|__qubes:__//vm-name/path                     | Qubes virtual machine
|__qubes-ssh:__//vm-name:me@example.com/path  | SSH server via a Qubes VM

`--subdir` In conjunction with `--dest` or `--from`, allows you to specify a subdirectory
below the mountpoint.

`--compression=zstd:3` accepts the form `type` or `type:level`. The three types available are
the default `zstd`, plus `zlib` and `bz2`. Note that Wyng will only default to `zstd` when the
'python3-zstd' package is installed; otherwise it will fall back to the less capable `zlib`.

`--hashtype=blake2b` accepts a value of either _'sha256'_ or _'blake2b'_ (the default).
The digest size used for blake2b is 256 bits. Note that with Python 3.5 the hashtype will
fall back to sha256 as blake2b was introduced in Python 3.6.

`--chunk-factor=1` sets the pre-compression data chunk size used within the destination archive.
Accepted range is an integer exponent from '1' to '6', resulting in a chunk size of 64kB for
factor '1', 128kB for factor '2', 256kB for factor '3' and so on. To maintain a good
space efficiency and performance balance, a factor of '2' or greater is suggested for archives
that will store volumes larger than about 100GB.

Note that _compression, hashtype_ and _chunk-factor_ cannot be changed for an archive once it is initialized.

### Options

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

`--volex=<volume>[,volume,*]`

Exclude one or more volumes from processing. May be used with commands that operate on multiple
volumes in a single invocation, such as `send`.

`--sparse-write`

Used with `receive`, this option does _not_ prevent Wyng from overwriting existing local volumes!
The sparse-write mode merely tells Wyng not to create a brand-new local volume for `receive`, and
results in the data being sparsely written into the volume instead. This is useful if the existing
local volume is a clone/snapshot of another volume and you wish to save local disk space. It is also
best used when the backup/archive storage is local (i.e. fast USB drive or similar) and you don't
want the added CPU usage of full `--sparse` mode.

`--sparse`

The sparse mode can be used with the `receive` command to intelligently overwrite an existing
local volume so that only the differences between the local and archived volumes will be fetched
from the archive and written to the local volume. This results in reduced remote disk and network
usage while receiving at the expense of some extra CPU usage on the local machine, and also uses
less local disk space when snapshots are a factor (implies '--sparse-write`).

`--dedup`

When used with the `send` command, data chunks from the new backup will be sent only if
they don't already exist somewhere in the archive. If its a duplicate, the chunk will be
linked instead of sent and stored, saving disk space and possibly time and bandwith.

The tradeoff for deduplicating is longer startup time for Wyng, in addition to using more
memory and CPU resources during backups. Using `--dedup` works best if you are backing-up
multiple volumes that have a lot of the same content and/or you are backing-up over a slow
Internet link.

`--autoprune=(off | on | min | full)` (_experimental_)

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

With `send`, attach a tagname of your choosing to the new backup session/snapshot; this may be
repeated on the command line to add multiple tags. Specifying an empty '' tag will cause Wyng
to ask for one or more tags to be manually input; this also causes `list` to display tag
information when listing sessions.


### Tips

* Its recommended to avoid backing up sensitive data to untrusted storage -- exercise caution
and add encryption where necessary.

* To reduce the size of incremental backups it may be helpful to remove cache
files, if they exist in your source volume(s). Typically, the greatest cache space
consumption comes from web browsers, so
volumes holding paths like /home/user/.cache can impacted by this, depending
on the amount and type of browser use associated with the volume. Three possible
approaches are to clear caches on browser exit, delete /home/user/.cache dirs on
system/container shutdown (this reasonably assumes cached data is expendable),
or to mount .cache on a separate volume that is not configured for backup.

* Another factor in space/bandwidth use is how sparse your source volumes are in
practice. Therefore it is best that the `discard` option is used when mounting
your volumes for normal use.

* The chunk size that your LVM thin pool was initialized with can also affect
disk space and I/O used when sending backups. Larger LVM chunk
sizes can mean larger incremental backups for volumes with lots of random writes.
To see the chunksize for your pool(s) run `sudo lvs -o name,chunksize`. Common sizes
are 128-512kB so if random writes are prevalent (i.e. for
large databases or mail archives) then using Wyng deduplication (which resolves
at 64kB by default) can reduce the size of your backup sessions.


### Troubleshooting notes

* Backup sessions shown in `list` output may be seemingly (but not actually) out of
order if the system's local time shifts
substantially between backups, such as when moving between time zones (including DST).
If this results in undesired selections with `--session` ranges, its possible
to nail down the precisely desired range by observing the output of
`list volumename` and using exact date-times from the listing.


### Encryption options

Wyng is slated to integrate encryption in the future. In the meantime,
here are some encryption approaches you can use to secure your backup archives:

* __Regular Linux systems__:

    Many options exist for mounting an encrypted filesystem on a local
    backup drive. Some examples you'll find use `gnome-disks` to
    format a partition as Ext4 on LUKS or VeraCrypt, or they use encrypted filesystems
    like [Encfs](https://wiki.ubuntu.com/SecureEncryptedRemoteVolumeHowTo)
    or [Cryfs](https://www.cryfs.org). These
    create a local filesystem mountpoint, so configuring Wyng with an
    'internal:/path' destination will suffice.

    For remote backups on untrusted servers, use one of the above encryption
    options on a shared folder (Encfs, Cryfs) or disk image file (LUKS, VeraCrypt).

    For remote backups where the server is trusted (i.e. encrypted and secured) it
    is possible to forgo setup of encrypted storage on your local computer and just
    specify 'ssh://user@address/path' for your Wyng destination.

* __Virtualized host systems__ using Xen, KVM or other hypervisors:

    Option A)  From the admin/storage VM, setup Wyng with an 'ssh://' destination where
    you wish to store the archive. This destination may be a local guest VM or a
    remote server.

    Option B)  For hypervisors that support attachment of block devices to
    different VMs: An encrypted block dev can be attached directly to the
    admin/storage VM where it is then decrypted and mounted. This requires only an
    'internal:/path' destination and benefits from not trusting a guest VM or remote
    server with handling encryption, but performance may be slower due to
    filesystem-network overhead.

* __Qubes OS:__ A brief description for dom0-encrypted remote storage from a Qubes laptop:

    1. Qube *remotefs* runs `sshfs` or other file sharing to access a remote filesystem
    and then `losetup` on a remote file (to size the file correctly during inital
    setup, use `truncate -s <size> mydisk.img` before using `losetup`).

    2. *Domain0* runs `qvm-block attach dom0 remotefs:loop0`.

    3. *Domain0* runs `cryptsetup` on /dev/xvdi to create/access the volume in its
    encrypted form. Finally, the resulting /dev/mapper device can be mounted for use.

    4. Setup Wyng on *Domain0* with `--dest=internal:/path`
    pointing to the mounted path.

    As an alternative to the above, if you have a trusted backup qube handling
    encryption, you can easily setup Wyng in dom0 with a 'qubes://vm-name/path'
    destination. Also, for Qubes OS where you have both a trusted backup VM *and*
    trusted server, you can backup to the server via the backup VM with a
    'qubes-ssh://vm-name:user@address/path' destination. These qubes options can
    achieve faster performance than the above `qvm-block attach` setup, but they
    move archive encryption out of Domain 0.

    Local USB storage is relatively simple: Attach the drive to dom0 then encrypt/decrypt it
    and then mount it.

### Authentication options

    Some of the above encryption methods have [options](https://www.kernel.org/doc/html/latest/admin-guide/device-mapper/dm-integrity.html) that enable authentication.

    Wyng archives can also be authenticated by signing the metadata. For example:

```
$ # Sign #
$ find /var/lib/wyng.backup -name archive.ini -o -name manifest -o -name '*info' | xargs b2sum >hashes
$ gpg --sign hashes

$ # Verify #
$ gpg --verify hashes && b2sum -c hashes && echo Archive OK.
```

### Beta testers

* Testing goals are basically stability, usability, security and efficiency. Compatibility
is also a valued topic, where source systems are generally expected to be a fairly recent
Linux distro or Qubes OS. Destination systems can vary a lot, they just need to have Python and
support Unix conventions.

* If you wish to run Wyng operations that may want to roll back later,
its possible to "backup the backup" in a relatively quick manner using a hardlink copy:
```
sudo cp -a /var/lib/wyng.backup /var/lib/wyng.backup-02
sudo cp -rl /dest/path/wyng.backup /dest/path/wyng.backup-02
```

Rolling back would involve deleting the wyng.backup dirs and then `cp` in the reverse
direction. Note that Wyng may require using --remap afterward. Also note this is _not_
recommended for regular use.

* Wyng is generally usable with filesystems that don't support hardlinks (such as encryption
filesystems), however one exception is when using deduplication mode. When setting
dedup higher than '1', Wyng will report that the destination is "not ready to receive commands"
if the destination fs doesn't allow hardlinks.


Donations
---
<a href="https://liberapay.com/tasket/donate"><img alt="Donate using Liberapay" src="media/lp_donate.svg" height=54></a>

<a href="https://www.patreon.com/tasket"><img alt="Donate with Patreon" src="media/become_a_patron_button.png" height=50></a>

If you like Wyng or my other efforts, monetary contributions are welcome and can
be made through [Liberapay](https://liberapay.com/tasket/donate)
or [Patreon](https://www.patreon.com/tasket).


External Links
---
Some other tools that use LVM metadata:

[lvmsync](https://github.com/mpalmer/lvmsync) (ruby). Synchronize logical volumes.

[lvm-thin-sendrcv](https://github.com/davidbartonau/lvm-thin-sendrcv) (java). Synchronize logical volumes.

[thinp-test-suite](https://github.com/jthornber/thinp-test-suite-deprecated) (ruby). POC backup program.
