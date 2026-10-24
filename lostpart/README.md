# lostpart

**Identify and recover lost disk partitions — Windows and Linux.**

`lostpart` finds filesystems that live on a disk but have **no partition
entry** in its partition table, and puts the missing entry back. It is the
tool you reach for when a partition disappeared after a repartition, a bad
`diskpart` run, an installer overwriting the MBR, or a disk whose partition
table was simply never written.

```
$ lostpart scan --device 0
device : \\.\PhysicalDrive0
table  : MBR
mode   : full
free   : 2 region(s), 931.4 GiB examined

  start   sectors       size  filesystem  conf  evidence
  1048576   4194304   2.0 GiB  ntfs         92%  boot sector + allocation bitmap

evidence:
  sector 1048576 (ntfs):
    - NTFS OEM identifier present
    - bytes_per_sector=512 (power of two, valid)
    - sectors_per_cluster=8
    - $MFT record 0 is readable
    - 1440/1440 clusters agree with the allocation bitmap (0 mismatches)
    - highest allocated cluster is 1439 of 524288
```

## Why it is trustworthy

A filesystem that happens to contain the bytes `NTFS    ` somewhere is not a
partition. `lostpart` does not trust signatures:

* **Every candidate is parsed.** The BIOS parameter block of the candidate is
  validated field by field — bytes per sector, sectors per cluster, cluster
  count, FAT layout, superblock geometry. A candidate that fails validation
  is discarded, and the reason is reported.
* **NTFS boundaries are proven with the allocation bitmap.** The `$Bitmap`
  meta-file of a volume says exactly which clusters are allocated. `lostpart`
  reads that bitmap and checks it against the actual bytes on the disk:
  clusters the bitmap calls *allocated* must contain data, clusters it calls
  *free* must be zeroed. This both confirms the start of the volume and
  determines where it ends — the highest allocated cluster. The sectors
  *before* the candidate are sampled too, to confirm they are foreign to the
  volume.
* **Every verdict carries its evidence.** The reasons behind a candidate are
  printed, so you can judge whether to trust it.

## Provenance

This is an independent, **clean-room** implementation written from the public
specifications of the on-disk formats:

| Format | Reference |
| --- | --- |
| MBR / protective MBR | IBM PC partition table layout |
| GPT | UEFI Specification 2.10, section 5 |
| NTFS | Microsoft [MS-FSCC] and the NTFS volume boot sector layout |
| exFAT | Microsoft exFAT file system specification |
| FAT12/16/32 | Microsoft [MS-FAT] specification |
| ext2/3/4 | Linux `Documentation/filesystems/ext2` |
| Linux swap | `Documentation/admin-guide/uses-of-swapon` |
| HFS+ | Apple TN1150, HFS Plus Volume Format |

No proprietary code was copied. The behaviour was studied from the outside —
by observing what a partition manager does to a disk — and then implemented
from the specifications.

## Install

```bash
pip install .
# or, for development
pip install -e ".[dev]"
```

Python 3.12 or newer. No third-party runtime dependencies.

## Usage

### List the disks

```bash
lostpart list
lostpart list --device 0
lostpart list --device /path/to/disk.img
```

### Scan for lost partitions

```bash
lostpart scan --device 0                  # full scan of the free space
lostpart scan --device 0 --mode quick      # faster, less thorough
lostpart scan --device 0 --json           # machine readable
lostpart scan --device 0 --checkpoint scan.db
```

The scan only looks at the **free space** between the known partitions, and
finds candidates by searching large blocks for filesystem signatures, then
validating each hit. Use `--checkpoint` to keep a SQLite checkpoint so an
interrupted scan can be resumed.

### Preview a candidate before writing anything

```bash
lostpart browse --device 0 --start 1048576
lostpart browse --device 0 --start 1048576 --path "Users/ana"
lostpart browse --device 0 --start 1048576 --json
```

`browse` parses the filesystem directly, so it works **without writing to
the disk** and without administrator privileges.

### Write the missing partition entry

```bash
# dry run: shows exactly what would change
lostpart recover --device 0 --start 1048576 --size 4194304 --fs ntfs

# write it, taking a backup first
lostpart recover --device 0 --start 1048576 --size 4194304 --fs ntfs --apply
```

