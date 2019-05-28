<h1 align="center">Sparsebak</h1>
<p align="center">
Fast <i>Time Machine</i>-like disk image backups for Linux LVM.
</p>

Introduction
---

Sparsebak is aimed at incremental backup management for logical volumes. A
focus on condensing logical volume *metadata* is combined with a sparsebundle-style
(similar to OS X Time Machine) storage format to achieve flexible and quick
archive operations.

The upshot of this combination is that sparsebak has nearly instantaneous access to
volume changes (no repeated scanning of volume data!), remains
space-efficient regardless of file sizes within a volume,
avoids "*aging snapshot*" space consumption pitfalls, and can make an indefinite
number of frequent backups using relatively little CPU / disk IO overhead.

Sparsebak is optimized to process data as *streams* whenever possible, which
avoids writing temporary caches of data to disk. It also doesn't require the
source admin system to ever mount processed volumes, meaning untrusted data
in guest filesystems can be handled safely on systems that rely on
container-based security.


Status
---

Can do full or incremental backups of Linux thin-provisioned LVM to local dom0
or VM filesystems or via ssh, as well as simple volume retrieval for restore and verify.
Fast pruning of past backup sessions is now possible.

Data verification currently relies on SHA-256 manifests being safely stored on the
source/admin system to maintain integrity. Encryption and key-based verification
are not yet implemented.

Sparsebak is in beta-testing and comes with no warranties expressed or implied.


Setup & Requirements
---

Before starting, thin-provisioning-tools, lvm2, and python >=3.5.4 must be installed. Configured volumes must reside in a LVM thin-provisioned pool.

`sparsebak.py` is currently distributed as a single python script with no complex
supporting modules or other program files; it can be placed in '/usr/local/bin'
or another place of your choosing. It looks in '/sparsebak/default.ini'
for settings that define what to back up and where the backup archive will
be located as well as the archive's metadata.

Settings are initialized with `arch-init`. Please note that dashed arguments are
always placed before the command:

```
sparsebak.py --source=vg/pool --dest=ssh://me@exmaple.com/mnt/bkdrive arch-init
```

...or...

```
sparsebak.py --source=vg/poolname --dest=internal:/ --subdir=home/user arch-init
```

The `--dest` argument always ends in a _mountpoint_ (mounted volume) absolute path.
In the second example, the destination system has no unique mountpoint in the
desired backup path, so `--dest` ends with the root '/' path and the `--subdir`
argument is supplied to complete the archive path.

The destination mountpoint is automatically checked to make sure its mounted
before executing certain sparsebak commands
including `send`, `receive`, `verify`, `delete` and `prune`.

(See the `arch-init` summary below for more details.)

Although not absolutely necessary, it is also recommended that the `monitor`
command be run at fairly frequent (10-30 min.)
intervals to minimize the amount of disk space that sparsebak-managed snapshots
may occupy. A rule in /etc/cron.d takes care of this:

```
*/20 * * * * root su -l -c '/usr/local/bin/sparsebak.py monitor'
```

This will harvest the locations of changed data (but not the data itself) and
rotate to fresh snapshots every 20 minutes.



Operation
---

Run `sparsebak.py` in a Linux environment using the following commands and options
in the form of `sparsebak.py [--options] command [volume_name]`.

### Command summary
  * `list volume_name` :  List volume sessions.
  * `send [volume_name]` :  Perform a backup of enabled volumes.
  * `receive --save-to=path volume_name` : Restore a volume from the archive.
  * `verify volume_name`:  Verify a volume against SHA-256 manifest.
  * `prune --session=date-times [volume_name]` : Remove older backup sessions.
  * `monitor` :  Scan and collect volume change info for all enabled volumes.
  * `diff volume_name` :  Compare local volume with archive.
  * `add volume_name` :  Add a volume to the configuration.
  * `delete volume_name` :  Remove entire volume from config and archive.
  * `arch-init --source --dest` : Initialize archive configuration.
  * `arch-delete` : Remove data and metadata for all volumes.

### Options summary
  * `-u, --unattended` :  Don't prompt for interactive input.
  * `--all-before` :  Select all sessions before the specified --session date-time.
  * `--session=date-time[,date-time]` : Select sessions by date-time (receive, verify, prune).
  * `--save-to=path` :  Required for `receive`.
  * `--tarfile` :  Store backups on destination as tar files (see notes).
  * `--remap` :  Remap volume during `diff`.
  * `--source`  :  (arch-init) Specify source for backups.
  * `--dest`  :  (arch-init) Specify destination of backup archive.
  * `--subdir`  :  (arch-init) Optional subdirectory bewlow mountpoint.
  * `--compression`  :  (arch-init) Set compression type:level.
  * `--chunk-factor`  :  (arch-init) Set archive chunk size.

