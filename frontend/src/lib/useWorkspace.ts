import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from './api'
import type { Collection, Paper } from '../types'
export function useWorkspace() {
  const [papers, setPapers] = useState<Paper[]>([])
  const [collections, setCollections] = useState<Collection[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const reload = useCallback(async () => {
    setError('')
    try { const [p, c] = await Promise.all([api.papers(), api.collections()]); setPapers(p.items); setCollections(c.items) }
    catch (e) { setError(errorMessage(e)) } finally { setLoading(false) }
  }, [])
  useEffect(() => { void reload() }, [reload])
  return {papers, collections, loading, error, reload}
}
export type Workspace = ReturnType<typeof useWorkspace>
