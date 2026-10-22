import { Plus, X } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ApiError, createOpenApplication } from '@/lib/api'
import type { AddOpenApplicationResult, OpenApplicationTargetType } from '@/lib/types'

const MAX_RESEARCH_ITEMS = 5

type ResearchItemDraft = { sourceType: 'url' | 'text'; content: string }

const TARGET_TYPE_ITEMS: Record<string, string> = {
  talent_pool: 'Talent pool',
  unsolicited: 'Unsolicited CV drop',
  cold_outreach: 'Cold outreach',
}
const NONE = 'none'

function emptyItem(): ResearchItemDraft {
  return { sourceType: 'text', content: '' }
}

// "Add Open Application" (D-251): one combined flow - up to 5 research items (URL or pasted
// text, unlabeled) plus any fields the user wants to pre-fill, submitted together. Creating the
// row immediately queues Company details' Generate step, which maps the intake into the
// structured fields (including Target name/type) - there is no separate review stage the way
// Add Job's Listing intake has, since nothing here is checked by code before the model runs.
export function AddOpenApplicationOverlay({
  open,
  onOpenChange,
  onCreated,
  onOpenApplication,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: () => void
  onOpenApplication: (applicationId: number) => void
}) {
  const [items, setItems] = useState<ResearchItemDraft[]>([emptyItem()])
  const [targetName, setTargetName] = useState('')
  const [targetType, setTargetType] = useState<OpenApplicationTargetType | ''>('')
  const [contactName, setContactName] = useState('')
  const [contactTitle, setContactTitle] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [angle, setAngle] = useState('')
  const [whyThisCompany, setWhyThisCompany] = useState('')
  const [otherNotes, setOtherNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function reset() {
    setItems([emptyItem()])
    setTargetName('')
    setTargetType('')
    setContactName('')
    setContactTitle('')
    setContactEmail('')
    setAngle('')
    setWhyThisCompany('')
    setOtherNotes('')
    setError(null)
  }

  function close(nextOpen: boolean) {
    if (!nextOpen) reset()
    onOpenChange(nextOpen)
  }

  function updateItem(index: number, next: Partial<ResearchItemDraft>) {
    setItems((current) => current.map((item, i) => (i === index ? { ...item, ...next } : item)))
  }

  const nonEmptyItems = items.filter((item) => item.content.trim() !== '')
  const hasAnyManualField = [
    targetName,
    targetType,
    contactName,
    contactTitle,
    contactEmail,
    angle,
    whyThisCompany,
    otherNotes,
  ].some((value) => value.trim() !== '')
  const canSubmit = nonEmptyItems.length > 0 || hasAnyManualField

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const result: AddOpenApplicationResult = await createOpenApplication({
        target_name: targetName.trim() || null,
        target_type: targetType || null,
        contact_name: contactName.trim() || null,
        contact_title: contactTitle.trim() || null,
        contact_email: contactEmail.trim() || null,
        angle: angle.trim() || null,
        why_this_company: whyThisCompany.trim() || null,
        other_notes: otherNotes.trim() || null,
        research_items: nonEmptyItems.map((item) => ({
          source_type: item.sourceType,
          content: item.content.trim(),
        })),
      })
      onCreated()
      close(false)
      onOpenApplication(result.application_id)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'This could not be created.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="flex h-[85vh] w-full max-w-3xl flex-col gap-3 sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Add Open Application</DialogTitle>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1">
          <div className="flex flex-col gap-2">
            <Label>Research (up to {MAX_RESEARCH_ITEMS}) - a URL or pasted text each</Label>
            <p className="text-xs text-muted-foreground">
              Anything relevant: company news, their careers page, a product page, who you know
              there. Claude maps this into the fields below once you create the application -
              you don&apos;t need to label each item.
            </p>
            {items.map((item, index) => (
              <div key={index} className="flex gap-2">
                <Select
                  items={{ text: 'Text', url: 'URL' }}
                  value={item.sourceType}
                  onValueChange={(value) =>
                    value && updateItem(index, { sourceType: value as 'url' | 'text' })
                  }
                >
                  <SelectTrigger className="w-24 shrink-0">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="text">Text</SelectItem>
                    <SelectItem value="url">URL</SelectItem>
                  </SelectContent>
                </Select>
                {item.sourceType === 'url' ? (
                  <Input
                    placeholder="https://..."
                    value={item.content}
                    onChange={(event) => updateItem(index, { content: event.target.value })}
                  />
                ) : (
                  <Textarea
                    rows={2}
                    placeholder="Paste anything relevant..."
                    value={item.content}
                    onChange={(event) => updateItem(index, { content: event.target.value })}
                    className="flex-1 resize-none"
                  />
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label="Remove this item"
                  onClick={() => setItems((current) => current.filter((_, i) => i !== index))}
                  disabled={items.length === 1}
                >
                  <X className="size-4" />
                </Button>
              </div>
            ))}
            {items.length < MAX_RESEARCH_ITEMS && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => setItems((current) => [...current, emptyItem()])}
              >
                <Plus className="size-3.5" aria-hidden="true" />
                Add another item
              </Button>
            )}
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label>Target name (optional - Claude can infer this)</Label>
              <Input value={targetName} onChange={(event) => setTargetName(event.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Target type (optional - Claude can infer this)</Label>
              <Select
                items={{ [NONE]: 'Not set', ...TARGET_TYPE_ITEMS }}
                value={targetType === '' ? NONE : targetType}
                onValueChange={(value) =>
                  setTargetType(value === NONE || !value ? '' : (value as OpenApplicationTargetType))
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Not set" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NONE}>Not set</SelectItem>
                  {Object.entries(TARGET_TYPE_ITEMS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Contact name (optional)</Label>
              <Input value={contactName} onChange={(event) => setContactName(event.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>Contact title (optional)</Label>
              <Input value={contactTitle} onChange={(event) => setContactTitle(event.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <Label>Contact email (optional)</Label>
              <Input value={contactEmail} onChange={(event) => setContactEmail(event.target.value)} />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>
              Angle (optional) - your own connection, e.g. a referral or someone you know there
            </Label>
            <Textarea
              rows={2}
              value={angle}
              onChange={(event) => setAngle(event.target.value)}
              className="resize-none"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Why this company (optional)</Label>
            <Textarea
              rows={2}
              value={whyThisCompany}
              onChange={(event) => setWhyThisCompany(event.target.value)}
              className="resize-none"
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>Other (optional) - anything else to pass along as context</Label>
            <Textarea
              rows={2}
              value={otherNotes}
              onChange={(event) => setOtherNotes(event.target.value)}
              className="resize-none"
            />
          </div>

          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>
            Cancel
          </Button>
          <Button disabled={busy || !canSubmit} onClick={() => void submit()}>
            {busy ? 'Creating...' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
