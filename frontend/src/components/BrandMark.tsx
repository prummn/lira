export function BrandMark({className=''}:{className?:string}) {
  return <svg className={`lira-mark ${className}`} viewBox="0 0 32 32" fill="none" aria-hidden="true">
    <path d="M6.5 8.5h12v17" />
    <path d="M25.5 23.5h-12v-17" />
    <circle className="lira-origin" cx="16" cy="16" r="2.25" />
  </svg>
}
