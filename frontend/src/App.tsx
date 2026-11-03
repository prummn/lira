import { useEffect, useRef, useState } from 'react'
import { BookOpen, Check, FileText, Folder, Library, MessageSquare, Moon, Network, Plus, Search, Settings, Sun, Users } from 'lucide-react'
import { api, errorMessage } from './lib/api'
import { UiProvider, useUi } from './lib/i18n'
import { useWorkspace } from './lib/useWorkspace'
import { Empty, ErrorBanner, Loading, Modal } from './components/Shared'
import { LibraryPage } from './pages/LibraryPage'
import { ReaderPage } from './pages/ReaderPage'
import { KnowledgePage } from './pages/KnowledgePage'
import { ResearchersPage } from './pages/ResearchersPage'
import { SettingsPage } from './pages/SettingsPage'
import { LibrarianPage } from './pages/LibrarianPage'
import { BrandMark } from './components/BrandMark'
import { CollectionResearch, ResearchStatusButton } from './components/CollectionResearch'
import { BackgroundTasksPage } from './pages/BackgroundTasksPage'
import { useBackgroundStatus } from './lib/useBackgroundStatus'
import { analysisTasksFromPapers } from './lib/intelligence'
import type { LibrarianThread, NotebookTab, Page } from './types'
import type { PdfLocator } from './components/PdfViewer'
import './styles.css'
import './intelligence.css'

