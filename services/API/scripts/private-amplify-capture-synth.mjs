// CDK-only entry for reviewing the complete Amplify backend before deployment.
// Amplify normally emits this signal from its deployer after importing backend.ts.
await import('../amplify/backend.ts');
process.emit('message', 'amplifySynth');
