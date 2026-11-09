/**
 * dsh-easypaper-translate (简易论文翻译) — bilingual PDF builder for reading foreign papers.
 *
 * The heavy lifting stays local (Python + PyMuPDF); this plugin only exposes it
 * as model-facing tools. Translation itself is done by the harness model, so
 * the configured model applies and nothing here calls an API directly.
 */

import { spawnSync } from 'node:child_process'
import { existsSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const PYDIR = resolve(HERE, '..', 'python')

/** Resolve a Python interpreter: override, the DSH runtime, then PATH. */
function pythonOf(override) {
  if (override) return override
  if (process.env.DSH_PAPER_PYTHON) return process.env.DSH_PAPER_PYTHON
  const bundled = join(homedir(), '.dsh', 'dsh-runtimes', 'dsh-primary-runtime',
    'dependencies', 'python', 'python.exe')
  return existsSync(bundled) ? bundled : 'python'
}

/** Run the pipeline CLI with the plugin's own python directory on sys.path. */
function runCli(args, python) {
  const env = { ...process.env }
  env.PYTHONPATH = [join(PYDIR, '.pylibs'), PYDIR, env.PYTHONPATH]
    .filter(Boolean).join(';')
  env.PYTHONIOENCODING = 'utf-8'
  const result = spawnSync(pythonOf(python), args, {
    cwd: PYDIR, env, encoding: 'utf8', timeout: 30 * 60 * 1000,
  })
  return {
    code: result.status ?? -1,
    stdout: (result.stdout || '').trim(),
    stderr: (result.stderr || '').trim(),
  }
}

function countJson(dir) {
  try {
    return readdirSync(dir).filter(file => /^p\d+\.json$/.test(file)).length
  } catch {
    return 0
  }
}

/** Coverage report: translated pages versus pages that have text blocks. */
function statusOf(work) {
  const pages = countJson(join(work, 'blocks'))
  const translated = ['zh', 'zh2', 'zh3'].reduce(
    (sum, folder) => sum + countJson(join(work, folder)), 0)
  return {
    pages,
    translated: Math.min(translated, pages),
    pending: Math.max(0, pages - translated),
    tables: existsSync(join(work, 'tables', 'matrices.json')),
    figures: existsSync(join(work, 'figs', 'overlay', 'boxes.json')),
  }
}

function batchList(dir) {
  try {
    return readdirSync(dir)
      .filter(file => file.toLowerCase().endsWith('.pdf'))
      .map(file => join(dir, file))
      .filter(path => statSync(path).isFile())
  } catch {
    return []
  }
}

export const name = 'easypaper-translate'
export const inject = ['tools']

export async function apply(ctx) {
  const { defineTool } = await import('@deepseek-ai/dsh-tools')

  ctx.tools.register(defineTool({
    name: 'paper_translate',
    description:
      'Bilingual PDF builder for reading English papers: odd pages keep the original, '
      + 'even pages carry the Chinese rendering of body text, tables (rebuilt as '
      + 'three-line tables) and figure labels. prepare runs the local extraction '
      + 'stages, build renders the PDF, status reports coverage, batch lists a folder '
      + 'for sequential processing. Translation is done by the session model.',
    parameters: {
      action: { type: 'string', required: true, description: 'prepare | build | status | batch' },
      pdfPath: { type: 'string', description: 'Absolute path to the source PDF' },
      workDir: { type: 'string', description: 'Work directory (default ./work)' },
      batchDir: { type: 'string', description: 'Folder of PDFs for action=batch' },
      dpi: { type: 'number', description: 'Output DPI: 150 | 200 | 300 (default 150)' },
      imageDpi: { type: 'number', description: 'Figure/table crop DPI (default 200)' },
      nameTemplate: {
        type: 'string',
        description: 'Output name template. Fields: {zh_title} {en_title} {stem} '
          + '{dpi} {pages} {date}. Default: [中英对照]{zh_title}+{en_title}',
      },
      pythonPath: { type: 'string', description: 'Override the Python interpreter' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args) {
      const work = resolve(args.workDir || 'work')

      if (args.action === 'status') {
        const state = statusOf(work)
        return `work: ${work}\npages ${state.pages}, translated ${state.translated}, `
          + `pending ${state.pending}\ntables ${state.tables ? 'ready' : 'missing'}, `
          + `figures ${state.figures ? 'ready' : 'missing'}`
      }

      if (args.action === 'batch') {
        const files = batchList(resolve(args.batchDir || '.'))
        return files.length
          ? `${files.length} PDF(s):\n${files.join('\n')}`
          : 'no PDF found in that folder'
      }

      if (!args.pdfPath) return `${args.action}: pdfPath is required`
      const pdf = resolve(args.pdfPath)
      if (!existsSync(pdf)) return `${args.action}: not found ${pdf}`

      if (args.action === 'prepare') {
        const result = runCli(['translate.py', 'run', pdf, '--work', work,
          '--img-dpi', String(args.imageDpi || 200),
          '--dpi', String(args.dpi || 150)], args.pythonPath)
        const state = statusOf(work)
        return `prepare: ${state.pages} page(s), translated ${state.translated}, `
          + `pending ${state.pending}\n${result.stdout.slice(-1500)}`
      }

      if (args.action === 'build') {
        const result = runCli(['translate.py', 'build', pdf, '--work', work,
          '--dpi', String(args.dpi || 150),
          '--name-template', args.nameTemplate || ''], args.pythonPath)
        const line = result.stdout.split('\n').find(item => item.startsWith('output: '))
        if (result.code === 0 && line) return `build: ok\n→ ${line.slice(8)}`
        return `build: failed (exit ${result.code})\n`
          + `${result.stderr.slice(-1200) || result.stdout.slice(-1200)}`
      }

      return `${args.action}: unknown action`
    },
  }))

  ctx.tools.register(defineTool({
    name: 'paper_translate_env',
    description:
      'Check or install the Python dependencies of the paper translator: '
      + 'PyMuPDF, SciPy and PyYAML. check reports the current state, install '
      + 'downloads the wheels once into the plugin folder.',
    parameters: {
      action: { type: 'string', required: true, description: 'check | install' },
      pythonPath: { type: 'string' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args) {
      const probe = () => runCli(['translate.py', 'selftest'], args.pythonPath)
      if (args.action === 'check') {
        const result = probe()
        return result.code === 0
          ? `deps ok\n${result.stdout}`
          : `deps missing\n${result.stderr.slice(-600)}`
      }
      const lines = []
      for (const wheel of ['pymupdf', 'scipy', 'pyyaml']) {
        const result = runCli(
          ['install_wheel.py', wheel, '--libs', '.pylibs'], args.pythonPath)
        lines.push(`${wheel}: ${result.code === 0
          ? 'ok'
          : (result.stderr.split('\n').pop() || 'failed')}`)
      }
      const after = probe()
      return `${lines.join('\n')}\n${after.code === 0 ? 'deps ok' : 'still missing'}`
    },
  }))
}
