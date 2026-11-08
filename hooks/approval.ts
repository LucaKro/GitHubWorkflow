import type { Register } from 'claude-code'

// Runs github_workflow.approval from the plugin's own source, the domain model's included,
// on the standard library alone, so it needs no runtime and always judges as this copy of
// the plugin does.
const CHECK =
  'import sys; sys.path[:0] = sys.argv[1].split(":"); from github_workflow.approval import main; main()'

// Approves a Bash call that is one workflow command a session runs on its own, so auto
// mode's classifier and the permission prompt are not asked about it. Only a call the
// session's own rules would ask about is approved: a refusal, by the guard or a rule,
// stands, and every other call is left as Claude Code decided it.
export const register: Register = (on) => {
  on('tool.check', { tool: 'Bash' }, async ($, e, next) => {
    const settled = await next(e)
    const command = (e.input as { command?: unknown }).command
    if (settled.decision !== 'ask' || typeof command !== 'string') return settled
    if (!command.includes('github-workflow')) return settled
    const checked = await $.process.run(
      ['python3', '-I', '-S', '-c', CHECK, `${$.plugin.root}/src:${$.plugin.root}/domain_model/src`],
      { stdin: command, timeoutMs: 10_000 },
    )
    if (checked.exitCode !== 0) return settled
    return {
      decision: 'allow',
      reason: 'a GitHubWorkflow command a session runs on its own',
    }
  }).catch(($, e, next) => next(e))
}
