import type { LibraryEntryOut, LibraryOut } from '../api/types'

/** The bench release of dm17ryk/openwrt, as the image library lists it for the DWR-921 C3 (U-Boot). */
export const libraryEntry: LibraryEntryOut = {
  sha256: 'd340a53f2de057a8d1d703239a22e9bd24b834dcd9a0e7397bf80861ff25cc10',
  boards: ['dlink,dwr-921-c3-uboot'],
  board: 'dlink,dwr-921-c3-uboot',
  revision: 'r35692-b8bffeefdf',
  target: 'ramips/mt7620',
  title: 'D-Link DWR-921 C3 (U-Boot)',
  image_name: 'openwrt-ramips-mt7620-dlink_dwr-921-c3-uboot-squashfs-sysupgrade.bin',
  size: 11272478,
  url: 'https://github.com/dm17ryk/openwrt/releases/download/DWR_921-c3-uboot-qmifix3/image.bin',
  release_tag: 'DWR_921-c3-uboot-qmifix3',
  release_name: 'DWR_921-c3-uboot-qmifix3',
  release_url: 'https://github.com/dm17ryk/openwrt/releases/tag/DWR_921-c3-uboot-qmifix3',
  published_at: '2026-11-05T10:00:00Z',
  prerelease: false,
  imported: false,
}

export const libraryFixture: LibraryOut = { entries: [libraryEntry], read_at: '2026-11-16T09:00:00', skipped: 0, error: null }
