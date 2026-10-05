export type Job = {
  id: number
  company: string
  role_title: string
  lane: string | null
  status: string
  next_action: string | null
  due_date: string | null
}
