#!/usr/bin/env node
/**
 * install-codex-mcp.mjs — import Codex MCP servers into a DeepSeek Harness (DSH) profile.
 *
 * DSH does not read ~/.codex/config.toml. It mounts one @deepseek-ai/dsh-mcp-client
 * row per MCP server in the profile's cordis.patch.yml. This script:
 *
 *   1. asks the Codex CLI for the *resolved* server list (`codex mcp list --json`),
 *   2. installs @deepseek-ai/dsh-mcp-client@<dsh version> into the DSH profile,
 *   3. translates each server into an idempotent, marked block in cordis.patch.yml,
 *   4. backs up the patch, then validates the composition with `dsh --dump-config`.
 *
 * The generated block is managed: re-running replaces it, leaving the rest of
 * cordis.patch.yml untouched. Codex config/plugin files are never modified.
 *
 * Usage:
 *   ./install-codex-mcp.mjs [options]
 *
 * Options:
 *   --profile <name>       DSH profile (default: $DSH_PROFILE or "headless")
 *   --dsh-home <dir>       DSH home (default: $DSH_HOME or ~/.dsh)
 *   --codex-home <dir>     Codex home (default: $CODEX_HOME or ~/.codex)
 *   --config <file>        Codex config.toml (default: <codex-home>/config.toml)
 *   --servers-json <file>  Use an exported `codex mcp list --json` file instead
 *   --prefix <text>        Prefix each imported serverName (e.g. "codex-")
 *   --only <names>         Comma-separated Codex server names to import
 *   --exclude <names>      Comma-separated Codex server names to skip
 *   --include-disabled     Import disabled Codex servers as disabled DSH rows
 *   --no-install           Do not run `dsh plugin add`; require an installed/local copy
 *   --dry-run              Print the patch and planned actions; write nothing
 *   --remove               Remove the managed block (does not uninstall the plugin)
 *   --no-verify            Skip `dsh --dump-config` after writing
 *   -h, --help             Show this help
 */

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';

const PLUGIN = '@deepseek-ai/dsh-mcp-client';
const BEGIN = '# >>> codex-mcp-import (managed block; regenerate with install-codex-mcp.mjs) >>>';
const END = '# <<< codex-mcp-import <<<';

const HELP = `Import Codex MCP servers into a DeepSeek Harness (DSH) profile.

Usage: install-codex-mcp.mjs [options]

  --profile <name>       DSH profile (default: $DSH_PROFILE or "headless")
  --dsh-home <dir>       DSH home (default: $DSH_HOME or ~/.dsh)
  --codex-home <dir>     Codex home (default: $CODEX_HOME or ~/.codex)
  --config <file>        Codex config.toml (default: <codex-home>/config.toml)
  --servers-json <file>  Use an exported "codex mcp list --json" file
  --prefix <text>        Prefix each imported serverName (e.g. "codex-")
  --only <names>         Comma-separated Codex server names to import
  --exclude <names>      Comma-separated Codex server names to skip
  --include-disabled     Import disabled Codex servers as disabled DSH rows
  --no-install           Do not run "dsh plugin add"
  --dry-run              Print the patch and planned actions; write nothing
  --remove               Remove the managed block (keeps the plugin installed)
  --no-verify            Skip the post-write "dsh --dump-config" check
  -h, --help             Show this help

The block lives in <dsh-home>/profiles/<profile>/cordis.patch.yml and is
replaced on every run. Everything outside the two marker lines is preserved.
`;

function die(message) {
  process.stderr.write(`install-codex-mcp: ${message}\n`);
  process.exit(1);
}

function note(message) {
  process.stdout.write(`install-codex-mcp: ${message}\n`);
}

function warn(message) {
  process.stderr.write(`install-codex-mcp: warning: ${message}\n`);
}

function expandHome(p) {
  if (!p) return p;
  if (p === '~') return os.homedir();
  if (p.startsWith('~/')) return path.join(os.homedir(), p.slice(2));
  return p;
}

