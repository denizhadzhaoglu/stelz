// One tile, one size scale — see mediaTokens.ts for why.
//
// Overlays (platform badge, "new", the ✕ reject button, frame markers) come in
// as children and position themselves absolutely against this box, exactly as
// they did when every call site hand-rolled its own relative aspect div.

import type { ReactNode } from 'react'
import { Img } from './ui'
import { TILE, type TileSize } from './mediaTokens'

export function MediaTile({
  src,
  alt = '',
  size = 'card',
  fit = 'cover',
  priority = false,
  className = '',
  children,
}: {
  src?: string | null
  alt?: string
  size?: TileSize
  fit?: 'cover' | 'contain'
  /** Above-the-fold hero: fetched eagerly, at high priority. */
  priority?: boolean
  className?: string
  children?: ReactNode
}) {
  return (
    <div className={`relative w-full overflow-hidden bg-[var(--color-bg)] ${TILE[size]} ${className}`}>
      <Img src={src} alt={alt} fit={fit} priority={priority} small={size === 'thumb'} />
      {children}
    </div>
  )
}
