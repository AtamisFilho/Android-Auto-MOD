# Changelog

All notable changes to this project are documented here.  The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-10-25

First release.

### Added

- **Raw device access** for Windows (`\\.\PhysicalDriveN` with
  `DeviceIoControl`), Linux (`/dev/sdX` with `ioctl`) and disk image files.
  The logical sector size reported by the device is used throughout, so both
  512e (Advanced Format) and 4Kn drives are handled correctly.
- **Partition table support** for MBR -- including the extended boot record
  chain -- and GPT, with GUID encoding, CRC32 verification and consistent
  primary and backup copies.
- **Free space computation**: the gaps between the known partitions, which
  are the places a lost partition can hide.
- **Filesystem probes** for NTFS, exFAT, FAT12/16/32, ext2/3/4, Linux swap
  and HFS+.  Every candidate is parsed field by field instead of being
  accepted on its signature alone.
- **NTFS boundary proof** through the `$Bitmap` allocation meta-file: the
  bitmap is matched against the actual bytes on the disk, which confirms the
  start of the volume and determines where it ends.  The `$MFT` is used as a
  cross-check and the sectors preceding the candidate are sampled to confirm
  they belong to a different volume.
- **Scanner** with a quick and a full mode, reporting the confidence and the
  concrete reasons behind every candidate.
- **Resumable checkpoints** backed by SQLite.
- **Conservative write-back**: dry run by default, an automatic backup of the
  partition table structures before every write, validation that rejects
  overlapping or out-of-range candidates, extension of the extended boot
  record chain when no primary MBR slot is free, and a GPT update that keeps
  both copies and all CRCs consistent.
- **Read-only browsing** of a candidate without mounting it, plus optional
  native mounting (drive letter on Windows, loop mount on Linux).
- **Command line interface** with `list`, `scan`, `recover`, `browse`,
  `backup` and `restore`.
- **Standalone binaries** for Windows x64 and Linux x64.
- **Test suite** of 76 tests built on synthetic disk images: MBR sectors, GPT
  disks with both copies and a complete NTFS volume with a real `$MFT` and
  `$Bitmap`.  No physical disk is touched by the tests.

[0.1.0]: https://github.com/AtamisFilho/testes/releases/tag/v0.1.0