function parseArgs(argv) {
  const opts = {
    profile: process.env.DSH_PROFILE || 'headless',
    dshHome: process.env.DSH_HOME || path.join(os.homedir(), '.dsh'),
    codexHome: process.env.CODEX_HOME || path.join(os.homedir(), '.codex'),
    config: null,
    serversJson: null,
    prefix: '',
    only: new Set(),
    exclude: new Set(),
    includeDisabled: false,
    install: true,
    dryRun: false,
    remove: false,
    verify: true,
    help: false,
  };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const need = () => {
      const value = argv[++i];
      if (value === undefined) die(`${arg} needs a value`);
      return value;
    };
    switch (arg) {
      case '--profile': opts.profile = need(); break;
      case '--dsh-home': opts.dshHome = expandHome(need()); break;
      case '--codex-home': opts.codexHome = expandHome(need()); break;
      case '--config': opts.config = expandHome(need()); break;
      case '--servers-json': opts.serversJson = expandHome(need()); break;
      case '--prefix': opts.prefix = need(); break;
      case '--only':
        for (const name of need().split(',').map((item) => item.trim()).filter(Boolean)) opts.only.add(name);
        break;
      case '--exclude':
        for (const name of need().split(',').map((item) => item.trim()).filter(Boolean)) opts.exclude.add(name);
        break;
      case '--include-disabled': opts.includeDisabled = true; break;
      case '--no-install': opts.install = false; break;
      case '--dry-run': opts.dryRun = true; break;
      case '--remove': opts.remove = true; break;
      case '--no-verify': opts.verify = false; break;
      case '-h':
      case '--help': opts.help = true; break;
      default:
        if (arg.startsWith('-')) die(`unknown option ${JSON.stringify(arg)} (use --help)`);
        die(`unexpected argument ${JSON.stringify(arg)} (use --help)`);
    }
  }
  return opts;
}

function which(command) {
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    if (!dir) continue;
    const candidate = path.join(dir, command);
    try {
      if (!fs.statSync(candidate).isFile()) continue;
      fs.accessSync(candidate, fs.constants.X_OK);
      return candidate;
    } catch {
      // keep looking
    }
  }
  return null;
}

