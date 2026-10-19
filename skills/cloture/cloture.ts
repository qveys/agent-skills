import type { Register } from 'claude-code'

const WRITE = new Set(['Edit', 'Write', 'NotebookEdit', 'MultiEdit'])
const MUTATING = /\b(git\s+(commit|push|add|merge|rebase|reset|checkout|mv|rm|apply|tag)|rm|mv|cp|mkdir|rmdir|touch|tee|ln|chmod|chown|npm\s+(i|install|uninstall)|pnpm\s+(add|install)|pip3?\s+install|brew\s+(install|upgrade|uninstall)|sed\s+-i|gh\s+(pr|api\s+-X)|docker\s+(rm|run|build|compose))\b|(^|[^>&])>>?\s*[^&\s]/
const TASKS = /^(TodoWrite|Task(Create|Update|List))$/

const SYSTEM = `Tu estimes la clôture d'une session de travail d'un assistant de code. Réponds par UNE ligne en français très concis (≤ 400 caractères), ou exactement SILENCE.

Entrée : extrait récent de la conversation (messages, outils, liste de tâches si présente).

Règles :
- "Réalisé" = vérifié (test, lecture, sortie observée), pas seulement écrit. Pour les dépôts ~/Git/brain/Second-Cerveau, ~/Git/brain, ~/Git/memoire-centralisee/memoire-perso, ~/Git/agent-skills : réalisé = vérifié ET commité/poussé (agent-skills : PR ouverte).
- Ne jamais inventer de n/m : n/m seulement s'il existe une vraie liste de tâches dans l'entrée.
- SILENCE si le travail est évidemment avancé à moins de 25 % (plus de 75 % reste), ou si rien n'est à signaler.
- Attentes différées (ni faites ni faisables maintenant, ex. PR qui attend l'OK de l'utilisateur) : hors décompte, sur une ligne séparée « en attente : … ».

Formats exacts (un seul pour la ligne principale) :
Clôture : OK
Clôture : n/m — reste X, Y
Clôture : ~n étapes : X, Y, Z   (estimation, tilde obligatoire, étapes nommées)
Clôture : non mesurable — reste : <1 phrase>
Clôture : bloqué sur toi — <quoi>
Optionnel, ligne suivante : en attente : …
Rien d'autre : pas de préambule, pas de markdown.`

type Msg = { role: string; text: string; toolUses: { tool: string; input: Record<string, unknown> }[]; toolResults?: unknown[] }

const isMutation = (m: Msg) =>
  m.toolUses.some(u => WRITE.has(u.tool) || (u.tool === 'Bash' && MUTATING.test(String(u.input.command ?? ''))))

// Messages du tour courant : après le dernier message utilisateur « humain » (sans tool_result).
const lastTurn = (msgs: Msg[]) => {
  const i = msgs.map(m => m.role === 'user' && !m.toolResults?.length).lastIndexOf(true)
  return msgs.slice(Math.max(i, 0))
}

const digest = (msgs: Msg[]) =>
  msgs
    .map(m => {
      const tools = m.toolUses
        .map(u => `[${u.tool}${TASKS.test(u.tool) ? ' ' + JSON.stringify(u.input) : ' ' + JSON.stringify(u.input).slice(0, 160)}]`)
        .join(' ')
      return `${m.role}: ${m.text.slice(0, 1200)} ${tools}`.trim()
    })
    .join('\n')
    .slice(-12000)

export const register: Register = on => {
  let isFirst = true
  let stop = new AbortController()

  on('turn.start', ($, e, next) => {
    if (e.agentId === undefined) {
      stop.abort()
      $.ui.status(undefined)
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (e.agentId !== undefined) return next(e)
    const wasFirst = isFirst
    isFirst = false
    stop = new AbortController()
    try {
      const all = (await $.session.messages()) as Msg[]
      if (!Array.isArray(all) || (!wasFirst && !isMutation({ role: '', text: '', toolUses: lastTurn(all).flatMap(m => m.toolUses) }))) return next(e)
      const r = await $.model.complete(
        { model: 'haiku', system: SYSTEM, prompt: digest(all.slice(-30)), maxTokens: 300 },
        { signal: stop.signal },
      )
      const text = r.isAnswered ? r.text.trim() : ''
      if (text && !/^SILENCE\b/.test(text) && !stop.signal.aborted) $.ui.status(text.slice(0, 400))
    } catch {
      // échec : rien à afficher
    }
    return next(e)
  })
}
