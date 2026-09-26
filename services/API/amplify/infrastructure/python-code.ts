import { Code, Runtime } from 'aws-cdk-lib/aws-lambda';
import path from 'node:path';

import { FUNCTION_ASSET_EXCLUDES } from './app-settings';

const PYTHON_SOURCE_DIRECTORIES = [
  'api',
  'autofix_dispatcher',
  'email_ingest',
  'email_send',
  'shared',
  'vendor',
  'worker',
] as const;

/** Build one deterministic Python Lambda asset shared by every application handler. */
export function applicationPythonCode(): Code {
  const copySources = PYTHON_SOURCE_DIRECTORIES
    .map((directory) => `cp -a "/asset-input/${directory}" /asset-output/`)
    .join(' && ');
  return Code.fromAsset(path.resolve('amplify/functions'), {
    exclude: FUNCTION_ASSET_EXCLUDES,
    bundling: {
      image: Runtime.PYTHON_3_14.bundlingImage,
      platform: 'linux/amd64',
      command: [
        'bash',
        '-c',
        [
          'python -m pip install --disable-pip-version-check --no-cache-dir --requirement /asset-input/requirements.txt --target /asset-output',
          copySources,
        ].join(' && '),
      ],
    },
  });
}