function realpathOrNull(p) {
  try {
    return fs.realpathSync(p);
  } catch {
    return null;
  }
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function findDshRoot(dshBin) {
  let dir = path.dirname(realpathOrNull(dshBin) || dshBin);
  for (;;) {
    const manifest = path.join(dir, 'package.json');
    if (fs.existsSync(manifest)) {
      try {
        const pkg = readJson(manifest);
        if (pkg.name === '@deepseek-ai/dsh') return dir;
      } catch {
        // not the one
      }
    }
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function dshVersion(dshBin, env) {
  let out;
  try {
    out = execFileSync(dshBin, ['--version'], {
      env,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (error) {
    die(`could not run "dsh --version": ${error.stderr?.toString().trim() || error.message}`);
  }
  const match = String(out).match(/\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?/);
  if (!match) die(`could not parse the dsh version from ${JSON.stringify(out.trim())}`);
  return match[0];
}

function hasExactDependency(profileDir, packageName, version) {
  const manifest = path.join(profileDir, 'package.json');
  if (!fs.existsSync(manifest)) return false;
  try {
    const pkg = readJson(manifest);
    return pkg.dependencies?.[packageName] === version;
  } catch {
    return false;
  }
}

function findLocalPlugin(dshRoot, version) {
  if (!dshRoot) return null;
  const candidates = [];
  const requireFromDsh = createRequire(path.join(dshRoot, 'package.json'));
  try {
    const resolved = requireFromDsh.resolve(PLUGIN);
    candidates.push(resolved);
  } catch {
    // package may use exports that require.resolve cannot reach; try paths below
  }
  candidates.push(path.join(dshRoot, 'node_modules', PLUGIN, 'lib', 'index.js'));

  let mismatch = null;
  for (const candidate of candidates) {
    const file = realpathOrNull(candidate);
    if (!file || !fs.existsSync(file)) continue;
    let dir = path.dirname(file);
    for (;;) {
      const manifest = path.join(dir, 'package.json');
      if (fs.existsSync(manifest)) {
        try {
          const pkg = readJson(manifest);
          if (pkg.name === PLUGIN) {
            if (version && pkg.version !== version) {
              mismatch ??= { file, version: pkg.version, mismatch: true };
            } else {
              return { file, version: pkg.version, mismatch: false };
            }
            break;
          }
        } catch {
          // keep looking
        }
      }
      const parent = path.dirname(dir);
      if (parent === dir) break;
      dir = parent;
    }
  }
  return mismatch;
}

function ensurePlugin({ profile, profileDir, dshHome, dshBin, version, install, dryRun }) {
  const env = { ...process.env, DSH_HOME: dshHome };
  const spec = `${PLUGIN}@${version}`;

  if (hasExactDependency(profileDir, PLUGIN, version)) {
    return { name: PLUGIN, how: 'already installed' };
  }

  if (!install) {
    const local = findLocalPlugin(findDshRoot(dshBin), version);
    if (local && !local.mismatch) {
      return { name: local.file, how: `local copy ${local.file}` };
    }
    die(`${PLUGIN}@${version} is not installed in profile "${profile}" and --no-install was given`);
  }

  if (dryRun) {
    return { name: PLUGIN, how: `would install ${spec}` };
  }

  note(`installing ${spec} into profile "${profile}" ...`);
  try {
    execFileSync(dshBin, ['plugin', '--profile', profile, 'add', spec], {
      env,
      stdio: 'inherit',
    });
  } catch {
    const local = findLocalPlugin(findDshRoot(dshBin), version);
    if (local && !local.mismatch) {
      warn(`registry install failed; falling back to the copy shipped with DSH: ${local.file}`);
      return { name: local.file, how: `local copy ${local.file}` };
    }
    die(`could not install ${spec} (see the pnpm output above)`);
  }

  if (!hasExactDependency(profileDir, PLUGIN, version)) {
    warn(`the profile manifest still does not pin ${spec}; the patch will use the package name and may fail to load`);
  }
  return { name: PLUGIN, how: `installed ${spec}` };
}

function readServers(opts) {
  if (opts.serversJson) {
    try {
      const parsed = JSON.parse(fs.readFileSync(opts.serversJson, 'utf8'));
      if (!Array.isArray(parsed)) die(`${opts.serversJson} must contain a JSON array`);
      return parsed;
    } catch (error) {
      die(`could not read ${opts.serversJson}: ${error.message}`);
    }
  }

  const codex = which('codex');
  if (!codex) {
    die('the "codex" CLI was not found on PATH; install Codex or pass --servers-json <file>');
  }
  const env = { ...process.env, CODEX_HOME: opts.codexHome };
  try {
    const out = execFileSync(codex, ['mcp', 'list', '--json'], {
      env,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      maxBuffer: 32 * 1024 * 1024,
    });
    const parsed = JSON.parse(out);
    if (!Array.isArray(parsed)) die('codex mcp list --json did not return an array');
    return parsed;
  } catch (error) {
    const stderr = error.stderr?.toString().trim();
    die(`could not run "codex mcp list --json"${stderr ? `: ${stderr}` : `: ${error.message}`}`);
  }
}

function hash(text) {
  return createHash('sha256').update(String(text)).digest('hex');
}

function slug(raw) {
  let s = String(raw)
    .normalize('NFKD')
    .replace(/[^A-Za-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  if (!s) s = 'server';
  if (s.length > 32) s = `${s.slice(0, 23)}-${hash(raw).slice(0, 8)}`;
  return s;
}

function uniqueName(base, used) {
  let name = base;
  let i = 2;
  while (used.has(name)) {
    const suffix = `-${i++}`;
    name = `${base.slice(0, 32 - suffix.length)}${suffix}`;
  }
  used.add(name);
  return name;
}

function uniqueId(base, used) {
  let id = base;
  let i = 2;
  while (used.has(id)) id = `${base}-${i++}`;
  used.add(id);
  return id;
}

function js(expression) {
  return { __js: expression };
}

function envExpression(name) {
  return js(`process.env[${JSON.stringify(name)}] ?? ''`);
}

function collectExistingServerNames(text) {
  const names = new Set();
  const re = /^\s*serverName:\s*['"]?([A-Za-z0-9_-]+)['"]?\s*(?:#.*)?$/gm;
  let match;
  while ((match = re.exec(text)) !== null) names.add(match[1]);
  return names;
}

function collectExistingIds(text) {
  const ids = new Set();
  const re = /^\s*-\s+id:\s*(?:"([^"]+)"|'([^']+)'|([A-Za-z0-9_.-]+))\s*$/gm;
  let match;
  while ((match = re.exec(text)) !== null) ids.add(match[1] || match[2] || match[3]);
  return ids;
}

function transformServer(server, opts, usedNames, usedIds, pluginName) {
  const t = server.transport || {};
  const display = server.name || 'server';
  const warnings = [];

  if (server.enabled === false && !opts.includeDisabled) {
    return { skipped: true, reason: 'disabled in Codex (use --include-disabled to import)' };
  }

  const requestedName = `${opts.prefix || ''}${display}`;
  const serverName = uniqueName(slug(requestedName), usedNames);
  const id = uniqueId(`codex-mcp-${serverName}`, usedIds);

  const config = {
    transport: null,
    serverName,
  };

  const type = t.type;
  if (type === 'stdio') {
    if (!t.command) {
      return { skipped: true, reason: 'stdio server has no command' };
    }
    config.transport = 'stdio';
    config.command = String(t.command);
    if (Array.isArray(t.args) && t.args.length > 0) config.args = t.args.map(String);

    const env = Object.create(null);
    for (const [key, value] of Object.entries(t.env || {})) env[key] = String(value);
    for (const entry of t.env_vars || []) {
      const name = typeof entry === 'string' ? entry : entry?.name;
      if (!name) {
        warnings.push('ignored an env_vars entry that has no name');
        continue;
      }
      env[name] = envExpression(name);
      if (process.env[name] === undefined) {
        warnings.push(`env var ${name} is not set now; DSH will read it when it starts`);
      }
      if (entry && typeof entry === 'object' && entry.source && entry.source !== 'local') {
        warnings.push(`env var ${name} uses source ${JSON.stringify(entry.source)}; DSH reads only the launch environment`);
      }
    }
    if (Object.keys(env).length > 0) config.env = env;
    if (t.cwd) config.cwd = String(t.cwd);
  } else if (type === 'streamable_http' || type === 'streamable-http' || type === 'http') {
    if (!t.url) {
      return { skipped: true, reason: 'HTTP server has no url' };
    }
    config.transport = 'streamable-http';
    config.url = String(t.url);

    const headers = {};
    for (const [key, value] of Object.entries(t.http_headers || {})) headers[key] = String(value);
    for (const [header, envName] of Object.entries(t.env_http_headers || {})) {
      headers[header] = envExpression(String(envName));
      if (process.env[envName] === undefined) {
        warnings.push(`header env var ${envName} is not set now; DSH will read it when it starts`);
      }
    }
    if (t.bearer_token_env_var) {
      const hasAuth = Object.keys(headers).some((key) => key.toLowerCase() === 'authorization');
      if (!hasAuth) {
        const name = String(t.bearer_token_env_var);
        headers.Authorization = js(`\`Bearer \${process.env[${JSON.stringify(name)}] ?? ''}\``);
        if (process.env[name] === undefined) {
          warnings.push(`bearer token env var ${name} is not set now; DSH will read it when it starts`);
        }
      }
    }
    if (Object.keys(headers).length > 0) config.headers = headers;
    if (t.http_headers_helper) {
      warnings.push('http_headers_helper is not supported by dsh-mcp-client; its headers are not imported');
    }
  } else {
    return { skipped: true, reason: `unsupported transport ${JSON.stringify(type)}` };
  }

  if (server.tool_timeout_sec != null) {
    // A non-numeric value used to become `toolCallTimeoutMs: NaN`, which the
    // generated YAML then carried as a literal. Only a finite positive number
    // is a timeout; record the bad input instead of writing it.
    const seconds = Number(server.tool_timeout_sec);
    if (Number.isFinite(seconds) && seconds > 0) {
      config.toolCallTimeoutMs = Math.round(seconds * 1000);
    } else {
      warnings.push(`tool_timeout_sec=${JSON.stringify(server.tool_timeout_sec)} is not a positive number; no per-server timeout was written`);
    }
  }
  if (server.startup_timeout_sec != null) {
    warnings.push(`startup_timeout_sec=${server.startup_timeout_sec} has no DSH per-server equivalent; connection errors are logged and the harness continues`);
  }
  if (server.enabled_tools != null || server.disabled_tools != null) {
    warnings.push('enabled_tools/disabled_tools have no DSH per-server equivalent; all server tools are exposed');
  }
  if (server.auth_status && !['unsupported', 'bearer_token', 'none'].includes(server.auth_status)) {
    warnings.push(`Codex auth mode ${JSON.stringify(server.auth_status)} is not supported; use a static header or bearer token`);
  }

  return {
    skipped: false,
    entry: {
      id,
      name: pluginName,
      sourceName: display,
      disabled: server.enabled === false,
      config,
    },
    warnings,
  };
}

function quote(value) {
  // JSON double-quoted strings are valid YAML double-quoted scalars.
  return JSON.stringify(String(value));
}

function emitConfig(config, indent) {
  const pad = ' '.repeat(indent);
  const lines = [];
  for (const [key, value] of Object.entries(config)) {
    if (value === undefined) continue;
    if (value && typeof value === 'object' && !Array.isArray(value) && value.__js) {
      lines.push(`${pad}${key}: !!js ${quote(value.__js)}`);
      continue;
    }
    if (Array.isArray(value)) {
      if (value.length === 0) {
        lines.push(`${pad}${key}: []`);
        continue;
      }
      lines.push(`${pad}${key}:`);
      for (const item of value) lines.push(`${pad}  - ${quote(item)}`);
      continue;
    }
    if (value && typeof value === 'object') {
      const keys = Object.keys(value);
      if (keys.length === 0) {
        lines.push(`${pad}${key}: {}`);
        continue;
      }
      lines.push(`${pad}${key}:`);
      for (const [childKey, childValue] of Object.entries(value)) {
        if (childValue && typeof childValue === 'object' && childValue.__js) {
          lines.push(`${pad}  ${quote(childKey)}: !!js ${quote(childValue.__js)}`);
        } else {
          lines.push(`${pad}  ${quote(childKey)}: ${quote(childValue)}`);
        }
      }
      continue;
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
      lines.push(`${pad}${key}: ${value}`);
      continue;
    }
    lines.push(`${pad}${key}: ${quote(value)}`);
  }
  return lines;
}

function emitBlock(entries) {
  if (entries.length === 0) return '';
  const lines = [BEGIN, '- insert:'];
  for (const entry of entries) {
    lines.push(`    - id: ${quote(entry.id)}`);
    lines.push(`      name: ${quote(entry.name)}`);
    if (entry.disabled) lines.push('      disabled: true');
    lines.push('      config:');
    lines.push(...emitConfig(entry.config, 8));
  }
  lines.push(END);
  return `${lines.join('\n')}\n`;
}

function stripManagedBlock(text) {
  const escapedBegin = BEGIN.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const escapedEnd = END.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(`(?:^|\\n)${escapedBegin}[\\s\\S]*?${escapedEnd}\\n?`, 'g');
  return text.replace(re, '\n');
}

function isEffectivelyEmpty(text) {
  const stripped = text
    .replace(/#[^\n]*/g, '')
    .replace(/\s+/g, '');
  return stripped === '' || stripped === '[]';
}

function mergePatch(existing, block) {
  const remainder = stripManagedBlock(existing);
  if (isEffectivelyEmpty(remainder)) {
    // Preserve leading comment headers, drop the empty flow sequence.
    const comments = remainder
      .split('\n')
      .filter((line) => line.trim().startsWith('#'))
      .join('\n');
    if (!block) return `${comments ? `${comments}\n` : ''}[]\n`;
    return `${comments ? `${comments}\n` : ''}${block}`;
  }
  if (!block) {
    const trimmed = remainder.replace(/\s+$/, '');
    return `${trimmed}\n`;
  }
  const trimmed = remainder.replace(/\s+$/, '');
  return `${trimmed}\n\n${block}`;
}

function backup(file) {
  const stamp = new Date().toISOString()
    .replace(/[-:]/g, '').replace('T', '-').replace('Z', '');
  let target = `${file}.bak-codex-mcp-${stamp}`;
  let suffix = 2;
  while (fs.existsSync(target)) {
    target = `${file}.bak-codex-mcp-${stamp}-${suffix++}`;
  }
  fs.writeFileSync(target, fs.readFileSync(file), { mode: 0o600 });
  return target;
}

function atomicWrite(file, text) {
  const dir = path.dirname(file);
  const tmp = path.join(dir, `.${path.basename(file)}.tmp-${process.pid}`);
  fs.writeFileSync(tmp, text, { mode: 0o600 });
  fs.renameSync(tmp, file);
}

function verifyComposition({ dshBin, profile, env, patchFile, original }) {
  try {
    execFileSync(dshBin, ['--profile', profile, '--dump-config'], {
      env,
      stdio: ['ignore', 'ignore', 'pipe'],
      maxBuffer: 32 * 1024 * 1024,
    });
  } catch (error) {
    const stderr = error.stderr?.toString().trim();
    try {
      atomicWrite(patchFile, original);
      warn(`validation failed; restored the previous ${path.basename(patchFile)}`);
    } catch {
      warn(`validation failed and the previous file could not be restored`);
    }
    die(`the composed profile is invalid${stderr ? `:\n${stderr}` : ''}`);
  }
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    process.stdout.write(HELP);
    return;
  }

  opts.dshHome = path.resolve(opts.dshHome);
  opts.codexHome = path.resolve(opts.codexHome);
  if (opts.config) {
    opts.config = path.resolve(opts.config);
    if (path.basename(opts.config) !== 'config.toml') {
      die('--config must point at a file named config.toml; use --codex-home <dir> otherwise');
    }
    opts.codexHome = path.dirname(opts.config);
  }

  const profileDir = path.join(opts.dshHome, 'profiles', opts.profile);
  const patchFile = path.join(profileDir, 'cordis.patch.yml');
  if (!fs.existsSync(profileDir)) {
    die(`DSH profile "${opts.profile}" does not exist at ${profileDir}`);
  }
  if (!fs.existsSync(patchFile)) {
    die(`${patchFile} does not exist; initialize the profile with "dsh ${opts.profile} --from-default-profile headless" first`);
  }

  const dshBin = which('dsh');
  if (!dshBin) die('the "dsh" command was not found on PATH');
  const env = { ...process.env, DSH_HOME: opts.dshHome };
  const version = dshVersion(dshBin, env);

  function checkPluginResolvable(pluginName) {
    if (path.isAbsolute(pluginName)) {
      if (!fs.existsSync(pluginName)) die(`the local MCP client file does not exist: ${pluginName}`);
      return;
    }
    try {
      createRequire(path.join(profileDir, 'package.json')).resolve(pluginName);
    } catch {
      warn(`${pluginName} is not resolvable from ${profileDir}; the profile may fail to load it`);
    }
  }

  const original = fs.readFileSync(patchFile, 'utf8');

  if (opts.remove) {
    const next = mergePatch(original, '');
    // mergePatch normalizes a trailing newline; a config that already has no
    // managed block (`[]` with no newline) must stay a strict no-op.
    if (next === original || next.trimEnd() === original.trimEnd()) {
      note('no managed block found; nothing to remove');
      return;
    }
    if (opts.dryRun) {
      process.stdout.write(next);
      return;
    }
    const saved = backup(patchFile);
    atomicWrite(patchFile, next);
    if (opts.verify) verifyComposition({ dshBin, profile: opts.profile, env, patchFile, original });
    note(`removed the managed MCP block from ${patchFile}`);
    note(`backup: ${saved}`);
    note(`the ${PLUGIN} package was left installed`);
    return;
  }

  const servers = readServers(opts);
  const plugin = ensurePlugin({
    profile: opts.profile,
    profileDir,
    dshHome: opts.dshHome,
    dshBin,
    version,
    install: opts.install,
    dryRun: opts.dryRun,
  });

  const cleaned = stripManagedBlock(original);
  if (!plugin.how.startsWith('would install')) checkPluginResolvable(plugin.name);
  const usedNames = collectExistingServerNames(cleaned);
  const usedIds = collectExistingIds(cleaned);
  const homePatch = path.join(opts.dshHome, 'cordis.patch.yml');
  if (fs.existsSync(homePatch)) {
    const homeText = stripManagedBlock(fs.readFileSync(homePatch, 'utf8'));
    for (const name of collectExistingServerNames(homeText)) usedNames.add(name);
    for (const id of collectExistingIds(homeText)) usedIds.add(id);
  }
  const entries = [];
  const skipped = [];

  for (const server of servers) {
    if (opts.only.size > 0 && !opts.only.has(server.name)) continue;
    if (opts.exclude.has(server.name)) continue;
    const result = transformServer(server, opts, usedNames, usedIds, plugin.name);
    if (result.skipped) {
      skipped.push({ name: server.name, reason: result.reason });
      continue;
    }
    entries.push(result.entry);
    for (const warning of result.warnings) warn(`${server.name}: ${warning}`);
  }

  const block = emitBlock(entries);
  const next = mergePatch(original, block);

  if (opts.dryRun) {
    process.stdout.write(`# ${plugin.how}\n`);
    process.stdout.write(`# profile: ${opts.profile}\n`);
    process.stdout.write(`# patch:   ${patchFile}\n`);
    process.stdout.write(next);
    for (const item of skipped) process.stderr.write(`install-codex-mcp: skipped ${item.name}: ${item.reason}\n`);
    return;
  }

  if (next === original) {
    note('patch is already up to date');
  } else {
    const saved = backup(patchFile);
    atomicWrite(patchFile, next);
    if (opts.verify) verifyComposition({ dshBin, profile: opts.profile, env, patchFile, original });
    note(`updated ${patchFile}`);
    note(`backup: ${saved}`);
  }

  note(`${plugin.how}; imported ${entries.length} server(s) for DSH ${version}`);
  for (const entry of entries) {
    note(`  mcp__${entry.config.serverName}__*  <- ${entry.sourceName}${entry.disabled ? ' (disabled)' : ''}`);
  }
  for (const item of skipped) note(`  skipped ${item.name}: ${item.reason}`);
  note('restart the profile (headless has HMR off), then ask the agent to call an mcp__<server>__<tool> tool');
  note(`verify with: DSH_HOME=${opts.dshHome} dsh --profile ${opts.profile} --dump-config`);
}

main();
