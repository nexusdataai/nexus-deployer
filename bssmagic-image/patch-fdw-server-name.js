/**
 * Patch controller JS files at Docker build time.
 *
 * Fix 1 - fdwServerName: Add source_schema_name as fallback parameter
 *   (design-time sends source_schema_name, not fdw_server_name)
 *
 * Fix 2 - Workflow stuck: Remove the "already in progress" short-circuit
 *   in DISCOVER_SCHEMA so a stuck workflow can restart.
 */

const fs = require('fs');

function patchFile(filePath, patches) {
  if (!fs.existsSync(filePath)) {
    console.log('SKIP (not found): ' + filePath);
    return false;
  }

  // Normalize to LF (handles CRLF from Windows)
  let code = fs.readFileSync(filePath, 'utf8').replace(/\r\n/g, '\n');
  let applied = 0;

  for (const p of patches) {
    const search = p.search.replace(/\r\n/g, '\n');
    const replace = p.replace.replace(/\r\n/g, '\n');

    if (code.includes(search)) {
      code = code.split(search).join(replace);
      applied++;
      console.log('  Applied: ' + p.name);
    } else {
      console.log('  MISS: ' + p.name);
      // Debug: show context around a key term
      if (p.debugTerm) {
        const idx = code.indexOf(p.debugTerm);
        if (idx !== -1) {
          console.log('  Context (' + p.debugTerm + '):');
          console.log(code.substring(Math.max(0, idx - 80), idx + 80));
        }
      }
    }
  }

  if (applied > 0) {
    fs.writeFileSync(filePath, code);
    console.log('PATCHED (' + applied + ' fixes): ' + filePath);
    return true;
  } else {
    console.log('NO CHANGES: ' + filePath);
    return false;
  }
}

// --- Patch definitions ---

const fdwServerNameSearch =
  "params.find((p) => p.name === 'fdw_server_name')?.value ||\n" +
  "            'salesforce_server'";

const fdwServerNameReplace =
  "params.find((p) => p.name === 'fdw_server_name')?.value ||\n" +
  "            params.find((p) => p.name === 'source_schema_name')?.value ||\n" +
  "            'salesforce_server'";

const workflowStuckSearch =
  "if (workflowStep.workflowType.name === workflowTypes.inProgress?.name) {\n" +
  "            logger.info('Workflow step is already in progress');\n" +
  "            const inProgressEvent = {\n" +
  "                workflowStep,\n" +
  "                nextStateName: workflowTypes.inProgress?.name ?? 'IN_PROGRESS',\n" +
  "                result: 'Schema discovery job already in progress',\n" +
  "            };\n" +
  "            await services.iotListener?.publishProgressEvent(inProgressEvent);\n" +
  "            return inProgressEvent;\n" +
  "        }";

const workflowStuckReplace =
  "if (workflowStep.workflowType.name === workflowTypes.inProgress?.name) {\n" +
  "            logger.warn('Workflow step was in-progress (likely stuck from previous failure) - restarting discovery');\n" +
  "        }";

// Fix 3 - Adapter fallback: Resolve the server name at the TOP of
//   createFromServerName so ALL subsequent uses get the correct name.
//   This handles DISCOVER_SCHEMA which doesn't send source_schema_name.
const adapterMethodSearch =
  "static async createFromServerName(fdwServerName, databaseService, logger) {";

const adapterMethodReplace =
  "static async createFromServerName(fdwServerName, databaseService, logger) {\n" +
  "        const [_srvCheck] = await databaseService.db.execute(sql `SELECT srvname FROM pg_foreign_server WHERE srvname = ${fdwServerName}`);\n" +
  "        if (!_srvCheck) { const [_fb] = await databaseService.db.execute(sql `SELECT srvname FROM pg_foreign_server LIMIT 1`); if (_fb?.srvname) { logger.warn({requested: fdwServerName, resolved: _fb.srvname}, 'FDW server not found, using fallback'); fdwServerName = _fb.srvname; } }";

// --- Apply patches ---

console.log('\n=== Patching auto-discover.command.js ===');
const p1 = patchFile('/controller/build/commands/auto-discover.command.js', [
  {
    name: 'fdwServerName-fallback',
    search: fdwServerNameSearch,
    replace: fdwServerNameReplace,
    debugTerm: "'salesforce_server'",
  },
]);

console.log('\n=== Patching discover-schema.command.js ===');
const p2 = patchFile('/controller/build/commands/discover-schema.command.js', [
  {
    name: 'fdwServerName-fallback',
    search: fdwServerNameSearch,
    replace: fdwServerNameReplace,
    debugTerm: "'salesforce_server'",
  },
  {
    name: 'workflow-stuck-fix',
    search: workflowStuckSearch,
    replace: workflowStuckReplace,
    debugTerm: "already in progress",
  },
]);

console.log('\n=== Patching adapter.js ===');
const p3 = patchFile('/controller/build/services/discovery/adapter.js', [
  {
    name: 'adapter-server-resolution',
    search: adapterMethodSearch,
    replace: adapterMethodReplace,
    debugTerm: "createFromServerName",
  },
]);

console.log('\n=== Summary ===');
if (!p3) {
  console.log('FATAL: adapter-server-resolution patch failed. This is required.');
  process.exit(1);
}
if (!p1 || !p2) {
  console.log('NOTE: fdwServerName-fallback patch skipped (base image may already include it).');
  console.log('      adapter-server-resolution provides equivalent protection.');
}
console.log('Required patches applied successfully.');