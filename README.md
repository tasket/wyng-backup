## Sparsebak

Fast disk image backups for Qubes OS and Linux LVM.

### Introduction

### Status

Can do full or incremental backups to local dom0 or VM filesystems, as well as
simple volume retreival for restore and verify. Fast pruning of past backup
sessions is now possible.

Verification currently relies on SHA-256 manifests being safely stored on the
source/admin system to maintain integrity. Encryption and key-based verification
are not yet implemented.

This is still in alpha/testing stage. Do NOT rely on this program as your primary backup system!

### Operation

Sparsebak looks in '/sparsebak/sparsebak.ini' for a list of volume names to
be monitored and backed up. Some settings you can change are `vgname` and `poolname`
for the volume group and pool, in addition to `destvm`, `destmountpoint` and `destdir`
which combine to a vm:dir/path specification for the backup destination. The
`destmountpoint` is checked to make sure its mounted for several sparsebak commands
including `send`, `receive`, `verify` and `prune` but not `monitor`.

The resulting backup metadata is also saved to '/sparsebak'. Backups
can be sent to a trusted Qubes VM with access to an
encryped removable volume, for example, or an encrypted remote filesystem layer
over sshfs or samba.

Commands and options:
  * `monitor` : Scan and collect volume change info for all enabled volumes.
  * `send` : Perform a backup of enabled volumes.
  * `receive --save-to=path volume_name` : Restore a volume from the archive.
  * `verify volume_name`: Verify a volume.
  * `list volume_name` : List volume sessions.
  * `prune --session=date-time[,date-time]` : Remove older backup sessions.
  * `-u, --unattended` : Don't prompt for interactive input.
  * `--tarfile=path` Store backups in tar files instead of folders (cannot be pruned).
  * `--session=date-time[,date-time\]` : Select sessions by date-time (receive, verify, prune)

The subcommands can be invoked on the command line like so:

   $ sudo sparsebak.py monitor

The `monitor` command takes no options and starts a monitor-only session
that collects volume change metadata. This only takes a few seconds and is good
to do on a frequent, regular basis (several times an hour or more) via cron or a
systemd timer. This command
exists to make sparsebak snapshots short-lived and relatively carefree --
sparsebak snapshots will not eat up disk space by accumulating large amounts of old data.

   $ sudo sparsebak.py send

The `send` command performs a backup after performing a scan and checking
that the backup destination is available. If sparsebak has no metadata on file about a
volume its treated as a new addition to the backup set and a full backup will
be performed on it; otherwise it will use the collected change information to do an
incremental backup.

The `receive` command retreives a volume instance (using the latest session ID
if `--session` isn't specified) and saves it to the path specified with `--save-to`.
If `--session` is used, only one date-time is accepted.

   $ sudo sparsebak.py --save-to myfile.img receive vm-work-private

...restores a volume called 'vm-work-private' to 'myfile.img' in
the current folder. Note its possible to specify any path, including block devices
such as '/dev/mapper/qubes_dom0-vm--work--private'. In this case, a writeable and
adequately sized block device (such as a thin LV) must already exist at the path.

The `verify` command is similar to `receive` without `--save-to`. For both
`receive` and `verify`, an exception error will be raised with a non-zero exit
code if the received data does not pass integrity checks.

The `prune` command can remove any backup session you specify, except for the
latest version, without re-writing the data archive or compromising volume integrity.
This is a great way to reclaim space on a backup drive!
To use, supply a single exact date-time in YYYYMMDD-HHMMSS format to remove a
specific session, or two date-times as a range:

   $ sudo sparsebak.py prune --session=20180605-000000,20180701-140000
   
...removes any backup sessions between midnight on June 5 through 2pm on July 1.
Specific volumes cannot yet be specified, so this operates across all enabled
volumes in the main sparsebak.ini config file.

#### Other restore options

The `spbk-assemble` tool can be used to create a regular disk image from within
a sparsebak archive. It should be run on a system/VM that has filesystem access
to the archive, using the syntax `spbk-assemble [-c] path-to-volume-name`. Use
`-c` option to do a local SHA-256 hash during assembly. This tool will
likely be deprecated in future releases.

Since sparsebak's archival folder format is similar to Apple's sparsebundle,
the possibility exists to adapt a FUSE sparsebundle handler to access archives
as a read-only filesystem. One such FUSE handler is....................

### Todo

* Basic functions: Volume selection, Delete

* Additional functions: Untar, receive-history, verify-history

* Encryption

* File name and sequence obfuscation

* Pool-based Deduplication

* Additional sanity checks

* Btrfs support
