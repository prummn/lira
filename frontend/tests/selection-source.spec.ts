import { expect, test } from '@playwright/test'
import { selectionChunk } from '../src/lib/selectionSource'

const chunks = [
  { id: 'header', page: 26, content: 'Agentic Reasoning for Large Language Models' },
  { id: 'memory', page: 26, content: 'Amem [24] builds context-\naware memory representations, such as Mem-α [315].' },
]

test('rendered citation spacing and Greek names locate the real chunk instead of the page header', () => {
  expect(selectionChunk(chunks, 'Amem [ 24 ] builds context- aware memory representations, such as Mem- α [ 315 ].', 26)?.id).toBe('memory')
})

test('a cross-block selection sends its page without inventing a chunk anchor', () => {
  expect(selectionChunk(chunks, chunks[0].content+' '+chunks[1].content, 26)).toBeUndefined()
})

test('selection anchors preserve Greek variables and respect the selected page', () => {
  expect(selectionChunk(chunks, 'Mem-β [315]', 26)).toBeUndefined()
  expect(selectionChunk(chunks, 'Mem-α [315]', 25)).toBeUndefined()
})
