const rendered = (value: string) => value.normalize('NFKC').toLowerCase().replace(/\s+/g, '')

/** A chunk ID is a hint, never a substitute for the actual selected text.
 * Cross-block ranges are resolved by the server using the page and full text.
 */
export function selectionChunk<T extends { content: string; page: number | null }>(chunks: T[], text: string, page?: number) {
  const query = rendered(text)
  if (!query) return undefined
  return chunks.find(chunk => (page === undefined || chunk.page === page) && rendered(chunk.content).includes(query))
}
