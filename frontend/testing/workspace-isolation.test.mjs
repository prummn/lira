import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import setup from '../playwright.config.ts'
import { verifyIsolatedWorkspace } from './isolated-backend.mjs'

test('browser tests require an isolation check before any tests execute', () => {
  assert.ok(setup.globalSetup, 'A working health endpoint alone must not authorize test imports')
})

test('only a disposable backend with this run identity authorizes tests, using read-only requests', async () => {
  const identity = { marker:'RIW_E2E_ISOLATED_V1',token:'test-run',database_is_temporary:true,storage_is_temporary:true }
  let status = 200, body = identity
  const requests = []
  const server = createServer((request, response) => {
    requests.push({ method:request.method,path:request.url })
    response.writeHead(status, { 'Content-Type':'application/json' })
    response.end(JSON.stringify(body))
  })
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve))
  const url = 'http://127.0.0.1:' + server.address().port
  try {
    await verifyIsolatedWorkspace(url,'test-run')
    for (const invalid of [
      { status:'ok' },
      { ...identity,token:'previous-run' },
      { ...identity,database_is_temporary:false },
      { ...identity,storage_is_temporary:false },
    ]) {
      body = invalid
      await assert.rejects(() => verifyIsolatedWorkspace(url,'test-run'), /Refusing to run browser tests/)
    }
    status = 404
    await assert.rejects(() => verifyIsolatedWorkspace(url,'test-run'), /Refusing to run browser tests/)
    const before = requests.length
    await assert.rejects(() => verifyIsolatedWorkspace(url,''), /Missing E2E isolation token/)
    await assert.rejects(() => verifyIsolatedWorkspace('https://example.com','test-run'), /must be local/)
    assert.equal(requests.length,before)
    assert.ok(requests.every(request => request.method==='GET' && request.path==='/api/e2e/identity'))
  } finally {
    await new Promise(resolve => server.close(resolve))
  }
})
