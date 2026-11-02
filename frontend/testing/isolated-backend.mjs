const marker = 'RIW_E2E_ISOLATED_V1'

/** Fail closed before any browser test can import papers or change settings. */
export async function verifyIsolatedWorkspace(baseURL, expectedToken) {
  if (!expectedToken) throw new Error('Missing E2E isolation token; refusing to run browser tests')
  const url = new URL('/api/e2e/identity', baseURL)
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) throw new Error('E2E services must be local')
  let identity
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(5000), redirect: 'error' })
    if (!response.ok) throw new Error('Missing isolated backend identity')
    identity = await response.json()
  } catch (error) {
    throw new Error('Refusing to run browser tests: the target does not identify as a disposable E2E workspace', { cause: error })
  }
  if (identity?.marker !== marker || identity?.token !== expectedToken || identity?.database_is_temporary !== true || identity?.storage_is_temporary !== true) {
    throw new Error('Refusing to run browser tests: backend identity does not match this isolated test run')
  }
}

export default async function globalSetup(config) {
  const token = process.env.RIW_E2E_TOKEN
  await verifyIsolatedWorkspace('http://127.0.0.1:8010', token)
  for (const project of config.projects) {
    if (!project.use.baseURL) throw new Error('Browser tests require an explicit isolated baseURL')
    await verifyIsolatedWorkspace(project.use.baseURL, token)
  }
}
