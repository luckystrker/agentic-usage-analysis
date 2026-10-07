#!/usr/bin/env node
/**
 * Self-installer for the `agentic-usage-analysis` skill.
 *
 * Copies SKILL.md, scripts/, references/ and evals/ from this npm package into an
 * agent skills directory, so the skill loads in agents that read SKILL.md
 * (ZCode, Claude Code, anything using ~/.agents/skills).
 *
 * Zero runtime dependencies. Node >= 18.
 *
 * Usage:
 *   npx agentic-usage-analysis               # install into the first detected skills dir
 *   npx agentic-usage-analysis --all         # install into every detected skills dir
 *   npx agentic-usage-analysis --dir <path>  # install into a specific skills dir
 *   npx agentic-usage-analysis uninstall     # remove the skill (all detected copies)
 *
 * Re-running the installer updates an existing copy (a clean re-copy, tracked via
 * the .npx-install.json marker file inside the skill directory).
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

const PKG_ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const MARKER = '.npx-install.json';
const SKILL_ENTRIES = ['SKILL.md', 'scripts', 'references', 'evals'];

// Priority order for the default (no --dir) install.
const CANDIDATES = [
  { agent: 'ZCode', skills: ['.zcode', 'skills'] },
  { agent: 'Claude Code', skills: ['.claude', 'skills'] },
  { agent: 'agents (~/.agents/skills)', skills: ['.agents', 'skills'] },
  { agent: 'OpenCode', skills: ['.config', 'opencode', 'skills'] },
  { agent: 'Codex', skills: ['.codex', 'skills'] },
  { agent: 'Cursor', skills: ['.cursor', 'skills'] },
];

const pkg = JSON.parse(fs.readFileSync(path.join(PKG_ROOT, 'package.json'), 'utf8'));

function skillName() {
  const md = fs.readFileSync(path.join(PKG_ROOT, 'SKILL.md'), 'utf8');
  const m = md.match(/^---\n([\s\S]*?)\n---/);
  const name = m && m[1].match(/^name:\s*(\S+)/m);
  return name ? name[1] : pkg.name;
}

const NAME = skillName();

function usage() {
  return `
${pkg.name} ${pkg.version} — skill installer

Usage:
  npx ${pkg.name}                 install into the first detected skills dir
  npx ${pkg.name} --all           install into every detected skills dir
  npx ${pkg.name} --dir <path>    install into this skills dir (or the skill dir itself)
  npx ${pkg.name} uninstall       remove the skill from every detected skills dir
  npx ${pkg.name} uninstall --dir <path>

Detected dirs are looked up under your home: ${CANDIDATES.map((c) => path.join('~', ...c.skills)).join(', ')}.
A candidate counts as detected when the skills dir itself or its agent dir exists.

The installed skill needs Python 3.10+ at analysis time (standard library only).
`.trim();
}

function parseArgs(argv) {
  const args = { command: 'install', dir: null, all: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === 'install' || a === 'uninstall') args.command = a;
    else if (a === '--dir') args.dir = argv[++i];
    else if (a === '--all') args.all = true;
    else if (a === '--help' || a === '-h') args.help = true;
    else if (a === '--version' || a === '-v') args.version = true;
    else {
      console.error(`Unknown argument: ${a}\n\n${usage()}`);
      process.exit(1);
    }
  }
  if (args.dir === undefined) {
    console.error(`--dir requires a path\n\n${usage()}`);
    process.exit(1);
  }
  return args;
}

function detectSkillsDirs() {
  const home = os.homedir();
  return CANDIDATES.map((c) => {
    const skillsDir = path.join(home, ...c.skills);
    // Fresh agent installs may not have created the skills subdir yet.
    const detected = fs.existsSync(skillsDir) || fs.existsSync(path.dirname(skillsDir));
    return { agent: c.agent, skillsDir, detected };
  });
}

// Accept both the skills dir (~/.claude/skills) and the skill dir itself
// (~/.claude/skills/agentic-usage-analysis).
function normalizeDirToSkills(dir) {
  const abs = path.resolve(dir);
  return path.basename(abs) === NAME ? path.dirname(abs) : abs;
}

function isOurs(dest) {
  if (fs.existsSync(path.join(dest, MARKER))) return true;
  try {
    const md = fs.readFileSync(path.join(dest, 'SKILL.md'), 'utf8');
    return new RegExp(`^name:\\s*${NAME}\\s*$`, 'm').test(md);
  } catch {
    return false;
  }
}

function assertSafeToRemove(dest) {
  const abs = path.resolve(dest);
  if (path.basename(abs) !== NAME || !fs.existsSync(path.join(abs, 'SKILL.md'))) {
    throw new Error(`refusing to remove ${dest}: does not look like the ${NAME} skill`);
  }
}

function installInto(skillsDir) {
  const dest = path.join(skillsDir, NAME);
  if (fs.existsSync(dest)) {
    if (fs.existsSync(path.join(dest, MARKER))) {
      // Our own previous install: clean update, so renamed/deleted files don't linger.
      assertSafeToRemove(dest);
      fs.rmSync(dest, { recursive: true, force: true });
    } else if (isOurs(dest)) {
      console.log(`  overwriting existing ${dest} (not installed by npx — local edits, if any, are replaced)`);
    } else {
      throw new Error(`${dest} exists and is not the ${NAME} skill; pick another --dir`);
    }
  }
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of SKILL_ENTRIES) {
    fs.cpSync(path.join(PKG_ROOT, entry), path.join(dest, entry), { recursive: true });
  }
  fs.writeFileSync(
    path.join(dest, MARKER),
    JSON.stringify({ package: pkg.name, version: pkg.version, installedAt: new Date().toISOString() }, null, 2) + '\n'
  );
  return dest;
}

function uninstallFrom(skillsDir) {
  const dest = path.join(skillsDir, NAME);
  if (!fs.existsSync(dest)) return null;
  assertSafeToRemove(dest);
  fs.rmSync(dest, { recursive: true, force: true });
  return dest;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) return console.log(usage());
  if (args.version) return console.log(pkg.version);

  const detected = detectSkillsDirs().filter((c) => c.detected);

  let targets;
  if (args.dir) {
    targets = [normalizeDirToSkills(args.dir)];
  } else if (args.command === 'uninstall') {
    targets = detected.map((c) => c.skillsDir);
    if (targets.length === 0) {
      console.log('No agent skills directories detected — nothing to uninstall.');
      return;
    }
  } else if (detected.length === 0) {
    console.error(
      `No agent skills directories detected (${CANDIDATES.map((c) => path.join('~', ...c.skills)).join(', ')}).\n` +
        `Create one or pass it explicitly:  npx ${pkg.name} --dir <skills-dir>`
    );
    process.exit(1);
  } else {
    targets = args.all ? detected.map((c) => c.skillsDir) : [detected[0].skillsDir];
  }

  if (args.command === 'install') {
    for (const dir of targets) {
      const dest = installInto(dir);
      console.log(`Installed ${NAME} ${pkg.version} -> ${dest}`);
    }
    if (!args.dir && !args.all && detected.length > 1) {
      console.log(`\nAlso detected (not used):`);
      for (const c of detected.slice(1)) console.log(`  ${c.skillsDir}  (${c.agent})`);
      console.log(`Install everywhere with --all, or target one with --dir <path>.`);
    }
    console.log(`\nNext: the skill loads on agent restart. Scripts need Python 3.10+:`);
    console.log(`  python <skills-dir>/${NAME}/scripts/discover.py --repo "C:\\path\\to\\repo"`);
  } else {
    let removed = 0;
    for (const dir of targets) {
      const dest = uninstallFrom(dir);
      if (dest) {
        console.log(`Removed ${dest}`);
        removed++;
      }
    }
    if (!removed) console.log(`${NAME} is not installed in any detected skills directory.`);
  }
}

try {
  main();
} catch (err) {
  console.error(`Error: ${err.message}`);
  process.exit(1);
}