Without `--apply` nothing is written. With it, the tool:

1. validates the candidate (it must not overlap an existing partition and
   must fit on the disk);
2. writes a backup of the partition table structures to
   `lostpart-backups/` (disable with `--no-backup`);
3. writes the entry — into a free primary MBR slot, into an extended boot
   record chain, or into a free GPT slot, keeping both GPT copies and their
   CRCs consistent.

### Back up and restore the partition table

```bash
lostpart backup --device 0 --output mbr-backup.json
lostpart restore --device 0 --backup mbr-backup.json
```

The backup is plain JSON with base64 payloads, so it can be inspected and
restored with standard tools.

## Supported filesystems

| Filesystem | Detection | Boundary proof | Browsing |
| --- | --- | --- | --- |
| NTFS | boot sector + BPB | `$Bitmap` matched against the disk, `$MFT` cross-check | yes |
| exFAT | boot sector + VBR validation | volume length from the VBR | yes |
| FAT12/16/32 | BPB geometry + type string | cluster count from the BPB | yes |
| ext2/3/4 | superblock magic + geometry | block count from the superblock | yes |
| Linux swap | swap header magic and version | cluster count from the header | n/a (no directory tree) |
| HFS+ | volume header signature, version, magic | block count from the header | best effort |

## Platform support

| | Windows | Linux |
| --- | --- | --- |
| Raw device access | `\\.\PhysicalDriveN` with `DeviceIoControl` | `/dev/sdX` with `ioctl` |
| Sector size detection | `IOCTL_DISK_GET_DRIVE_GEOMETRY_EX` | `BLKSSZGET` |
| Native mounting | drive letter assignment | loop mount with an offset |

Both 512e (Advanced Format) and 4Kn drives are handled: the logical sector
size reported by the device is used throughout, while the filesystem's own
byte-per-sector is used for the internal cluster arithmetic.

Disk images (`.img`, `.dd`, …) can be used everywhere a physical disk can,
which is handy for testing and for offline analysis.

## Safety

* **Nothing is written without `--apply`.** `recover` and `scan` open the
  device read-only.
* **A backup is taken before every write.**
* **Writes are validated first** — overlapping or out-of-range candidates are
  rejected.
* **The GPT is kept consistent**: both entry arrays, both headers and all
  CRCs are rewritten together.

Raw disk access needs elevated privileges on Windows (run as administrator)
and root on Linux.

## Project layout

```
lostpart/
├── constants.py       on-disk constants, per format
├── device.py          raw device access (Windows, Linux, image files)
├── errors.py          exception hierarchy
├── cli.py             command line interface
├── fs/                filesystem probes and read-only readers
│   ├── base.py        the probe/reader contract
│   ├── ntfs.py        NTFS boot sector, $MFT, runlists
│   ├── exfat.py       exFAT
│   ├── fat.py         FAT12/16/32
│   ├── ext.py         ext2/3/4
│   ├── swap.py        Linux swap
│   ├── hfsplus.py     HFS+
│   └── registry.py    probe dispatch
├── tables/            partition table parsing and building
│   ├── mbr.py         MBR and the EBR chain
│   ├── gpt.py         GPT, GUIDs, CRC32
│   └── table.py       unified table view
├── scan/              finding lost partitions
│   ├── unallocated.py free space computation
│   ├── scanner.py     the scan itself
│   ├── bitmap_match.py  NTFS allocation bitmap proof
│   ├── checkpoint.py  resumable SQLite checkpoints
│   └── model.py       candidate and result records
├── recover/           writing the entry back
│   ├── writer.py      MBR and GPT entry writing
│   └── backup.py      backup and restore
└── browse/            previewing a recovered partition
    └── lister.py      internal and native browsing
```

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

The test suite builds synthetic disk images — MBR sectors, GPT disks with
both copies, and a complete NTFS volume with a real `$MFT` and `$Bitmap` —
and exercises the scanner, the bitmap matcher and the writers against them.
No physical disk is ever touched by the tests.

## License

MIT — see [LICENSE](LICENSE).
