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
avoids snapshot space consumption pitfalls, and can make an indefinite number of
frequent backups to an archive with relatively little CPU / disk IO overhead.

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

This tool is still in alpha/testing stage. Do NOT rely on it as your primary backup system!


Setup & Requirements
---

Required packages: thin-provisioning-tools, lvm2, python3. Configured volumes
must reside in lvm thin-provisioned pools.

`sparsebak.py` is currently distributed as a single python script with no complex
supporting modules or other program files; it can be placed in '/usr/local/bin'
or another place of your choosing. It looks in '/sparsebak/sparsebak.ini'
for global settings and a list of volume names to be monitored
and backed up. Some settings you can change are `vgname` and `poolname`
for the volume group and pool, in addition to `destvm`, `destmountpoint` and `destdir`
which combine to a vm:dir/path specification for the backup destination. The
`destmountpoint` is checked to make sure its mounted for several sparsebak commands
including `send`, `receive`, `verify` and `prune`, but not `monitor`.

Backup metadata is also saved to '/sparsebak' folder.

#### Example config sparsebak.ini

```
[var]
vgname = dom0
poolname = pool00
destvm = ssh://user@exmaple.com
destmountpoint = /mnt/backupdrive
destdir = backups

[volumes]
vm-untrusted-private = enable
vm-personal-private = disable
vm-banking-private = enable
```

The `destvm` setting accepts a format of `ssh://user@exmaple.com`, `qubes://vmname`,
`qubes-ssh://vmname|user@example.com`, or `internal:` for local/admin storage. Backups
can be sent to a trusted VM with access to an
encryped removable volume, for example, or to an ssh: destination or an encrypted
remote filesystem layer over sshfs or samba (see [Encryption options] below).

Although not absolutely necessary, it is recommended that the `monitor`
command be run at fairly frequent (10-20 min.)
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
in the form of `sparsebak.py [options] command [volume_name]`.

### Command summary
  * `list volume_name` :  List volume sessions.
  * `send [volume_name]` :  Perform a backup of enabled volumes.
  * `receive --save-to=path volume_name` : Restore a volume from the archive.
  * `verify volume_name`:  Verify a volume against SHA-256 manifest.
  * `prune --session=date-times [volume_name]` : Remove older backup sessions.
  * `monitor` :  Scan and collect volume change info for all enabled volumes.
  * `diff volume_name` :  Compare local volume with archive.
  * `delete volume_name` :  Remove entire volume from archive.

### Options summary
  * `-u, --unattended` :  Don't prompt for interactive input.
  * `--tarfile` :  Store backups on destination as tar files (see notes).
  * `--save-to=path` :  Required for `receive`.
  * `--session=date-time[,date-time]` : Select sessions by date-time (receive, verify, prune).
  * `--remap` :  Remap volume during `diff`.

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
the current folder. Note its possible to specify any path, including block devices
such as '/dev/vgname/vm-work-private'. In this case, a writeable
block device (such as a thin LV) must already exist at the path, although
sparsebak will handle resizing for you automatically.


#### verify

The `verify` command is similar to `receive` without `--save-to`. For both
`receive` and `verify` modes, an exception error will be raised with a non-zero exit
code if the received data does not pass integrity checks.


#### prune

The `prune` command can remove any backup session you specify, except for the
latest version, without re-writing the data archive or compromising volume integrity.
This is a great way to reclaim space on a backup drive!
To use, supply a single exact date-time in YYYYMMDD-HHMMSS format to remove a
specific session, or two date-times as a range:

   $ sudo sparsebak.py prune --session=20180605-000000,20180701-140000
   
...removes any backup sessions from midnight on June 5 through 2pm on July 1.
If specific volumes aren't specified, `prune` will operate across all volumes
enabled in the config file.


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


#### delete

   $ sudo sparsebak.py delete vm-untrusted-private

Removes an entire volume's data and metadata from the source system and
destination archive. Use with caution!


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

Its currently recommended to avoid backing up sensitive data during testing if
the destination volume is untrusted -- exercise caution.

Otherwise, there are still reasons to be cautious such as not wasting X number of
testing/trial hours. A good way to avoid losing archives to corruption/bugs is to
make a quick linked copy of the sparsebak destination folder; either `cp -rl` or
`rsync -H` can do this efficiently. For example `cp -rl sparsebak backup-sparsebak`.
At the same time, do a regular copy of the source metadata folder with
`sudo cp -a /sparsebak /backup-sparsebak'.

If you should need to start over again with a particular volume then deleting the
volume's subfolders on both the source and destination should suffice. If it doesn't
suffice you may need to `lvremove` the volume's .tick and .tock snapshots. A new
command `purge-metadata` was added to take care of these steps on the source system,
but removal should still be done manually on the destination.

Avoid switching/swapping the /sparsebak dir and ini file, even for testing purposes.
If you somehow must have more than one, there must be no overlap of names in
the volumes section. In the future sparsebak will support multiple archive ini
configs.


Troubleshooting notes
---

A recent change now requires a type prefix for the `destvm` setting. This was
done to allow clear specification of the type of proceduced calls required and
so protocols like `ssh` can be supported unambiguously. Existing users will
have to change their .ini setting to add a `ssh://`, `qubes://` or `internal:`
prefix.

### Encryption options

Sparsebak will likely support encryption in the future. In the meantime here is a
brief description for ad-hoc locally-encrypted remote storage from a Qubes laptop:

1. Qube *remotefs* runs `sshfs` to access a remote filesystem and then `losetup` on a
remote file (to size the file correctly during inital setup,
use `truncate -s <size> myfile.img` before using `losetup`).

2. *Domain0* then runs `qvm-block attach backup remotefs:loop0`.

3. Qube *backup* (no net access) runs `cryptsetup` on /dev/xvdi to create/access
the volume in its encrypted form.

A local USB storage option similar to the above can be achived by substituting *sys-usb*
for *remotefs*.

Other systems can utilize a simplified version of this procedure by omitting
step 2 and performing steps 1 and 3 in a single context.

Todo
---

* Inclusion of system-specific metadata in backups (VM/container configs, etc.)

* Encryption integration

* Additional functions: untar, verify-archive

* Show configured vs present volumes in list output

* File name and sequence obfuscation

* Pool-based Deduplication

* Additional sanity checks

* Btrfs, XFS, ZFS support
