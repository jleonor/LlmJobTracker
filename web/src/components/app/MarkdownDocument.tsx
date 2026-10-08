import ReactMarkdown from 'react-markdown'

// The shared rendering for a generated profile document (career history, questionnaire report,
// strategy): used by the analysis overlay's document panes and the revise overlay's current-
// document pane, so a document reads the same way everywhere it is shown.
export function MarkdownDocument({ text }: { text: string }) {
  return (
    <article className="prose prose-sm dark:prose-invert max-w-none">
      <ReactMarkdown>{text}</ReactMarkdown>
    </article>
  )
}
