import { expect, test } from 'claude-code/testing'

const WORKFLOW_COMMAND = { tool: 'Bash', input: { command: 'github-workflow push' } } as const

// What the check answers, as `$.process.run` resolves it, exiting with the given status.
const checkExiting = (exitCode: number) => ({
  value: { exitCode, stdout: '', stderr: '', isStdoutTruncated: false, isStderrTruncated: false },
})

test('a workflow command the check approves is allowed where it would be asked about', async ($, on) => {
  on('tool.check', () => ({ decision: 'ask' }))
  const given: string[] = []
  on('process.run', (_, e) => {
    given.push(e.init?.stdin ?? '')
    return checkExiting(0)
  })

  const checked = await $.tool.check(WORKFLOW_COMMAND)

  expect([checked.decision, given]).toEqual(['allow', [WORKFLOW_COMMAND.input.command]])
})

test('a workflow command the check leaves is still asked about', async ($, on) => {
  on('tool.check', () => ({ decision: 'ask' }))
  on('process.run', () => checkExiting(1))

  const checked = await $.tool.check(WORKFLOW_COMMAND)

  expect(checked.decision).toBe('ask')
})

test('a refused workflow command stays refused, unchecked', async ($, on) => {
  on('tool.check', () => ({ decision: 'deny', reason: 'the guard refused it' }))
  let checks = 0
  on('process.run', () => {
    checks += 1
    return checkExiting(0)
  })

  const checked = await $.tool.check(WORKFLOW_COMMAND)

  expect([checked.decision, checks]).toEqual(['deny', 0])
})

test('a command that runs no workflow command is left unchecked', async ($, on) => {
  on('tool.check', () => ({ decision: 'ask' }))
  let checks = 0
  on('process.run', () => {
    checks += 1
    return checkExiting(0)
  })

  const checked = await $.tool.check({ tool: 'Bash', input: { command: 'rm -rf build' } })

  expect([checked.decision, checks]).toEqual(['ask', 0])
})
