## sparsebak

Fast disk image backups for Qubes OS and Linux LVM.

### Status

Can do full or incremental backups to local dom0 or VM filesystems, as well as
simple volume retreival for restoring.

This is still in alpha/testing stage. Do NOT rely on this program as your primary backup system!

### Operation

sparsebak looks in '/sparsebak/sparsebak.ini' for a list of volume names to
be monitored and backed up. Some settings you can change are `vgname` and `poolname`
for the volume group and pool, in addition to `destvm`, `destmountpoint` and `destdir`
which combine to a vm:dir/path specification for the backup destination. The
`destmountpoint` is checked to make sure its mounted when sparsebak is run in `send` mode.

The resulting backup metadata is also saved to '/sparsebak' for now. Backups
can be sent to a trusted Qubes VM with access to an
encryped removable volume, for example, or an encrypted remote filesystem.

Command options:
  monitor : Only scan and collect volume change info.
  send : Perform a backup after scanning volume changes.
  -u, --unattended
  --tarfile	Store backups in tar files instead of chunks (cannot be pruned).

The subcommands can be invoked on the command line like so:

   $ sparsebak.py monitor

The `monitor` subcommand starts a monitor-only session
that collects volume change metadata. This only takes a few seconds and is good
to do on a frequent, regular basis (several times an hour or more) via cron or a
systemd timer. This command
exists to make sparsebak snapshots short-lived and relatively carefree --
sparsebak snapshots will not eat up disk space by accumulating large amounts of old data.

   $ sparsebak.py send

The `send` subcommand performs a backup after performing a scan and checking
that the backup destination is available. If sparsebak has no metadata on file about a
volume its treated as a new addition to the backup set and a full backup will
be performed on it; otherwise it will use the collected change information to do an
incremental backup.

### Restoring

The `spbk-assemble` tool can be used to create a regular disk image from a
sparsebak archive. It should be run on a system/VM that has filesystem access
to the archive, using the syntax `spbk-assemble path-to-volume-name`.

### Todo

* Basic functions: Volume selection, Restore, Delete

* Encryption

* Pool-based Deduplication

* Additional sanity checks

* Btrfs support
