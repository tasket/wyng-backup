## sparsebak

Efficient, disk image-based backups for Qubes OS and Linux LVM.

### Status

Can do full or incremental backups to local dom0 or VM filesystems, as well as
simple volume retreival for restoring.

This is still in alpha/testing stage. Do NOT rely on this program as your primary backup system!

### Operation

sparsebak looks in '/sparsebak/set01/sparsebak.conf' for a list of volume names to
be monitored and backed up. The volumes should all be from qubes_dom0/pool00,
unless you have changed the `vgname` and `poolname` variables. Other variables to
set are `destvm`, `destmountpoint` and `destdir`.

The resulting backup metadata is also saved to '/sparsebak/set01/' for now. Backups
can be sent to a trusted Qubes VM with access to an
encryped removable volume, for example, or an encrypted remote filesystem.

Currently the default mode (with no command options) is a monitor-only session
that collects volume change metadata. This only takes a few seconds and is good
to do on a frequent, regular basis - i.e. several times an hour.

Command options:
  -s, --send    Perform a backup after scanning volume changes.
  -f, --full    No longer used; -f is now implied by -s.

### Restoring

The `spbk-assemble` tool can be used to create a regular disk image from a
sparsebak archive. It should be run on a system/VM that has filesystem access
to the archive, using the syntax `spbk-assemble <path-to-set/vggroup/volumename`.

### Todo

* Basic functions: Volume selection, Restore, Delete

* Encryption

* Pool-based Deduplication

* Additional sanity checks

* Btrfs support