#### send

   $ sudo sparsebak.py send

The `send` command performs a backup after performing a scan and checking
that the backup destination is available. If sparsebak has no metadata on file about a
volume its treated as a new addition to the backup set and a full backup will
be performed on it; otherwise it will use the collected change information to do an
incremental backup.

(Note the `--tarfile` option output will currently prevent some operations
like `prune` and `receive` from working; this can be resolved by manually un-taring the archive
on the destination and changing format 'tar' to 'folders' in the local session 'info' file.
In future, tar archives will have limited `prune` and full `receive` support.)

#### receive

The `receive` command retreives a volume instance (using the latest session ID
if `--session` isn't specified) from the archive and saves it to the path specified
with `--save-to`. If `--session` is used, only one date-time is accepted.

   $ sudo sparsebak.py --save-to=myfile.img receive vm-work-private

...restores a volume called 'vm-work-private' to 'myfile.img' in
the current folder. Note that its possible to specify any path, including block
devices such as '/dev/vgname/vm-work-private'. In this case, the lv volume will
be automatically created if the configured volume group matches the save path.

Resizing is automatic if the path is a logical volume or regular file. For any
`--save-to` type, sparsebak will try to `blkdiscard` or `truncate` old data
before saving.


#### verify

The `verify` command is similar to `receive` without `--save-to`. For both
`receive` and `verify` modes, an exception error will be raised with a non-zero exit
code if the received data does not pass integrity checks.


#### prune

The `prune` command can quickly remove any prior backup session you specify
without re-writing the data archive or compromising volume integrity.
This is a great way to reclaim space on a backup drive!
To use, supply a single exact date-time in YYYYMMDD-HHMMSS format to remove a
specific session, or two date-times as a range:

   $ sudo sparsebak.py prune --session=20180605-000000,20180701-140000
   
...removes any backup sessions from midnight on June 5 through 2pm on July 1.
Alternately, `--all-before` may be used with a single `--session` date-time
to select all sessions prior to that time.

If specific volumes aren't specified, `prune` will operate across all
enabled volumes.


#### monitor

   $ sudo sparsebak.py monitor

The `monitor` command starts a monitor-only session
that collects snapshot change metadata. This only takes a few seconds and is good
to do on a frequent, regular basis (several times an hour or more) via cron or a
systemd timer. This command isn't strictly necessary but
exists to make sparsebak snapshots short-lived and relatively carefree --
sparsebak snapshots will not eat up disk space by accumulating large amounts of old data.


#### diff

   $ sudo sparsebak.py diff vm-work-private

Compare a current configured volume with the archive copy and report any differences.
This is useful for diagnostics and can also be useful after a verification
error has occurred. The `--remap` option will record any differences into the
volume's current change map, resulting in those blocks being backed-up on
the next `send`.


#### add

   $ sudo sparsebak.py add vm-untrusted-private

Adds a new entry to the list of volumes configured for backup.


#### delete

   $ sudo sparsebak.py delete vm-untrusted-private

Removes a volume's config, snapshots and metadata from the source system and
all of its *data* from the destination archive. Use with caution!


#### arch-init

Initializes the settings for an archive. Parameters:

`--source` is required and
takes the source volumes' volume group and pool as `--source=vgname/poolname`.
These LVM objects don't have to exist before using `arch-init` but they will
have to be there later, of course.

`--dest` is required and accepts one of the following forms
– always ending in a mountpoint path:

   `ssh://user@exmaple.com/mpoint`
   `internal:/mpoint`
   `qubes://vm-name/mpoint`
   `qubes-ssh://vm-name|me@example.com/mpoint`

`--subdir` allows you to specify a subdirectory below the mountpoint.

`--compression=zlib:4` accepts the form `type:level`. However, only zlib compression
is supported at this time so this option is currently only useful to set the
compression level.


### Other restore options

The `spbk-assemble` tool can still be used to create a regular disk image from within
a sparsebak archive. It should be run on a system/VM that has filesystem access
to the archive, using the syntax `spbk-assemble [-c] path-to-volume-name`. Use
`-c` option to do a local SHA-256 hash during assembly. This tool will
likely be deprecated in future releases.

Since sparsebak's archival folder format is similar to Apple's sparsebundle,
the possibility exists to adapt a FUSE sparsebundle handler to access archives
as a read-only filesystem. One such FUSE handler is
[sparsebundlefs](https://github.com/torarnv/sparsebundlefs).
Another, [sparsebundle-loopback](https://github.com/jeffmahoney/sparsebundle-loopback)
is written in Python.


Tips
----

* If the destination volume is not thoroughly trusted, its currently recommended
to avoid backing up sensitive data to such a volume -- exercise caution.

* To reduce the size of incremental backups it may be helpful to remove cache
files, if they exist in your volume(s). Typically, the greatest cache space
consumption comes from web browsers, so
volumes holding paths like /home/user/.cache can impacted by this, depending
on the amount and type of browser use associated with the volume. Two possible
approaches are to delete /home/user/.cache dirs on browser exit or system/container
shutdown (this reasonably assumes cached data is expendable), or to mount .cache
on a separate volume that is not configured for backup.

* The chunk size of your LVM thin pool can also affect disk space and I/O used when
doing backups. The chunk size varies depending on considerations (such as curbing
fragmentation) made at the time of pool creation. The smaller the pool chunk size
(ranging from 64kB to 1GB) the
better the resolution of metadata scanning. In pratical terms, larger pool chunk
sizes mean larger incremental backups for volumes with lots of random writes,
but little difference for volumes with mostly sequential writes. To see the
chunksize for your pool(s) run `sudo lvs -o name,chunksize`.

* Another factor in space/bandwidth use is how sparse your source volumes are in
practice. Therefore it is best that the `discard` option is used when mounting
your volumes for normal use (this is the default for most Linux systems).



Testing
---

* Even with non-sensitive data, precaution can avoid wasting X number of
testing hours. A good way to avoid losing archives to corruption/bugs is to
make a quick linked copy of the sparsebak destination folder; either `cp -rl` or
`rsync -H` can do this efficiently. For example `cp -rl sparsebak backup-sparsebak`.
At the same time, do a regular copy of the source metadata folder with
`sudo cp -a /sparsebak /backup-sparsebak'.

* If you should need to start fresh with a particular volume and using `delete`
fails, the volume can be removed manually: Deleting the
volume's subfolders on both the source and destination, then `lvremove` the
volume's .tick and .tock snapshots.

* Avoid switching/swapping the /sparsebak dir and ini file, even for testing purposes.
If you somehow must have more than one, there must be no overlap of names in
the volumes section. In the future sparsebak will support multiple archive ini
configs.

* *Deduplication* has been added as an experimental feature for v0.2beta; this is
a means to reduce allocated disk space, network traffic and (sometimes) overall
backup times.
  - To deduplicate existing archive data, issue the command:
  `sparsebak.py --testing-dedup=N dedup-existing`
  where 'N' is the algorithm number to be tested. Current available choices are
  2, 3, 4 and 5 for *dict*, *sqlite*, *array tree* and *bytearray tree*. The 2/dict
  option, however, is not a contender for general release due to its very heavy
  memory footprint.
  - To deduplicate while backing up (also reduces net bandwidth), issue the command
`sparsebak.py --testing-dedup=N send`.
  - No committment is implied by using dedup options: You can try the options
  with the above commands whenever you like, switch between algorithms or switch
  between using dedup and not using it.
  - Dedup requires a hardlink-capable filesystem for the archive/destination.
  Trying to use it without this (rather common) capability will cause the
  operation to fail.


Troubleshooting notes
---

* Sessions may be listed seemingly out of order if the system's local time shifts
substantially between backups, such as when moving between time zones.
If this results in undesired selections with `--session` parameters, its possible
to nail down the precisely desired range by observing the output of
`list volumename` and using exact date-times from the listing.

### Encryption options

Sparsebak will likely integrate encryption in the future. In the meantime, here is a
brief description for ad-hoc locally-encrypted remote storage from a Qubes laptop:

1. Qube *remotefs* runs `sshfs` to access a remote filesystem and then `losetup` on a
remote file (to size the file correctly during inital setup,
use `truncate -s <size> myfile.img` before using `losetup`).

2. *Domain0* runs `qvm-block attach dom0 remotefs:loop0`.

3. *Domain0* runs `cryptsetup` on /dev/xvdi to create/access the volume in its
encrypted form. Finally, the resulting /dev/mapper device can be mounted for use.

4. Configure default.ini on *Domain0* for an `internal:` destination type
pointing to the mounted path.

A local USB storage option similar to the above can be achived by substituting *sys-usb*
for *remotefs*.

Other systems without Qubes' security model can utilize a simplified version of
this procedure by omitting step 2 and performing steps 1 and 3 in a single context.


Todo
---

* Encryption integration

* Additional functions: untar, verify-archive

* File name and sequence obfuscation

* Additional sanity checks

* Btrfs and ZFS support
