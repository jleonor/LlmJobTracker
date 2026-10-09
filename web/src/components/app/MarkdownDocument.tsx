import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// The shared rendering for a generated profile document (career history, questionnaire report,
// strategy) or job document (listing, positioning breakdown): used by every overlay's document
// panes and the FilePreview overlay alike, so a document reads the same way everywhere it is
// shown. remark-gfm renders the positioning breakdown's weight/match table (job-llm-steps.md §3)
// as an actual table instead of a wall of pipe characters.
export function MarkdownDocument({ text }: { text: string }) {
  return (
    <article className="prose prose-sm dark:prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </article>
  )
}
