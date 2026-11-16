export function megabytes(size: number | null): string {
  return size === null ? '' : `${(size / 2 ** 20).toFixed(1)} MB`
}
