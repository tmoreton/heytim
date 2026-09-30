#!/usr/bin/env node

import { readFileSync } from 'node:fs';

const [auditPath, lockPath] = process.argv.slice(2);
const fail = (message) => {
  console.error(`CDK dependency audit failed: ${message}`);
  process.exit(1);
};

let audit;
let lock;
try {
  audit = JSON.parse(readFileSync(auditPath, 'utf8'));
  lock = JSON.parse(readFileSync(lockPath, 'utf8'));
} catch (error) {
  fail(`could not read audit report or lockfile: ${error.message}`);
}

if (audit.error || !audit.vulnerabilities || !audit.metadata?.vulnerabilities) {
  fail('npm did not return a complete vulnerability report');
}

const findings = Object.values(audit.vulnerabilities);
const serious = findings.filter((finding) =>
  ['high', 'critical'].includes(finding.severity),
);
if (
  serious.length !==
  audit.metadata.vulnerabilities.high + audit.metadata.vulnerabilities.critical
) {
  fail('npm severity totals do not match the reported findings');
}
const direct = serious.filter((finding) => finding.isDirect);
if (direct.length > 0) {
  fail(`direct dependencies have high or critical findings: ${direct.map((finding) => finding.name).join(', ')}`);
}
console.log('CDK direct dependency audit passed.');

if (serious.length === 0) {
  console.log('CDK transitive dependency audit passed.');
  process.exit(0);
}

const known = serious.length === 1 && serious[0];
const expectedAdvisories = [
  'https://github.com/advisories/GHSA-6j4f-fj2g-mc7p',
  'https://github.com/advisories/GHSA-q2hr-2g5m-vwhr',
  'https://github.com/advisories/GHSA-qhr7-859c-m2p7',
];
const actualAdvisories = Array.isArray(known?.via)
  ? known.via.map((advisory) => advisory.url).sort()
  : [];
const bundledPath = 'node_modules/aws-cdk-lib/node_modules/brace-expansion';
if (
  known?.name !== 'brace-expansion' ||
  known.severity !== 'high' ||
  known.isDirect !== false ||
  JSON.stringify(known.nodes) !== JSON.stringify([bundledPath]) ||
  JSON.stringify(actualAdvisories) !== JSON.stringify(expectedAdvisories) ||
  lock.packages?.['node_modules/aws-cdk-lib']?.version !== '2.268.0' ||
  lock.packages?.[bundledPath]?.version !== '5.0.9' ||
  audit.metadata.vulnerabilities.high !== 1 ||
  audit.metadata.vulnerabilities.critical !== 0
) {
  fail(`unexpected high or critical transitive finding: ${serious.map((finding) => finding.name).join(', ')}`);
}

console.warn(
  'Known bundled aws-cdk-lib brace-expansion 5.0.9 finding remains open: ' +
  'https://github.com/aws/aws-cdk/issues/38932',
);
