<h1 align="center">Sparsebak</h1>
<p align="center">
Fast <i>Time Machine</i>-like disk image backups for Qubes OS and Linux LVM.
</p>

Introduction
---

Sparsebak is aimed at incremental archive management at the logical volume level
where a snapshot management interface is available. Examples of such interfaces
are LVM commands, Btrfs / XFS / ZFS tools, etc. This lv focus is combined with
a /sparsebundle/-like storage format that enables flexible and quick maintainance
operations.

The upshot of this combination is that sparsebak has nearly instantaneous access to
volume changes, remains fairly space-efficient regardless of updated-file sizes,
avoids snapshot space consumption pitfalls, and can make an indefinite* number of
frequent backups to an archive with relatively little CPU / disk IO overhead.

Sparsebak is optimized to process data as /streams/ whenever possible, which
avoids writing temporary caches of data to disk. It also doesn't require the
source admin system to ever /mount/ processed volumes, meaning untrusted data
and filesystems can be handled safely.

(* See `prune` command for freeing space on the destination.)


Status
---

Can do full or incremental backups of Linux thin LVM to local dom0 or VM filesystems, as well as
simple volume retreival for restore and verify. Fast pruning of past backup
sessions is now possible.

Data verification currently relies on SHA-256 manifests being safely stored on the
source/admin system to maintain integrity. Encryption and key-based verification
are not yet implemented.

This tool is still in alpha/testing stage. Do NOT rely on it as your primary backup system!


Setup & Requirements
---

Required packages: thin-provisioning-tools, lvm2, python3. Configured volumes
must reside in lvm thin-provisioned pools.

Sparsebak is currently distributed as a single python script with no complex
supporting modules or other program files. It looks in '/sparsebak/sparsebak.ini'
for global settings and a list of volume names to be monitored
and backed up. Some settings you can change are `vgname` and `poolname`
for the volume group and pool, in addition to `destvm`, `destmountpoint` and `destdir`
which combine to a vm:dir/path specification for the backup destination. The
`destmountpoint` is checked to make sure its mounted for several sparsebak commands
including `send`, `receive`, `verify` and `prune`, but not `monitor`.

#### Example config .ini

```
[var]
vgname = qubes_dom0
poolname = pool00
destvm = backup
destmountpoint = /mnt/volume
destdir = backups

[volumes]
vm-untrusted-private = enable
vm-personal-private = disable
vm-banking-private = enable
```

The resulting backup metadata is also saved to '/sparsebak'. Backups
can be sent to a trusted Qubes VM with access to an
encryped removable volume, for example, or an encrypted remote filesystem layer
over sshfs or samba.


Operation
---

Run `sparsebak.py` in a Linux environment using the following commands and options
in the form of `sparsebak.py [options] command [volume_name]`.

### Command summary
  * `monitor` : Scan and collect volume change info for all enabled volumes.
  * `send [volume_name]` : Perform a backup of enabled volumes.
  * `receive --save-to=path volume_name` : Restore a volume from the archive.
  * `verify volume_name`: Verify a volume.
  * `list volume_name` : List volume sessions.
  * `resync volume_name` : Re-synchronize delta map with archive
  * `prune --session=date-times [volume_name]` : Remove older backup sessions.

### Options summary
  * `-u, --unattended` : Don't prompt for interactive input.
  * `--tarfile` : Store backups on destination as tar files (see notes).
  * `--save-to=path` : Required for `receive`.
  * `--session=date-time[,date-time\]` : Select sessions by date-time (receive, verify, prune).

#### monitor

   $ sudo sparsebak.py monitor

The `monitor` command takes no options and starts a monitor-only session
that collects volume change metadata. This only takes a few seconds and is good
to do on a frequent, regular basis (several times an hour or more) via cron or a
systemd timer. This command
exists to make sparsebak snapshots short-lived and relatively carefree --
sparsebak snapshots will not eat up disk space by accumulating large amounts of old data.

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
such as '/dev/mapper/qubes_dom0-vm--work--private'. In this case, a writeable and
adequately sized block device (such as a thin LV) must already exist at the path.


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
   
...removes any backup sessions between midnight on June 5 through 2pm on July 1.
Specific volumes cannot yet be specified, so this operates across all enabled
volumes in the main sparsebak.ini config file.


### Other restore options

The `spbk-assemble` tool can be used to create a regular disk image from within
a sparsebak archive. It should be run on a system/VM that has filesystem access
to the archive, using the syntax `spbk-assemble [-c] path-to-volume-name`. Use
`-c` option to do a local SHA-256 hash during assembly. This tool will
likely be deprecated in future releases.

Since sparsebak's archival folder format is similar to Apple's sparsebundle,
the possibility exists to adapt a FUSE sparsebundle handler to access archives
as a read-only filesystem. One such FUSE handler is
[sparsebundlefs](https://github.com/torarnv/sparsebundlefs).


Testing
---

Its currently recommended to avoid backing up sensitive data during testing if
the destination volume is untrusted -- exercise caution.

Otherwise, there are still reasons to be cautious such as not wasting X number of
testing/trial hours. A good way to avoid losing archives to corruption/bugs is to
make a quick linked copy of the sparsebak destination folder; either `cp` or `rsync` can
do this efficiently. For example `cp -rl sparsebak backup-sparsebak`. At the same
time, do a regular copy of the source metadata folder with `sudo cp /sparsebak /backup-sparsebak'.

If you should need to start over again with a particular volume then deleting the
volume's subfolders on both the source and destination should suffice. If it doesn't
suffice you may need to `lvremove` the volume's .tick and .tock snapshots.

### Encrytion options

Sparsebak will likely support encryption in the future. In the meantime here is a
brief description for ad-hoc locally-encrypted remote storage from Qubes OS:

1. Qube /remotefs/ runs `sshfs` to access a remote filesystem and then `losetup` on a
remote file (to size the file correctly during inital setup,
use `truncate -s <size> myfile.img` before using `losetup`).

2. /dom0/ then runs `qvm-block attach backup remotefs:loop0`.

3. Qube /backup/ (no net access) runs `cryptsetup` on /dev/xvdi to create/access
the volume in its encrypted form.

A local USB storage option similar to the above can be achived by substituting /sys-usb/
for /remotefs/.


Todo
---

* Basic functions: Volume selection options, Delete

* Inclusion of system-specific metadata in backups (Qubes VM configs, etc.)

* Additional functions: Untar, receive-archive, verify-archive

* Show configured vs present volumes in list output

* Encryption

* File name and sequence obfuscation

* Pool-based Deduplication

* Additional sanity checks

* Btrfs, XFS, ZFS support
