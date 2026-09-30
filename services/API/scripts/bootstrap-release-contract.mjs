export const assertBootstrapReady = (bootstrap) => {
  if (!Array.isArray(bootstrap?.bots)
      || !bootstrap.bots.some((bot) => bot?.systemRole === 'chief' && bot.templateId === 'chief')) {
    throw new Error('Bootstrap did not return the installed Chief bot.');
  }

  const templates = bootstrap?.botTemplates;
  if (!Array.isArray(templates)
      || !templates.some((template) => template?.id === 'chief')
      || !templates.some((template) => typeof template?.id === 'string' && template.id !== 'chief')) {
    throw new Error('Bootstrap did not return Chief and an installable bot template.');
  }
};
