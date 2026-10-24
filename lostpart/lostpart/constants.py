"""Constants shared across :mod:`lostpart`.

All on-disk constants are documented in the relevant public specifications:

* MBR / protective MBR -- IBM PC / Microsoft partition table layout.
* GPT -- UEFI Specification 2.10, section 5 (partition table structures).
* NTFS -- Microsoft [MS-FSCC] and the NTFS volume boot sector layout.
* exFAT -- Microsoft exFAT file system specification.
* FAT -- Microsoft [MS-FAT] specification.
* ext2/3/4 -- Linux `Documentation/filesystems/ext2` and the on-disk superblock.
* Linux swap -- `Documentation/admin-guide/uses-of-swapon`.
* HFS+ -- Apple Technical QA / TN1150 HFS Plus Volume Format.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Generic geometry
# --------------------------------------------------------------------------

DEFAULT_SECTOR_SIZE = 512

#: Sector sizes that may legally appear in a BIOS Parameter Block.
VALID_BYTES_PER_SECTOR = (512, 1024, 2048, 4096)

#: Sector counts that may legally appear in a BIOS Parameter Block.
VALID_SECTORS_PER_CLUSTER = (
    1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768,
)

#: The MBR lives at LBA 0, the primary GPT header at LBA 1 and the primary
#: GPT entry array at LBA 2.
MBR_LBA = 0
GPT_HEADER_LBA = 1
GPT_ENTRY_ARRAY_LBA = 2

GPT_SIGNATURE = b"EFI PART"
MBR_BOOT_SIGNATURE = b"\x55\xaa"

#: Size of a single GPT partition entry.
GPT_ENTRY_SIZE = 128
#: Number of entries in the default Microsoft GPT layout.
GPT_DEFAULT_ENTRY_COUNT = 128

#: Maximum number of primary MBR partitions.
MBR_MAX_PRIMARY = 4
#: Extended boot record (logical partition descriptor) type byte.
MBR_TYPE_EXTENDED = 0x05
#: Extended boot record type used by Windows for the "extended" container.
MBR_TYPE_EXTENDED_WIN = 0x0F

# --------------------------------------------------------------------------
# MBR partition type bytes (well-known subset)
# --------------------------------------------------------------------------

MBR_TYPE_EMPTY = 0x00
MBR_TYPE_FAT12 = 0x01
MBR_TYPE_FAT16_SMALL = 0x04
MBR_TYPE_FAT16 = 0x06
MBR_TYPE_NTFS = 0x07
MBR_TYPE_FAT32 = 0x0B
MBR_TYPE_FAT32_LBA = 0x0C
MBR_TYPE_HFS = 0x0A
MBR_TYPE_HFS_PLUS = 0x0A
MBR_TYPE_LINUX_SWAP = 0x82
MBR_TYPE_LINUX = 0x83
MBR_TYPE_LINUX_EXTENDED = 0x85
MBR_TYPE_LVM = 0x8E
MBR_TYPE_LDM = 0x42
MBR_TYPE_GPT_PROTECTIVE = 0xEE
MBR_TYPE_IBM_FAT32 = 0x0C

#: Mapping of MBR type byte -> human readable label.
MBR_TYPE_LABELS: dict[int, str] = {
    0x01: "FAT12",
    0x04: "FAT16 <32M",
    0x06: "FAT16",
    0x07: "NTFS / exFAT / HPFS",
    0x0A: "HFS / HFS+",
    0x0B: "FAT32",
    0x0C: "FAT32 (LBA)",
    0x0E: "FAT16 (LBA)",
    0x0F: "Extended (LBA)",
    0x11: "Hidden FAT12",
    0x12: "Compaq diagnostics",
    0x14: "Hidden FAT16 <32M",
    0x16: "Hidden FAT16",
    0x17: "Hidden NTFS",
    0x1B: "Hidden FAT32",
    0x1C: "Hidden FAT32 (LBA)",
    0x42: "Windows Dynamic Disk (LDM)",
    0x82: "Linux swap",
    0x83: "Linux",
    0x85: "Linux extended",
    0x8E: "Linux LVM",
    0xEE: "GPT protective",
    0xEF: "EFI system partition",
    0xFD: "Linux RAID",
}

# --------------------------------------------------------------------------
# GPT partition type GUIDs
# --------------------------------------------------------------------------

GPT_TYPE_BASIC_DATA = "{EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}"
GPT_TYPE_EFI_SYSTEM = "{C12A7328-F81F-11D2-BA4B-00A0C93EC93B}"
GPT_TYPE_EFI_MSP = "{E3C9E316-0B5C-4DB8-817D-F92DF00215AE}"
GPT_TYPE_MS_BASIC = "{EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}"
GPT_TYPE_MS_RESERVED = "{E3C9E316-0B5C-4DB8-817D-F92DF00215AE}"
GPT_TYPE_LINUX_SWAP = "{0657FD6D-A4AB-43C4-84E5-0933C84B4F4F}"
GPT_TYPE_LINUX_FILESYSTEM = "{0FC63DAF-8483-4772-8E79-3D69D8477DE4}"
GPT_TYPE_LINUX_LVM = "{E6D6D379-F507-44C2-A23C-238F2A3DF928}"
GPT_TYPE_LINUX_RAID = "{A19D880F-05FC-4D3B-A006-743F0F84911E}"
GPT_TYPE_APPLE_HFS = "{48465300-0000-11AA-AA11-00306543ECAC}"
GPT_TYPE_APPLE_HFS_CASE = "{55465300-0000-11AA-AA11-00306543ECAC}"
GPT_TYPE_APPLE_EFI = "{7C3457EF-0000-11AA-AA11-00306543ECAC}"
GPT_TYPE_UEFI = "{C12A7328-F81F-11D2-BA4B-00A0C93EC93B}"

#: The all-zero GUID, used by an unused GPT partition entry.
GPT_TYPE_EMPTY = "{00000000-0000-0000-0000-000000000000}"

#: Human readable labels for the GPT type GUIDs we recognise.
GPT_TYPE_LABELS: dict[str, str] = {
    GPT_TYPE_BASIC_DATA: "Basic data partition",
    GPT_TYPE_EFI_SYSTEM: "EFI system partition",
    GPT_TYPE_EFI_MSP: "Microsoft reserved partition",
    GPT_TYPE_LINUX_SWAP: "Linux swap",
    GPT_TYPE_LINUX_FILESYSTEM: "Linux filesystem",
    GPT_TYPE_LINUX_LVM: "Linux LVM",
    GPT_TYPE_LINUX_RAID: "Linux RAID",
    GPT_TYPE_APPLE_HFS: "Apple HFS+",
    GPT_TYPE_APPLE_HFS_CASE: "Apple HFS+ (case-sensitive)",
    GPT_TYPE_APPLE_EFI: "Apple UEFI",
}

#: Default GUID used when a recovered GPT entry must be given a fresh type.
GPT_TYPE_LINUX_BY_FS: dict[str, str] = {
    "ntfs": GPT_TYPE_BASIC_DATA,
    "exfat": GPT_TYPE_BASIC_DATA,
    "fat32": GPT_TYPE_BASIC_DATA,
    "fat16": GPT_TYPE_BASIC_DATA,
    "fat12": GPT_TYPE_BASIC_DATA,
    "ext2": GPT_TYPE_LINUX_FILESYSTEM,
    "ext3": GPT_TYPE_LINUX_FILESYSTEM,
    "ext4": GPT_TYPE_LINUX_FILESYSTEM,
    "swap": GPT_TYPE_LINUX_SWAP,
    "hfsplus": GPT_TYPE_APPLE_HFS,
}

# --------------------------------------------------------------------------
# NTFS
# --------------------------------------------------------------------------

NTFS_OEM_ID = b"NTFS    "
NTFS_BOOT_SECTOR_SIZE = 512

#: Byte offset of the NTFS volume boot sector inside the partition.
NTFS_VBR_OFFSET = 0
#: Byte offset of the backup boot sector (16 sectors into the volume).
NTFS_BACKUP_VBR_SECTOR = 16

#: Byte offsets inside the NTFS volume boot sector.
NTFS_OFF_OEM = 0x03
NTFS_OFF_BYTES_PER_SECTOR = 0x0B
NTFS_OFF_SECTORS_PER_CLUSTER = 0x0D
NTFS_OFF_TOTAL_SECTORS = 0x28
NTFS_OFF_MFT_LCN = 0x30
NTFS_OFF_MFTMIRR_LCN = 0x38
NTFS_OFF_CLUSTER_PER_FILE_RECORD = 0x40
NTFS_OFF_VOLUME_SERIAL = 0x48
NTFS_OFF_BOOT_SIGNATURE = 0x1FE

#: ``$Bitmap`` and ``$MFT`` are the two meta-files that matter for boundary
#: detection: the first describes cluster allocation, the second anchors the
#: volume structure.
NTFS_BITMAP_FILENAME = "$Bitmap"
NTFS_MFT_FILENAME = "$MFT"

# --------------------------------------------------------------------------
# exFAT
# --------------------------------------------------------------------------

EXFAT_OEM_ID = b"EXFAT   "
EXFAT_BOOT_SECTOR_SIZE = 512

EXFAT_OFF_OEM = 0x03
EXFAT_OFF_VOLUME_LENGTH = 0x48
EXFAT_OFF_FAT_OFFSET = 0x50
EXFAT_OFF_FAT_LENGTH = 0x54
EXFAT_OFF_CLUSTER_HEAP_OFFSET = 0x58
EXFAT_OFF_CLUSTER_COUNT = 0x5C
EXFAT_OFF_ROOT_DIR_CLUSTER = 0x60
EXFAT_OFF_VOLUME_SERIAL = 0x64
EXFAT_OFF_BYTES_PER_SECTOR_SHIFT = 0x6C
EXFAT_OFF_SECTORS_PER_CLUSTER_SHIFT = 0x6D
EXFAT_OFF_BOOT_SIGNATURE = 0x1FE

# --------------------------------------------------------------------------
# FAT
# --------------------------------------------------------------------------

FAT32_SIGNATURE = b"FAT32   "
FAT16_SIGNATURE = b"FAT16   "
FAT12_SIGNATURE = b"FAT12   "

FAT_OFF_OEM = 0x03
FAT_OFF_BYTES_PER_SECTOR = 0x0B
FAT_OFF_SECTORS_PER_CLUSTER = 0x0D
FAT_OFF_RESERVED_SECTORS = 0x0E
FAT_OFF_NUM_FATS = 0x10
FAT_OFF_ROOT_ENTRIES = 0x11
FAT_OFF_TOTAL_SECTORS_16 = 0x13
FAT_OFF_FAT_SIZE_16 = 0x16
FAT_OFF_TOTAL_SECTORS_32 = 0x20
FAT_OFF_FAT_SIZE_32 = 0x24
FAT_OFF_ROOT_CLUSTER_32 = 0x2C
FAT_OFF_FSINFO = 0x30
FAT_OFF_BOOT_SECTOR_BACKUP = 0x32
FAT_OFF_EXTENDED_BOOT_SIGNATURE = 0x28
FAT_OFF_VOLUME_ID = 0x40
FAT_OFF_VOLUME_LABEL = 0x44
FAT_OFF_FS_TYPE = 0x4F
FAT_OFF_BOOT_SIGNATURE = 0x1FE

#: FAT12/FAT16 store the file system type string at a different offset than
#: FAT32 does.
FAT16_OFF_VOLUME_ID = 0x27
FAT16_OFF_VOLUME_LABEL = 0x2B
FAT16_OFF_FS_TYPE = 0x36

# --------------------------------------------------------------------------
# ext2/3/4
# --------------------------------------------------------------------------

EXT_SUPERBLOCK_OFFSET = 0x400  # 1024 bytes into the partition
EXT_SUPERBLOCK_MAGIC = 0xEF53
EXT_ROOT_INODE = 2

EXT_OFF_INODES_COUNT = 0x00
EXT_OFF_BLOCKS_COUNT = 0x04
EXT_OFF_FIRST_DATA_BLOCK = 0x14
EXT_OFF_LOG_BLOCK_SIZE = 0x18
EXT_OFF_BLOCKS_PER_GROUP = 0x20
EXT_OFF_INODES_PER_GROUP = 0x28
EXT_OFF_MAGIC = 0x38
EXT_OFF_STATE = 0x3A
EXT_OFF_FEATURE_COMPAT = 0x5C
EXT_OFF_FEATURE_INCOMPAT = 0x60
EXT_OFF_FEATURE_RO_COMPAT = 0x64
EXT_OFF_UUID = 0x68
EXT_OFF_VOLUME_NAME = 0x78
EXT_OFF_LAST_MOUNTED = 0x88
EXT_OFF_FEATURE_INCOMPAT_EXTENTS = 0x40
EXT_OFF_FEATURE_INCOMPAT_64BIT = 0x80
EXT_OFF_FEATURE_RO_COMPAT_HUGE = 0x08
EXT_OFF_FEATURE_RO_COMPAT_GDT_CSUM = 0x10
EXT_OFF_FEATURE_RO_COMPAT_DIR_NLINK = 0x20
EXT_OFF_FEATURE_RO_COMPAT_METADATA_CSUM = 0x400
EXT_OFF_FEATURE_COMPAT_HAS_JOURNAL = 0x04

EXT_FEATURE_INCOMPAT_EXTENTS = 0x40
EXT_FEATURE_INCOMPAT_64BIT = 0x80
EXT_FEATURE_COMPAT_HAS_JOURNAL = 0x04

#: ext inode mode bits we care about.
EXT_S_IFMT = 0xF000
EXT_S_IFDIR = 0x4000
EXT_S_IFREG = 0x8000
EXT_S_IFLNK = 0xA000

# --------------------------------------------------------------------------
# Linux swap
# --------------------------------------------------------------------------

SWAP_MAGIC_1 = 0x5A6D7368  # "hsmZ" little endian -> "SWAPSPACE2"
SWAP_MAGIC_2 = 0x53415748  # "SWAP-SPACE"
SWAP_VERSION_1 = 1
SWAP_VERSION_2 = 2

#: The kernel places ``struct swap_header_s`` (68 bytes) at the very end of
#: the first 4096 byte page, so the magic lives at offset 4028.
SWAP_HEADER_OFFSET = 4096 - 68
SWAP_MAGIC_OFFSET = 4096 - 68
#: Some tools look for the magic at the end of the 10 byte "SWAPSPACE2"
#: signature instead; both locations are checked.
SWAP_MAGIC_ALT_OFFSET = 4086
SWAP_SIGNATURE = b"SWAPSPACE2"
SWAP_HEADER_SIZE = 68

SWAP_OFF_MAGIC = 0x00
SWAP_OFF_VERSION = 0x04
SWAP_OFF_LAST_PAGE = 0x08
SWAP_OFF_NR_CLUSTERS = 0x0C
SWAP_OFF_PAGE_SIZE = 0x10
SWAP_OFF_FLAGS = 0x14
SWAP_OFF_VOLUME_LABEL = 0x24
SWAP_OFF_UUID = 0x34

# --------------------------------------------------------------------------
# HFS+
# --------------------------------------------------------------------------

HFSPLUS_SIGNATURE = b"H+"        # at offset 1024
HFSPLUS_SIGNATURE_OFFSET = 1024
#: TN1150 places the UInt16 version at offset 2 of the volume header, which
#: is absolute offset 1026 -- not 1025, which is the last byte of the
#: two byte signature.
HFSPLUS_VERSION_OFFSET = 1026
HFSPLUS_BLOCK_SIZE_OFFSET = 1024 + 40
HFSPLUS_TOTAL_BLOCKS_OFFSET = 1024 + 44
HFSPLUS_MAGIC_OFFSET = 1024 + 1028  # HFSPLUS_MAGIC = 0x482B

HFSPLUS_MAGIC = 0x482B
HFSPLUS_VERSION_4 = 4
HFSPLUS_VERSION_5 = 5