const navigation = [ {id:'library',icon:Library}, {id:'reader',icon:BookOpen}, {id:'librarian',icon:MessageSquare}, {id:'knowledge',icon:Network}, {id:'researchers',icon:Users}, {id:'settings',icon:Settings} ] as const
function WorkspaceApp() {
  const {t, theme, setTheme} = useUi()
  const workspace = useWorkspace()
  const background=useBackgroundStatus()
  const backgroundStatus=background.status&&{...background.status,analysis_tasks:background.status.analysis_tasks??analysisTasksFromPapers(workspace.papers)}
  const [page, setPage] = useState<Page>('library')
  const [collectionId, setCollectionId] = useState('')
  const [initialLocator,setInitialLocator] = useState<PdfLocator|null>(null)
  const [initialNotebookTab,setInitialNotebookTab]=useState<NotebookTab>('overview')
  const [readerOrigin,setReaderOrigin]=useState<'library'|'librarian'|'research'|'background'>('library')
  const [thread,setThread]=useState<LibrarianThread>(()=>{
    try{const saved=JSON.parse(localStorage.getItem('riw-librarian-scope')??'{}');return {scope:typeof saved.scope==='string'?saved.scope:'',selectedIds:Array.isArray(saved.selectedIds)?saved.selectedIds.filter((id:unknown)=>typeof id==='string'):[],turns:[]}}
    catch{return {scope:'',selectedIds:[],turns:[]}}
  })
  useEffect(()=>{try{localStorage.setItem('riw-librarian-scope',JSON.stringify({scope:thread.scope,selectedIds:thread.selectedIds}))}catch{/* Conversation content is saved by the backend. */}},[thread.scope,thread.selectedIds])
  const [paperId, setPaperId] = useState(() => localStorage.getItem('riw-last-paper') ?? '')
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [collectionColor, setCollectionColor] = useState('#536f89')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [toast, setToast] = useState('')
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()
  const searchRef = useRef<HTMLInputElement>(null)
  const notify = (message: string) => { setToast(message); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(''), 4000) }
  const openPaper = (id: string, locator?:PdfLocator, tab:NotebookTab='overview') => { setReaderOrigin(page==='librarian'?'librarian':page==='research'?'research':page==='background'?'background':'library');setInitialLocator(locator??null);setInitialNotebookTab(tab); setPaperId(id); localStorage.setItem('riw-last-paper', id); setPage('reader') }
  const presenceId=useRef(`lira-${crypto.randomUUID()}`)
  useEffect(()=>{
    const report=()=>{void api.readingPresence(presenceId.current,(page==='reader'||page==='librarian')&&document.visibilityState==='visible').catch(()=>{})}
    report();const timer=setInterval(report,20000);document.addEventListener('visibilitychange',report)
    return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',report);void api.readingPresence(presenceId.current,false).catch(()=>{})}
  },[page])
  const openResearch=(view:'essay'|'findings'='essay')=>{sessionStorage.setItem(`lira-research-view-${collectionId}`,view);setPage('research')}
  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setPage('library'); searchRef.current?.focus() } }
    window.addEventListener('keydown', handler); return () => { window.removeEventListener('keydown', handler); clearTimeout(toastTimer.current) }
  }, [])
  const canCreateCollection = page === 'library' && !collectionId
  const openCreateCollection = () => { if(canCreateCollection) {setFormError('');setCreating(true)} }
  const collectionDeleted = (id:string) => {
    setCollectionId('');setPage('library');setQuery('')
    setThread(current=>current.scope===id?{scope:'',selectedIds:[],turns:[]}:current)
  }
  const createCollection = async () => {
    if(!canCreateCollection || !name.trim() || busy) return
    setBusy(true); setFormError('')
    try { const created = await api.createCollection(name.trim(), description.trim(), collectionColor); await workspace.reload(); setCollectionId(created.id); setCreating(false); setName(''); setDescription(''); setCollectionColor('#536f89'); setPage('library'); notify(t('saved')) }
    catch (error) { setFormError(errorMessage(error)) } finally { setBusy(false) }
  }
  return <div className={'app-shell ' + (page === 'reader' ? 'reader-active' : '')}>
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark"><BrandMark/></span><div><strong>{t('brand')}</strong><small>{t('brandCaption')}</small></div></div>
      <div className="workspace-label"><span className="workspace-dot"/>{t('workspace')}</div>
      <nav className="primary-nav" aria-label={t('workspace')}>{navigation.map(item => <button key={item.id} aria-label={t(item.id)} className={'nav-item ' + (page === item.id ? 'active' : '')} onClick={() => setPage(item.id)}><item.icon size={17}/><span>{t(item.id)}</span>{item.id === 'library' && <small>{workspace.papers.length}</small>}</button>)}</nav>
      <div className="sidebar-section-header"><span>{t('collections')}</span>{canCreateCollection && <button className="icon-btn" aria-label={t('newCollection')} onClick={openCreateCollection}><Plus size={16}/></button>}</div>
      <nav className="collection-nav" aria-label={t('collections')}><button aria-label={t('allPapers')} className={'collection-item ' + (!collectionId ? 'active' : '')} onClick={() => {setCollectionId(''); setPage('library')}}><Folder size={14}/><span>{t('allPapers')}</span><small>{workspace.papers.length}</small></button>{workspace.collections.map(item => <button key={item.id} aria-label={item.name} className={'collection-item ' + (collectionId === item.id ? 'active' : '')} onClick={() => {setCollectionId(item.id); setPage('library')}}><span className="collection-dot" style={{background:item.color}}/><span>{item.name}</span><small>{item.paper_count}</small></button>)}</nav>
      <ResearchStatusButton status={backgroundStatus} error={background.error} open={()=>setPage('background')}/>
      <div className="sidebar-foot"><div><span className="sync-dot"/>{t('local')}</div><small>{t('localHint')}</small></div>
    </aside>
    <main className="main-shell">
      <header className="topbar"><div className="breadcrumbs"><span>{t('workspace')}</span><span>/</span><strong>{t(page)}</strong></div><div className="topbar-actions"><label className="command-search"><Search size={15}/><input ref={searchRef} aria-label={t('search')} value={query} onFocus={() => setPage('library')} onChange={e => {setQuery(e.target.value); setPage('library')}} placeholder={t('search')}/><kbd>Ctrl K</kbd></label><button className="icon-btn" aria-label={t('theme')} onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? <Sun size={18}/> : <Moon size={18}/>}</button></div></header>
      <div key={page} className={'page-wrap page-transition ' + (page === 'reader' ? 'reader-wrap' : page === 'librarian' ? 'librarian-wrap' : '')}>
        {page === 'background' ? <BackgroundTasksPage status={backgroundStatus} error={background.error} refresh={background.refresh} openPaper={openPaper} collections={workspace.collections} cancelAnalysis={workspace.cancelAnalysis} queueAnalysis={workspace.queueAnalysis} reloadWorkspace={workspace.reload} openResearch={id=>{setCollectionId(id);setPage('research')}}/> : workspace.loading ? <Loading text={t('loading')}/> : workspace.error ? <div className="connect-state"><Empty title={t('connectTitle')} text={t('connectHint')}/><ErrorBanner error={workspace.error} retry={() => void workspace.reload()}/></div> : <>
          {page === 'library' && <LibraryPage workspace={workspace} collectionId={collectionId} query={query} setQuery={setQuery} openPaper={openPaper} newCollection={openCreateCollection} collectionDeleted={collectionDeleted} notify={notify} openResearch={openResearch}/>}
          {page === 'research' && (workspace.collections.find(c=>c.id===collectionId)?<CollectionResearch key={collectionId} collection={workspace.collections.find(c=>c.id===collectionId)!} back={()=>setPage('library')} openPaper={openPaper} openSettings={()=>setPage('settings')} notify={notify}/>:<Empty title="先选择一个专题" text="专题文章从一组你关心的论文开始。">{canCreateCollection&&<button className="btn secondary" onClick={openCreateCollection}>{t('newCollection')}</button>}</Empty>)}
          {page === 'reader' && (paperId ? <ReaderPage openPaper={openPaper} key={paperId} paperId={paperId} initialLocator={initialLocator} initialTab={initialNotebookTab} collections={workspace.collections} reloadWorkspace={workspace.reload} workspace={workspace} backLabel={readerOrigin==='background'?t('backgroundBack'):readerOrigin==='librarian'?t('backLibrarian'):readerOrigin==='research'?(sessionStorage.getItem(`lira-research-view-${collectionId}`)==='findings'?'返回研究线索':'返回专题文章'):t('back')} back={() => setPage(readerOrigin)} notify={notify}/> : <Empty title={t('noPdf')} text={t('emptyHint')}><button className="btn secondary" onClick={() => setPage('library')}><FileText size={16}/>{t('back')}</button></Empty>)}
          {page === 'librarian' && <LibrarianPage workspace={workspace} thread={thread} setThread={setThread} openPaper={openPaper} openSettings={() => setPage('settings')}/>}
          {page === 'knowledge' && <KnowledgePage workspace={workspace} collectionId={collectionId} setCollectionId={setCollectionId} openPaper={openPaper}/>}
          {page === 'researchers' && <ResearchersPage workspace={workspace} openPaper={openPaper}/>}
          {page === 'settings' && <SettingsPage workspace={workspace}/>}
        </>}
      </div>
    </main>
    {toast && <div className="toast" role="status"><Check size={16}/>{toast}</div>}
    {creating && canCreateCollection && <Modal title={t('newCollection')} close={() => !busy && setCreating(false)}><form onSubmit={event => {event.preventDefault(); void createCollection()}}><label>{t('name')}<input autoFocus required maxLength={200} aria-label={t('name')} value={name} onChange={e => setName(e.target.value)} placeholder={t('collectionNameHint')}/></label><label>{t('description')}<textarea value={description} onChange={e => setDescription(e.target.value)} placeholder={t('collectionDescriptionHint')}/></label><label>{t('collectionColor')}<div className="collection-color-control"><span className="collection-color-brush" style={{color:collectionColor}}><svg viewBox="0 0 160 48" aria-hidden="true"><path fill="currentColor" d="M3 38C14 33 26 28 39 24L32 22 34 19C54 12 83 9 108 8 115 8 120 9 122 11L137 12 146 15 132 16C142 16 149 19 151 22L157 25 157 28 137 27C119 26 103 29 86 33L69 38Q65 39 62 36L58 35 53 37Q50 38 47 35L22 43Q18 44 16 41L15 39 5 41Z"/></svg><input type="color" aria-label={t('collectionColor')} value={collectionColor} disabled={busy} onChange={e=>setCollectionColor(e.target.value)}/></span><span>{t('collectionColorHint')}</span></div></label>{formError && <ErrorBanner error={formError}/>}<div className="modal-actions"><button className="btn secondary" type="button" onClick={() => setCreating(false)} disabled={busy}>{t('cancel')}</button><button className="btn primary" disabled={busy || !name.trim()}>{t('create')}</button></div></form></Modal>}
  </div>
}
export default function App() { return <UiProvider><WorkspaceApp/></UiProvider> }
